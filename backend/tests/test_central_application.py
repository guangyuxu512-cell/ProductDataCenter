from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_application
from app.modules.central.api import get_central_client
from app.modules.central.client import CentralApplicationClient, CentralConnectionError


APPLICATION_TOKEN = "synthetic-application-token-0123456789abcdef"
PRODUCT_TOKEN = "synthetic-product-token-0123456789abcdef"
RPA_TOKEN = "synthetic-rpa-token"
COOKIE_VALUE = "synthetic-store-cookie-never-expose"


@pytest.fixture
def configured(tmp_path):
    token_path = tmp_path / "central_token"
    token_path.write_text(APPLICATION_TOKEN + "\n")
    return Settings(
        _env_file=None, central_application_enabled=True,
        central_application_base_url="https://central.test",
        central_application_token_file=token_path,
        api_token=PRODUCT_TOKEN, rpa_api_token=RPA_TOKEN,
    )


def shop(shop_id, platform="douyin", status="valid"):
    return {"shop_id": str(shop_id), "display_name": "测试店铺", "platform": platform, "session_status": status}


def session(shop_id, platform="douyin"):
    return {"shop_id": str(shop_id), "platform": platform, "session_version": 2,
            "cookies": [{"name": "sessionid", "value": COOKIE_VALUE, "domain": ".jinritemai.com",
                         "httpOnly": True, "path": "/"}]}


def mock_client(settings, handler):
    return CentralApplicationClient(settings, transport=httpx.MockTransport(handler))


def test_contract_reads_shop_list_and_one_session_without_worker_or_secret_repr(configured):
    shop_id = uuid4()
    seen = []

    def handler(request):
        seen.append(str(request.url))
        assert request.headers["X-Application-ID"] == "product-library"
        assert request.headers["Authorization"] == "Bearer " + APPLICATION_TOKEN
        assert request.headers["Cache-Control"] == "no-store"
        if request.url.path.endswith("/session"):
            return httpx.Response(200, json=session(shop_id), headers={"Cache-Control": "no-store"})
        return httpx.Response(200, json=[shop(shop_id)])

    client = mock_client(configured, handler)
    assert client.list_shops()[0].shop_id == shop_id
    context = client.read_session(shop_id, "douyin")
    assert context.shop_id == shop_id and context.session_version == 2
    assert context.cookies[0].value.get_secret_value() == COOKIE_VALUE
    assert context.cookies[0].http_only is True
    assert COOKIE_VALUE not in repr(context)
    assert COOKIE_VALUE not in context.model_dump_json()
    assert APPLICATION_TOKEN not in repr(configured)
    assert len(seen) == 2 and all("/internal/applications/v1/shops" in url for url in seen)


def test_session_identity_platform_and_cache_policy_are_checked(configured):
    shop_id = uuid4()
    for payload, headers in [
        (session(uuid4()), {"Cache-Control": "no-store"}),
        (session(shop_id, "pdd"), {"Cache-Control": "no-store"}),
        (session(shop_id), {}),
        ({**session(shop_id), "cookies": []}, {"Cache-Control": "no-store"}),
    ]:
        client = mock_client(configured, lambda request: httpx.Response(200, json=payload, headers=headers))
        with pytest.raises(CentralConnectionError, match="invalid_response"):
            client.read_session(shop_id, "douyin")


def test_rejects_redirects_without_sending_token_to_another_host(configured):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://other.test/collect"})

    client = mock_client(configured, handler)
    with pytest.raises(CentralConnectionError, match="upstream_unavailable"):
        client.list_shops()
    assert hosts == ["central.test"]


@pytest.mark.parametrize("bad_url", ["http://central.test", "https://u:p@central.test",
                                    "https://central.test/path", "https://central.test/?q=secret"])
def test_rejects_insecure_or_unexpected_base_url_before_request(configured, bad_url):
    configured.central_application_base_url = bad_url
    client = mock_client(configured, lambda request: pytest.fail("unexpected network request"))
    with pytest.raises(CentralConnectionError, match="invalid_configuration"):
        client.list_shops()


def test_bad_or_reused_token_fails_closed_without_leaking(configured):
    configured.central_application_token_file.write_text(PRODUCT_TOKEN)
    client = mock_client(configured, lambda request: pytest.fail("unexpected network request"))
    with pytest.raises(CentralConnectionError) as error:
        client.list_shops()
    assert error.value.reason == "invalid_configuration"
    assert PRODUCT_TOKEN not in repr(error.value)


