import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_application
from app.modules.product_edit.api import get_editor_repository
from app.modules.product_edit.models import EditorState, ProductDraft

PRODUCT = "3760269504500859111"
FINGERPRINT = "a" * 64
ADMIN = {"Authorization": "Bearer admin-test-token"}
RPA = {"Authorization": "Bearer rpa-test-token"}


class FakeEditor:
    ready = True
    manual_ready = True

    def permissions(self):
        return self.ready, self.manual_ready

    def read(self, product_id):
        return EditorState(productId=product_id, revision=0, sourceFingerprint=FINGERPRINT,
                           sourceChanged=False, draft=ProductDraft(title="测试商品"))

    def save(self, product_id, body):
        assert body.expectedRevision == 0 and body.sourceFingerprint == FINGERPRINT
        return EditorState(productId=product_id, revision=1, sourceFingerprint=FINGERPRINT,
                           sourceChanged=False, draft=body.draft)

    def create_manual(self, title, group_id):
        return EditorState(productId="manual:12345678901234567890", revision=1,
                           sourceFingerprint=FINGERPRINT, sourceChanged=False, draft=ProductDraft(title=title))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "rpa-test-token")
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_EDITS", "true")
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("BACKEND_RPA_API_TOKEN_FILE", raising=False)
    get_settings.cache_clear()
    app = create_application()
    editor = FakeEditor()
    app.dependency_overrides[get_editor_repository] = lambda: editor
    with TestClient(app) as test_client:
        yield test_client, editor
    get_settings.cache_clear()


def test_edit_requires_separate_admin_token_and_feature_flag(client, monkeypatch):
    http, _ = client
    path = f"/api/v1/products/{PRODUCT}/edit-draft"
    assert http.get(path).status_code == 401
    assert http.get(path, headers=RPA).status_code == 401
    assert http.get(path, headers=ADMIN).json()["revision"] == 0
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_EDITS", "false")
    get_settings.cache_clear()
    assert http.get(path, headers=ADMIN).status_code == 403


def test_save_validated_draft_and_manual_create_without_source_id(client):
    http, _ = client
    path = f"/api/v1/products/{PRODUCT}/edit-draft"
    saved = http.put(path, headers=ADMIN, json={"expectedRevision": 0, "sourceFingerprint": FINGERPRINT,
                                                "draft": {"title": "新标题"}})
    assert saved.status_code == 200 and saved.json()["draft"]["title"] == "新标题"
    created = http.post("/api/v1/products/manual", headers=ADMIN, json={"title": "手工商品"})
    assert created.status_code == 201 and created.json()["productId"].startswith("manual:")
    assert http.post("/api/v1/products/manual", headers=ADMIN, json={"title": "  "}).status_code == 422
    assert http.get("/api/v1/products/not-valid/edit-draft", headers=ADMIN).status_code == 404


def test_missing_schema_or_database_permissions_fail_closed(client):
    http, editor = client
    editor.ready = False
    assert http.get(f"/api/v1/products/{PRODUCT}/edit-draft", headers=ADMIN).status_code == 503
    editor.manual_ready = False
    assert http.post("/api/v1/products/manual", headers=ADMIN, json={"title": "商品"}).status_code == 503
