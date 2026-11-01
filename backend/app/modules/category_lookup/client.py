"""Read-only Douyin category lookup using an authorized central Session."""

import json
import logging
import re
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.core.config import Settings
from app.modules.central.client import CentralShopSession


BASE = "https://fxg.jinritemai.com"
REFERER = BASE + "/ffa/g/create"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
MAX_BYTES = 3 * 1024 * 1024
_ALLOWED_SIGNER_HOSTS = {"product-cloud-signer-v1-product-signer-1", "product-signer"}


class _RedactHttpxUrls(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg == 'HTTP Request: %s %s "%s %d %s"' and isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[1] = str(args[1]).split("?", 1)[0]
            record.args = tuple(args)
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(item, _RedactHttpxUrls) for item in _httpx_logger.filters):
    _httpx_logger.addFilter(_RedactHttpxUrls())


class LookupError(Exception):
    def __init__(self, reason: str, platform_code: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.platform_code = platform_code


class DouyinCategoryClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def search(self, session: CentralShopSession, keyword: str) -> list[dict]:
        payload = self._call(session, "GET", "/product/tproduct/searchCategoryN", "165756507732",
                             {"key": keyword, "search_type": 1})
        return normalize_candidates(payload.get("data"))

    def schema(self, session: CentralShopSession, category_id: str, title: str) -> list[dict]:
        body = {
            "context": {"feature": {"session_publish_id": "helper_" + uuid4().hex,
                                    "image_smart_publish_info": "[]"},
                        "operation_type": "select_normal,normal", "category_id": category_id, "ability": []},
            "model": {"pic": {"value": []}, "title": {"value": title or "商品"},
                      "goods_category_appeal": {"value": False}},
            "appid": 1, "_bid": "ffa_goods", "_lid": "029388877158",
        }
        payload = self._call(session, "POST", "/product/tproduct/getSchema", "029388877158", {}, body)
        model = payload.get("data", {}).get("model", {}) if isinstance(payload.get("data"), dict) else {}
        group = model.get("category_properties", {}) if isinstance(model, dict) else {}
        items = group.get("items") if isinstance(group, dict) else None
        if not isinstance(items, list):
            raise LookupError("invalid_schema")
        return normalize_fields(items)

    def _signer(self) -> tuple[str, str]:
        if not self.settings.douyin_category_lookup_enabled:
            raise LookupError("not_configured")
        try:
            url = urlsplit(self.settings.douyin_signer_url)
            port = url.port
            key_file = self.settings.douyin_signer_key_file
            if (url.scheme != "http" or url.hostname not in _ALLOWED_SIGNER_HOSTS or port != 8787
                    or url.username is not None or url.password is not None or url.path not in ("", "/")
                    or url.query or url.fragment or key_file is None):
                raise ValueError()
            with key_file.open("r", encoding="ascii") as handle:
                key = handle.read(1025).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", key):
                raise ValueError()
        except (ValueError, OSError, UnicodeError):
            raise LookupError("invalid_configuration") from None
        return self.settings.douyin_signer_url.rstrip("/"), key

    def _call(self, session: CentralShopSession, method: str, path: str, lid: str,
              extra: dict, body: dict | None = None) -> dict:
        signer_url, signer_key = self._signer()
        cookies = httpx.Cookies()
        fp = ""
        for item in session.cookies:
            domain = (item.domain or "").lstrip(".").lower()
            if domain != "jinritemai.com" and not domain.endswith(".jinritemai.com"):
                continue
            value = item.value.get_secret_value()
            cookies.set(item.name, value, domain=item.domain or "", path=item.path or "/")
            if item.name == "s_v_web_id":
                fp = value
        params = {"appid": 1, "_bid": "ffa_goods", "_lid": lid, **extra}
        if fp:
            params.update({"verifyFp": fp, "fp": fp})
        headers = {"accept": "application/json, text/plain, */*", "accept-language": "zh-CN,zh;q=0.9",
                   "user-agent": USER_AGENT, "referer": REFERER, "origin": BASE,
                   "x-tt-from-end": "PC", "x-tt-from-appid": "ffa-goods"}
        content = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if content is not None:
            headers["content-type"] = "application/json;charset=UTF-8"
        try:
            with httpx.Client(timeout=20, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                request = client.build_request(method, BASE + path, params=params, headers=headers,
                                               cookies=cookies, content=content)
                cookie = request.headers.get("cookie", "")
                if not cookie:
                    raise LookupError("session_unavailable")
                for _ in range(2):
                    sign_body = {"host": "fxg.jinritemai.com", "full_url": str(request.url), "method": method,
                                 "user_agent": USER_AGENT, "referer": REFERER, "cookie": cookie, "aid": 4272}
                    if "msToken" in request.url.params:
                        sign_body["ms_token"] = request.url.params["msToken"]
                    if content is not None:
                        sign_body["body"] = content.decode()
                    signed = client.post(signer_url + "/sign", headers={"X-API-Key": signer_key}, json=sign_body)
                    if signed.status_code != 200:
                        raise LookupError("signer_unavailable")
                    data = signed.json()
                    if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("a_bogus"), str) or not data["a_bogus"]:
                        raise LookupError("signer_unavailable")
                    ms_token = data.get("msToken")
                    if isinstance(ms_token, str) and ms_token and "msToken" not in request.url.params:
                        request.url = request.url.copy_add_param("msToken", ms_token)
                        continue
                    request.url = request.url.copy_add_param("a_bogus", data["a_bogus"])
                    break
                else:
                    raise LookupError("signer_unavailable")
                response = client.send(request, stream=True)
                try:
                    if response.status_code != 200:
                        raise LookupError("platform_unavailable")
                    content_bytes = bytearray()
                    for chunk in response.iter_bytes():
                        content_bytes.extend(chunk)
                        if len(content_bytes) > MAX_BYTES:
                            raise LookupError("invalid_response")
                finally:
                    response.close()
                payload = json.loads(content_bytes)
        except LookupError:
            raise
        except (httpx.HTTPError, OSError, ValueError, TypeError):
            raise LookupError("platform_unavailable") from None
        if not isinstance(payload, dict):
            raise LookupError("invalid_response")
        code = payload.get("code", payload.get("st", payload.get("errno")))
        if isinstance(code, str) and code.isdecimal():
            code = int(code)
        if not isinstance(code, int) or isinstance(code, bool):
            raise LookupError("invalid_response")
        if code != 0:
            raise LookupError("platform_rejected", code)
        return payload


def normalize_candidates(value) -> list[dict]:
    """Extract explicit category ids/names without choosing a candidate."""
    result, seen = [], set()
    path_keys = ("category_list", "categoryList", "category_path_list", "categoryPathList", "path_list", "pathList", "paths", "breadcrumb")
    id_keys = ("category_leaf_id", "leaf_cid", "leafCid", "leaf_category_id", "leafCategoryId",
               "third_cid", "thirdCid", "category_id", "categoryId", "cid", "id", "value")
    name_keys = ("category_name", "categoryName", "name", "label", "title", "third_cname", "thirdCname", "leaf_cname", "leafCname")
    path_names = ("category_path", "categoryPath", "category_path_name", "categoryPathName", "full_path", "fullPath", "path", "full_name", "fullName", "category_full_name", "categoryFullName", "category_name_path", "categoryNamePath")
    level_names = (("first_cname", "firstCname", "first_name", "firstName"),
                   ("second_cname", "secondCname", "second_name", "secondName"),
                   ("third_cname", "thirdCname", "third_name", "thirdName"),
                   ("fourth_cname", "fourthCname", "fourth_name", "fourthName"),
                   ("leaf_cname", "leafCname", "leaf_name", "leafName"))

    def walk(node, depth=0):
        if depth > 12 or len(result) >= 200:
            return
        if isinstance(node, list):
            for child in node[:1000]:
                walk(child, depth + 1)
            return
        if not isinstance(node, dict):
            return
        path_items = next((node[k] for k in path_keys if isinstance(node.get(k), list)), [])
        cid = next((node[k] for k in id_keys if str(node.get(k) or "").isdigit()), None)
        if cid is None:
            for item in reversed(path_items):
                if isinstance(item, dict):
                    cid = next((item[k] for k in id_keys if str(item.get(k) or "").isdigit()), None)
                    if cid is not None:
                        break
        name = next((node[k].strip() for k in name_keys if isinstance(node.get(k), str) and node[k].strip()), "")
        path = next((node[k].strip() for k in path_names if isinstance(node.get(k), str) and node[k].strip()), "")
        if not path and path_items:
            path = " > ".join(str(next((item[k] for k in name_keys if item.get(k)), ""))
                              if isinstance(item, dict) else str(item) for item in path_items)
        if not path:
            levels = [next((node[k].strip() for k in keys if isinstance(node.get(k), str) and node[k].strip()), "")
                      for keys in level_names]
            path = " > ".join(value for i, value in enumerate(levels) if value and (i == 0 or value != levels[i - 1]))
        if cid is not None and (name or path) and str(cid) not in seen:
            seen.add(str(cid))
            result.append({"id": str(cid), "name": (name or path)[-200:], "path": (path or name)[:500]})
        for k, child in node.items():
            if k not in path_keys and isinstance(child, (dict, list)):
                walk(child, depth + 1)
    walk(value)
    return result


def normalize_fields(items: list) -> list[dict]:
    fields = []
    for item in items[:1000]:
        if not isinstance(item, dict) or item.get("hidden") is True or item.get("available") is False:
            continue
        key = item.get("id")
        if not isinstance(key, (str, int)) or isinstance(key, bool) or not str(key).strip():
            continue
        label = item.get("label") or item.get("name") or str(key)
        if not isinstance(label, str):
            continue
        options = []
        for option in item.get("options", []) if isinstance(item.get("options"), list) else []:
            if not isinstance(option, dict):
                continue
            name = option.get("value_name") or option.get("label") or option.get("name") or option.get("text")
            val = option.get("value_id", option.get("value", option.get("id")))
            if isinstance(name, str) and isinstance(val, (str, int)) and not isinstance(val, bool):
                options.append({"label": name[:200], "value": str(val)[:200]})
        fields.append({"id": str(key)[:100], "label": label[:200], "required": item.get("required") in (True, 1),
                       "options": options[:500]})
    return fields
