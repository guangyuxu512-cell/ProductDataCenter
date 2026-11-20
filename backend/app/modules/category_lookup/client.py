"""Category definitions returned by the authorized local Worker."""
import re
from uuid import UUID

from app.core.config import Settings
from .worker_lookup import LookupError, lookup


class DouyinCategoryClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def search(self, shop_id: UUID, keyword: str) -> list[dict]:
        return lookup(self.settings, operation="search", category_id="0", title=keyword, shop_id=shop_id)

    def predict(self, shop_id: UUID, title: str, image_url: str) -> dict:
        return lookup(self.settings, operation="predict", category_id="0", title=title,
                      image_url=image_url, shop_id=shop_id)

    def category_options(self, shop_id: UUID, parent_id: str) -> list[dict]:
        return lookup(self.settings, operation="tree", category_id=parent_id, title="商品", shop_id=shop_id)

    def schema(self, shop_id: UUID, category_id: str, title: str) -> list[dict]:
        return lookup(self.settings, operation="schema", category_id=category_id,
                      title=title or "商品", shop_id=shop_id)


def normalize_category_options(value, parent_id: str) -> list[dict]:
    """Keep the platform's explicit tree relationships and leaf flags."""
    if not isinstance(value, list) or len(value) > 10000:
        raise LookupError("invalid_tree")
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise LookupError("invalid_tree")
        cid = item.get("id")
        name = item.get("name")
        leaf = item.get("is_leaf")
        parent = item.get("parent_cid")
        if (isinstance(cid, bool) or not re.fullmatch(r"[0-9]{1,20}", str(cid or ""))
                or not isinstance(name, str) or not name.strip() or len(name) > 300
                or not isinstance(leaf, bool)
                or (parent is not None and str(parent) != parent_id)):
            raise LookupError("invalid_tree")
        identity = str(cid)
        if identity in seen:
            continue
        seen.add(identity)
        result.append({"id": identity, "name": name.strip(), "isLeaf": leaf,
                       "enabled": item.get("enable", 1) not in (0, False)})
    return result


def normalize_predictions(data: dict) -> dict:
    """Preserve platform category IDs at every level; do not choose a candidate."""
    entries = data.get("candidate_category_details")
    if entries is None:
        entries = []
    if not isinstance(entries, list) or len(entries) > 200:
        raise LookupError("invalid_response")
    candidates, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise LookupError("invalid_response")
        levels = []
        ended = False
        for prefix in ("first", "second", "third", "fourth"):
            raw_id = entry.get(prefix + "_cid")
            name = entry.get(prefix + "_cname")
            missing = raw_id is None or raw_id == "" or raw_id == 0 or raw_id == "0"
            if missing:
                ended = True
                continue
            identity = str(raw_id)
            if (ended or isinstance(raw_id, bool) or not re.fullmatch(r"[0-9]{1,20}", identity) or not identity.strip("0")
                    or not isinstance(name, str) or not name.strip() or len(name) > 300):
                raise LookupError("invalid_response")
            levels.append({"id": identity, "name": name.strip()})
        if not levels:
            raise LookupError("invalid_response")
        identity = levels[-1]["id"]
        if identity in seen:
            continue
        seen.add(identity)
        deleted = entry.get("deleted")
        forbidden = entry.get("forbidden_status")
        if deleted in (True, 1, "1") or forbidden not in (None, False, 0, "", "0"):
            selectable = False
        elif deleted in (False, 0) and forbidden in (False, 0, "0"):
            selectable = True
        else:
            selectable = None
        candidates.append({"id": identity, "name": levels[-1]["name"],
                           "path": " > ".join(level["name"] for level in levels), "levels": levels,
                           "selectable": selectable})
    explicit = data.get("predict_cid")
    recommended_id = str(explicit) if not isinstance(explicit, bool) and str(explicit or "").isdigit() else None
    if recommended_id and (not recommended_id.strip("0") or recommended_id not in seen):
        recommended_id = None
    if recommended_id and next(item for item in candidates if item["id"] == recommended_id)["selectable"] is not True:
        recommended_id = None
    return {"candidates": candidates, "recommendedId": recommended_id}




