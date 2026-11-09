from __future__ import annotations

import html
import re
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import DATABASE_URL, logger

STORE_BASE_URL = "https://shgarde.com"

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
    future=True,
)

# Invisible Unicode bidi/directional control chars
_BIDI_CONTROLS = dict.fromkeys(
    [0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069],
    None,
)

# Common Arabic/English e-commerce search synonyms in Shgarde Store
_SEARCH_SYNONYMS: dict[str, list[str]] = {
    "بلاك": ["شاحن", "حائط", "جداري", "gan"],
    "بلاكات": ["شاحن", "حائط", "جداري", "gan"],
    "راس شاحن": ["شاحن", "حائط", "جداري"],
    "باور بانك": ["بوربنك", "بطارية", "power bank"],
    "باوربنك": ["بوربنك", "بطارية", "power bank"],
    "بطاريه متنقله": ["بوربنك", "power bank"],
    "بطارية متنقلة": ["بوربنك", "power bank"],
    "ايفون": ["أيفون", "ايفون", "iphone", "ابل", "apple"],
    "أيفون": ["أيفون", "ايفون", "iphone", "ابل", "apple"],
    "iphone": ["أيفون", "ايفون", "iphone", "ابل"],
    "سماعه": ["سماعة", "سماعات", "tws", "earbuds", "صوتى"],
    "سماعة": ["سماعة", "سماعات", "tws", "earbuds", "صوتى"],
    "سماعات": ["سماعة", "سماعات", "tws", "earbuds", "صوتى"],
    "واير": ["كابل", "كيبل", "سلك", "الكابلات", "cable"],
    "وصلة": ["كابل", "كيبل", "الكابلات", "محول"],
    "وصله": ["كابل", "كيبل", "الكابلات", "محول"],
    "كيبل": ["كابل", "كيبل", "الكابلات", "cable"],
    "كفر": ["كفر", "جراب", "حماية", "case", "الحمايات"],
    "جراب": ["كفر", "جراب", "حماية", "case", "الحمايات"],
    "لزقه": ["حماية", "شاشة", "حمايات الشاشة"],
    "حمايه": ["حماية", "شاشة", "الحمايات والشاشات"],
    "انكر": ["أنكر", "انكر", "anker"],
    "أنكر": ["أنكر", "انكر", "anker"],
    "بيسوس": ["بيسوس", "baseus"],
    "يوجرين": ["يو جريين", "ugreen"],
    "يو جرين": ["يو جريين", "ugreen"],
    "راف باور": ["راف بور", "ravpower"],
    "بروميت": ["بروميت", "promate"],
    "ساعه": ["ساعة", "الساعات الذكية", "watch"],
    "ساعة": ["ساعة", "الساعات الذكية", "watch"],
}


def _format_phone(number: str | None) -> str | None:
    """Return phone normalised to +966 / international format without bidi controls."""
    if not number:
        return None
    cleaned = str(number).translate(_BIDI_CONTROLS)
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return None
    digits = digits.lstrip("0")
    if digits.startswith("966"):
        digits = digits[3:]
    if not digits:
        return None
    return f"+966{digits}"


def _clean_html(raw_html: str | None) -> str:
    """Convert HTML product descriptions into clean plain text for WhatsApp."""
    if not raw_html:
        return ""
    text_val = re.sub(r"<(?:br|p|/p|/li|/div|/h[1-6])\b[^>]*>", "\n", str(raw_html), flags=re.IGNORECASE)
    text_val = re.sub(r"<li\b[^>]*>", "• ", text_val, flags=re.IGNORECASE)
    text_val = re.sub(r"<[^>]+>", " ", text_val)
    text_val = html.unescape(text_val)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text_val.splitlines()]
    clean_lines = [line for line in lines if line]
    return "\n".join(clean_lines)[:600]


def _compute_final_price(
    unit_price: float,
    discount: float,
    discount_type: str | None,
    discount_start_date: int | None = None,
    discount_end_date: int | None = None,
) -> float:
    """Compute effective price in KWD after applying active product discount."""
    if not discount or discount <= 0:
        return round(unit_price, 3)

    now_ts = int(datetime.utcnow().timestamp())
    if discount_start_date and discount_end_date:
        if not (discount_start_date <= now_ts <= discount_end_date):
            return round(unit_price, 3)

    if str(discount_type).lower() == "percent":
        final = unit_price * (1.0 - (discount / 100.0))
    else:
        final = unit_price - discount
    return round(max(final, 0.0), 3)


