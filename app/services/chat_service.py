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
from app.services.prompts import get_system_prompt, get_tools
from app.services.apartment_types import (
    TYPE_LABELS,
    base_neighborhood_name,
    detect_type,
    neighborhood_type_keys,
    neighborhood_type_map,
)
from app.db.seed_data import get_config
from app.db.database import search_properties, search_upcoming_properties, price_range

_client_kwargs = {"api_key": LLM_API_KEY}
if LLM_BASE_URL:
    _client_kwargs["base_url"] = LLM_BASE_URL
client = OpenAI(**_client_kwargs)


# DeepSeek is more likely than OpenAI to copy emojis from examples in a long
# system prompt. Keep this as a deterministic output guardrail as well.
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
    """Return the property currently shown by a tool result, if any."""
    property_data = tool_result.get("property")
    if isinstance(property_data, dict):
        return property_data

    properties = tool_result.get("properties")
    if isinstance(properties, list):
        for property_data in properties:
            if isinstance(property_data, dict):
                return property_data
    return None


def _reply_mentions_property(reply: str, property_data: dict) -> bool:
    """Avoid adding a property link to a price-only/no-results response."""
    normalised_reply = re.sub(r"\s+", " ", reply).strip()
    for key in ("title", "building_name"):
        value = str(property_data.get(key) or "").strip()
        if len(value) >= 4 and value in normalised_reply:
            return True
    return False


def _prepare_customer_reply(reply: str, property_data: dict | None = None) -> str:
    """Clean customer output and guarantee the current property's website link."""
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

    link_block = (
        "تقدر تشوف كل تفاصيل الشقة على موقعنا من هنا:\n"
        f"{canonical_url}"
    )
    return f"{cleaned}\n\n{link_block}".strip()


def filter_properties(properties: list[dict], apartment_type: str | None) -> list[dict]:
    if not apartment_type or apartment_type == "any":
        return properties
    return [
        p for p in properties
        if detect_type(p.get("title"), p.get("description"), p.get("rooms_count")) == apartment_type
    ]

# Process-memory sessions: phone → list of chat messages
SESSIONS: dict[str, list[dict]] = {}

# Separate store for search result state (not mixed into message history)
# phone → {"results": [...], "index": int}
SEARCH_STATE: dict[str, dict] = {}

# Keep search slots separate from the LLM's free-form conversation history.
CRITERIA: dict[str, dict] = {}

_DIRECTION_AREAS = {
    "شمال": ("العارض", "العقيق", "النرجس"), "شرق": ("المونسية",),
    "غرب": ("العريجاء",), "وسط": ("الملز",), "جنوب": ("منفوحة",),
}


def _normalise_arabic(value: str) -> str:
    return re.sub(r"[\u064b-\u0652ـ]", "", value.lower()).translate(
        str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"})
    )


