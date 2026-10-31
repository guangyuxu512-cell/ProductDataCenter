import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.main import create_application

ADMIN = {"Authorization": "Bearer admin-test-token"}
RPA = {"Authorization": "Bearer rpa-test-token"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("BACKEND_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("BACKEND_RPA_API_TOKEN", "rpa-test-token")
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_EDITS", "true")
    monkeypatch.setenv("BACKEND_PRODUCT_ASSET_ROOT", str(tmp_path))
    monkeypatch.delenv("BACKEND_API_TOKEN_FILE", raising=False)
    get_settings.cache_clear()
    with TestClient(create_application()) as test_client:
        yield test_client, tmp_path
    get_settings.cache_clear()


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (2, 2), (255, 0, 0)).save(output, "PNG")
    return output.getvalue()


def test_only_uploaded_images_are_stored_and_reused(client):
    http, root = client
    data = image_bytes()
    assert http.post("/api/v1/product-assets", content=data, headers=RPA).status_code == 401
    result = http.post("/api/v1/product-assets", content=data, headers=ADMIN)
    assert result.status_code == 200
    item = result.json()
    assert item["sha256"] == hashlib.sha256(data).hexdigest()
    assert http.post("/api/v1/product-assets", content=data, headers=ADMIN).json() == item
    assert len(list(root.iterdir())) == 1
    response = http.get(item["url"], headers=ADMIN)
    assert response.content == data and response.headers["content-type"] == "image/png"
    assert http.get(item["url"], headers=RPA).status_code == 401


def test_invalid_or_disabled_uploads_and_symlinks_are_rejected(client, monkeypatch):
    http, root = client
    assert http.post("/api/v1/product-assets", content=b"not an image", headers=ADMIN).status_code == 400
    digest = hashlib.sha256(image_bytes()).hexdigest()
    outside = root.parent / "outside.png"
    outside.write_bytes(image_bytes())
    (root / f"{digest}.png").symlink_to(outside)
    assert http.post("/api/v1/product-assets", content=image_bytes(), headers=ADMIN).status_code == 409
    assert http.get(f"/api/v1/product-assets/{digest}.png", headers=ADMIN).status_code == 404
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_EDITS", "false")
    get_settings.cache_clear()
    assert http.post("/api/v1/product-assets", content=image_bytes(), headers=ADMIN).status_code == 403
