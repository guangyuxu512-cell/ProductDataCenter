import base64
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_application
from app.modules.products.editing import apply_edit
from app.modules.products.manual import manual_package
from app.modules.products.schemas import ProductEdit
from app.modules.product_images.urls import canonical_package_text, canonical_product_image_url


TOKEN = "test-image-upload-admin-token"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/CZYAAAAASUVORK5CYII=")


def test_upload_url_is_public_and_is_preserved_in_the_package(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", TOKEN)
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_WRITES", "true")
    monkeypatch.setenv("BACKEND_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_IMAGE_PUBLIC_BASE_URL", "https://images.example.test")
    get_settings.cache_clear()
    with TestClient(create_application()) as client:
        assert client.post('/api/v1/product-images', content=PNG).status_code == 401
        response = client.post('/api/v1/product-images', content=PNG, headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "image/png"})
        assert response.status_code == 201
        url = response.json()['url']
        assert url.startswith('https://images.example.test/rpa/v1/product-images/')
        # A remote browser, the platform, or an RPA image downloader can read
        # the exact URL without receiving the administrative token.
        image = client.get(urlsplit(url).path, headers={'Origin': 'http://product-library.example.test'})
        assert image.status_code == 200 and image.content == PNG and image.headers['content-type'] == 'image/png'
        assert image.headers['access-control-allow-origin'] == '*'
        package, _ = manual_package('手动商品')
        spec_id = package['spec_detail_value']['value'][0]['spec_values'][0]['id']
        edit = ProductEdit(expectedVersion='a' * 64, mainImages=[url], detailImages=[url],
                           specImages=[{'specId': spec_id, 'url': url}])
        output = apply_edit(package, 'douyin', edit)
        assert output['goodsInfo']['goodsImageList'] == [url]
        assert output['goodsDetailInfo']['detail_imgs'][0]['url_list'] == [url]
        assert output['spec_detail_value']['value'][0]['spec_values'][0]['img_url'] == url
        assert output['goodsSkuInfo']['sku_detail'][0]['spec_item_list'][0]['big_pic'] == url
    get_settings.cache_clear()


def test_upload_fails_closed_and_rejects_non_images_and_large_files(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", TOKEN)
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_WRITES", "true")
    monkeypatch.setenv("BACKEND_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_IMAGE_UPLOAD_MAX_BYTES", "100")
    monkeypatch.delenv("BACKEND_IMAGE_PUBLIC_BASE_URL", raising=False)
    get_settings.cache_clear()
    headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "image/png"}
    with TestClient(create_application()) as client:
        assert client.post('/api/v1/product-images', content=PNG, headers=headers).status_code == 503
        assert not list(tmp_path.iterdir())
        monkeypatch.setenv("BACKEND_IMAGE_PUBLIC_BASE_URL", "https://images.example.test")
        get_settings.cache_clear()
        assert client.post('/api/v1/product-images', content=b'<svg/>', headers=headers).status_code == 415
        assert client.post('/api/v1/product-images', content=PNG, headers={**headers, 'Content-Type': 'text/plain'}).status_code == 415
        assert client.post('/api/v1/product-images', content=PNG * 4, headers=headers).status_code == 413
        assert client.get('/rpa/v1/product-images/invalid.jpg').status_code == 404
        assert not list(tmp_path.iterdir())
    get_settings.cache_clear()


def test_only_configured_product_image_urls_are_canonicalized():
    old = "http://100.91.242.119:3612/rpa/v1/product-images/" + "a" * 32 + ".png"
    public = "https://rpa.example.test"
    assert canonical_product_image_url(old, public, "http://100.91.242.119:3612") == \
        public + "/rpa/v1/product-images/" + "a" * 32 + ".png"
    source = "https://p3.example.test/rpa/v1/product-images/" + "a" * 32 + ".png"
    assert canonical_product_image_url(source, public, "http://100.91.242.119:3612") == source
    malformed = "http://100.91.242.119:3612/rpa/v1/product-images/not-owned.png"
    assert canonical_product_image_url(malformed, public, "http://100.91.242.119:3612") == malformed
    assert canonical_product_image_url(old, "http://public.example.test", "http://100.91.242.119:3612") == old
    package = '{"ours":"' + old + '","source":"' + source + '"}'
    rewritten = canonical_package_text(package, public, "http://100.91.242.119:3612")
    assert public in rewritten and source in rewritten and old not in rewritten


def test_upload_rejects_non_https_public_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKEND_API_TOKEN", TOKEN)
    monkeypatch.setenv("BACKEND_ENABLE_PRODUCT_WRITES", "true")
    monkeypatch.setenv("BACKEND_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_IMAGE_PUBLIC_BASE_URL", "http://100.91.242.119:3612")
    get_settings.cache_clear()
    with TestClient(create_application()) as client:
        response = client.post('/api/v1/product-images', content=PNG,
            headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "image/png"})
        assert response.status_code == 503 and not list(tmp_path.iterdir())
    get_settings.cache_clear()


def test_edit_snapshot_rewrites_only_owned_legacy_image_values_without_mutating_source():
    from types import SimpleNamespace
    from app.modules.products.service import ProductService

    old = "https://old-images.example.test"
    current = "https://images.example.test"
    name = "a" * 32 + ".png"
    old_url = old + "/rpa/v1/product-images/" + name
    source_url = "https://source.example.test/rpa/v1/product-images/" + name
    snapshot = {"version": "test-version", "mainImages": [old_url, source_url],
                "specImages": [{"specId": "42", "url": old_url}]}

    class Repo:
        def edit_snapshot(self, product_id, **kwargs):
            assert product_id == "123" and kwargs == {"allowed_groups": ["group"]}
            return snapshot

    settings = SimpleNamespace(image_public_base_url=current, image_legacy_base_urls=old)
    result = ProductService(Repo(), settings).edit_snapshot("123", allowed_groups=["group"])
    assert result["version"] == "test-version"
    assert result["mainImages"] == [current + "/rpa/v1/product-images/" + name, source_url]
    assert result["specImages"][0]["url"] == current + "/rpa/v1/product-images/" + name
    assert snapshot["mainImages"][0] == old_url and snapshot["specImages"][0]["url"] == old_url


def test_edit_write_normalizes_owned_images_without_changing_source_or_explicit_fields():
    from types import SimpleNamespace
    from app.modules.products.service import ProductService

    old = "https://old-images.example.test"
    current = "https://images.example.test"
    name = "b" * 32 + ".png"
    old_url = old + "/rpa/v1/product-images/" + name
    source_url = "https://source.example.test/rpa/v1/product-images/" + name
    edit = ProductEdit(expectedVersion="a" * 64, mainImages=[old_url, source_url],
                       specImages=[{"specId": "1", "url": old_url}])

    class Repo:
        def save_edit(self, product_id, value, **kwargs):
            assert product_id == "123" and kwargs == {}
            return value

    settings = SimpleNamespace(image_public_base_url=current, image_legacy_base_urls=old)
    result = ProductService(Repo(), settings).save_edit("123", edit)
    assert result.mainImages == [current + "/rpa/v1/product-images/" + name, source_url]
    assert result.specImages[0].url == current + "/rpa/v1/product-images/" + name
    assert result.model_fields_set == edit.model_fields_set
    assert edit.mainImages[0] == old_url
