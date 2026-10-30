"""仅使用名称固定的隔离测试库；绝不连接 NAS 或修改生产数据。"""
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.modules.products.errors import GroupNameConflict
from app.modules.products.queries import parse_product_list_options
from app.modules.products.repository import ProductRepository
from app.modules.products.service import ProductService

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine():
    value = os.environ.get("BACKEND_DATABASE_URL")
    if not value:
        pytest.skip("需要显式的隔离 PostgreSQL 连接")
    url = make_url(value)
    assert url.database == "product_workbench_test", "拒绝对非隔离库执行测试"
    assert url.host in {"127.0.0.1", "localhost", "postgres"}, "拒绝访问外部数据库"
    engine = create_engine(value)
    with engine.begin() as conn:
        assert conn.execute(text("SELECT current_database()")).scalar_one() == "product_workbench_test"
        assert conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one() == 0, "需要全新的隔离库"
        for path in sorted((Path(__file__).parent / "fixtures/collector").glob("*.sql")):
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
        conn.execute(text("""INSERT INTO products(product_id, source_platform, source_product_id, title,
            shop_name, category_path, current_price_min, current_price_max, captured_at, uu_json)
            VALUES ('3760269504500859111', 'douyin', '3760269504500859111', '厨房收纳盒', '测试店铺', '家居/厨房',
            19.99, 29.99, '2026-10-26T08:18:34.999999+08', '{"goodsInfo":{"productId":"3760269504500859111"}}'),
            ('pdd:3760269504500859111', 'pinduoduo', '3760269504500859111', '桌面收纳盒', '测试店铺', '家居/桌面',
            9.99, 9.99, '2026-10-26T08:18:35+08', '{"goodsInfo":{"productId":"3760269504500859111"}}')"""))
        conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
            VALUES ('3760269504500859111','main',0,'','https://fixture.invalid/main.png')"""))
        conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,sort_order)
            VALUES ('3760269504500859111','sku-1','白色',19.99,0)"""))
    yield engine
    engine.dispose()


def test_exact_id_and_second_precision(engine):
    repo = ProductRepository(engine)
    found = repo.list(parse_product_list_options({"productId": "3760269504500859111"}))
    assert found["total"] == 2
    assert found["items"][1]["main_image_url"] == "https://fixture.invalid/main.png"
    found = repo.list(parse_product_list_options({"capturedFromTime": "2026-10-26T08:18:34", "capturedToTime": "2026-10-26T08:18:34"}))
    assert found["total"] == 1 and found["items"][0]["product_id"] == "3760269504500859111"
    assert repo.list(parse_product_list_options({"q": "厨房收纳"}))["total"] == 1
    assert repo.list(parse_product_list_options({"includeTotal": "false"}))["total"] is None
    detail = repo.detail("3760269504500859111")
    assert detail["product"]["source_platform"] == "douyin" and len(detail["skus"]) == 1
    assert "uu_json" not in detail["product"]


def test_rpa_group_list_uses_real_postgres_and_preserves_uu(engine, tmp_path):
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service

    repo = ProductRepository(engine)
    group_service = ProductService(repo, Settings(data_root=tmp_path))
    group = group_service.save_group("RPA 测试分组")["group"]
    try:
        group_service.assign_group(["3760269504500859111", "pdd:3760269504500859111"], group["groupId"])
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_settings] = lambda: settings
        # Auth reads the cached configuration directly, so explicitly seed it for this isolated test.
        from unittest.mock import patch
        with patch("app.core.security.access.get_settings", return_value=settings):
            app.dependency_overrides[get_service] = lambda: group_service
            with TestClient(app) as client:
                auth = {"Authorization": "Bearer rpa-test"}
                page = client.get(f"/rpa/v1/product-groups/{group['groupId']}/products?limit=1", headers=auth).json()
                assert page["total"] == 2
                second = client.get(f"/rpa/v1/product-groups/{group['groupId']}/products?limit=1&offset=1", headers=auth).json()
                assert page["items"][0]["product_id"] != second["items"][0]["product_id"]
                response = client.get("/rpa/v1/products/3760269504500859111/uu", headers=auth)
                assert response.status_code == 200
                assert response.json()["goodsInfo"]["productId"] == "3760269504500859111"
                assert len(response.headers["x-uu-sha256"]) == 64
    finally:
        group_service.delete_group(group["groupId"])


def test_list_and_count_share_snapshot_under_concurrent_insert(engine):
    injected = False
    def after_cursor(conn, cursor, statement, parameters, context, executemany):
        nonlocal injected
        if not injected and "SELECT p.product_id" in statement:
            injected = True
            with engine.begin() as writer:
                writer.execute(text("INSERT INTO products(product_id,title) VALUES ('9999999999999999999','并发商品')"))
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM products")).scalar_one()
    event.listen(engine, "after_cursor_execute", after_cursor)
    try:
        result = ProductRepository(engine).list(parse_product_list_options({}))
        assert result["total"] == before and len(result["items"]) == before
    finally:
        event.remove(engine, "after_cursor_execute", after_cursor)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id='9999999999999999999'"))


def test_group_crud_preserves_products_skus_uu_and_files(engine, tmp_path):
    repo = ProductRepository(engine)
    service = ProductService(repo, Settings(data_root=tmp_path))
    with engine.connect() as conn:
        before = conn.execute(text("SELECT product_id, uu_json, raw_rel_path FROM products ORDER BY product_id")).all()
    created = service.save_group("测试分组")['group']
    with pytest.raises(GroupNameConflict):
        service.save_group("测试分组")
    service.assign_group(["3760269504500859111"], created["groupId"])
    renamed = service.save_group("重命名分组", created["groupId"])["group"]
    assert renamed["productCount"] == 1
    assert repo.list(parse_product_list_options({"groupId": str(created["groupId"])}))["total"] == 1
    assert service.delete_group(created["groupId"])["deleted"]["productCount"] == 1
    assert repo.detail("3760269504500859111")["product"]["group_id"] is None
    with engine.connect() as conn:
        after = conn.execute(text("SELECT product_id, uu_json, raw_rel_path FROM products ORDER BY product_id")).all()
        assert conn.execute(text("SELECT count(*) FROM product_skus")).scalar_one() == 1
        indexes = conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='products'")).scalars().all()
    assert before == after
    assert "products_search_trgm_idx" in indexes and "products_captured_at_idx" in indexes
