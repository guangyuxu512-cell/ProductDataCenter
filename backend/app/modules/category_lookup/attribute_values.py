"""Interpret existing values only against explicit platform form metadata."""
from decimal import Decimal, InvalidOperation
import re


UNVERIFIED = "__unverified__"


def normalize_multi_values(field, values):
    if getattr(field, "control", None) != "multi" or getattr(field, "ruleStatus", None) != "confirmed":
        return values
    by_name = {}
    for option in field.options:
        by_name.setdefault(option.label.strip(), []).append(option)
    result = []
    for value in values:
        name, value_id = value["name"], value["valueId"]
        matching_id = [option for option in field.options if option.value == value_id and value_id not in ("", "0")]
        if len(matching_id) == 1:
            result.append({"valueId": matching_id[0].value, "name": matching_id[0].label})
            continue
        matching_name = by_name.get(name, [])
        if value_id in ("", "0") and len(matching_name) == 1:
            result.append({"valueId": matching_name[0].value, "name": matching_name[0].label})
            continue
        # Legacy bundles sometimes join multiple labels into one value. Only
        # split when every piece unambiguously matches this field's options.
        parts = [part.strip() for part in re.split(r"[|、,，;；]", name)]
        if value_id in ("", "0") and len(parts) > 1 and all(len(by_name.get(part, [])) == 1 for part in parts):
            result.extend({"valueId": by_name[part][0].value, "name": by_name[part][0].label} for part in parts)
        else:
            result.append(value)
    seen = set()
    return [value for value in result if not ((key := (value["valueId"], value["name"])) in seen or seen.add(key))]


def measure_valid(value: str, templates) -> bool:
    for template in templates:
        patterns = []
        for index, module in enumerate(template.modules):
            prefix = re.escape(module.prefix)
            suffix = r"[xX×*]" if module.suffix in ("*", "×", "x", "X") else re.escape(module.suffix)
            units = sorted((re.escape(unit.label) for unit in module.units), key=len, reverse=True)
            unit = "(?:" + "|".join(units) + ")" if units else ""
            patterns.append(r"\s*" + prefix + rf"\s*(?P<n{index}>[+-]?(?:\d+(?:\.\d*)?|\.\d+))?\s*"
                            + (rf"(?P<u{index}>{unit})?" if unit else "") + r"\s*" + suffix)
        match = re.fullmatch("".join(patterns) + r"\s*", value)
        if not match:
            continue
        valid = True
        has_number = False
        for index, module in enumerate(template.modules):
            number = match.group(f"n{index}")
            unit = match.groupdict().get(f"u{index}")
            if (module.required and not number) or (number and module.units and not unit) or (unit and not number):
                valid = False
                break
            if not number:
                continue
            has_number = True
            try:
                decimal = Decimal(number)
                digits = max(-decimal.as_tuple().exponent, 0)
                if (not decimal.is_finite()
                    or (module.dataType == "int" and decimal != decimal.to_integral_value())
                    or (module.minimum is not None and decimal < Decimal(str(module.minimum)))
                    or (module.maximum is not None and decimal > Decimal(str(module.maximum)))
                    or (module.precision is not None and digits > module.precision)):
                    valid = False
                    break
            except InvalidOperation:
                valid = False
                break
        if valid and has_number:
            return True
    return False