def _update_criteria(phone: str, message: str) -> dict:
    """Extract deterministic slots so requests work in any word order."""
    criteria = CRITERIA.setdefault(phone, {})
    text = _normalise_arabic(message.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    config = get_config()
    areas = config["neighborhood_groups"]
    normalised_areas = {_normalise_arabic(area): area for area in areas}

    generic_any = any(x in text for x in ("اي شيء", "اي شئ", "اي شي", "اي نوع", "ما يفرق النوع", "مايفرق النوع"))
    # Keep a previously selected type when the customer says the type does not
    # matter. The model decides whether that also means an open budget.
    if generic_any and not criteria.get("apartment_type"):
        criteria["apartment_type"] = "any"
    elif "غرفتين" in text or re.search(r"(?<!\d)2\s*غرف", text):
        criteria["apartment_type"] = "two_bedroom"
    elif any(x in text for x in ("استوديو", "استديو", "ستوديو", "ستديو", "studio")):
        criteria["apartment_type"] = "studio"
    elif ("غرفه" in text or "اوضه" in text or re.search(r"(?<!\d)1\s*غرف", text)) and "صاله" in text:
        criteria["apartment_type"] = "one_bedroom"

    requested_type = criteria.get("apartment_type")
    if requested_type in ("studio", "one_bedroom", "two_bedroom"):
        available_areas = config["neighborhood_groups_by_type"].get(requested_type, [])
    else:
        available_areas = areas

    # A previous "any area" choice may have included studios-only areas. Once
    # the customer chooses a specific type, retain the broad scope but reduce
    # it to neighborhoods that actually contain that type.
    if criteria.get("area_scope", "").startswith("all"):
        previous = [n.strip() for n in criteria.get("neighborhood", "").split(",") if n.strip()]
        criteria["neighborhood"] = ",".join(n for n in previous if n in available_areas)

    direction_areas: list[str] = []
    for direction, candidates in _DIRECTION_AREAS.items():
        if re.search(rf"(?<!\w){direction}(?!\w)", text):
            expected = {_normalise_arabic(x) for x in candidates}
            direction_areas = [
                area for area in available_areas
                if _normalise_arabic(area) in expected
            ]
            break

    unrestricted_area = any(x in text for x in (
        "اي حي", "اي مكان", "كل الاحياء", "كل حي", "وين ما كان", "كل الرياض", "الرياض كلها",
    ))
    if unrestricted_area:
        selected = direction_areas or available_areas
        criteria["neighborhood"] = ",".join(selected)
        criteria["area_scope"] = "all neighborhoods in the requested direction" if direction_areas else "all available neighborhoods"
    elif "جرير" in text:
        criteria["neighborhood"], criteria["area_scope"] = "الملز", "الملز (جرير)"
    else:
        selected = [area for key, area in normalised_areas.items() if key in text]
        if not selected:
            selected = direction_areas
        if selected:
            criteria["neighborhood"] = ",".join(dict.fromkeys(selected))
            criteria["area_scope"] = "customer location preference"

    if any(x in text for x in ("اغلي", "اعلي سعر", "بسعر اعلي")):
        criteria["sort_order"] = "desc"
        criteria["min_budget"], criteria["max_budget"] = 0, 999999
        criteria["budget_source"] = "open"
        SEARCH_STATE.pop(phone, None)  # This is a new search, never the next old result.
    elif any(x in text for x in ("ارخص", "اوفرا", "اوفر")):
        criteria["sort_order"] = "asc"
        SEARCH_STATE.pop(phone, None)

    excluded = [
        area for key, area in normalised_areas.items()
        if re.search(rf"(?:ما\s*ابي|مو|مش|غير|بدون)\s*(?:في\s*)?.{{0,12}}{re.escape(key)}", text)
    ]
    if excluded:
        criteria["excluded_neighborhoods"] = list(dict.fromkeys(excluded))
        chosen = [n.strip() for n in criteria.get("neighborhood", "").split(",") if n.strip()]
        remaining = [n for n in chosen if n not in criteria["excluded_neighborhoods"]]
        if remaining:
            criteria["neighborhood"] = ",".join(remaining)

    # Never mistake "2 غرف" / "غرفة 1", phone numbers, or building sub-numbers for a monthly budget.
    budget_text = re.sub(r"(?<=\d)[,٬](?=\d{3}\b)", "", text)
    budget_text = re.sub(r"(?:\+?966|00966|05)\d{7,9}", "", budget_text)
    budget_text = re.sub(r"(?<!\d)[1-9]\s*(?:غرف\w*|حمام\w*|دور|طابق|اشخاص|ايام|يوم|شهور|شهر)|(?:غرف\w*|شقه|عماره|مبني|دور)\s*[1-9](?!\d)", "", budget_text)
    for area_key in normalised_areas:
        budget_text = re.sub(rf"{re.escape(area_key)}\s+\d+(?!\d)", area_key, budget_text)
    numbers = [int(n) for n in re.findall(r"\d+", budget_text) if 100 <= int(n) <= 500000]
    # A bare number is a valid answer to "كم ميزانيتك؟". Keep that behavior;
    # the room-number patterns above are removed before this check.
    explicit_budget = bool(numbers)
    if len(numbers) >= 2 and ("بين" in budget_text or re.search(r"من\s*\d+\s*(?:الى|الي|ل)\s*\d+", budget_text)):
        criteria["min_budget"], criteria["max_budget"] = min(numbers[:2]), max(numbers[:2])
        criteria["budget_source"] = "explicit"
    elif explicit_budget:
        amount = numbers[-1]
        criteria["min_budget"], criteria["max_budget"] = (
            (amount, 999999)
            if any(x in text for x in ("فوق", "اكثر", "اعلي", "اعلى"))
            else (0, amount)
        )
        criteria["budget_source"] = "explicit"
    return criteria


def _split_neighborhoods(value: str | list[str]) -> list[str]:
    """Convert the comma-separated neighborhood slot/tool argument to a list."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _live_type_validation(criteria: dict) -> dict | None:
    """Read exact type availability for the current area before the LLM replies.

    This is intentionally separate from the optional budget search. It prevents
    the model from inventing a price range when the customer has named a type
    and area but has not supplied a budget yet.
    """
    apartment_type = criteria.get("apartment_type")
    neighborhood = criteria.get("neighborhood")
    if apartment_type not in TYPE_LABELS or not neighborhood:
        return None

    neighborhoods = _split_neighborhoods(neighborhood)
    sql_rooms = 2 if apartment_type == "two_bedroom" else 1
    room_results = search_properties(
        neighborhoods,
        max_budget=999999,
        min_budget=0,
        rooms_count=sql_rooms,
        limit=None,
        sort_order="asc",
    )
    exact_results = filter_properties(room_results, apartment_type)
    prices = [r["monthly_price"] for r in exact_results]
    other_types = list(dict.fromkeys(
        detect_type(r.get("title"), r.get("description"), r.get("rooms_count"))
        for r in room_results
        if detect_type(r.get("title"), r.get("description"), r.get("rooms_count")) != apartment_type
    ))

    return {
        "requested_type": TYPE_LABELS[apartment_type],
        "neighborhoods": neighborhoods,
        "exact_count": len(exact_results),
        "price_min": int(min(prices)) if prices else None,
        "price_max": int(max(prices)) if prices else None,
        "other_types_in_same_room_bucket": [TYPE_LABELS.get(kind, kind) for kind in other_types],
    }


def _criteria_context(criteria: dict) -> str:
    config = get_config()
    fields = {key: criteria.get(key, "MISSING") for key in (
        "neighborhood",
        "area_scope",
        "excluded_neighborhoods",
        "apartment_type",
        "min_budget",
        "max_budget",
        "budget_source",
        "sort_order",
    )}
    apartment_type = criteria.get("apartment_type")
    if apartment_type in ("studio", "one_bedroom", "two_bedroom"):
        live_areas = config["neighborhood_groups_by_type"].get(apartment_type, [])
    else:
        live_areas = config["neighborhood_groups"]
    live_areas_text = "، ".join(live_areas) or "لا توجد أحياء فيها وحدات مطابقة حاليًا"
    area_type_keys = neighborhood_type_keys(config, criteria.get("neighborhood"))
    area_type_text = "، ".join(TYPE_LABELS[key] for key in area_type_keys) or "لا يوجد نوع شقة متاح في الحي المحدد حاليًا"
    area_type_map = neighborhood_type_map(config, criteria.get("neighborhood"))
    area_type_details = "؛ ".join(
        f"{area}: {', '.join(TYPE_LABELS[key] for key in types) or 'لا يوجد نوع متاح'}"
        for area, types in area_type_map.items()
    ) or area_type_text
    validation = _live_type_validation(criteria)
    validation_text = ""
    if validation:
        validation_json = json.dumps(validation, ensure_ascii=False)
        if validation["exact_count"]:
            validation_text = (
                f" AUTHORITATIVE LIVE TYPE VALIDATION from the database: {validation_json}. "
                "Use only this exact count and price range for the requested type and area; "
                "never replace it with a remembered or guessed range."
            )
        else:
            validation_text = (
                f" AUTHORITATIVE LIVE TYPE VALIDATION from the database: {validation_json}. "
                "The exact requested type has zero units in the requested area(s). "
                "This is not an above-budget case: do not say units exist at a higher price, "
                "do not quote a price, and do not show a property for that type."
            )
    requested_type_text = TYPE_LABELS.get(
        apartment_type,
        "أي نوع شقة" if apartment_type == "any" else "MISSING",
    )
    return (
        "INTERNAL CONFIRMED SEARCH STATE (never expose it): " + json.dumps(fields, ensure_ascii=False)
        + ". Values other than MISSING were already supplied by the customer. Interpret the latest customer message and the conversation naturally. If the customer asks to see what is available, says they do not know/care, or does not answer a preference, use the known values and broad live defaults instead of asking another question: all live areas when the area is missing, any available type when the type is missing, and max_budget=999999 when the budget is missing. Retain an explicit budget already supplied. Call search_properties as soon as a useful real result can be shown; never make the customer complete every slot. For an availability request, never answer with only a type list or ask the customer to choose a type. If the exact requested type has zero real units in a known area, search that same area again with apartment_type=any and show the first real alternative. If sort_order is desc or asc from the latest message, this is a NEW search; do not use next_property or any old result."
        + f" LIVE INVENTORY AREAS for the requested type right now: {live_areas_text}. If a specific apartment type is known, list and search only these live areas when offering broad locations; never claim that another building-only area has that type."
        + f" LIVE TYPES FOR EACH REQUESTED NEIGHBORHOOD from the database: {area_type_details}. The list is per area, not a global union; if multiple neighborhoods are selected, never imply that every type exists in every neighborhood."
        + f" REQUESTED TYPE LABEL: {requested_type_text}. Use this exact customer-facing type; never call غرفة وصالة غرفتين وصالة or vice versa."
        + validation_text
    )


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
        # Remove stale per-turn INTERNAL CONFIRMED SEARCH STATE messages from prior turns
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
    return SESSIONS[phone]


def process_message(phone: str, message: str) -> tuple[str, list[str]]:
    criteria = _update_criteria(phone, message)
    messages = get_session(
        phone,
        criteria.get("apartment_type"),
        criteria.get("neighborhood"),
    )
    messages.append({"role": "system", "content": _criteria_context(criteria)})
    messages.append({"role": "user", "content": message})

    # ── Phone-scoped tool implementations ──────────────────────────────────────

    def _search(neighborhood: str, max_budget: int, min_budget: int = 0, apartment_type: str | None = None, sort_order: str = "asc") -> dict:
        """Run DB search, store all results, return only the FIRST property.

        *neighborhood* may be a single name or comma-separated names (for
        direction-based searches like "شمال").
        """
        neighborhoods = _split_neighborhoods(neighborhood)
        if not neighborhoods:
            return {
                "found": 0,
                "availability": "no_neighborhood",
                "error": "A neighborhood is required before searching.",
            }

        excluded = set(CRITERIA.get(phone, {}).get("excluded_neighborhoods", []))
        if excluded:
            neighborhoods = [n for n in neighborhoods if n not in excluded]
            if not neighborhoods:
                return {
                    "found": 0,
                    "availability": "excluded",
                    "error": "All requested neighborhoods are excluded by the customer.",
                }

        # Map apartment_type to rooms_count filter in SQL (first-level filtering)
        sql_rooms = None
        if apartment_type == "two_bedroom":
            sql_rooms = 2
        elif apartment_type in ("one_bedroom", "studio"):
            sql_rooms = 1

        # Fetch all results matching neighborhood and rooms_count
        # Use high budget to calculate the accurate price range over all stock
        # Fetch the full candidate set before applying the exact type filter.
        # Limiting SQL first caused false "no availability" answers when a match
        # (such as Al Olaya) appeared after the first 10 rows.
        room_results = search_properties(
            neighborhoods,
            max_budget=999999,
            min_budget=0,
            rooms_count=sql_rooms,
            limit=None,
            sort_order=sort_order,
        )
        available_types = list(dict.fromkeys(
            detect_type(r.get("title"), r.get("description"), r.get("rooms_count"))
            for r in room_results
        ))
        available_types_by_area: dict[str, list[str]] = {}
        for result in room_results:
            area = base_neighborhood_name(result.get("building_name"))
            apartment_kind = detect_type(
                result.get("title"),
                result.get("description"),
                result.get("rooms_count"),
            )
            if area and apartment_kind not in available_types_by_area.setdefault(area, []):
                available_types_by_area[area].append(apartment_kind)
        available_types_by_area_labels = {
            area: [TYPE_LABELS.get(kind, kind) for kind in types]
            for area, types in available_types_by_area.items()
        }

        # Filter by specific type (studio vs one_bedroom) in Python
        all_results = filter_properties(room_results, apartment_type)

        # Separate stock (regardless of budget) and active results (within budget)
        all_stock = all_results
        active_results = [r for r in all_stock if min_budget <= r["monthly_price"] <= max_budget]

        SEARCH_STATE[phone] = {"results": active_results, "index": 0}

        # Calculate min/max prices for the exact type
        if all_stock:
            prices = [r["monthly_price"] for r in all_stock]
            price_min = min(prices)
            price_max = max(prices)
        else:
            price_min, price_max = None, None

        if not active_results:
            # Check if stock exists above budget
            if all_stock:
                return {
                    "found": 0,
                    "availability": "above_budget",
                    "requested_apartment_type": TYPE_LABELS.get(apartment_type, apartment_type),
                    "searched_neighborhoods": neighborhoods,
                    "exact_type_count": len(all_stock),
                    "available_types_in_searched_neighborhoods": [
                        TYPE_LABELS.get(kind, kind) for kind in available_types
                    ],
                    "available_types_by_neighborhood": available_types_by_area_labels,
                    "exists_above_budget": True,
                    "price_min": price_min,
                    "price_max": price_max,
                }
            return {
                "found": 0,
                "availability": "not_available_for_requested_type",
                "requested_apartment_type": TYPE_LABELS.get(apartment_type, apartment_type),
                "searched_neighborhoods": neighborhoods,
                "exact_type_count": 0,
                "available_types_in_searched_neighborhoods": [
                    TYPE_LABELS.get(kind, kind) for kind in available_types
                ],
                "available_types_by_neighborhood": available_types_by_area_labels,
                "exists_above_budget": False,
                "price_min": None,
                "price_max": None,
                "other_types_in_searched_neighborhoods": [
                    TYPE_LABELS.get(kind, kind) for kind in available_types
                    if kind != apartment_type
                ],
            }

        first = active_results[0]
        return {
            "total_found": len(active_results),
            "current_index": 1,
            "has_more": len(active_results) > 1,
            "requested_apartment_type": TYPE_LABELS.get(apartment_type, apartment_type),
            "searched_neighborhoods": neighborhoods,
            "exact_type_count": len(all_stock),
            "available_types_in_searched_neighborhoods": [
                TYPE_LABELS.get(kind, kind) for kind in available_types
            ],
            "available_types_by_neighborhood": available_types_by_area_labels,
            "price_min": price_min,
            "price_max": price_max,
            "property": first,
        }

    def _search_upcoming(
        neighborhood: str,
        max_budget: int,
        min_budget: int = 0,
        apartment_type: str | None = None,
        days_ahead: int = 30,
    ) -> dict:
        """Find apartments becoming available soon."""
        neighborhoods = _split_neighborhoods(neighborhood)
        if not neighborhoods:
            return {"found": 0, "error": "A neighborhood is required before searching."}

        excluded = set(CRITERIA.get(phone, {}).get("excluded_neighborhoods", []))
        if excluded:
            neighborhoods = [n for n in neighborhoods if n not in excluded]
            if not neighborhoods:
                return {"found": 0, "error": "All requested neighborhoods are excluded by the customer."}

        sql_rooms = None
        if apartment_type == "two_bedroom":
            sql_rooms = 2
        elif apartment_type in ("one_bedroom", "studio"):
            sql_rooms = 1

        results = search_upcoming_properties(
            neighborhoods, max_budget=999999, min_budget=0, rooms_count=sql_rooms, days_ahead=days_ahead
        )
        
        # Filter by type in Python
        results = filter_properties(results, apartment_type)
        
        # Filter by budget
        results = [r for r in results if min_budget <= r["monthly_price"] <= max_budget]

        if not results:
            return {"found": 0}

        return {
            "total_found": len(results),
            "properties": results,
        }

    def _next_property() -> dict:
        """Advance to the next search result and return it."""
        state = SEARCH_STATE.get(phone)
        if not state or not state.get("results"):
            return {"error": "ما في نتائج بحث سابقة. اطلب من العميل يحدد الحي والميزانية مجددًا."}

        results = state["results"]
        new_idx = state["index"] + 1

        if new_idx >= len(results):
            return {"found": 0, "message": "هذه كانت آخر شقة في نتائج البحث."}

        state["index"] = new_idx
        prop = results[new_idx]
        return {
            "total_found": len(results),
            "current_index": new_idx + 1,
            "has_more": new_idx + 1 < len(results),
            "property": prop,
        }

    available_functions = {
        "search_properties": _search,
        "search_upcoming_properties": _search_upcoming,
        "next_property": _next_property,
    }

    # ── Main loop ───────────────────────────────────────────────────────────────

    def _merge_search_calls(tool_calls: list) -> list:
        """If the model issues multiple search_properties calls in one round,
        merge them into a single call with all neighborhoods joined.

        This prevents the LLM from making 3 separate calls (العارض, العقيق, النرجس)
        when it should make one call with all three names.
        """
        search_calls = [
            tc for tc in tool_calls if tc.function.name == "search_properties"
        ]
        other_calls = [
            tc for tc in tool_calls if tc.function.name != "search_properties"
        ]

        if len(search_calls) <= 1:
            return tool_calls  # nothing to merge

        # Parse all search args
        parsed = []
        for tc in search_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            parsed.append(args)

        # Collect all neighborhood names
        all_neighborhoods = []
        for args in parsed:
            nb = args.get("neighborhood", "")
            for n in str(nb).split(","):
                n = n.strip()
                if n and n not in all_neighborhoods:
                    all_neighborhoods.append(n)

        # Use params from first call, override neighborhood with merged list
        base_args = parsed[0].copy()
        base_args["neighborhood"] = ",".join(all_neighborhoods)

        # Build a synthetic merged tool call using the first call's ID
        import copy
        merged_tc = copy.deepcopy(search_calls[0])
        merged_tc.function.arguments = json.dumps(base_args, ensure_ascii=False)

        logger.info(
            "Merged %d search_properties calls into one: neighborhoods=%r",
            len(search_calls), all_neighborhoods,
        )

        # Return the merged search call + a synthetic "skipped" response for the
        # other search call IDs so the API gets a tool result for every call ID.
        skipped_ids = [tc.id for tc in search_calls[1:]]
        return [merged_tc] + other_calls, skipped_ids

    MAX_TOOL_ROUNDS = 8
    current_property: dict | None = None
    for _ in range(MAX_TOOL_ROUNDS):
        completion_kwargs = {
            "model": LLM_MODEL,
            "messages": messages,
            "tools": get_tools(criteria.get("apartment_type")),
        }

        if LLM_PROVIDER == "deepseek":
            # DeepSeek V4 thinking mode rejects the OpenAI-specific
            # tool_choice parameter. Omitting it keeps the default behavior
            # (automatic tool selection). If configured, pass the V4 thinking
            # toggle through the OpenAI SDK's provider-specific request body.
            if DEEPSEEK_THINKING:
                completion_kwargs["extra_body"] = {
                    "thinking": {"type": DEEPSEEK_THINKING}
                }
        else:
            completion_kwargs["tool_choice"] = "auto"

        response = client.chat.completions.create(**completion_kwargs)
        assistant_msg = response.choices[0].message
        assistant_message = assistant_msg.model_dump(exclude_none=True)

        # DeepSeek thinking/tool-call turns require reasoning_content to be
        # replayed, and some V4 responses omit content when a tool is called.
        # model_dump preserves provider-specific fields; add an empty content
        # value when necessary so the next request has a valid assistant turn.
        reasoning_content = getattr(assistant_msg, "reasoning_content", None)
        if reasoning_content is not None:
            assistant_message["reasoning_content"] = reasoning_content

        if assistant_msg.tool_calls:
            if assistant_msg.content is not None:
                assistant_message["content"] = _strip_emojis(assistant_msg.content)
            if "content" not in assistant_message:
                assistant_message["content"] = ""
        else:
            assistant_message["content"] = _prepare_customer_reply(
                assistant_msg.content or "تحت أمرك.",
                current_property,
            )
        messages.append(assistant_message)

        if not assistant_msg.tool_calls:
            return (assistant_message["content"], [])

        # Merge multiple search_properties calls into one if needed
        tool_calls = assistant_msg.tool_calls
        skipped_ids: list[str] = []
        merge_result = _merge_search_calls(tool_calls)
        if isinstance(merge_result, tuple):
            tool_calls, skipped_ids = merge_result

        # Add dummy tool results for skipped (merged) call IDs so OpenAI
        # doesn't complain about missing tool responses.
        for skipped_id in skipped_ids:
            messages.append({
                "role": "tool",
                "tool_call_id": skipped_id,
                "name": "search_properties",
                "content": json.dumps({"merged": True}, ensure_ascii=False),
            })

        for tool_call in tool_calls:
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

            if fn_name in {"search_properties", "search_upcoming_properties", "next_property"}:
                current_property = _extract_property(tool_result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": fn_name,
                "content": json.dumps(tool_result, ensure_ascii=False, default=str),
            })

    logger.warning("Exceeded tool-call rounds for %s", phone)
    return ("معذرة، حصل خطأ بسيط. ممكن تعيد طلبك؟", [])
