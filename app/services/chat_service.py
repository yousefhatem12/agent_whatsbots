from __future__ import annotations

import json
import re

from openai import OpenAI

from app.core.config import (
    DEEPSEEK_THINKING,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_PROVIDER,
    logger,
)
from app.db.database import (
    get_offers_and_deals,
    log_chat_turn,
    search_products,
)
from app.db.seed_data import get_config
from app.services.apartment_types import detect_type
from app.services.prompts import get_system_prompt, get_tools

_client_kwargs = {"api_key": LLM_API_KEY}
if LLM_BASE_URL:
    _client_kwargs["base_url"] = LLM_BASE_URL
client = OpenAI(**_client_kwargs)

_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF"
    r"\u20E3\uFE0E\uFE0F\u200D\uD800-\uDFFF]+"
)


def _strip_emojis(text: str) -> str:
    """Remove emoji characters while preserving normal Arabic/WhatsApp text."""
    cleaned = _EMOJI_RE.sub("", str(text))
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip()


def _extract_property(tool_result: dict) -> dict | None:
    """Return the product/property currently shown by a tool result, if any."""
    for key in ("product", "property"):
        item = tool_result.get(key)
        if isinstance(item, dict):
            return item

    for list_key in ("products", "properties"):
        items = tool_result.get(list_key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    return item
    return None


def _reply_mentions_property(reply: str, property_data: dict) -> bool:
    """Check whether the reply mentions the current product/property."""
    normalised_reply = re.sub(r"\s+", " ", reply).strip().lower()
    for key in ("title", "name", "brand_name", "category_name", "building_name"):
        value = str(property_data.get(key) or "").strip().lower()
        if len(value) >= 3 and value in normalised_reply:
            return True
    return False


def _prepare_customer_reply(reply: str, property_data: dict | None = None) -> str:
    """Clean customer output and guarantee the current item's website link."""
    cleaned = _strip_emojis(reply)
    # Normalize accidental Markdown bold (**text**) to WhatsApp bold (*text*)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"*\1*", cleaned)
    # Unwrap accidental Markdown links [label](https://...) into raw URLs
    cleaned = re.sub(r"\[[^\]]*\]\((https?://[^\s)]+)\)", r"\1", cleaned)
    if not property_data or not _reply_mentions_property(cleaned, property_data):
        return cleaned

    canonical_url = str(property_data.get("canonical_url") or "").strip()
    if not canonical_url or canonical_url in cleaned:
        return cleaned

    is_product = "/product/" in canonical_url or "shgarde.com" in canonical_url
    intro = (
        "تقدر تشوف تفاصيل المنتج وتطلبه مباشرة من موقعنا من هنا:"
        if is_product
        else "تقدر تشوف كل تفاصيل الشقة على موقعنا من هنا:"
    )
    return f"{cleaned}\n\n{intro}\n{canonical_url}".strip()


def filter_properties(properties: list[dict], apartment_type: str | None) -> list[dict]:
    if not apartment_type or apartment_type == "any":
        return properties
    return [
        p for p in properties
        if detect_type(p.get("title"), p.get("description"), p.get("rooms_count")) == apartment_type
    ]


# Process-memory sessions: phone -> list of chat messages
SESSIONS: dict[str, list[dict]] = {}

# Separate store for search result state: phone -> {"results": [...], "index": int}
SEARCH_STATE: dict[str, dict] = {}

# Keep extracted search slots per phone
CRITERIA: dict[str, dict] = {}

_DIRECTION_AREAS = {
    "شمال": ("العارض", "العقيق", "النرجس"),
    "شرق": ("المونسية",),
    "غرب": ("العريجاء",),
    "وسط": ("الملز",),
    "جنوب": ("منفوحة",),
}


def _normalise_arabic(value: str) -> str:
    return re.sub(r"[\u064b-\u0652ـ]", "", value.lower()).translate(
        str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
    )


def _update_criteria(phone: str, message: str) -> dict:
    """Extract deterministic search slots from the customer message."""
    criteria = CRITERIA.setdefault(phone, {})
    text = _normalise_arabic(message.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    config = get_config()

    # Check brand match
    brands = config.get("brands", [])
    normalised_brands = {_normalise_arabic(b): b for b in brands}
    matched_brands = [b for k, b in normalised_brands.items() if k and k in text]
    if matched_brands:
        criteria["brand"] = matched_brands[0]

    # Check category match
    categories = config.get("categories", [])
    normalised_cats = {_normalise_arabic(c): c for c in categories}
    matched_cats = [c for k, c in normalised_cats.items() if k and k in text]
    if matched_cats:
        criteria["category"] = matched_cats[0]

    # Backward-compatible real-estate slot extraction for unit tests
    areas = config.get("neighborhood_groups", [])
    normalised_areas = {_normalise_arabic(area): area for area in areas}
    if "غرفتين" in text or re.search(r"(?<!\d)2\s*غرف", text):
        criteria["apartment_type"] = "two_bedroom"
    elif any(x in text for x in ("استوديو", "استديو", "ستوديو", "ستديو", "studio")):
        criteria["apartment_type"] = "studio"
    elif ("غرفه" in text or "اوضه" in text or re.search(r"(?<!\d)1\s*غرف", text)) and "صاله" in text:
        criteria["apartment_type"] = "one_bedroom"

    selected_areas = [area for key, area in normalised_areas.items() if key and key in text]
    if selected_areas:
        criteria["neighborhood"] = ",".join(dict.fromkeys(selected_areas))

    if any(x in text for x in ("اغلي", "اعلي سعر", "بسعر اعلي")):
        criteria["sort_order"] = "desc"
        SEARCH_STATE.pop(phone, None)
    elif any(x in text for x in ("ارخص", "اوفرا", "اوفر", "اقل سعر")):
        criteria["sort_order"] = "asc"
        SEARCH_STATE.pop(phone, None)

    budget_text = re.sub(r"(?<=\d)[,٬](?=\d{3}\b)", "", text)
    budget_text = re.sub(r"(?:\+?966|00966|05|965)\d{7,9}", "", budget_text)
    budget_text = re.sub(
        r"(?<!\d)[1-9]\s*(?:غرف\w*|حمام\w*|دور|طابق|اشخاص|ايام|يوم|شهور|شهر)|"
        r"(?:غرف\w*|شقه|عماره|مبني|دور)\s*[1-9](?!\d)",
        "",
        budget_text,
    )
    for area_key in normalised_areas:
        budget_text = re.sub(rf"{re.escape(area_key)}\s+\d+(?!\d)", area_key, budget_text)
    numbers = [int(n) for n in re.findall(r"\d+", budget_text) if 100 <= int(n) <= 500000]
    if numbers:
        amount = numbers[-1]
        criteria["min_budget"], criteria["max_budget"] = (
            (amount, 999999)
            if any(x in text for x in ("فوق", "اكثر", "اعلي", "اعلى"))
            else (0, amount)
        )
        criteria["budget_source"] = "explicit"

    return criteria


def reset_session(phone: str) -> None:
    """Clear conversation history, search results, and criteria for a phone number."""
    SESSIONS.pop(phone, None)
    SEARCH_STATE.pop(phone, None)
    CRITERIA.pop(phone, None)


def get_session(
    phone: str,
    apartment_type: str | None = None,
    neighborhood: str | None = None,
) -> list[dict]:
    if phone not in SESSIONS:
        SESSIONS[phone] = [{
            "role": "system",
            "content": get_system_prompt(apartment_type, neighborhood),
        }]
    else:
        SESSIONS[phone] = [
            msg for msg in SESSIONS[phone]
            if not (
                msg.get("role") == "system"
                and str(msg.get("content", "")).startswith("INTERNAL CONFIRMED SEARCH STATE")
            )
        ]
        for msg in SESSIONS[phone]:
            if msg["role"] == "system":
                msg["content"] = get_system_prompt(apartment_type, neighborhood)
                break
        # Keep conversation window bounded so long WhatsApp threads stay fast
        if len(SESSIONS[phone]) > 25:
            SESSIONS[phone] = [SESSIONS[phone][0]] + SESSIONS[phone][-20:]
    return SESSIONS[phone]


def process_message(phone: str, message: str) -> tuple[str, list[str]]:
    criteria = _update_criteria(phone, message)
    messages = get_session(
        phone,
        criteria.get("apartment_type"),
        criteria.get("neighborhood"),
    )
    messages.append({"role": "user", "content": message})

    def _search_products_tool(
        query: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        max_price: float | None = None,
        min_price: float = 0.0,
        sort_order: str = "asc",
        # Fallback parameters if model uses legacy argument names
        neighborhood: str | None = None,
        max_budget: float | None = None,
        min_budget: float | None = None,
        **_kwargs,
    ) -> dict:
        effective_query = query or neighborhood
        effective_cat = category or criteria.get("category")
        effective_brand = brand or criteria.get("brand")
        effective_max = max_price if max_price is not None else max_budget
        effective_min = min_price if min_price is not None else (min_budget or 0.0)

        results = search_products(
            query=effective_query,
            category=effective_cat if not query else category,
            brand=effective_brand if not query else brand,
            max_price=effective_max,
            min_price=effective_min,
            sort_order=sort_order,
            limit=20,
        )

        # Fallback: if combined query+brand/category returned 0, retry with query alone
        if not results and effective_query and (category or brand):
            results = search_products(
                query=effective_query,
                max_price=effective_max,
                min_price=effective_min,
                sort_order=sort_order,
                limit=20,
            )

        # Second fallback: search by brand or category alone if query had no exact match
        if not results and (effective_brand or effective_cat):
            results = search_products(
                category=effective_cat,
                brand=effective_brand,
                max_price=effective_max,
                min_price=effective_min,
                sort_order=sort_order,
                limit=20,
            )

        SEARCH_STATE[phone] = {"results": results, "index": 0}

        if not results:
            return {
                "found": 0,
                "message": "لا يوجد منتج مطابق تمامًا لهذا البحث في المخزون حاليًا.",
                "available_categories": get_config().get("categories", [])[:15],
                "available_brands": get_config().get("brands", [])[:15],
            }

        prices = [r["final_price"] for r in results]
        first = results[0]
        return {
            "total_found": len(results),
            "current_index": 1,
            "has_more": len(results) > 1,
            "currency": "د.ك",
            "price_min": min(prices),
            "price_max": max(prices),
            "product": first,
            "other_matches_preview": [
                {"title": r["title"], "price": r["final_price"], "brand": r["brand_name"], "url": r["canonical_url"]}
                for r in results[1:4]
            ],
        }

    def _offers_tool(category: str | None = None, brand: str | None = None, **_kwargs) -> dict:
        results = get_offers_and_deals(category=category, brand=brand, limit=15)
        SEARCH_STATE[phone] = {"results": results, "index": 0}
        if not results:
            return {"found": 0, "message": "لا توجد عروض مطابقة في هذا القسم حاليًا."}
        first = results[0]
        return {
            "total_found": len(results),
            "current_index": 1,
            "has_more": len(results) > 1,
            "currency": "د.ك",
            "product": first,
            "other_offers_preview": [
                {"title": r["title"], "price": r["final_price"], "brand": r["brand_name"], "url": r["canonical_url"]}
                for r in results[1:4]
            ],
        }

    def _next_item_tool(**_kwargs) -> dict:
        state = SEARCH_STATE.get(phone)
        if not state or not state.get("results"):
            return {"error": "ما في نتائج بحث سابقة. اسأل العميل عن المنتج أو الماركة اللي يبيها."}

        results = state["results"]
        new_idx = state["index"] + 1
        if new_idx >= len(results):
            return {"found": 0, "message": "هذا كان آخر منتج في نتائج البحث الحالية."}

        state["index"] = new_idx
        item = results[new_idx]
        return {
            "total_found": len(results),
            "current_index": new_idx + 1,
            "has_more": new_idx + 1 < len(results),
            "currency": "د.ك",
            "product": item,
        }

    available_functions = {
        "search_products": _search_products_tool,
        "get_offers_and_deals": _offers_tool,
        "next_product": _next_item_tool,
        # Aliases
        "search_properties": _search_products_tool,
        "search_upcoming_properties": _offers_tool,
        "next_property": _next_item_tool,
    }

    MAX_TOOL_ROUNDS = 6
    current_property: dict | None = None
    for _ in range(MAX_TOOL_ROUNDS):
        completion_kwargs = {
            "model": LLM_MODEL,
            "messages": messages,
            "tools": get_tools(criteria.get("apartment_type")),
        }

        if LLM_PROVIDER == "deepseek":
            if DEEPSEEK_THINKING:
                completion_kwargs["extra_body"] = {
                    "thinking": {"type": DEEPSEEK_THINKING}
                }
        else:
            completion_kwargs["tool_choice"] = "auto"

        response = client.chat.completions.create(**completion_kwargs)
        assistant_msg = response.choices[0].message
        assistant_message = assistant_msg.model_dump(exclude_none=True)

        reasoning_content = getattr(assistant_msg, "reasoning_content", None)
        if reasoning_content is not None:
            assistant_message["reasoning_content"] = reasoning_content

        if assistant_msg.tool_calls:
            if assistant_msg.content is not None:
                assistant_message["content"] = _strip_emojis(assistant_msg.content)
            if "content" not in assistant_message:
                assistant_message["content"] = ""
        else:
            final_reply = _prepare_customer_reply(
                assistant_msg.content or "تحت أمرك.",
                current_property,
            )
            assistant_message["content"] = final_reply
            messages.append(assistant_message)
            log_chat_turn(phone, message, final_reply)
            return (final_reply, [])

        messages.append(assistant_message)

        for tool_call in assistant_msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                fn_args = {}

            logger.info("Tool requested: %s | args: %s", fn_name, fn_args)

            fn = available_functions.get(fn_name)
            if fn is None:
                tool_result = {"error": f"Unknown tool: {fn_name}"}
            else:
                try:
                    tool_result = fn(**fn_args)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Tool %s raised", fn_name)
                    tool_result = {"error": str(exc)}

            extracted = _extract_property(tool_result)
            if extracted:
                current_property = extracted

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": fn_name,
                "content": json.dumps(tool_result, ensure_ascii=False, default=str),
            })

    logger.warning("Exceeded tool-call rounds for %s", phone)
    fallback_msg = "معذرة، حصل خطأ بسيط. ممكن تعيد طلبك؟"
    log_chat_turn(phone, message, fallback_msg)
    return (fallback_msg, [])
