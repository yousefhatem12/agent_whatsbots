"""
Dynamic store configuration loaded from the live Shgarde MySQL database (shgarde_dummy).
Results are cached for CACHE_TTL seconds so the DB isn't hit on every message.
The cache refreshes automatically — no app restart needed when products/categories/brands change.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("realestate-chat")

_cache: dict | None = None
_cache_time: float = 0
CACHE_TTL: int = 60

DEFAULT_CATEGORIES = [
    "وصل حديثاً",
    "أكسسوارات",
    "صفقة اليوم",
    "الهواتف الذكية",
    "صوتى",
    "الأجهزة المنزلية",
    "الكابلات",
    "الحمايات والشاشات",
    "الساعات الذكية",
    "إكسسوارات السيارة",
    "هواتف أيفون",
    "سامسونج",
    "الكمبيوتر واللاب توب",
    "ستاند سيارة",
    "سماعات TWS",
    "بوربنك",
    "سماعات الرأس",
    "شواحن الحائط",
    "مكبر صوت",
    "الألعاب",
    "أجهزة لوحية وأيباد",
]

DEFAULT_BRANDS = [
    "بيسوس",
    "بروميت",
    "يو جريين",
    "شاومي",
    "راف بور",
    "موفت",
    "أنكر",
    "ابل",
    "هافيت",
    "روك ستون",
    "هاي فيوتشر",
    "سيا إلكترونيك",
    "سامسونج",
    "هونر",
    "اوبو",
    "إنفنكس",
    "إنيرجيزر",
    "سكينأرما",
    "بلومز",
    "ريلمي",
]


def _default_config() -> dict:
    return {
        "store_name": "متجر شقردي",
        "store_url": "https://shgarde.com",
        "currency": "د.ك",
        "currency_code": "KWD",
        "categories": list(DEFAULT_CATEGORIES),
        "brands": list(DEFAULT_BRANDS),
        "total_products": 1710,
        "price_min": 0.99,
        "price_max": 885.0,
        # Backward-compatible keys
        "city": "الكويت",
        "neighborhoods": list(DEFAULT_CATEGORIES),
        "neighborhood_groups": list(DEFAULT_CATEGORIES),
        "neighborhoods_by_type": {
            "studio": list(DEFAULT_CATEGORIES),
            "one_bedroom": list(DEFAULT_CATEGORIES),
            "two_bedroom": list(DEFAULT_CATEGORIES),
        },
        "neighborhood_groups_by_type": {
            "studio": list(DEFAULT_CATEGORIES),
            "one_bedroom": list(DEFAULT_CATEGORIES),
            "two_bedroom": list(DEFAULT_CATEGORIES),
            "any": list(DEFAULT_CATEGORIES),
        },
        "available_types_by_neighborhood": {},
        "available_types": list(DEFAULT_BRANDS),
    }


def get_config() -> dict:
    """Return store categories, brands, and price range, refreshing from DB if stale."""
    global _cache, _cache_time
    now = time.time()
    if _cache is None or (now - _cache_time) > CACHE_TTL:
        try:
            _cache = _load_from_db()
            _cache_time = now
            logger.info(
                "DB config refreshed: %d categories, %d brands, %d products, price range %s–%s %s",
                len(_cache["categories"]),
                len(_cache["brands"]),
                _cache["total_products"],
                _cache["price_min"],
                _cache["price_max"],
                _cache["currency"],
            )
        except Exception:
            logger.warning("Failed to refresh DB config from database; using fallback/cached config", exc_info=True)
            if _cache is not None:
                return _cache
            return _default_config()
    return _cache


def _load_from_db() -> dict:
    from sqlalchemy import text
    from app.db.database import engine

    with engine.connect() as conn:
        category_rows = conn.execute(
            text("""
                SELECT
                    c.id,
                    c.name,
                    COUNT(p.id) AS product_count
                FROM categories c
                JOIN products p
                  ON p.category_id = c.id
                 AND p.published = 1
                 AND p.approved = 1
                WHERE c.name IS NOT NULL
                  AND TRIM(c.name) <> ''
                GROUP BY c.id, c.name
                HAVING product_count > 0
                ORDER BY product_count DESC, c.name ASC
            """)
        ).fetchall()

        brand_rows = conn.execute(
            text("""
                SELECT
                    b.id,
                    b.name,
                    COUNT(p.id) AS product_count
                FROM brands b
                JOIN products p
                  ON p.brand_id = b.id
                 AND p.published = 1
                 AND p.approved = 1
                WHERE b.name IS NOT NULL
                  AND TRIM(b.name) <> ''
                GROUP BY b.id, b.name
                HAVING product_count > 0
                ORDER BY product_count DESC, b.name ASC
            """)
        ).fetchall()

        price_row = conn.execute(
            text("""
                SELECT
                    COUNT(*)        AS total_products,
                    MIN(unit_price) AS min_price,
                    MAX(unit_price) AS max_price
                FROM products
                WHERE published = 1
                  AND approved = 1
                  AND unit_price IS NOT NULL
            """)
        ).fetchone()

    categories = [str(r[1]).strip() for r in category_rows if r[1] and str(r[1]).strip()]
    brands = [str(r[1]).strip() for r in brand_rows if r[1] and str(r[1]).strip()]

    total_products = int(price_row[0]) if price_row and price_row[0] is not None else 0
    price_min = round(float(price_row[1]), 3) if price_row and price_row[1] is not None else 0.0
    price_max = round(float(price_row[2]), 3) if price_row and price_row[2] is not None else 9999.0

    if not categories:
        categories = list(DEFAULT_CATEGORIES)
    if not brands:
        brands = list(DEFAULT_BRANDS)

    return {
        "store_name": "متجر شقردي",
        "store_url": "https://shgarde.com",
        "currency": "د.ك",
        "currency_code": "KWD",
        "categories": categories,
        "brands": brands,
        "total_products": total_products,
        "price_min": price_min,
        "price_max": price_max,
        # Backward-compatible keys
        "city": "الكويت",
        "neighborhoods": categories,
        "neighborhood_groups": categories,
        "neighborhoods_by_type": {
            "studio": categories,
            "one_bedroom": categories,
            "two_bedroom": categories,
        },
        "neighborhood_groups_by_type": {
            "studio": categories,
            "one_bedroom": categories,
            "two_bedroom": categories,
            "any": categories,
        },
        "available_types_by_neighborhood": {cat: brands[:5] for cat in categories},
        "available_types": brands,
    }
