"""Helpers for identifying the apartment types used by the chat inventory."""

import re


TYPE_LABELS = {
    "studio": "استوديو",
    "one_bedroom": "غرفة وصالة",
    "two_bedroom": "غرفتين وصالة",
}


def base_neighborhood_name(name: str) -> str:
    """Return the customer-facing neighborhood name without a building number."""
    return re.sub(r"\s+\d+$", "", str(name or "")).strip()


def neighborhood_type_keys(config: dict, neighborhoods: str | list[str] | None = None) -> list[str]:
    """Return types present in the selected neighborhood(s) from DB config."""
    if not neighborhoods:
        return list(config.get("available_types", []))

    if isinstance(neighborhoods, str):
        names = [part.strip() for part in neighborhoods.split(",") if part.strip()]
    else:
        names = [str(part).strip() for part in neighborhoods if str(part).strip()]

    mapping = config.get("available_types_by_neighborhood", {})
    found: list[str] = []
    for name in names:
        for apartment_type in mapping.get(base_neighborhood_name(name), []):
            if apartment_type not in found:
                found.append(apartment_type)
    return found


def neighborhood_type_map(config: dict, neighborhoods: str | list[str] | None = None) -> dict[str, list[str]]:
    """Return the exact available type keys for each selected neighborhood."""
    if not neighborhoods:
        return {}

    if isinstance(neighborhoods, str):
        names = [part.strip() for part in neighborhoods.split(",") if part.strip()]
    else:
        names = [str(part).strip() for part in neighborhoods if str(part).strip()]

    mapping = config.get("available_types_by_neighborhood", {})
    return {
        base_neighborhood_name(name): list(mapping.get(base_neighborhood_name(name), []))
        for name in names
    }


def detect_type(
    title: str | None,
    description: str | None,
    rooms_count: int | None = None,
) -> str:
    """Return the customer-facing apartment type for an inventory row.

    ``rooms_count=1`` is shared by studios and one-bedroom apartments, so the
    title/description must be inspected before falling back to the numeric
    room count.
    """
    text = f"{title or ''} {description or ''}".lower()

    if (
        "غرفتين" in text
        or re.search(r"(?:^|\D)[2٢]\s*غرف", text)
        or rooms_count == 2
    ):
        return "two_bedroom"

    if re.search(r"وصال[ةه]|و\s*صال[ةه]", text):
        return "one_bedroom"

    return "studio"
