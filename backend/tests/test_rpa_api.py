import hashlib
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_application
from app.modules.products.api import get_service
from app.modules.products.service import ProductService

GROUP = UUID("482f31fa-bb52-495e-b479-05eb10ebe532")
PRODUCT = "3760269504500859111"
AUTH = {"Authorization": "Bearer rpa-only-token"}
ADMIN = {"Authorization": "Bearer admin-only-token"}
UU = '{"title":"商品","skus":[{"name":"红色"}]}'.encode()


class FakeRepository:
    def groups(self):
        return [{"groupId": GROUP, "name": "待上架", "productCount": 1}]

    def group_exists(self, group_id):
        return group_id == GROUP

    def list(self, options):
        assert options.group_id == str(GROUP)
        return {"items": [{"product_id": PRODUCT, "source_platform": "douyin", "title": "商品",
                            "main_image_url": "https://example.com/a.webp", "raw_rel_path": "secret-path"}],
                "total": 1 if options.include_total else None, "limit": options.limit, "offset": options.offset}

    def export_rows(self, ids):
        if ids != [PRODUCT]:
            return []
        return [{"product_id": PRODUCT, "uu_rel_path": "", "uu_text": UU.decode()}]

    def exportable_rows(self, ids):
        return self.export_rows(ids)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_TOKEN", "admin-only-token")
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "rpa-only-token")
    monkeypatch.setenv("BACKEND_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN_FILE", raising=False)
    monkeypatch.setenv("BACKEND_ENABLE_GROUP_WRITES", "true")
    get_settings.cache_clear()
    app = create_application()
    app.dependency_overrides[get_service] = lambda: ProductService(FakeRepository(), get_settings())
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_rpa_separate_auth_and_no_writes(client):
    path = "/rpa/v1/product-groups"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=ADMIN).status_code == 401
    assert client.get(path, headers=AUTH).json()["groups"][0]["productCount"] == 1
    assert client.post(path, headers=AUTH, json={"name": "x"}).status_code == 405
    assert client.post("/api/v1/product-groups", headers=AUTH, json={"name": "x"}).status_code == 401


def test_token_missing_or_same_as_admin_fails_closed(client, monkeypatch):
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN")
    get_settings.cache_clear()
    assert client.get("/rpa/v1/product-groups", headers=AUTH).status_code == 503
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "admin-only-token")
    get_settings.cache_clear()
    assert client.get("/rpa/v1/product-groups", headers=ADMIN).status_code == 503


def test_group_products_are_minimal_and_preserve_string_ids(client):
    response = client.get(f"/rpa/v1/product-groups/{GROUP}/products?limit=1&offset=0", headers=AUTH)
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["product_id"] == PRODUCT
    assert "raw_rel_path" not in page["items"][0]
    assert client.get(f"/rpa/v1/product-groups/{UUID(int=0)}/products", headers=AUTH).status_code == 404


def test_uu_bytes_hash_and_version_check(client):
    path = f"/rpa/v1/products/{PRODUCT}/uu"
    response = client.get(path, headers=AUTH)
    assert response.content == UU
    digest = hashlib.sha256(UU).hexdigest()
    assert response.headers["x-uu-sha256"] == digest
    assert client.get(path, headers=AUTH, params={"expected_sha256": digest}).content == UU
    mismatch = client.get(path, headers=AUTH, params={"expected_sha256": "0" * 64})
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "RPA_UU_VERSION_CHANGED"
    assert client.get(path, headers=AUTH, params={"expected_sha256": "x" * 64}).status_code == 400
    assert client.get("/rpa/v1/products/12345678/uu", headers=AUTH).status_code == 404


def test_original_uu_file_bytes_are_not_rewritten(client, tmp_path, monkeypatch):
    original = b'{\r\n  "goodsId": "3760269504500859111"\r\n}\r\n'
    (tmp_path / "product.txt").write_bytes(original)
    monkeypatch.setattr(FakeRepository, "export_rows", lambda self, ids: [{
        "product_id": PRODUCT, "uu_rel_path": "product.txt", "uu_text": "{}",
        "uu_sha256": hashlib.sha256(original).hexdigest(),
    }])
    response = client.get(f"/rpa/v1/products/{PRODUCT}/uu", headers=AUTH)
    assert response.content == original
    assert response.headers["x-uu-sha256"] == hashlib.sha256(original).hexdigest()


def test_saved_draft_cannot_be_silently_served_as_original(client, monkeypatch):
    from app.modules.products.errors import ProductDraftPending

    def unavailable(self, ids):
        raise ProductDraftPending()

    monkeypatch.setattr(FakeRepository, "exportable_rows", unavailable)
    response = client.get(f"/rpa/v1/products/{PRODUCT}/uu", headers=AUTH)
    assert response.status_code == 409
    assert response.json()["code"] == "PRODUCT_DRAFT_PENDING"
    for path in ("/api/v1/products/export-uu", "/api/v1/products/export-packages"):
        response = client.post(path, headers=ADMIN, json={"productIds": [PRODUCT]})
        assert response.status_code == 409
        assert response.json()["code"] == "PRODUCT_DRAFT_PENDING"