@pytest.mark.parametrize("response,reason", [
    (httpx.Response(401, text=COOKIE_VALUE), "authentication_failed"),
    (httpx.Response(503, text=COOKIE_VALUE), "upstream_unavailable"),
    (httpx.Response(200, text="invalid " + COOKIE_VALUE), "invalid_response"),
    (httpx.Response(200, content=b"a" * (1024 * 1024 + 1)), "invalid_response"),
])
def test_errors_are_bounded_and_never_expose_response_contents(configured, response, reason):
    client = mock_client(configured, lambda request: response)
    with pytest.raises(CentralConnectionError) as error:
        client.list_shops()
    assert error.value.reason == reason
    assert COOKIE_VALUE not in repr(error.value)


def test_connection_status_is_product_authenticated_and_only_returns_counts(configured, monkeypatch):
    ids = [uuid4() for _ in range(4)]
    payload = [shop(ids[0], status="valid"), shop(ids[1], status="captured"),
               shop(ids[2], status="invalid"), shop(ids[3], platform="pdd", status="valid")]
    client = mock_client(configured, lambda request: httpx.Response(200, json=payload))
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_TOKEN)
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_TOKEN)
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN_FILE", raising=False)
    get_settings.cache_clear()
    app = create_application()
    app.dependency_overrides[get_central_client] = lambda: client
    try:
        with TestClient(app) as api:
            assert api.get("/api/v1/central/status").status_code == 401
            assert api.get("/api/v1/central/status", headers={"Authorization": f"Bearer {RPA_TOKEN}"}).status_code == 401
            response = api.get("/api/v1/central/status", headers={"Authorization": f"Bearer {PRODUCT_TOKEN}"})
            assert response.status_code == 200
            assert response.json() == {"state": "connected", "authorized_shop_count": 4,
                                       "eligible_douyin_shop_count": 2, "reason": None}
            assert response.headers["Cache-Control"] == "no-store"
            assert str(ids[0]) not in response.text and APPLICATION_TOKEN not in response.text
            assert COOKIE_VALUE not in response.text and "测试店铺" not in response.text
            # There is deliberately no browser or RPA endpoint that returns a Session.
            assert api.get(f"/api/v1/central/shops/{ids[0]}/session",
                           headers={"Authorization": f"Bearer {PRODUCT_TOKEN}"}).status_code == 404
    finally:
        get_settings.cache_clear()


def test_disabled_connection_reports_unknown_counts_without_calling_network(monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_TOKEN)
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BACKEND_CENTRAL_APPLICATION_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(create_application()) as api:
            response = api.get("/api/v1/central/status", headers={"Authorization": f"Bearer {PRODUCT_TOKEN}"})
            assert response.json() == {"state": "not_configured", "authorized_shop_count": None,
                                       "eligible_douyin_shop_count": None, "reason": None}
    finally:
        get_settings.cache_clear()


def test_bad_optional_configuration_does_not_break_product_or_rpa(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_TOKEN)
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", RPA_TOKEN)
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("BACKEND_CENTRAL_APPLICATION_ENABLED", "true")
    monkeypatch.setenv("BACKEND_CENTRAL_APPLICATION_BASE_URL", "http://not-allowed.test")
    monkeypatch.setenv("BACKEND_CENTRAL_APPLICATION_TOKEN_FILE", str(tmp_path / "missing"))
    get_settings.cache_clear()
    try:
        with TestClient(create_application()) as api:
            headers = {"Authorization": f"Bearer {PRODUCT_TOKEN}"}
            status = api.get("/api/v1/central/status", headers=headers)
            assert status.json() == {"state": "unavailable", "authorized_shop_count": None,
                                     "eligible_douyin_shop_count": None, "reason": "invalid_configuration"}
            assert api.get("/api/v1/capabilities", headers=headers).status_code == 200
            assert api.get("/rpa/v1/product-groups").status_code == 401
            assert api.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()


def test_invalid_optional_switch_does_not_disable_other_apis(monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", PRODUCT_TOKEN)
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("BACKEND_CENTRAL_APPLICATION_ENABLED", "invalid-flag")
    get_settings.cache_clear()
    try:
        with TestClient(create_application()) as api:
            headers = {"Authorization": f"Bearer {PRODUCT_TOKEN}"}
            status = api.get("/api/v1/central/status", headers=headers)
            assert status.json()["state"] == "unavailable"
            assert status.json()["reason"] == "invalid_configuration"
            assert api.get("/api/v1/capabilities", headers=headers).status_code == 200
            assert api.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()
