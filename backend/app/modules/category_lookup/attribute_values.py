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


def multi_measure_valid(value: str, rule, options=()) -> bool | None:
    """Validate a composite value; None means the joined text is ambiguous."""
    if rule is None or not rule.units:
        return False
    units = sorted((unit.label for unit in rule.units if unit.label), key=len, reverse=True)
    text = value.strip()
    unit = next((unit for unit in units if text.endswith(unit)), None)
    if not unit:
        return False
    text = text[:-len(unit)].strip()
    numeric = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")

    def valid_number(raw):
        try:
            number = Decimal(raw)
            decimals = max(-number.as_tuple().exponent, 0)
            return (number.is_finite() and (rule.dataType != "int" or number == number.to_integral_value())
                    and (rule.minimum is None or number >= Decimal(str(rule.minimum)))
                    and (rule.maximum is None or number <= Decimal(str(rule.maximum)))
                    and (rule.precision is None or decimals <= rule.precision))
        except InvalidOperation:
            return False

    # Prefer an actual platform option when it uniquely defines the boundary.
    known = {text[len(option.label):].strip() for option in options
             if option.label and text.startswith(option.label)
             and numeric.fullmatch(text[len(option.label):].strip())}
    if len(known) == 1:
        return valid_number(next(iter(known)))
    if len(known) > 1:
        return None
    # Custom enum values may themselves end in digits. Only accept them when
    # exactly one split satisfies the explicit platform number rules.
    candidates = {(text[:index].strip(), text[index:].strip()) for index in range(1, len(text))
                  if text[:index].strip() and numeric.fullmatch(text[index:].strip())}
    valid = [(name, number) for name, number in candidates if valid_number(number)]
    return True if len(valid) == 1 else None if len(valid) > 1 else False


def multi_measure_parts(value: str, rule, options=()) -> tuple[str, Decimal] | None:
    """Resolve a valid material value only when the name/amount boundary is unique."""
    if multi_measure_valid(value, rule, options) is not True:
        return None
    text = value.strip()
    units = sorted((unit.label for unit in rule.units if unit.label), key=len, reverse=True)
    unit = next((unit for unit in units if text.endswith(unit)), None)
    if not unit:
        return None
    text = text[:-len(unit)].strip()
    numeric = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
    known = {(option.label, text[len(option.label):].strip()) for option in options
             if option.label and text.startswith(option.label)
             and numeric.fullmatch(text[len(option.label):].strip())}
    if len(known) == 1:
        name, number = next(iter(known))
        return name, Decimal(number)
    if len(known) > 1:
        return None
    candidates = []
    for index in range(1, len(text)):
        name, number = text[:index].strip(), text[index:].strip()
        if not name or not numeric.fullmatch(number):
            continue
        decimal = Decimal(number)
        digits = max(-decimal.as_tuple().exponent, 0)
        if (decimal.is_finite() and (rule.dataType != "int" or decimal == decimal.to_integral_value())
                and (rule.minimum is None or decimal >= Decimal(str(rule.minimum)))
                and (rule.maximum is None or decimal <= Decimal(str(rule.maximum)))
                and (rule.precision is None or digits <= rule.precision)):
            candidates.append((name, decimal))
    return candidates[0] if len(candidates) == 1 else None