def _format_product_rows(rows) -> list[dict]:
    """Convert raw SQL product rows into clean dictionaries for the LLM and API."""
    results: list[dict] = []
    for row in rows:
        r = dict(row)
        unit_price = round(float(r.get("unit_price") or 0.0), 3)
        discount = round(float(r.get("discount") or 0.0), 3)
        discount_type = r.get("discount_type")
        final_price = _compute_final_price(
            unit_price=unit_price,
            discount=discount,
            discount_type=discount_type,
            discount_start_date=r.get("discount_start_date"),
            discount_end_date=r.get("discount_end_date"),
        )
        slug = str(r.get("slug") or "").strip()
        canonical_url = f"{STORE_BASE_URL}/product/{slug}" if slug else STORE_BASE_URL
        stock = int(r.get("current_stock") or 0)
        title = str(r.get("ar_name") or r.get("name") or "").strip()
        category_name = str(r.get("category_name") or "").strip()
        brand_name = str(r.get("brand_name") or "").strip()
        description = _clean_html(r.get("ar_description") or r.get("description"))

        results.append({
            "id": int(r["id"]),
            "title": title,
            "name": title,
            "category_name": category_name,
            "building_name": category_name or brand_name,  # compatibility field
            "brand_name": brand_name,
            "unit_price": unit_price,
            "final_price": final_price,
            "monthly_price": final_price,  # compatibility field
            "currency": "د.ك",
            "has_discount": final_price < unit_price,
            "discount": discount if final_price < unit_price else 0.0,
            "discount_type": discount_type if final_price < unit_price else None,
            "current_stock": stock,
            "in_stock": stock > 0,
            "description": description,
            "canonical_url": canonical_url,
        })
    return results


def _expand_query_terms(query: str | None) -> list[str]:
    """Break a user query into normalized search keywords and synonyms."""
    if not query:
        return []
    cleaned = str(query).strip()
    if not cleaned:
        return []

    norm = re.sub(r"[\u064b-\u0652ـ]", "", cleaned.lower())
    for phrase, syns in _SEARCH_SYNONYMS.items():
        if phrase in norm:
            return syns

    stop_words = {
        "في", "من", "على", "عن", "مع", "او", "أو", "هل", "موجود", "متاح", "متوفر",
        "عندكم", "ابي", "أبي", "ابغى", "أبغى", "عايز", "اريد", "أريد", "سعر", "بكم",
        "كم", "منتج", "منتجات", "متجر", "شقردي", "ماركة", "ماركه", "قسم", "فئة", "اللي",
    }
    raw_tokens = [tok.strip() for tok in re.split(r"[\s,،/\\|+\-]+", cleaned) if tok.strip()]
    tokens: list[str] = []
    for tok in raw_tokens:
        if tok.lower() in stop_words or len(tok) < 2:
            continue
        tokens.append(tok)
        if tok.startswith("ال") and len(tok) > 3:
            tokens.append(tok[2:])
    return list(dict.fromkeys(tokens)) or [cleaned]