def normalize_measure_templates(raw) -> list[dict]:
    """Preserve supported platform measure modules; never infer them from labels."""
    if not isinstance(raw, list) or not raw:
        return []
    templates = []
    for template in raw:
        if not isinstance(template, dict) or not isinstance(template.get("value_modules"), list):
            return []
        modules = []
        for module in template["value_modules"]:
            if not isinstance(module, dict) or module.get("input_type") != "input":
                return []
            rule = module.get("validate_rule")
            if not isinstance(rule, dict) or rule.get("data_type") not in {"float", "int"}:
                return []
            # Unknown linkage or per-unit validation must not be treated as
            # validated until its platform semantics have been implemented.
            if module.get("unit_linkage") not in (None, {}) or rule.get("unit_rules") not in (None, []):
                return []
            units = module.get("unit_options")
            if not isinstance(units, list):
                return []
            if any(not isinstance(unit, dict) or not isinstance(unit.get("label"), str)
                   or not isinstance(unit.get("value"), (str, int)) or isinstance(unit.get("value"), bool)
                   for unit in units):
                return []
            minimum, maximum, precision = rule.get("min"), rule.get("max"), rule.get("precision")
            if (any(value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool))
                    for value in (minimum, maximum))
                    or (precision is not None and (not isinstance(precision, int) or isinstance(precision, bool) or precision < 0))):
                return []
            modules.append({"id": str(module.get("module_id") or ""), "prefix": str(module.get("prefix") or ""),
                            "suffix": str(module.get("suffix") or ""), "required": module.get("value_required") is True,
                            "requiredTips": str(module.get("required_tips") or ""),
                            "placeholder": str(module.get("module_shading_words") or ""),
                            "units": [{"label": unit["label"], "value": str(unit["value"])} for unit in units],
                            "dataType": rule["data_type"], "minimum": minimum, "maximum": maximum,
                            "precision": precision})
        if not modules:
            return []
        templates.append({"id": str(template.get("template_id") or ""),
                          "name": str(template.get("display_name") or ""), "modules": modules})
    return templates


def normalize_multi_measure(raw) -> dict | None:
    """Recognize the platform's enum-with-custom-value plus numeric-unit form.

    Other module structures remain unknown until their format is documented by
    a real response; do not infer them from the attribute's label.
    """
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        return None
    modules = raw[0].get("value_modules")
    if not isinstance(modules, list) or len(modules) != 2 or not all(isinstance(x, dict) for x in modules):
        return None
    enum, number = modules
    enum_rule = enum.get("validate_rule")
    if (enum.get("input_type") != "enum_diy" or not isinstance(enum_rule, dict)
            or enum_rule.get("data_type") != "string" or enum.get("value_required") is not True
            or enum.get("prefix") not in (None, "") or enum.get("suffix") not in (None, "")
            or enum.get("unit_options") not in (None, []) or enum.get("unit_linkage") not in (None, {})
            or enum_rule.get("unit_rules") not in (None, [])
            or any(enum_rule.get(key) is not None for key in ("min", "max", "precision"))
            or number.get("value_required") is not True or number.get("prefix") not in (None, "")
            or number.get("suffix") not in (None, "")):
        return None
    normalized = normalize_measure_templates([{"template_id": raw[0].get("template_id"),
        "display_name": raw[0].get("display_name"), "value_modules": [number]}])
    if (not normalized or not normalized[0]["modules"][0]["units"]
            or any(not unit["label"].strip() for unit in normalized[0]["modules"][0]["units"])):
        return None
    measure = normalized[0]["modules"][0]
    return {key: measure[key] for key in ("units", "minimum", "maximum", "precision", "dataType")}


def normalize_options(raw) -> list[dict]:
    """Normalize option IDs and labels without inferring platform values."""
    options, option_ids = [], set()
    for option in raw if isinstance(raw, list) else []:
        if not isinstance(option, dict):
            continue
        name = option.get("value_name") or option.get("label") or option.get("name") or option.get("text")
        val = option.get("value_id", option.get("value", option.get("id")))
        if isinstance(name, str) and isinstance(val, (str, int)) and not isinstance(val, bool):
            identity = str(val)[:200]
            if identity not in option_ids:
                option_ids.add(identity)
                options.append({"label": name[:200], "value": identity})
    return options


