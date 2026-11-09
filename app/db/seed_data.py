"""
Dynamic config loaded from the live database.
Results are cached for CACHE_TTL seconds so the DB isn't hit on every message.
The cache refreshes automatically — no app restart needed when data changes.
"""
from __future__ import annotations

import re
import time
import logging

logger = logging.getLogger("realestate-chat")

_cache: dict | None = None
_cache_time: float = 0
# Keep this short so a newly registered building/neighborhood appears in the
# conversation without an application restart.  This query is small and is
# also used by the deterministic Arabic area matcher.
CACHE_TTL: int = 60


def get_config() -> dict:
    """Return neighborhood list and price range, refreshing from DB if stale."""
    global _cache, _cache_time
    now = time.time()
    if _cache is None or (now - _cache_time) > CACHE_TTL:
        try:
            _cache = _load_from_db()
            _cache_time = now
            logger.info(
                "DB config refreshed: %d neighborhoods (%d groups), price range %s–%s SAR",
                len(_cache["neighborhoods"]),
                len(_cache["neighborhood_groups"]),
                _cache["price_min"],
                _cache["price_max"],
            )
        except Exception:
            if _cache is not None:
                logger.warning("Failed to refresh DB config; serving cached config", exc_info=True)
                return _cache
            raise
    return _cache


def _load_from_db() -> dict:
    from app.db.database import engine
    from app.services.apartment_types import TYPE_LABELS, base_neighborhood_name, detect_type
    from sqlalchemy import text

    with engine.connect() as conn:
        # Only expose neighborhoods that have at least one currently approved
        # listing.  Building records can exist long before a unit is available
        # and must not be presented to a customer as available areas.
        inventory_rows = conn.execute(
            text("""
                SELECT DISTINCT
                    b.name AS building_name,
                    p.title,
                    p.description,
                    p.rooms_count
                FROM properties p
                JOIN buildings b
                  ON b.id = CASE WHEN p.id = 130 THEN 11 ELSE p.building_id END
                WHERE p.status = 'approved'
                  AND p.price_monthly IS NOT NULL
                  AND b.name IS NOT NULL
                  AND TRIM(b.name) <> ''
                ORDER BY b.name
            """)
        ).fetchall()

        # Price range across all approved listings
        price_row = conn.execute(
            text("""
                SELECT
                    MIN(price_monthly) AS min_price,
                    MAX(price_monthly) AS max_price
                FROM properties
                WHERE status = 'approved'
                  AND price_monthly IS NOT NULL
            """)
        ).fetchone()

    neighborhoods: list[str] = []
    neighborhoods_by_type: dict[str, list[str]] = {
        "studio": [],
        "one_bedroom": [],
        "two_bedroom": [],
    }
    for row in inventory_rows:
        name = row[0]
        if not name:
            continue
        if name not in neighborhoods:
            neighborhoods.append(name)

        apartment_type = detect_type(row[1], row[2], row[3])
        if name not in neighborhoods_by_type[apartment_type]:
            neighborhoods_by_type[apartment_type].append(name)

    price_min = int(price_row[0]) if price_row and price_row[0] is not None else 0
    price_max = int(price_row[1]) if price_row and price_row[1] is not None else 99999

    # Build unique base names by stripping trailing numbers
    # e.g. "النرجس 1" and "النرجس 3" → "النرجس"
    seen: set = set()
    grouped: list = []
    for name in neighborhoods:
        base = base_neighborhood_name(name)
        if base not in seen:
            seen.add(base)
            grouped.append(base)

    grouped_by_type: dict[str, list[str]] = {}
    for apartment_type, names in neighborhoods_by_type.items():
        seen = set()
        grouped_names = []
        for name in names:
            base = base_neighborhood_name(name)
            if base not in seen:
                seen.add(base)
                grouped_names.append(base)
        grouped_by_type[apartment_type] = grouped_names

    grouped_by_type["any"] = grouped

    available_types_by_neighborhood: dict[str, list[str]] = {
        base: [] for base in grouped
    }
    for apartment_type, names in neighborhoods_by_type.items():
        for name in names:
            base = base_neighborhood_name(name)
            if apartment_type not in available_types_by_neighborhood.setdefault(base, []):
                available_types_by_neighborhood[base].append(apartment_type)

    return {
        "city": "الرياض",
        "neighborhoods": neighborhoods,  # full names used for DB search
        "neighborhood_groups": grouped,  # all live areas shown before type is known
        "neighborhoods_by_type": neighborhoods_by_type,
        "neighborhood_groups_by_type": grouped_by_type,
        "available_types_by_neighborhood": available_types_by_neighborhood,
        "available_types": [
            apartment_type
            for apartment_type in TYPE_LABELS
            if grouped_by_type.get(apartment_type)
        ],
        "price_min": price_min,
        "price_max": price_max,
    }