def search_products(
    query: str | None = None,
    category: str | None = None,
    brand: str | None = None,
    max_price: float | None = None,
    min_price: float = 0.0,
    in_stock_only: bool = False,
    sort_order: str = "asc",
    limit: int | None = 10,
) -> list[dict]:
    """Search published products in Shgarde Store (`shgarde_dummy`) by keyword, category, brand, and price."""
    min_p = float(min_price) if min_price is not None else 0.0
    max_p = float(max_price) if max_price is not None else 999999.0
    order_dir = "DESC" if str(sort_order).lower() == "desc" else "ASC"

    where_clauses = [
        "p.published = 1",
        "p.approved = 1",
        "p.unit_price BETWEEN :min_p AND :max_p",
    ]
    params: dict = {
        "min_p": min_p,
        "max_p": max_p,
    }

    if in_stock_only:
        where_clauses.append("p.current_stock > 0")

    if category and str(category).strip() and str(category).strip().lower() != "any":
        cats = [c.strip() for c in str(category).split(",") if c.strip()]
        cat_or = []
        for idx, c_val in enumerate(cats):
            key = f"cat_{idx}"
            params[key] = f"%{c_val}%"
            cat_or.append(
                f"(c.name LIKE :{key} OR p.name LIKE :{key} OR EXISTS ("
                f"SELECT 1 FROM product_categories pc JOIN categories c2 ON c2.id = pc.category_id "
                f"WHERE pc.product_id = p.id AND c2.name LIKE :{key}))"
            )
        if cat_or:
            where_clauses.append("(" + " OR ".join(cat_or) + ")")

    if brand and str(brand).strip() and str(brand).strip().lower() != "any":
        brands = [b.strip() for b in str(brand).split(",") if b.strip()]
        brand_or = []
        for idx, b_val in enumerate(brands):
            key = f"brand_{idx}"
            params[key] = f"%{b_val}%"
            brand_or.append(f"(b.name LIKE :{key} OR b.slug LIKE :{key} OR p.name LIKE :{key})")
        if brand_or:
            where_clauses.append("(" + " OR ".join(brand_or) + ")")

    score_expr = "0"
    if query and str(query).strip():
        terms = _expand_query_terms(query)
        term_clauses = []
        score_parts = []
        for idx, term in enumerate(terms):
            key = f"q_{idx}"
            params[key] = f"%{term}%"
            clause = (
                f"(p.name LIKE :{key} OR pt.name LIKE :{key} OR p.tags LIKE :{key} "
                f"OR c.name LIKE :{key} OR b.name LIKE :{key} OR p.slug LIKE :{key})"
            )
            term_clauses.append(clause)
            score_parts.append(f"(CASE WHEN p.name LIKE :{key} OR pt.name LIKE :{key} THEN 3 WHEN b.name LIKE :{key} OR c.name LIKE :{key} THEN 2 ELSE 1 END)")
        if term_clauses:
            # Match ANY expanded keyword and rank rows matching the most keywords first
            where_clauses.append("(" + " OR ".join(term_clauses) + ")")
            score_expr = " + ".join(score_parts)

    limit_sql = ""
    if limit is not None:
        params["limit"] = int(limit)
        limit_sql = "LIMIT :limit"

    sql = f"""
        SELECT
            p.id,
            p.name,
            MAX(pt.name)        AS ar_name,
            MAX(pt.description) AS ar_description,
            p.category_id,
            c.name              AS category_name,
            p.brand_id,
            b.name              AS brand_name,
            p.unit_price,
            p.discount,
            p.discount_type,
            p.discount_start_date,
            p.discount_end_date,
            p.current_stock,
            p.slug,
            p.description,
            ({score_expr})      AS match_score
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN brands b ON b.id = p.brand_id
        LEFT JOIN product_translations pt ON pt.product_id = p.id AND pt.lang IN ('sa', 'ar', 'en')
        WHERE {" AND ".join(where_clauses)}
        GROUP BY p.id
        ORDER BY (p.current_stock > 0) DESC, match_score DESC, p.unit_price {order_dir}
        {limit_sql}
    """

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except Exception:
        logger.warning("DB search_products query failed", exc_info=True)
        return []

    results = _format_product_rows(rows)
    logger.info(
        "DB search_products: query=%r category=%r brand=%r price %s-%s KWD -> %d results",
        query, category, brand, min_p, max_p, len(results),
    )
    return results


