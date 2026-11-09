from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import DATABASE_URL, logger

# Read-only engine — we never create or modify tables.
engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
    future=True,
)


# Invisible Unicode bidi/directional control chars that sometimes prefix phone
# numbers in the DB (e.g. U+202D). They corrupt display and must be removed.
_BIDI_CONTROLS = dict.fromkeys(
    [0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069],
    None,
)


def _format_phone(number: str | None) -> str | None:
    """Return the supervisor phone normalised to +966 international format.

    Strips invisible bidi/directional control chars, spaces, dashes and other
    separators, then rebuilds the number as +966XXXXXXXXX regardless of whether
    it was stored locally (05xxxxxxxx), with a country code (966...), or already
    international (+966...).
    """
    if not number:
        return None

    # Remove bidi controls, then keep digits only (drops spaces, dashes, +, etc.)
    cleaned = str(number).translate(_BIDI_CONTROLS)
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits:
        return None

    # Drop any leading zeros (local "05..." or international "00966..." prefix),
    # then strip the 966 country code if present, leaving the subscriber digits.
    digits = digits.lstrip("0")
    if digits.startswith("966"):
        digits = digits[3:]

    if not digits:
        return None
    return f"+966{digits}"


def _format_rows(rows) -> list[dict]:
    """Shared helper: convert raw DB rows into clean dicts for the API."""
    results = []
    for row in rows:
        r = dict(row)

        # Drop the raw images payload — image URLs are never surfaced anymore.
        r.pop("images", None)
        r.pop("area", None)  # Remove the area field to prevent mentioning sizes/areas

        # Contact numbers sent when a customer accepts: supervisor first, guard
        # as the fallback if the supervisor doesn't answer.
        r["supervisor_phone"] = _format_phone(r.get("supervisor_phone"))
        r["guard_phone"] = _format_phone(r.get("guard_phone"))

        # Convert Decimal → float for JSON serialisation.
        for key in ("monthly_price", "price_semi_annual", "price_annual"):
            if r.get(key) is not None:
                r[key] = float(r[key])

        results.append(r)
    return results


def search_properties(
    neighborhoods: "list[str] | str",
    max_budget: int,
    min_budget: int = 0,
    rooms_count: int | None = None,
    limit: int | None = 10,
    sort_order: str = "asc",
):
    """Search approved properties by neighborhood(s), budget, and optional room count.

    *neighborhoods* can be a single string OR a list of strings (used when the
    customer says a direction like "شمال" and we need to search multiple areas).
    """
    min_budget = int(min_budget) if min_budget is not None else 0
    max_budget = int(max_budget) if max_budget is not None else 10 ** 9
    sort_order = "DESC" if str(sort_order).lower() == "desc" else "ASC"

    # Normalise to a list
    if isinstance(neighborhoods, str):
        neighborhoods = [n.strip() for n in neighborhoods.split(",") if n.strip()]
    else:
        neighborhoods = [str(n).strip() for n in neighborhoods if str(n).strip()]

    if not neighborhoods:
        return []

    # Build LIKE terms
    nb_terms = [f"%{nb}%" for nb in neighborhoods]

    # Dynamic WHERE clause for multiple neighborhoods
    nb_clauses = " OR ".join(
        f"b.name LIKE :nb{i} OR p.title LIKE :nb{i}" for i in range(len(nb_terms))
    )
    params: dict = {f"nb{i}": t for i, t in enumerate(nb_terms)}
    params["min_b"] = min_budget
    params["max_b"] = max_budget

    rooms_clause = ""
    if rooms_count is not None:
        rooms_clause = "AND p.rooms_count = :rooms"
        params["rooms"] = int(rooms_count)

    limit_clause = "" if limit is None else "LIMIT :limit"
    if limit is not None:
        params["limit"] = int(limit)

    sql = f"""
        SELECT
            p.id,
            p.title,
            p.location,
            b.name          AS building_name,
            p.price_monthly AS monthly_price,
            p.price_semi_annual,
            p.price_annual,
            p.description,
            p.rooms_count,
            p.baths_count,
            p.area,
            p.supervisor_phone,
            p.guard_phone,
            p.canonical_url
        FROM properties p
        LEFT JOIN buildings b ON b.id = CASE WHEN p.id = 130 THEN 11 ELSE p.building_id END
        WHERE p.status = 'approved'
          AND ({nb_clauses})
          AND p.price_monthly BETWEEN :min_b AND :max_b
          {rooms_clause}
        ORDER BY p.price_monthly {sort_order}
        {limit_clause}
    """

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except Exception:
        logger.warning("DB search_properties query failed", exc_info=True)
        return []

    results = _format_rows(rows)

    logger.info(
        "DB search: neighborhoods=%r rooms=%s budget %s-%s SAR → %d results",
        neighborhoods, rooms_count, min_budget, max_budget, len(results),
    )
    return results


