import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.image_storage import create_image_storage_application
from app.main import create_application
from app.modules.product_images import remote_upload


ADMIN = "isolated-test-admin-value"
STORAGE = "isolated-test-storage-value"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/CZYAAAAASUVORK5CYII=")
PUBLIC = "https://images.example.test"
NAME = "a" * 32 + ".png"


@pytest.fixture(autouse=True)
def clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def configure(monkeypatch, tmp_path):
    token_file = tmp_path / "storage-credential"
    token_file.write_text(STORAGE, encoding="utf-8")
    monkeypatch.setenv("BACKEND_API_TOKEN", ADMIN)
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_WRITES", "true")
    monkeypatch.setenv("BACKEND_IMAGE_PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("BACKEND_IMAGE_REMOTE_UPLOAD_ORIGIN", "http://100.91.1.2:19000")
    monkeypatch.setenv("BACKEND_IMAGE_REMOTE_UPLOAD_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("BACKEND_IMAGE_STORAGE_DIR", raising=False)


def use_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(remote_upload, "_client", lambda: httpx.AsyncClient(
        transport=transport, follow_redirects=False, trust_env=False,
    ))


def test_upload_is_authenticated_forwarded_and_returns_nas_public_url(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    received = []

    async def handler(request):
        received.append((request.url.path, request.headers.get("authorization"),
                         request.headers.get("content-type"), await request.aread()))
        return httpx.Response(201, json={"url": PUBLIC + "/rpa/v1/product-images/" + NAME})

    use_transport(monkeypatch, handler)
    with TestClient(create_application()) as client:
        assert client.post("/api/v1/product-images", content=PNG).status_code == 401
        response = client.post("/api/v1/product-images", content=PNG,
                               headers={"Authorization": "Bearer " + ADMIN, "Content-Type": "image/png"})
    assert response.status_code == 201
    assert response.json() == {"url": PUBLIC + "/rpa/v1/product-images/" + NAME}
    assert received == [("/api/v1/product-images", "Bearer " + STORAGE, "image/png", PNG)]
    assert [item.name for item in tmp_path.iterdir()] == ["storage-credential"]


def test_remote_mode_never_falls_back_or_forwards_invalid_images(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("BACKEND_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_IMAGE_UPLOAD_MAX_BYTES", "100")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(201, json={"url": PUBLIC + "/rpa/v1/product-images/" + NAME})

    use_transport(monkeypatch, handler)
    headers = {"Authorization": "Bearer " + ADMIN, "Content-Type": "image/png"}
    with TestClient(create_application()) as client:
        assert client.post("/api/v1/product-images", content=b"not an image", headers=headers).status_code == 415
        assert client.post("/api/v1/product-images", content=PNG * 4, headers=headers).status_code == 413
        monkeypatch.delenv("BACKEND_IMAGE_REMOTE_UPLOAD_TOKEN_FILE")
        get_settings.cache_clear()
        assert client.post("/api/v1/product-images", content=PNG, headers=headers).status_code == 503
    assert not calls
    assert [item.name for item in tmp_path.iterdir()] == ["storage-credential"]


@pytest.mark.parametrize("duplicate", ["admin", "rpa"])
def test_storage_credential_must_be_distinct_from_management_and_rpa(tmp_path, monkeypatch, duplicate):
    configure(monkeypatch, tmp_path)
    if duplicate == "admin":
        (tmp_path / "storage-credential").write_text(ADMIN, encoding="utf-8")
    else:
        monkeypatch.setenv("BACKEND_RPA_API_TOKEN", STORAGE)
    calls = []
    use_transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(500))
    with TestClient(create_application()) as client:
        response = client.post("/api/v1/product-images", content=PNG,
                               headers={"Authorization": "Bearer " + ADMIN, "Content-Type": "image/png"})
    assert response.status_code == 503 and not calls


@pytest.mark.parametrize("origin", [
    "http://example.com", "http://8.8.8.8", "http://169.254.169.254",
    "http://user@100.91.1.2", "http://@100.91.1.2", "https://example.com/path",
    "https://example.com/?access=secret", "http://100.91.1.2?", "http://100.91.1.2#", "ftp://100.91.1.2",
])
def test_invalid_remote_origin_fails_before_contacting_nas(tmp_path, monkeypatch, origin):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("BACKEND_IMAGE_REMOTE_UPLOAD_ORIGIN", origin)
    calls = []
    use_transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(500))
    with TestClient(create_application()) as client:
        response = client.post("/api/v1/product-images", content=PNG,
                               headers={"Authorization": "Bearer " + ADMIN, "Content-Type": "image/png"})
    assert response.status_code == 503 and not calls


@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://attacker.example.test"}),
    httpx.Response(401),
    httpx.Response(201, json={"url": "https://attacker.example.test/picture.png"}),
    httpx.Response(201, json={"url": PUBLIC + "/rpa/v1/product-images/" + "a" * 32 + ".jpg"}),
    httpx.Response(201, content=b"x" * 4097),
])
def test_upstream_failures_and_untrusted_urls_do_not_report_success(tmp_path, monkeypatch, response):
    configure(monkeypatch, tmp_path)
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return response

    use_transport(monkeypatch, handler)
    with TestClient(create_application()) as client:
        result = client.post("/api/v1/product-images", content=PNG,
                             headers={"Authorization": "Bearer " + ADMIN, "Content-Type": "image/png"})
    assert result.status_code == 503 and calls == ["100.91.1.2"]
    assert STORAGE not in result.text


def test_image_only_application_has_no_product_or_precheck_api(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", STORAGE)
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_WRITES", "true")
    monkeypatch.setenv("BACKEND_IMAGE_PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("BACKEND_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("BACKEND_IMAGE_REMOTE_UPLOAD_ORIGIN", raising=False)
    monkeypatch.delenv("BACKEND_IMAGE_REMOTE_UPLOAD_TOKEN_FILE", raising=False)
    with TestClient(create_image_storage_application()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/products").status_code == 404
        assert client.post("/api/v1/prechecks/query").status_code == 404
        assert client.post("/api/v1/product-images", content=PNG).status_code == 401
        response = client.post("/api/v1/product-images", content=PNG,
                               headers={"Authorization": "Bearer " + STORAGE, "Content-Type": "image/png"})
        assert response.status_code == 201
        name = response.json()["url"].rsplit("/", 1)[1]
        assert client.get("/rpa/v1/product-images/" + name).content == PNG
        assert (tmp_path / name).read_bytes() == PNG


def test_image_only_service_refuses_recursive_remote_configuration(tmp_path, monkeypatch):
    configure(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="不能继续转发"):
        with TestClient(create_image_storage_application()):
            pass