def get_offers_and_deals(
    category: str | None = None,
    brand: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Return products currently on offer/deal (todays_deal, discount > 0, flash_deal, or صفقة اليوم)."""
    where_clauses = [
        "p.published = 1",
        "p.approved = 1",
        "p.current_stock > 0",
        "(p.todays_deal = 1 OR p.discount > 0 OR c.name LIKE '%صفقة%' OR EXISTS (SELECT 1 FROM flash_deal_products fdp WHERE fdp.product_id = p.id))",
    ]
    params: dict = {"limit": int(limit)}

    if category and str(category).strip() and str(category).strip().lower() != "any":
        params["cat"] = f"%{str(category).strip()}%"
        where_clauses.append("(c.name LIKE :cat OR p.name LIKE :cat)")

    if brand and str(brand).strip() and str(brand).strip().lower() != "any":
        params["brand"] = f"%{str(brand).strip()}%"
        where_clauses.append("(b.name LIKE :brand OR p.name LIKE :brand)")

    sql = f"""
        SELECT
            p.id,
            p.name,
            MAX(pt.name)        AS ar_name,
            MAX(pt.description) AS ar_description,
            p.category_id,
            c.name              AS category_name,
            p.brand_id,
            b.name              AS brand_name,
            p.unit_price,
            p.discount,
            p.discount_type,
            p.discount_start_date,
            p.discount_end_date,
            p.current_stock,
            p.slug,
            p.description
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN brands b ON b.id = p.brand_id
        LEFT JOIN product_translations pt ON pt.product_id = p.id AND pt.lang IN ('sa', 'ar', 'en')
        WHERE {" AND ".join(where_clauses)}
        GROUP BY p.id
        ORDER BY p.discount DESC, p.todays_deal DESC, p.unit_price ASC
        LIMIT :limit
    """

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except Exception:
        logger.warning("DB get_offers_and_deals query failed", exc_info=True)
        return []

    return _format_product_rows(rows)


def log_chat_turn(phone: str, user_message: str, bot_reply: str) -> None:
    """Persist the WhatsApp chat turn into `whatsapp_users` and `whatsapp_chat_history`."""
    if not phone or not user_message:
        return
    try:
        with engine.begin() as conn:
            user_row = conn.execute(
                text("SELECT id FROM whatsapp_users WHERE phone = :phone LIMIT 1"),
                {"phone": phone},
            ).fetchone()
            if user_row:
                user_id = int(user_row[0])
            else:
                res = conn.execute(
                    text("INSERT INTO whatsapp_users (phone, name, created_at) VALUES (:phone, :name, NOW())"),
                    {"phone": phone, "name": f"User_{phone[-4:]}" if len(phone) >= 4 else phone},
                )
                user_id = int(res.lastrowid)

            conn.execute(
                text("""
                    INSERT INTO whatsapp_chat_history (user_id, user_message, bot_reply, created_at)
                    VALUES (:uid, :umsg, :breply, NOW())
                """),
                {"uid": user_id, "umsg": user_message, "breply": bot_reply},
            )
    except Exception:
        logger.debug("Could not log chat turn to whatsapp_chat_history", exc_info=True)


# ── Backward-compatible wrappers ─────────────────────────────────────────────

def search_properties(
    neighborhoods: list[str] | str,
    max_budget: float = 999999,
    min_budget: float = 0,
    rooms_count: int | None = None,
    limit: int | None = 10,
    sort_order: str = "asc",
) -> list[dict]:
    if isinstance(neighborhoods, list):
        cat_or_query = ",".join(str(x).strip() for x in neighborhoods if str(x).strip())
    else:
        cat_or_query = str(neighborhoods or "").strip()
    if not cat_or_query:
        return []
    return search_products(
        query=cat_or_query,
        max_price=max_budget,
        min_price=min_budget,
        sort_order=sort_order,
        limit=limit,
    )


def price_range(
    neighborhoods: list[str] | str,
    rooms_count: int | None = None,
) -> dict:
    results = search_properties(neighborhoods, max_budget=999999, min_budget=0, limit=None)
    if not results:
        return {"count": 0}
    prices = [r["final_price"] for r in results]
    return {
        "count": len(results),
        "price_min": min(prices),
        "price_max": max(prices),
    }


def search_upcoming_properties(
    neighborhoods: list[str] | str,
    max_budget: float = 999999,
    min_budget: float = 0,
    rooms_count: int | None = None,
    days_ahead: int = 30,
) -> list[dict]:
    if isinstance(neighborhoods, list):
        cat_str = ",".join(str(x).strip() for x in neighborhoods if str(x).strip())
    else:
        cat_str = str(neighborhoods or "").strip()
    if not cat_str:
        return []
    return get_offers_and_deals(category=cat_str, limit=5)
