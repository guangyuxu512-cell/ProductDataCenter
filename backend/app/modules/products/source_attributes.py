"""Read explicit attributes from the source package without guessing values."""

from itertools import islice


def _text(value, limit: int) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    result = str(value).strip()
    return result if len(result) <= limit else ""


def source_attributes(category_values, format_groups, properties=None) -> list[dict]:
    """Return source facts only, without inferring missing or target values."""
    result: list[dict] = []
    by_id: dict[str, dict] = {}
    ambiguous_ids: set[str] = set()

    def add(identity, name, values):
        identity = _text(identity, 100)
        name = _text(name, 200)
        value_items = []
        seen_values = set()
        for raw in values[:30]:
            if isinstance(raw, dict):
                value_name = _text(raw.get("name", raw.get("value_name", raw.get("label"))), 2000)
                value_id = _text(raw.get("valueId", raw.get("value_id", raw.get("id"))), 200) or "0"
            else:
                value_name = _text(raw, 2000)
                value_id = "0"
            marker = (value_id, value_name)
            if value_name and marker not in seen_values:
                seen_values.add(marker)
                value_items.append({"valueId": value_id, "name": value_name})
        if not name or not value_items or len(result) >= 300:
            return
        # The explicit property-value block is preferred when both formats
        # contain the same attribute; do not merge conflicting descriptions.
        if identity and (identity in by_id or identity in ambiguous_ids):
            return
        item = {"id": identity or None, "name": name,
                "values": [value["name"] for value in value_items], "valueItems": value_items}
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
                add(identity, next(iter(names)), [
                    {"valueId": entry.get("value_id"), "name": entry.get("value_name")} for entry in rows
                ])
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
    # Newer PDD source packages carry properties in product.properties.
    if isinstance(properties, list):
        for item in properties[:300]:
            if isinstance(item, dict) and isinstance(item.get("values"), list):
                add(item.get("propertyId"), item.get("key"), item["values"])
    return result
