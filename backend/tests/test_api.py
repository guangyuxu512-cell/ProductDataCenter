from fastapi.testclient import TestClient
import pytest

from app.core.config import get_settings
from app.main import create_application
from app.modules.products.api import get_service
from app.modules.products.service import ProductService


class FakeRepository:
    def list(self, options):
        return {"items": [{"product_id": "3760269504500859111", "source_platform": "douyin", "title": "商品",
            "current_price_min": "19.99", "current_price_max": "19.99"}],
            "total": 1 if options.include_total else None, "totalIncluded": options.include_total,
            "limit": options.limit, "offset": options.offset}

    def groups(self):
        return []

    def detail(self, product_id):
        return None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", "isolated-test-token")
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("BACKEND_ENABLE_GROUP_WRITES", "false")
    get_settings.cache_clear()
    app = create_application()
    app.dependency_overrides[get_service] = lambda: ProductService(FakeRepository(), get_settings())
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


AUTH = {"Authorization": "Bearer isolated-test-token"}


def test_authentication_is_required(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/products").status_code == 401
    assert client.get("/api/v1/products", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_list_preserves_string_id_money_and_optional_total(client):
    response = client.get("/api/v1/products?includeTotal=false", headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["product_id"] == "3760269504500859111"
    assert data["items"][0]["current_price_min"] == "19.99"
    assert data["total"] is None and data["totalIncluded"] is False
    assert response.headers["X-Request-ID"]


def test_invalid_date_returns_meaningful_error(client):
    response = client.get("/api/v1/products?capturedFromTime=2026-10-26T10:00:01&capturedToTime=2026-10-26T10:00:00", headers=AUTH)
    assert response.status_code == 400
    assert "不能晚于" in response.json()["message"]


def test_group_writes_default_off_and_detail_not_found(client):
    assert client.get("/api/v1/capabilities", headers=AUTH).json()["groupWrites"] is False
    assert client.post("/api/v1/product-groups", json={"name": "test"}, headers=AUTH).status_code == 403
    response = client.get("/api/v1/products/3760269504500859111", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["code"] == "PRODUCT_NOT_FOUND"


def test_unconfigured_token_fails_closed(client, monkeypatch):
    monkeypatch.delenv("BACKEND_API_TOKEN")
    get_settings.cache_clear()
    assert client.get("/api/v1/products", headers=AUTH).status_code == 503
