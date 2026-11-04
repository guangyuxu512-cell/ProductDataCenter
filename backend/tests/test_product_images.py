import base64
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_application
from app.modules.products.editing import apply_edit
from app.modules.products.manual import manual_package
from app.modules.products.schemas import ProductEdit


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
        image = client.get(urlsplit(url).path)
        assert image.status_code == 200 and image.content == PNG and image.headers['content-type'] == 'image/png'
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
