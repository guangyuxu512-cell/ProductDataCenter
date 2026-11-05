"""Resolve the platform's real no-brand option without inventing identifiers."""

from __future__ import annotations


NO_BRAND_LABEL = "无品牌"


def no_brand_selection(attributes) -> dict | None:
    brands = [field for field in attributes
              if str(getattr(field, "label", "")).strip() == "品牌"
              and getattr(field, "ruleStatus", "unknown") == "confirmed"
              and getattr(field, "control", "unknown") == "single"]
    if len(brands) != 1:
        return None
    matches = [option for option in brands[0].options if option.label.strip() == NO_BRAND_LABEL]
    if len(matches) != 1 or not matches[0].value.strip():
        return None
    return {"fieldId": brands[0].id, "fieldName": brands[0].label,
            "valueId": matches[0].value, "valueName": matches[0].label}