def price_range(
    neighborhoods: "list[str] | str",
    rooms_count: int | None = None,
) -> dict:
    """Return the TRUE min/max monthly price for approved listings matching the
    given neighborhood(s) and (optionally) rooms_count.

    Unlike search_properties (which is capped at LIMIT 10), this is a SQL
    aggregate over ALL matching rows — so the reported range is never truncated.
    Used to quote an accurate price range for the customer's requested type.
    Returns {"count": 0} when nothing matches.
    """
    if isinstance(neighborhoods, str):
        neighborhoods = [n.strip() for n in neighborhoods.split(",") if n.strip()]
    else:
        neighborhoods = [str(n).strip() for n in neighborhoods if str(n).strip()]

    if not neighborhoods:
        return {"count": 0}

    nb_terms = [f"%{nb}%" for nb in neighborhoods]
    nb_clauses = " OR ".join(
        f"b.name LIKE :nb{i} OR p.title LIKE :nb{i}" for i in range(len(nb_terms))
    )
    params: dict = {f"nb{i}": t for i, t in enumerate(nb_terms)}

    rooms_clause = ""
    if rooms_count is not None:
        rooms_clause = "AND p.rooms_count = :rooms"
        params["rooms"] = int(rooms_count)

    sql = f"""
        SELECT
            COUNT(*)              AS cnt,
            MIN(p.price_monthly)  AS min_price,
            MAX(p.price_monthly)  AS max_price
        FROM properties p
        LEFT JOIN buildings b ON b.id = CASE WHEN p.id = 130 THEN 11 ELSE p.building_id END
        WHERE p.status = 'approved'
          AND p.price_monthly IS NOT NULL
          AND ({nb_clauses})
          {rooms_clause}
    """

    try:
        with engine.connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
    except Exception:
        logger.warning("DB price_range query failed", exc_info=True)
        return {"count": 0}

    count = int(row["cnt"]) if row and row["cnt"] is not None else 0
    if count == 0:
        return {"count": 0}

    return {
        "count": count,
        "price_min": float(row["min_price"]) if row["min_price"] is not None else None,
        "price_max": float(row["max_price"]) if row["max_price"] is not None else None,
    }


def search_upcoming_properties(
    neighborhoods: "list[str] | str",
    max_budget: int,
    min_budget: int = 0,
    rooms_count: int | None = None,
    days_ahead: int = 30,
):
    """Find properties whose current rental ends within *days_ahead* days.

    These are apartments that will become available soon — useful when no
    currently-available apartment matches the customer's criteria.
    """
    min_budget = int(min_budget) if min_budget is not None else 0
    max_budget = int(max_budget) if max_budget is not None else 10 ** 9

    if isinstance(neighborhoods, str):
        neighborhoods = [n.strip() for n in neighborhoods.split(",") if n.strip()]
    else:
        neighborhoods = [str(n).strip() for n in neighborhoods if str(n).strip()]

    if not neighborhoods:
        return []

    nb_terms = [f"%{nb}%" for nb in neighborhoods]
    nb_clauses = " OR ".join(
        f"b.name LIKE :nb{i} OR p.title LIKE :nb{i}" for i in range(len(nb_terms))
    )
    params: dict = {f"nb{i}": t for i, t in enumerate(nb_terms)}
    params["min_b"] = min_budget
    params["max_b"] = max_budget
    params["days"] = int(days_ahead)

    rooms_clause = ""
    if rooms_count is not None:
        rooms_clause = "AND p.rooms_count = :rooms"
        params["rooms"] = int(rooms_count)

    sql = f"""
        SELECT
            p.id,
            p.title,
            p.location,
            b.name          AS building_name,
            p.price_monthly AS monthly_price,
            p.price_semi_annual,
            p.price_annual,
            p.description,
            p.rooms_count,
            p.baths_count,
            p.area,
            p.supervisor_phone,
            p.guard_phone,
            p.canonical_url,
            p.rented_until
        FROM properties p
        LEFT JOIN buildings b ON b.id = CASE WHEN p.id = 130 THEN 11 ELSE p.building_id END
        WHERE p.status = 'approved'
          AND p.rented_until IS NOT NULL
          AND p.rented_until BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL :days DAY)
          AND ({nb_clauses})
          AND p.price_monthly BETWEEN :min_b AND :max_b
          {rooms_clause}
        ORDER BY p.rented_until ASC
        LIMIT 5
    """

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
    except Exception:
        logger.warning("DB search_properties query failed", exc_info=True)
        return []

    results = _format_rows(rows)

    # Add days_until_available to each result
    from datetime import date
    today = date.today()
    for r in results:
        if r.get("rented_until"):
            delta = r["rented_until"] - today
            r["days_until_available"] = max(delta.days, 0)
            r["rented_until"] = str(r["rented_until"])

    logger.info(
        "DB upcoming: neighborhoods=%r rooms=%s budget %s-%s SAR within %d days → %d results",
        neighborhoods, rooms_count, min_budget, max_budget, days_ahead, len(results),
    )
    return results
