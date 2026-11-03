"""仅使用名称固定的隔离测试库；绝不连接 NAS 或修改生产数据。"""
import json
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
            19.99, 29.99, '2026-10-26T08:18:34.999999+08', '{"goodsInfo":{"productId":"3760269504500859111","catId1":"100","catId2":"200","catId3":"300","catId4":"0"}}'),
            ('pdd:3760269504500859111', 'pinduoduo', '3760269504500859111', '桌面收纳盒', '测试店铺', '家居/桌面',
            9.99, 9.99, '2026-10-26T08:18:35+08', '{"goodsInfo":{"productId":"3760269504500859111","catId3":"999"}}')"""))
        conn.execute(text("""UPDATE products SET uu_json = uu_json || CAST(:attributes AS jsonb)
            WHERE product_id=:id"""), {"id": "3760269504500859111", "attributes": json.dumps({
                "category_properties_value": {"value": {"501": [{"k": "材质", "value_name": "棉"}]}},
                "goodsDetailInfo": {"product_format": [{"format": [
                    {"property_id": "502", "name": "品牌", "message": [{"desc": "测试品牌"}]},
                ]}]},
            }, ensure_ascii=False)})
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
    assert detail["sourceCategoryId"] == "300"
    assert detail["sourceAttributes"] == [
        {"id": "501", "name": "材质", "values": ["棉"]},
        {"id": "502", "name": "品牌", "values": ["测试品牌"]},
    ]
    pdd_detail = repo.detail("pdd:3760269504500859111")
    assert pdd_detail["sourceCategoryId"] is None and pdd_detail["sourceAttributes"] == []
    assert "uu_json" not in detail["product"]


@pytest.mark.parametrize("legacy", [False, True])
def test_prediction_reads_pdd_package_from_postgres_without_changing_it(engine, tmp_path, legacy):
    from uuid import uuid4
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.category_lookup.api import get_central, get_lookup
    from app.modules.central.client import CentralCookie, CentralShop, CentralShopSession
    from app.modules.products.api import get_service

    product_id = "pdd:3760269504500859111"
    title = "拼多多完整标题" * 12
    package = {"product": {"title": title}, "images": {"main": [{"url": "https://fixture.invalid/main.png"}]}}
    if legacy:
        package = {"goodsInfo": {"goodsName": title, "goodsImageList": ["https://fixture.invalid/main.png"]}}
    with engine.begin() as conn:
        original = conn.execute(text("SELECT uu_json::text FROM products WHERE product_id=:id"), {"id": product_id}).scalar_one()
        conn.execute(text("UPDATE products SET uu_json=CAST(:package AS jsonb) WHERE product_id=:id"),
                     {"id": product_id, "package": json.dumps(package, ensure_ascii=False)})
        before = conn.execute(text("SELECT uu_json::text FROM products WHERE product_id=:id"), {"id": product_id}).scalar_one()
    settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test",
                        douyin_category_lookup_enabled=True)
    shop_id = uuid4()
    class Central:
        def list_shops(self):
            return [CentralShop(shop_id=shop_id, display_name="测试店", platform="douyin", session_status="valid")]
        def read_session(self, requested, expected_platform):
            return CentralShopSession(shop_id=requested, platform=expected_platform, session_version=1,
                cookies=(CentralCookie(name="sessionid", value="synthetic", domain=".jinritemai.com"),))
    class Lookup:
        def __init__(self): self.settings = settings
        def predict(self, session, actual_title, image_url):
            assert actual_title == title and image_url == "https://fixture.invalid/main.png"
            return {"recommendedId": None, "candidates": []}
    app = create_application()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_service] = lambda: ProductService(ProductRepository(engine), settings)
    app.dependency_overrides[get_central] = lambda: Central()
    app.dependency_overrides[get_lookup] = lambda: Lookup()
    try:
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            result = client.post("/api/v1/category-lookup/predict", json={"productId": product_id},
                                 headers={"Authorization": "Bearer admin-test"})
            assert result.status_code == 200 and result.json()["status"] == "no_recommendation"
        with engine.connect() as conn:
            assert conn.execute(text("SELECT uu_json::text FROM products WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == before
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET uu_json=CAST(:package AS jsonb) WHERE product_id=:id"),
                         {"id": product_id, "package": original})


@pytest.mark.parametrize("legacy", [False, True])
def test_pdd_target_category_and_attributes_round_trip_without_changing_source(engine, tmp_path, legacy):
    import hashlib
    from app.modules.products.schemas import ProductEdit

    product_id = "pdd:3760269504500859111"
    package = {"product": {"title": "收纳盒", "categoryIds": ["77"]}, "images": {"main": [], "detail": []},
               "skus": [{"skuId": "100", "onSale": False}]}
    if legacy:
        package = {"goodsInfo": {"goodsName": "收纳盒", "catId1": "77", "goodsImageList": []},
                   "goodsSkuInfo": {"spec_detail": {"value": [{"sku_status": False}]}},
                   "goodsDetailInfo": {"detail_imgs": []}}
    with engine.begin() as conn:
        original = conn.execute(text("SELECT uu_json::text, title_status, category_path FROM products WHERE product_id=:id"),
                                {"id": product_id}).one()
        conn.execute(text("UPDATE products SET uu_json=CAST(:package AS jsonb) WHERE product_id=:id"),
                     {"id": product_id, "package": json.dumps(package, ensure_ascii=False)})
        initial = conn.execute(text("SELECT uu_json::text FROM products WHERE product_id=:id"), {"id": product_id}).scalar_one()
    try:
        repo = ProductRepository(engine)
        edit = ProductEdit(expectedVersion=hashlib.sha256(initial.encode()).hexdigest(),
            category=[{"id": "10", "name": "家居"}, {"id": "11", "name": "收纳"}],
            attributes=[{"id": "12", "name": "材质", "values": [{"valueId": "13", "name": "塑料"}]}])
        repo.save_edit(product_id, edit)
        detail = repo.detail(product_id)
        assert detail["targetCategory"] == [{"id": "10", "name": "家居"}, {"id": "11", "name": "收纳"}]
        assert detail["targetAttributes"] == [{"id": "12", "name": "材质", "values": ["塑料"]}]
        assert detail["product"]["category_path"] == original.category_path
        saved = json.loads(repo.export_rows([product_id])[0]["uu_text"])
        assert all(saved[key] == value for key, value in package.items())
        assert saved["douyinTarget"]["attributes"]["12"]["values"][0]["valueId"] == "13"
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET uu_json=CAST(:package AS jsonb), title_status=:status WHERE product_id=:id"),
                         {"id": product_id, "package": original[0], "status": original[1]})


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


def test_edit_updates_same_database_package_rpa_reads_and_rejects_stale_version(engine, tmp_path):
    import hashlib
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.errors import ProductEditConflict
    from app.modules.products.export import current_uu_bytes
    from app.modules.products.schemas import ProductEdit

    identity = "9999999999999999911"
    package = {"goodsId": identity, "goodsInfo": {"goodsName": "旧标题", "catId1": "1", "catId2": "0",
               "catId3": "0", "catId4": "0", "goodsImageList": ["https://example.test/a", "https://example.test/b"]},
               "goodsDetailInfo": {"detail_imgs": [], "detail_imgs_new": []},
               "goodsSkuInfo": {"spec_detail": {"value": [{"sku_status": False}]}}}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO products(product_id,source_platform,source_product_id,title,uu_json)
            VALUES (:id,'douyin',:id,'旧标题',CAST(:package AS jsonb))"""), {"id": identity, "package": json.dumps(package)})
        for index, url in enumerate(package["goodsInfo"]["goodsImageList"]):
            conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                VALUES (:id,'main',:position,'',:url)"""), {"id": identity, "position": index, "url": url})
    try:
        repo = ProductRepository(engine)
        version = repo.edit_snapshot(identity)["version"]
        edit = ProductEdit(expectedVersion=version, title="新的商品", mainImages=["https://example.test/b"])
        new_version = repo.save_edit(identity, edit)["version"]
        with pytest.raises(ProductEditConflict):
            repo.save_edit(identity, edit)
        exported, source = current_uu_bytes(repo.export_rows([identity])[0], 1_000_000)
        saved = json.loads(exported)
        assert source == "database" and new_version != version
        assert saved["goodsInfo"]["goodsName"] == "新的商品"
        assert saved["goodsInfo"]["goodsImageList"] == ["https://example.test/b"]
        assert saved["goodsSkuInfo"] == package["goodsSkuInfo"]
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            response = client.get(f"/rpa/v1/products/{identity}/uu", headers={"Authorization": "Bearer rpa-test"})
            assert response.status_code == 200 and response.content == exported
            assert response.headers["x-uu-sha256"] == hashlib.sha256(exported).hexdigest()
            assert client.patch(f"/api/v1/products/{identity}", headers={"Authorization": "Bearer rpa-test"},
                                json={"expectedVersion": new_version, "title": "越权"}).status_code == 401
        detail = repo.detail(identity)
        assert detail["product"]["title"] == "新的商品"
        assert [image["source_url"] for image in detail["images"]] == ["https://example.test/b"]
        assert detail["product"]["main_image_count"] == 1
        assert "商品库已修改" in detail["product"]["title_status"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": identity})


def test_sku_changes_and_image_are_consistent_in_database_package_and_projections(engine):
    from app.modules.products.export import current_uu_bytes
    from app.modules.products.schemas import ProductEdit

    identity = "9999999999999999912"
    package = {"goodsId": identity, "goodsInfo": {"goodsName": "SKU 测试", "skuInfoMap": {
        "11_21": {"sku_id": "1001", "extra_business_info": '{"first_price":{"left_price_num":1200}}'},
        "12_22": {"sku_id": "1002", "extra_business_info": '{"first_price":{"left_price_num":1600}}'}}},
        "goodsSkuInfo": {"sku_detail": [{"name": "颜色", "spec_item_list": [
            {"spec_item_id": "11", "name": "黑色", "big_pic": "https://example.test/old"},
            {"spec_item_id": "12", "name": "白色", "big_pic": ""}]}],
            "spec_detail": {"value": [
                {"spec_detail_ids": ["11", "21"], "price": "12", "sku_status": True, "stock_info": {"stock_num": 5}},
                {"spec_detail_ids": ["12", "22"], "price": "16", "sku_status": False, "stock_info": {"stock_num": 0}}]}},
        "spec_detail_value": {"value": [{"name": "颜色", "spec_values": [
            {"id": "11", "name": "黑色", "img_url": ""},
            {"id": "12", "name": "白色", "img_url": ""}]}]}}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO products(product_id,source_platform,source_product_id,title,uu_json,sku_count)
            VALUES (:id,'douyin',:id,'SKU 测试',CAST(:package AS jsonb),2)"""), {"id": identity, "package": json.dumps(package)})
        conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,sort_order)
            VALUES (:id,'1001','黑色',12,0),(:id,'1002','白色',16,1)"""), {"id": identity})
    try:
        repo = ProductRepository(engine)
        snapshot = repo.edit_snapshot(identity)
        assert snapshot["specImages"][0]["url"] == "https://example.test/old"
        assert snapshot["skus"][1]["enabled"] is False
        edit = ProductEdit(expectedVersion=snapshot["version"],
            skus=[{"specIds": ["11", "21"], "price": "19.90", "stock": 7},
                  {"specIds": ["12", "22"], "delete": True}],
            specImages=[{"specId": "11", "url": "https://example.test/new"}])
        repo.save_edit(identity, edit)
        body, _ = current_uu_bytes(repo.export_rows([identity])[0], 1_000_000)
        saved = json.loads(body)
        assert saved["goodsSkuInfo"]["spec_detail"]["value"] == [
            {"price": "19.90", "sku_status": True, "stock_info": {"stock_num": 7}, "spec_detail_ids": ["11", "21"]}]
        assert saved["goodsSkuInfo"]["sku_detail"][0]["spec_item_list"][0]["big_pic"] == "https://example.test/new"
        assert set(saved["goodsInfo"]["skuInfoMap"]) == {"11_21"}
        detail = repo.detail(identity)
        assert detail["product"]["sku_count"] == 1
        assert str(detail["skus"][0]["current_price"]) == "19.90" and len(detail["skus"]) == 1
        assert [image["source_url"] for image in detail["images"]] == ["https://example.test/new"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": identity})


def test_moved_spec_image_group_is_visible_to_rpa_without_losing_off_sale_skus(engine, tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.schemas import ProductEdit

    identity = "9999999999999999913"
    package = {"goodsId": identity, "goodsInfo": {"goodsName": "SKU 测试", "skuInfoMap": {
        "11_21": {"sku_id": "1001"}, "11_22": {"sku_id": "1002"}, "12_22": {"sku_id": "1003"}}},
        "goodsSkuInfo": {"sku_detail": [
            {"name": "颜色", "spec_item_list": [{"spec_item_id": "11", "big_pic": "https://example.test/black"},
                                              {"spec_item_id": "12", "big_pic": ""}]},
            {"name": "款式", "spec_item_list": [{"spec_item_id": "21", "big_pic": ""},
                                              {"spec_item_id": "22", "big_pic": "", "small_pic": "https://example.test/short"}]}],
            "spec_detail": {"value": [{"spec_detail_ids": ["11", "21"], "price": "12", "sku_status": True},
                                       {"spec_detail_ids": ["11", "22"], "price": "13", "sku_status": True},
                                       {"spec_detail_ids": ["12", "22"], "price": "16", "sku_status": False}]}},
        "spec_detail_value": {"value": [
            {"name": "颜色", "spec_values": [{"id": "11", "name": "黑色", "img_url": "https://example.test/black"},
                                           {"id": "12", "name": "白色", "img_url": ""}]},
            {"name": "款式", "spec_values": [{"id": "21", "name": "长款", "img_url": ""},
                                           {"id": "22", "name": "短款", "img_url": ""}]}]}}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO products(product_id,source_platform,source_product_id,title,uu_json,sku_count)
            VALUES (:id,'douyin',:id,'SKU 测试',CAST(:package AS jsonb),3)"""),
            {"id": identity, "package": json.dumps(package)})
        conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,sort_order)
            VALUES (:id,'1001','黑色长款',12,0),(:id,'1002','黑色短款',13,1),(:id,'1003','白色短款',16,2)"""),
            {"id": identity})
    try:
        repo = ProductRepository(engine)
        snapshot = repo.edit_snapshot(identity)
        assert snapshot["specGroups"][1]["movable"] is True
        assert snapshot["specGroups"][1]["values"][1]["url"] == "https://example.test/short"
        repo.save_edit(identity, ProductEdit(expectedVersion=snapshot["version"], specImageGroupIndex=1,
            specImages=[{"specId": "21", "url": "https://example.test/long"}]))
        refreshed = repo.edit_snapshot(identity)
        assert [group["name"] for group in refreshed["specGroups"]] == ["款式", "颜色"]
        assert refreshed["skus"][-1]["enabled"] is False
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            response = client.get(f"/rpa/v1/products/{identity}/uu", headers={"Authorization": "Bearer rpa-test"})
            assert response.status_code == 200
            saved = response.json()
        assert saved["goodsSkuInfo"]["sku_detail"][0]["spec_item_list"][0]["big_pic"] == "https://example.test/long"
        assert [row["spec_detail_ids"] for row in saved["goodsSkuInfo"]["spec_detail"]["value"]] == [
            ["21", "11"], ["22", "11"], ["22", "12"]]
        assert saved["goodsSkuInfo"]["spec_detail"]["value"][-1]["sku_status"] is False
        assert [image["source_url"] for image in repo.detail(identity)["images"]] == [
            "https://example.test/long", "https://example.test/short"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": identity})


def test_spec_structure_save_updates_postgres_projection_and_rpa_payload(engine, tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.schemas import ProductEdit

    identity = "9999999999999999914"
    package = {"goodsId": identity, "goodsInfo": {"goodsName": "规格测试", "skuInfoMap": {
        "11": {"sku_id": "1001"}, "12": {"sku_id": "1002"}}},
        "goodsSkuInfo": {"sku_detail": [{"name": "颜色", "spec_item_list": [
            {"spec_item_id": "11", "name": "黑", "big_pic": "https://example.test/black"},
            {"spec_item_id": "12", "name": "白", "big_pic": ""}]}],
            "spec_detail": {"value": [
                {"spec_detail_ids": ["11"], "price": "12", "sku_status": True, "stock_info": {"stock_num": 5}},
                {"spec_detail_ids": ["12"], "price": "16", "sku_status": False, "stock_info": {"stock_num": 0}}]}},
        "spec_detail_value": {"value": [{"name": "颜色", "spec_values": [
            {"id": "11", "name": "黑", "img_url": "https://example.test/black"},
            {"id": "12", "name": "白", "img_url": ""}]}]}}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO products(product_id,source_platform,source_product_id,title,uu_json,sku_count)
            VALUES (:id,'douyin',:id,'规格测试',CAST(:package AS jsonb),2)"""),
            {"id": identity, "package": json.dumps(package)})
        conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,image_rel_path,sort_order)
            VALUES (:id,'1001','黑',12,'sku/black.jpg',0),(:id,'1002','白',16,'',1)"""), {"id": identity})
        conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
            VALUES (:id,'sku',0,'sku/black.jpg','https://example.test/black')"""), {"id": identity})
    try:
        repo = ProductRepository(engine)
        snapshot = repo.edit_snapshot(identity)
        edit = ProductEdit(expectedVersion=snapshot["version"], specStructure={
            "groups": [{"sourceIndex": 0, "name": "颜色", "values": [
                {"id": "11", "name": "深黑", "url": "https://example.test/black"},
                {"id": "12", "name": "白"}, {"id": "local-red", "name": "红", "url": "https://example.test/red"}]}],
            "skus": [{"sourceSpecIds": ["11"], "specIds": ["11"], "price": "12", "stock": "5", "enabled": True},
                     {"sourceSpecIds": ["12"], "specIds": ["12"], "price": "16", "stock": "0", "enabled": False},
                     {"specIds": ["local-red"], "price": "20", "stock": "2", "enabled": True}]})
        repo.save_edit(identity, edit)
        refreshed = repo.edit_snapshot(identity)
        assert len(refreshed["skus"]) == 3
        assert refreshed["skus"][1]["skuId"] == "1002" and refreshed["skus"][1]["enabled"] is False
        assert refreshed["skus"][2]["skuId"].startswith("local-")
        detail = repo.detail(identity)
        assert detail["product"]["sku_count"] == 3
        assert [sku["sku_id"] for sku in detail["skus"]][:2] == ["1001", "1002"]
        assert detail["skus"][0]["sku_name"] == "颜色: 深黑"
        assert detail["skus"][0]["image_rel_path"] == "sku/black.jpg"
        assert [image["source_url"] for image in detail["images"]] == ["https://example.test/black", "https://example.test/red"]
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            response = client.get(f"/rpa/v1/products/{identity}/uu", headers={"Authorization": "Bearer rpa-test"})
            assert response.status_code == 200
            saved = response.json()
        assert saved["goodsInfo"]["skuInfoMap"]["12"]["sku_id"] == "1002"
        assert "sku_id" not in saved["goodsInfo"]["skuInfoMap"]["local-red"]
        assert saved["goodsSkuInfo"]["spec_detail"]["value"][-1]["stock_info"]["stock_num"] == 2
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": identity})