def normalize_fields(items: list) -> list[dict]:
    fields = []
    # The platform response is already capped by MAX_BYTES. Do not silently
    # discard later attributes or options from an otherwise valid response.
    for item in items:
        if not isinstance(item, dict) or item.get("hidden") is True or item.get("available") is False:
            continue
        key = item.get("id")
        if not isinstance(key, (str, int)) or isinstance(key, bool) or not str(key).strip():
            continue
        label = item.get("label") or item.get("name") or str(key)
        if not isinstance(label, str):
            continue
        options = normalize_options(item.get("options"))

        # The current Douyin form response keeps the actual editor capability
        # in ``additions``.  In particular, ``ui_type=multi_select`` controls
        # multiplicity and ``diy_type=1`` permits a user-created value.  Older
        # captures used explicit top-level flags, so keep that narrow fallback.
        # Missing metadata is deliberately ``unknown``: absence is not proof
        # that the platform forbids a source value.
        additions = item.get("additions") if isinstance(item.get("additions"), dict) else {}
        ui_type = additions.get("ui_type")
        diy_type = additions.get("diy_type")
        control = "unknown"
        allow_custom = None
        rule_status = "unknown"
        measure_templates = []
        multi_measure = None
        if ui_type in {"select", "search", "multi_select"}:
            control = "multi" if ui_type == "multi_select" else "single"
            if diy_type in (0, "0", False):
                allow_custom = False
                rule_status = "confirmed"
            elif diy_type in (1, "1", True):
                allow_custom = True
                rule_status = "confirmed"
        elif ui_type == "text":
            control, allow_custom, rule_status = "text", False, "confirmed"
        elif ui_type == "number":
            control, allow_custom, rule_status = "number", False, "confirmed"
        elif ui_type == "measure":
            measure_templates = normalize_measure_templates(additions.get("measure_templates"))
            if measure_templates:
                control, allow_custom, rule_status = "measure", False, "confirmed"
        elif ui_type == "multi_value_measure" and diy_type in (1, "1", True):
            multi_measure = normalize_multi_measure(additions.get("measure_templates"))
            if multi_measure:
                control, allow_custom, rule_status = "multi_measure", True, "confirmed"
                # For this confirmed platform control, the enum module owns
                # the choices.  Its values are not necessarily the numeric
                # IDs found in the attribute's top-level options.  Prefer the
                # nested list as one set, avoiding duplicate labels with two
                # different IDs.  Older Worker results omit it entirely.
                enum = additions["measure_templates"][0]["value_modules"][0]
                nested_options = normalize_options(enum.get("value_options"))
                if nested_options:
                    options = nested_options
        elif ui_type is None:
            field_type = item.get("type")
            if options and isinstance(item.get("multiple"), bool):
                control = "multi" if item["multiple"] else "single"
                if isinstance(item.get("allow_create"), bool):
                    allow_custom = item["allow_create"]
                    rule_status = "confirmed"
            elif not options and field_type in {"text", "number"}:
                control, allow_custom, rule_status = field_type, False, "confirmed"
        limits = [rule.get("value") for rule in item.get("rules", [])
                  if isinstance(rule, dict) and rule.get("type") == "max_input_num"
                  and isinstance(rule.get("value"), int) and not isinstance(rule.get("value"), bool)
                  and rule["value"] > 0] if isinstance(item.get("rules"), list) else []
        field = {"id": str(key)[:100], "label": label[:200], "required": item.get("required") in (True, 1),
                 "options": options, "control": control, "allowCustom": allow_custom, "ruleStatus": rule_status}
        if limits:
            field["maxValues"] = min(limits)
        if measure_templates:
            field["measureTemplates"] = measure_templates
        if multi_measure:
            field["multiMeasureRule"] = multi_measure
        fields.append(field)
    return fields
