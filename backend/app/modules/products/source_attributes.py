"""Read the explicit product attributes in a Douyin source package."""

from itertools import islice


def _text(value, limit: int) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    result = str(value).strip()
    return result if len(result) <= limit else ""


def source_attributes(category_values, format_groups) -> list[dict]:
    """Return source facts only, without inferring missing or target values."""
    result: list[dict] = []
    by_id: dict[str, dict] = {}
    ambiguous_ids: set[str] = set()

    def add(identity, name, values):
        identity = _text(identity, 100)
        name = _text(name, 200)
        values = list(dict.fromkeys(value for value in (_text(v, 2000) for v in values[:30]) if value))
        if not name or not values or len(result) >= 300:
            return
        # The explicit property-value block is preferred when both formats
        # contain the same attribute; do not merge conflicting descriptions.
        if identity and (identity in by_id or identity in ambiguous_ids):
            return
        item = {"id": identity or None, "name": name, "values": values}
        result.append(item)
        if identity:
            by_id[identity] = item

    if isinstance(category_values, dict):
        for identity, entries in islice(category_values.items(), 300):
            if not isinstance(entries, list):
                continue
            rows = [entry for entry in entries[:30] if isinstance(entry, dict)]
            names = {_text(entry.get("k"), 200) for entry in rows} - {""}
            if len(names) == 1:
                add(identity, next(iter(names)), [entry.get("value_name") for entry in rows])
            elif len(names) > 1:
                ambiguous_ids.add(_text(identity, 100))

    if isinstance(format_groups, list):
        for group in format_groups[:100]:
            fields = group.get("format") if isinstance(group, dict) else None
            if not isinstance(fields, list):
                continue
            for field in fields[:300]:
                if not isinstance(field, dict) or not isinstance(field.get("message"), list):
                    continue
                values = [message.get("desc") for message in field["message"][:30] if isinstance(message, dict)]
                add(field.get("property_id"), field.get("name"), values)
    return result
