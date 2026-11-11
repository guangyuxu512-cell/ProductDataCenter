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


def test_scoped_tokens_enforce_group_boundaries_across_real_database_operations(engine, tmp_path):
    """The same group boundary applies to reads, writes, export, precheck and RPA."""
    import io
    import zipfile
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import create_application
    from app.modules.prechecks.queue import PrecheckQueue
    from app.modules.products.api import get_service

    repo = ProductRepository(engine)
    settings = Settings(_env_file=None, api_token="integration-admin", rpa_api_token="integration-rpa",
                        scoped_token_store_file=tmp_path / "tokens.sqlite3", data_root=tmp_path,
                        enable_group_writes=True, enable_product_writes=True)
    service = ProductService(repo, settings)
    group_a = service.save_group("Token 隔离 A")["group"]["groupId"]
    group_b = service.save_group("Token 隔离 B")["group"]["groupId"]
    a = repo.create_manual("Token A 商品", group_id=group_a)
    b = repo.create_manual("Token B 商品", group_id=group_b)
    created = [a, b]
    app = create_application()
    app.dependency_overrides[get_service] = lambda: service
    admin = {"Authorization": "Bearer integration-admin"}
    try:
        (tmp_path / "scope-a.png").write_bytes(b"scope-a")
        (tmp_path / "scope-b.png").write_bytes(b"scope-b")
        with engine.begin() as conn:
            for identity, path in [(a, "scope-a.png"), (b, "scope-b.png")]:
                conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                    VALUES (:id,'main',0,:path,'')"""), {"id": identity, "path": path})
        with patch("app.core.security.access.get_settings", return_value=settings), \
             patch("app.modules.access_tokens.api.get_settings", return_value=settings), \
             patch("app.modules.products.api.get_settings", return_value=settings), \
             patch("app.modules.prechecks.api._queue", return_value=PrecheckQueue(engine)), TestClient(app) as c:
            issue = c.post("/api/v1/tokens", headers=admin, json={"name": "隔离测试",
                "permissions": ["*"], "groupIds": [str(group_a)]})
            assert issue.status_code == 201, issue.text
            auth = {"Authorization": "Bearer " + issue.json()["token"]}
            page = c.get("/api/v1/products", headers=auth).json()
            assert [x["product_id"] for x in page["items"]] == [a] and page["total"] == 1
            assert c.get("/api/v1/products", headers=auth, params={"groupId": str(group_b)}).json()["total"] == 0
            assert c.get(f"/api/v1/products/{a}", headers=auth).status_code == 200
            assert c.get(f"/api/v1/products/{b}", headers=auth).status_code == 404
            assert c.get(f"/api/v1/products/{a}/images/main/0", headers=auth).content == b"scope-a"
            assert c.get(f"/api/v1/products/{b}/images/main/0", headers=auth).status_code == 404
            a_version = c.get(f"/api/v1/products/{a}/edit", headers=auth).json()["version"]
            assert c.get(f"/api/v1/products/{b}/edit", headers=auth).status_code == 404
            b_version = repo.edit_snapshot(b)["version"]
            assert c.patch(f"/api/v1/products/{b}", headers=auth,
                           json={"expectedVersion": b_version, "title": "不应修改"}).status_code == 404
            assert c.patch(f"/api/v1/products/{a}", headers=auth,
                           json={"expectedVersion": a_version, "title": "允许修改"}).status_code == 200
            assert repo.detail(b)["product"]["title"] == "Token B 商品"
            assert c.post("/api/v1/product-groups", headers=auth, json={"name": "越界新分组"}).status_code == 403
            assert c.patch(f"/api/v1/product-groups/{group_b}", headers=auth, json={"name": "越界"}).status_code == 403
            assert c.patch("/api/v1/products/group", headers=auth,
                           json={"productIds": [a], "groupId": str(group_b)}).status_code == 403
            assert c.patch("/api/v1/products/group", headers=auth,
                           json={"productIds": [b], "groupId": str(group_a)}).json()["updated"] == []
            assert str(repo.detail(b)["product"]["group_id"]) == str(group_b)
            queue = c.post("/api/v1/prechecks/run", headers=auth, json={"productIds": [a, b]})
            assert queue.status_code == 200 and [x["productId"] for x in queue.json()["items"]] == [a]
            result = c.post("/api/v1/prechecks/query", headers=auth, json={"productIds": [a, b]})
            assert result.status_code == 200 and [x["productId"] for x in result.json()["items"]] == [a]
            exported = c.post("/api/v1/products/export-uu", headers=auth, json={"productIds": [a, b]})
            assert exported.status_code == 200
            with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
            assert [x["productId"] for x in manifest["products"]] == [a]
            assert [x["groupId"] for x in c.get("/rpa/v1/product-groups", headers=auth).json()["groups"]] == [str(group_a)]
            assert c.get(f"/rpa/v1/product-groups/{group_b}/products", headers=auth).status_code == 403
            assert c.get(f"/rpa/v1/products/{a}/uu", headers=auth).status_code == 200
            assert c.get(f"/rpa/v1/products/{b}/uu", headers=auth).status_code == 404
            assert [row["product_id"] for row in repo.category_paths([a, b], allowed_groups={str(group_a)})] == [a]
            created_response = c.post("/api/v1/products", headers=auth,
                                      json={"title": "限定分组新建", "groupId": str(group_a)})
            assert created_response.status_code == 200, created_response.text
            created.append(created_response.json()["productId"])
            assert c.post("/api/v1/products", headers=auth,
                          json={"title": "不允许新建", "groupId": str(group_b)}).status_code == 403
            deleted = c.post("/api/v1/products/delete", headers=auth, json={"productIds": [a, b]})
            assert deleted.status_code == 200 and deleted.json()["deleted"] == [a]
            assert repo.detail(b) is not None
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=ANY(CAST(:ids AS text[]))"), {"ids": created})
            conn.execute(text("DELETE FROM product_groups WHERE group_id IN (:a,:b)"), {"a": group_a, "b": group_b})


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
        {"id": "501", "name": "材质", "values": ["棉"], "valueItems": [{"valueId": "0", "name": "棉"}]},
        {"id": "502", "name": "品牌", "values": ["测试品牌"], "valueItems": [{"valueId": "0", "name": "测试品牌"}]},
    ]
    pdd_detail = repo.detail("pdd:3760269504500859111")
    assert pdd_detail["sourceCategoryId"] is None and pdd_detail["sourceAttributes"] == []
    assert "uu_json" not in detail["product"]


def test_category_paths_read_exact_package_fields_without_modifying_products(engine):
    repo = ProductRepository(engine)
    ids = ["3760269504500859111", "pdd:3760269504500859111"]
    with engine.connect() as conn:
        before = conn.execute(text("SELECT product_id, uu_json::text FROM products WHERE product_id=ANY(CAST(:ids AS text[])) ORDER BY product_id"),
                              {"ids": ids}).all()
    rows = repo.category_paths(ids)
    assert [rows[0][key] for key in ("cat1", "cat2", "cat3", "cat4")] == ["100", "200", "300", "0"]
    assert rows[1]["source_platform"] == "pinduoduo" and rows[1]["cat3"] == "999"
    with engine.connect() as conn:
        after = conn.execute(text("SELECT product_id, uu_json::text FROM products WHERE product_id=ANY(CAST(:ids AS text[])) ORDER BY product_id"),
                             {"ids": ids}).all()
    assert before == after


def test_pdd_category_display_does_not_change_saved_ids(engine):
    product_id = "pdd:3760269504500859111"
    with engine.begin() as conn:
        original = conn.execute(text("SELECT category_path FROM products WHERE product_id=:id"), {"id": product_id}).scalar_one()
        conn.execute(text("UPDATE products SET category_path=:path WHERE product_id=:id"),
                     {"id": product_id, "path": "9323 → 9481 → 10417 → 11366"})
    try:
        repo = ProductRepository(engine)
        expected = "五金工具 → 手动工具 → 扳手 → 梅花扳手"
        assert repo.detail(product_id)["product"]["category_path"] == expected
        row = next(item for item in repo.list(parse_product_list_options({"productId": product_id}))["items"]
                   if item["product_id"] == product_id)
        assert row["category_path"] == expected
        with engine.connect() as conn:
            assert conn.execute(text("SELECT category_path FROM products WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == "9323 → 9481 → 10417 → 11366"
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET category_path=:path WHERE product_id=:id"),
                         {"id": product_id, "path": original})


def test_manual_product_can_be_edited_and_read_by_rpa(engine, tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.schemas import ProductEdit

    repo = ProductRepository(engine)
    product_id = repo.create_manual("手动新建商品")
    try:
        snapshot = repo.edit_snapshot(product_id)
        spec_id = snapshot["specGroups"][0]["values"][0]["id"]
        repo.save_edit(product_id, ProductEdit(expectedVersion=snapshot["version"],
            category=[{"id": "100", "name": "家居"}], mainImages=["https://fixture.invalid/main.png"],
            skus=[{"specIds": [spec_id], "price": "9.90", "stock": 5, "enabled": True}]))
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            response = client.get(f"/rpa/v1/products/{product_id}/uu", headers={"Authorization": "Bearer rpa-test"})
        assert response.status_code == 200
        package = response.json()
        assert package["goodsInfo"]["goodsName"] == "手动新建商品"
        assert package["goodsInfo"]["catId1"] == "100"
        assert package["goodsSkuInfo"]["spec_detail"]["value"][0]["stock_info"]["stock_num"] == 5
        assert repo.detail(product_id)["product"]["title_status"].startswith("手动创建")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_product_deletion_cascades_records_and_preserves_shared_image(engine, tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service

    repo = ProductRepository(engine)
    identities = [repo.create_manual("单删隔离商品"), repo.create_manual("批删隔离商品一"),
                  repo.create_manual("批删隔离商品二"), repo.create_manual("保留隔离商品")]
    shared = tmp_path / "shared.png"
    shared.write_bytes(b"shared test image")
    try:
        with engine.begin() as conn:
            for identity in identities:
                conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                    VALUES (:id,'main',0,'shared.png','https://fixture.invalid/shared.png')"""), {"id": identity})
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test", enable_product_writes=True)
        app = create_application()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            admin, rpa = {"Authorization": "Bearer admin-test"}, {"Authorization": "Bearer rpa-test"}
            assert client.post("/api/v1/products/delete", json={"productIds": [identities[0]]}).status_code == 401
            assert client.post("/api/v1/products/delete", headers=rpa, json={"productIds": [identities[0]]}).status_code == 401
            single = client.post("/api/v1/products/delete", headers=admin, json={"productIds": [identities[0]]})
            assert single.status_code == 200 and single.json() == {"deleted": [identities[0]], "missing": []}
            assert client.get(f"/rpa/v1/products/{identities[0]}/uu", headers=rpa).status_code == 404
            exported = client.post("/api/v1/products/export-uu", headers=admin,
                                   json={"productIds": [identities[0], identities[3]]})
            assert exported.status_code == 200 and exported.headers["x-export-count"] == "1"
            assert exported.headers["x-export-missing-count"] == "1"
            batch = client.post("/api/v1/products/delete", headers=admin,
                                json={"productIds": [identities[1], identities[2]]})
            assert batch.status_code == 200 and set(batch.json()["deleted"]) == set(identities[1:3])
        with engine.connect() as conn:
            for table in ("products", "product_skus", "product_images", "product_prechecks"):
                assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE product_id=ANY(CAST(:ids AS text[]))"),
                                    {"ids": identities[:3]}).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM product_images WHERE product_id=:id"),
                                {"id": identities[3]}).scalar_one() == 1
        assert shared.read_bytes() == b"shared test image"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=ANY(CAST(:ids AS text[]))"), {"ids": identities})


def test_product_delete_role_only_needs_parent_table_delete(engine):
    role = "pdc_delete_role_test"
    repo = ProductRepository(engine)
    product_id = repo.create_manual("授权隔离商品")
    limited = None
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN")
            conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
            conn.exec_driver_sql(f"GRANT SELECT, DELETE ON products TO {role}")
            assert not conn.execute(text("SELECT has_table_privilege(:role, 'product_prechecks', 'DELETE')"),
                                    {"role": role}).scalar_one()
        limited = create_engine(engine.url)
        @event.listens_for(limited, "connect")
        def assume_role(connection, _record):
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {role}")
        assert ProductRepository(limited).delete_products([product_id]) == [product_id]
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM product_prechecks WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == 0
    finally:
        if limited is not None:
            limited.dispose()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})
            if conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}).scalar_one():
                conn.exec_driver_sql(f"DROP OWNED BY {role}")
                conn.exec_driver_sql(f"DROP ROLE {role}")


def test_real_schema_attribute_values_roundtrip_to_export_and_rpa(engine, tmp_path):
    from io import BytesIO
    from unittest.mock import patch
    from zipfile import ZipFile
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.schemas import ProductEdit

    repo = ProductRepository(engine)
    product_id = repo.create_manual("属性隔离商品")
    expected = {
        "2595": [("64357", "3周岁-6周岁"), ("64359", "6周岁-8周岁")],
        "4738": [("0", "11*22*22cm")],
        "989": [("0", "普通文本尺寸")],
        "810": [("10445", "可拆卸"), ("0", "测试定制功能")],
    }
    try:
        snapshot = repo.edit_snapshot(product_id)
        repo.save_edit(product_id, ProductEdit(expectedVersion=snapshot["version"],
            category=[{"id": "1000001467", "name": "玩具"}, {"id": "1000001477", "name": "益智早教玩具"},
                      {"id": "1000001535", "name": "智力思维训练"}],
            attributes=[{"id": identity, "name": label, "values": [{"valueId": value_id, "name": name}
                         for value_id, name in expected[identity]]} for identity, label in
                        [("2595", "适用年龄"), ("4738", "规格尺寸"), ("989", "尺寸"), ("810", "功能")]]))
        actual = {item["id"]: [(value["valueId"], value["name"]) for value in item["valueItems"]]
                  for item in repo.detail(product_id)["sourceAttributes"]}
        assert actual == expected
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            rpa = client.get(f"/rpa/v1/products/{product_id}/uu", headers={"Authorization": "Bearer rpa-test"})
            exported = client.post("/api/v1/products/export-uu", headers={"Authorization": "Bearer admin-test"},
                                   json={"productIds": [product_id]})
        assert rpa.status_code == exported.status_code == 200
        with ZipFile(BytesIO(exported.content)) as archive:
            filename = next(name for name in archive.namelist() if name.startswith("UU/") and name.endswith("_UU.txt"))
            package = json.loads(archive.read(filename))
        assert package["category_properties_value"] == rpa.json()["category_properties_value"]
        for identity, values in expected.items():
            assert [(item["value_id"], item["value_name"]) for item in
                    package["category_properties_value"]["value"][identity]] == values
        with engine.connect() as conn:
            assert conn.execute(text("SELECT state FROM product_prechecks WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == "pending"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_manual_create_saves_complete_package_atomically_with_restricted_role(engine, tmp_path):
    from contextlib import contextmanager
    from decimal import Decimal
    from unittest.mock import patch as mock_patch
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.errors import ProductRequestError
    from app.modules.products.schemas import ProductEdit

    role = "manual_test_" + uuid4().hex[:12]
    seed = uuid4().hex
    title = "手动创建完整测试"
    spec = f"local-{seed}-spec"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
        conn.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        conn.exec_driver_sql(f'GRANT SELECT ON products, product_skus, product_images TO "{role}"')
        conn.exec_driver_sql(f'GRANT INSERT ON products, product_skus, product_images TO "{role}"')
        conn.exec_driver_sql(f'''GRANT UPDATE (uu_json, uu_sha256, title, title_status,
            category_level_1, category_level_2, category_level_3, category_level_4,
            category_path, category_leaf_id, main_image_count, detail_image_count,
            sku_image_count, sku_count, current_price_min, current_price_max) ON products TO "{role}"''')
        conn.exec_driver_sql(f'GRANT UPDATE (sku_name, current_price, image_rel_path, sort_order) ON product_skus TO "{role}"')
        conn.exec_driver_sql(f'GRANT DELETE ON product_skus, product_images TO "{role}"')

    class RestrictedEngine:
        @contextmanager
        def begin(self):
            with engine.begin() as conn:
                conn.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
                yield conn

    repo = ProductRepository(RestrictedEngine())
    patch = ProductEdit(expectedVersion="0" * 64, title=title,
        category=[{"id": "100", "name": "家居"}], mainImages=["https://fixture.invalid/main.png"],
        specStructure={"groups": [{"sourceIndex": 0, "name": "颜色", "values": [
            {"id": spec, "name": "白色", "url": "https://fixture.invalid/white.png"},
            {"id": "local-blue", "name": "蓝色", "url": "https://fixture.invalid/blue.png"}]}],
            "skus": [{"sourceSpecIds": [spec], "specIds": [spec], "price": "9.90", "stock": "5", "enabled": True},
                     {"sourceSpecIds": None, "specIds": ["local-blue"], "price": "12.00", "stock": "3", "enabled": True}]})
    product_id = None
    try:
        product_id = repo.create_manual(title, seed, patch)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT uu_json, category_path FROM products WHERE product_id=:id"),
                               {"id": product_id}).mappings().one()
            assert row["category_path"] == "家居"
            assert row["uu_json"]["goodsInfo"]["goodsImageList"] == ["https://fixture.invalid/main.png"]
            assert row["uu_json"]["goodsSkuInfo"]["spec_detail"]["value"][0]["stock_info"]["stock_num"] == 5
            prices = conn.execute(text("SELECT current_price FROM product_skus WHERE product_id=:id ORDER BY sort_order"),
                                  {"id": product_id}).scalars().all()
            assert prices == [Decimal("9.90"), Decimal("12.00")]
        settings = Settings(data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_service] = lambda: ProductService(ProductRepository(engine), settings)
        with mock_patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            response = client.get(f"/rpa/v1/products/{product_id}/uu", headers={"Authorization": "Bearer rpa-test"})
        assert response.status_code == 200
        assert response.json()["goodsSkuInfo"]["spec_detail"]["value"][1]["stock_info"]["stock_num"] == 3
        bad_title = "失败回滚测试"
        bad = ProductEdit(expectedVersion="0" * 64, title=bad_title,
                          skus=[{"specIds": ["does-not-exist"], "price": "1.00"}])
        with pytest.raises(ProductRequestError):
            repo.create_manual(bad_title, seed, bad)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM products WHERE title=:title"),
                                {"title": bad_title}).scalar_one() == 0
    finally:
        with engine.begin() as conn:
            if product_id:
                conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})
            conn.exec_driver_sql(f'DROP OWNED BY "{role}"')
            conn.exec_driver_sql(f'DROP ROLE "{role}"')


def test_automatic_precheck_tracks_committed_package_revisions(engine):
    from app.modules.prechecks.queue import PrecheckQueue

    repo, queue = ProductRepository(engine), PrecheckQueue(engine)
    product_id = repo.create_manual("自动预检隔离商品")
    try:
        initial = queue.results([product_id])[0]
        assert initial["state"] == "pending" and initial["result"] is None
        first = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET uu_json=uu_json || '{\"testRevision\": 2}'::jsonb WHERE product_id=:id"),
                         {"id": product_id})
        assert queue.complete(first, {"status": "ready", "issues": []}) is False
        queue.retry(first)
        second = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert second["revision"] == first["revision"] + 1
        assert queue.complete(second, {"productId": product_id, "status": "needs_completion", "issues": ["商品主图"]})
        with engine.begin() as conn:
            conn.execute(text("UPDATE products SET uu_json=uu_json WHERE product_id=:id"), {"id": product_id})
        final = queue.results([product_id])[0]
        assert final["state"] == "done" and final["result"]["issues"] == ["商品主图"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})
        assert queue.results([product_id]) == []


def test_manual_enqueue_invalidates_an_inflight_precheck(engine):
    from app.modules.prechecks.queue import PrecheckQueue

    repo, queue = ProductRepository(engine), PrecheckQueue(engine)
    product_id = repo.create_manual("手动预检隔离商品")
    try:
        first = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        queued = queue.enqueue([product_id, "missing-product"])
        assert len(queued) == 1
        assert queued[0]["productId"] == product_id
        assert queued[0]["revision"] == first["revision"] + 1
        assert queued[0]["state"] == "pending" and queued[0]["result"] is None
        assert queue.complete(first, {"productId": product_id, "status": "ready", "issues": []}) is False
        second = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert second["revision"] == queued[0]["revision"]
        assert queue.complete(second, {"productId": product_id, "status": "ready", "issues": []}) is True
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_worker_precheck_wait_states_and_revision_fence(engine):
    from app.modules.prechecks.queue import PrecheckQueue

    repo, queue = ProductRepository(engine), PrecheckQueue(engine)
    product_id = repo.create_manual("Worker 等待隔离商品")
    try:
        first = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert queue.defer_worker(first, running=True) is True
        assert queue.results([product_id])[0]["state"] == "running"
        with engine.begin() as conn:
            conn.execute(text("UPDATE product_prechecks SET lease_until=now()-interval '1 second' WHERE product_id=:id"),
                         {"id": product_id})
        second = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert second["attempts"] == first["attempts"] + 1
        assert queue.defer_worker(first) is False
        assert queue.defer_worker(second) is True
        assert queue.results([product_id])[0]["state"] == "pending"
        with engine.begin() as conn:
            conn.execute(text("UPDATE product_prechecks SET available_at=now()-interval '1 second' WHERE product_id=:id"),
                         {"id": product_id})
        third = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert queue.defer_worker(third, running=True, waiting_result=True) is True
        waiting = queue.results([product_id])[0]
        assert waiting["state"] == "running" and waiting["waitingForWorker"] is True and waiting["error"] is None
        with engine.begin() as conn:
            conn.execute(text("UPDATE product_prechecks SET lease_until=now()-interval '1 second' WHERE product_id=:id"),
                         {"id": product_id})
        fourth = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert queue.complete(third, {"status": "ready", "issues": []}) is False
        assert queue.complete(fourth, {"status": "ready", "issues": []}) is True
        queue.enqueue([product_id])
        assert queue.defer_worker(fourth) is False
        assert queue.complete(fourth, {"status": "ready", "issues": []}) is False
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_collected_pdd_auto_precheck_keeps_recommendation_for_confirmation(engine, tmp_path):
    from uuid import uuid4
    from app.modules.central.client import CentralCookie, CentralShop, CentralShopSession
    from app.modules.prechecks.queue import PrecheckQueue
    from app.modules.prechecks.runner import PrecheckRunner

    product_id = "pdd:1234567890123456789"
    shop_id = uuid4()
    title = "完整拼多多标题" * 4
    image = "https://fixture.invalid/main.png"
    package = {"product": {"title": title}, "images": {"main": [{"url": image}]}}
    settings = Settings(data_root=tmp_path, douyin_category_lookup_enabled=True)
    class Central:
        def list_shops(self):
            return [CentralShop(shop_id=shop_id, display_name="隔离店铺", platform="douyin", session_status="valid")]
        def read_session(self, requested, expected_platform):
            return CentralShopSession(shop_id=requested, platform=expected_platform, session_version=1,
                cookies=(CentralCookie(name="sessionid", value="synthetic", domain=".jinritemai.com"),))
    class Lookup:
        def __init__(self): self.settings = settings
        def predict(self, session, actual_title, image_url):
            assert actual_title == title and image_url == image
            return {"recommendedId": "102", "candidates": [{"id": "102", "name": "收纳架", "path": "居家 > 收纳架",
                "selectable": True, "levels": [{"id": "100", "name": "居家"}, {"id": "102", "name": "收纳架"}]}]}
    try:
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO products(product_id, source_platform, title, captured_at, uu_json)
                VALUES (:id, 'pinduoduo', :title, now(), CAST(:package AS jsonb))"""),
                {"id": product_id, "title": title, "package": json.dumps(package, ensure_ascii=False)})
            conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,sort_order)
                VALUES (:id,'sku-1','默认',9.90,0)"""), {"id": product_id})
            conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url)
                VALUES (:id,'main',0,'',:image)"""), {"id": product_id, "image": image})
        queue = PrecheckQueue(engine)
        claim = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        runner = PrecheckRunner(engine, settings)
        runner.central, runner.lookup = Central(), Lookup()
        runner.process(claim)
        record = queue.results([product_id])[0]
        assert record["state"] == "done" and record["result"]["status"] == "needs_category"
        assert record["result"]["prediction"]["recommendedId"] == "102"
        assert ProductRepository(engine).detail(product_id)["targetCategory"] == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_product_writes_do_not_require_direct_queue_insert_permission(engine):
    role = "pdc_precheck_writer_test"
    product_id = "pdd:1234567890123456790"
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN")
            conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
            conn.exec_driver_sql(f"GRANT INSERT ON products TO {role}")
            assert not conn.execute(text("SELECT has_table_privilege(:role, 'product_prechecks', 'INSERT')"),
                                    {"role": role}).scalar_one()
            conn.exec_driver_sql(f"SET LOCAL ROLE {role}")
            conn.execute(text("""INSERT INTO products(product_id,source_platform,title,uu_json)
                VALUES (:id,'pinduoduo','权限测试','{}'::jsonb)"""), {"id": product_id})
            conn.exec_driver_sql("RESET ROLE")
            assert conn.execute(text("SELECT state FROM product_prechecks WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == "pending"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})
            if conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:role)"), {"role": role}).scalar_one():
                conn.exec_driver_sql(f"DROP OWNED BY {role}")
                conn.exec_driver_sql(f"DROP ROLE {role}")


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
    package = {"product": {"title": "收纳盒", "categoryIds": ["77"],
                           "properties": [{"key": "产地", "values": ["中国大陆"], "propertyId": "482"}]}, "images": {"main": [], "detail": []},
               "skus": [{"skuId": "100", "onSale": False}]}
    if legacy:
        package = {"goodsInfo": {"goodsName": "收纳盒", "catId1": "77", "goodsImageList": []},
                   "goodsSkuInfo": {"spec_detail": {"value": [{"sku_status": False}]}},
                   "goodsDetailInfo": {"detail_imgs": [], "product_format": [{"format": [
                       {"property_id": "482", "name": "产地", "message": [{"desc": "中国大陆"}]}]}]}}
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
        assert detail["sourceAttributes"] == [{"id": "482", "name": "产地", "values": ["中国大陆"],
                                                "valueItems": [{"valueId": "0", "name": "中国大陆"}]}]
        assert detail["targetAttributes"] == [{"id": "12", "name": "材质", "values": ["塑料"],
                                                "valueItems": [{"valueId": "13", "name": "塑料"}]}]
        assert detail["product"]["category_path"] == original.category_path
        saved = json.loads(repo.export_rows([product_id])[0]["uu_text"])
        assert all(saved[key] == value for key, value in package.items())
        assert saved["douyinTarget"]["attributes"]["12"]["values"][0]["valueId"] == "13"
        # The repository hashes PostgreSQL's JSON text, not Python's serialization.
        with engine.connect() as conn:
            version = hashlib.sha256(conn.execute(text("SELECT uu_json::text FROM products WHERE product_id=:id"),
                                                 {"id": product_id}).scalar_one().encode()).hexdigest()
        repo.save_edit(product_id, ProductEdit(expectedVersion=version,
            attributes=[{"id": "12", "name": "材质", "values": []}]))
        assert repo.detail(product_id)["targetAttributes"] == [{"id": "12", "name": "材质", "values": [],
                                                                 "valueItems": []}]
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


def test_pdd_spec_image_replacement_preserves_other_skus_and_unmapped_images(engine, tmp_path):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.errors import ProductRequestError
    from app.modules.products.export import current_uu_bytes
    from app.modules.products.schemas import ProductEdit

    identity = "pdd:9999999999999999915"
    package = {"goodsInfo": {"goodsName": "拼多多规格图测试", "skuInfoMap": {
        "11": {"sku_id": "1001"}, "12": {"sku_id": "1002"}}},
        "spec_detail_value": {"value": [{"name": "颜色", "spec_values": [
            {"id": "11", "name": "黑色", "img_url": "https://example.test/black"},
            {"id": "12", "name": "白色", "img_url": "https://example.test/white"}]}]},
        "goodsSkuInfo": {"sku_detail": [{"name": "颜色", "spec_item_list": [
            {"spec_item_id": "11", "big_pic": "https://example.test/black"},
            {"spec_item_id": "12", "big_pic": "https://example.test/white"}]}],
            "spec_detail": {"value": [{"spec_detail_ids": ["11"], "price": "2", "sku_status": False},
                                       {"spec_detail_ids": ["12"], "price": "3", "sku_status": True}]}},
        "unknown": {"keep": True}}
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO products(product_id,source_platform,source_product_id,title,uu_json,sku_count)
            VALUES (:id,'pinduoduo','9999999999999999915','隔离商品',CAST(:package AS jsonb),2)"""),
            {"id": identity, "package": json.dumps(package, ensure_ascii=False)})
        conn.execute(text("""INSERT INTO product_skus(product_id,sku_id,sku_name,current_price,image_rel_path,sort_order)
            VALUES (:id,'1001','黑色',2,'black-file',0),(:id,'1002','白色',3,'white-file',1)"""), {"id": identity})
        conn.execute(text("""INSERT INTO product_images(product_id,image_type,sort_order,rel_path,source_url) VALUES
            (:id,'sku',0,'black-file','https://example.test/black'),
            (:id,'sku',1,'white-file','https://example.test/white'),
            (:id,'sku',2,'other-file','https://example.test/unmapped'),
            (:id,'sku',3,'local-only-file',''),
            (:id,'sku',4,'duplicate-file','https://example.test/white')"""), {"id": identity})
    try:
        repo = ProductRepository(engine)
        snapshot = repo.edit_snapshot(identity)
        assert snapshot["specImagesEditable"] is True
        repo.save_edit(identity, ProductEdit(expectedVersion=snapshot["version"],
            specImages=[{"specId": "11", "url": "https://example.test/new"}]))
        detail = repo.detail(identity)
        image_rows = [image for image in detail["images"] if image["image_type"] == "sku"]
        assert [(row["source_url"], row["rel_path"]) for row in image_rows] == [
            ("https://example.test/new", ""), ("https://example.test/white", "white-file"),
            ("https://example.test/unmapped", "other-file"), ("", "local-only-file"),
            ("https://example.test/white", "duplicate-file")]
        assert [sku["image_rel_path"] for sku in detail["skus"]] == ["", "white-file"]
        exported, _ = current_uu_bytes(repo.export_rows([identity])[0], 1_000_000)
        result = json.loads(exported)
        assert result["spec_detail_value"]["value"][0]["spec_values"][0]["img_url"] == "https://example.test/new"
        assert result["spec_detail_value"]["value"][0]["spec_values"][1]["img_url"] == "https://example.test/white"
        assert result["goodsSkuInfo"]["spec_detail"] == package["goodsSkuInfo"]["spec_detail"]
        assert result["goodsInfo"] == package["goodsInfo"] and result["unknown"] == package["unknown"]
        settings = Settings(_env_file=None, data_root=tmp_path, api_token="admin-test", rpa_api_token="rpa-test")
        app = create_application()
        app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
        with patch("app.core.security.access.get_settings", return_value=settings), TestClient(app) as client:
            response = client.get(f"/rpa/v1/products/{identity}/uu", headers={"Authorization": "Bearer rpa-test"})
            assert response.status_code == 200 and response.content == exported
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM product_skus WHERE product_id=:id AND sku_id='1002'"), {"id": identity})
        unsafe = repo.edit_snapshot(identity)
        assert unsafe["specImagesEditable"] is False
        with pytest.raises(ProductRequestError):
            repo.save_edit(identity, ProductEdit(expectedVersion=unsafe["version"],
                specImages=[{"specId": "11", "url": "https://example.test/rejected"}]))
        after, _ = current_uu_bytes(repo.export_rows([identity])[0], 1_000_000)
        assert after == exported
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": identity})


def test_uploaded_image_urls_round_trip_through_postgres_and_rpa(engine, tmp_path):
    import base64
    from unittest.mock import patch
    from urllib.parse import urlsplit

    from fastapi.testclient import TestClient
    from app.main import create_application
    from app.modules.products.api import get_service
    from app.modules.products.schemas import ProductEdit

    image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/CZYAAAAASUVORK5CYII=")
    settings = Settings(_env_file=None, api_token="admin-test", rpa_api_token="rpa-test", enable_product_writes=True,
                        image_storage_dir=tmp_path, image_public_base_url="https://images.example.test")
    repo = ProductRepository(engine)
    product_id = repo.create_manual("图片上传隔离商品")
    app = create_application()
    app.dependency_overrides[get_service] = lambda: ProductService(repo, settings)
    try:
        with patch("app.core.security.access.get_settings", return_value=settings), \
             patch("app.modules.product_images.api.get_settings", return_value=settings), TestClient(app) as client:
            uploaded = client.post('/api/v1/product-images', content=image,
                                   headers={"Authorization": "Bearer admin-test", "Content-Type": "image/png"})
            assert uploaded.status_code == 201
            url = uploaded.json()["url"]
            snapshot = repo.edit_snapshot(product_id)
            spec_id = snapshot["specImages"][0]["id"]
            repo.save_edit(product_id, ProductEdit(expectedVersion=snapshot["version"], mainImages=[url], detailImages=[url],
                                                  specImages=[{"specId": spec_id, "url": url}]))
            response = client.get(f"/rpa/v1/products/{product_id}/uu", headers={"Authorization": "Bearer rpa-test"})
            assert response.status_code == 200
            package = response.json()
            assert package["goodsInfo"]["goodsImageList"] == [url]
            assert package["goodsDetailInfo"]["detail_imgs"][0]["url_list"] == [url]
            assert package["goodsSkuInfo"]["sku_detail"][0]["spec_item_list"][0]["big_pic"] == url
            assert client.get(urlsplit(url).path).content == image
        assert [x["source_url"] for x in repo.detail(product_id)["images"]].count(url) == 3
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


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


def test_no_brand_batch_updates_only_brand_and_preserves_later_manual_choice(engine):
    product_id = "1234567890123456799"
    package = {
        "goodsInfo": {"goodsName": "品牌隔离测试", "catId4": "1000008074"},
        "category_properties_value": {"value": {
            "100": [{"k": "材质", "value_id": "7", "value_name": "棉"}],
            "1687": [{"k": "品牌", "value_id": "other", "value_name": "其他品牌"}],
        }},
        "unrelated": {"keep": [1, 2, 3]},
    }
    selection = {"fieldId": "1687", "fieldName": "品牌",
                 "valueId": "596120136", "valueName": "无品牌"}
    try:
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO products(product_id,source_platform,title,title_status,uu_json)
                VALUES (:id,'douyin','品牌隔离测试','采集完成',CAST(:package AS jsonb))"""),
                {"id": product_id, "package": json.dumps(package, ensure_ascii=False)})
        repo = ProductRepository(engine)
        assert repo.set_default_brand(product_id, selection, force=True, mark_modified=False) == "updated"
        with engine.connect() as conn:
            saved, status, queue_state = conn.execute(text("""SELECT uu_json,title_status,
                (SELECT state FROM product_prechecks WHERE product_id=:id) FROM products WHERE product_id=:id"""),
                {"id": product_id}).one()
        assert saved["category_properties_value"]["value"]["1687"] == [{
            "diy_type": 0, "k": "品牌", "value_id": "596120136", "value_name": "无品牌",
        }]
        assert saved["category_properties_value"]["value"]["100"] == package["category_properties_value"]["value"]["100"]
        assert saved["unrelated"] == package["unrelated"] and status == "采集完成" and queue_state == "pending"
        assert repo.set_default_brand(product_id, selection, force=True, mark_modified=False) == "already"
        with engine.begin() as conn:
            conn.execute(text("""UPDATE products SET title_status='采集完成 | 商品库已修改',
                uu_json=jsonb_set(uu_json,'{category_properties_value,value,1687}',
                '[{"k":"品牌","value_id":"2065951823","value_name":"HP/惠普"}]'::jsonb)
                WHERE product_id=:id"""), {"id": product_id})
        assert repo.set_default_brand(product_id, selection, force=False, mark_modified=False) == "manual"
        with engine.connect() as conn:
            assert conn.execute(text("""SELECT uu_json #>> '{category_properties_value,value,1687,0,value_name}'
                FROM products WHERE product_id=:id"""), {"id": product_id}).scalar_one() == "HP/惠普"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_worker_brand_write_is_fenced_by_precheck_claim(engine):
    from uuid import uuid4
    from app.modules.prechecks.queue import PrecheckQueue

    product_id = str(uuid4().int)[:19]
    package = {"goodsInfo": {"goodsName": "隔离品牌测试", "catId4": "1000008074"},
               "category_properties_value": {"value": {}}}
    selection = {"fieldId": "1687", "fieldName": "品牌", "valueId": "596120136", "valueName": "无品牌"}
    repo, queue = ProductRepository(engine), PrecheckQueue(engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO products(product_id,source_platform,title,title_status,uu_json)
                VALUES (:id,'douyin','隔离品牌测试','采集完成',CAST(:package AS jsonb))"""),
                {"id": product_id, "package": json.dumps(package, ensure_ascii=False)})
        old = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        queue.enqueue([product_id])
        current = next(item for item in queue.claim(100) if item["product_id"] == product_id)
        assert repo.set_default_brand(product_id, selection, expected_precheck_claim=old) == "stale"
        with engine.connect() as conn:
            assert conn.execute(text("SELECT uu_json FROM products WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == package
        assert repo.set_default_brand(product_id, selection, expected_precheck_claim=current) == "updated"
        result = queue.results([product_id])[0]
        assert result["revision"] == current["revision"] + 1 and result["state"] == "pending"
        assert queue.complete(current, {"status": "ready", "issues": []}) is False
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})


def test_worker_brand_waits_for_concurrent_edit_then_rejects_stale_claim(engine):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from uuid import uuid4
    from app.modules.prechecks.queue import PrecheckQueue

    product_id = str(uuid4().int)[:19]
    package = {"goodsInfo": {"goodsName": "隔离编辑测试", "catId4": "1000008074"},
               "category_properties_value": {"value": {}}}
    edited = {"goodsInfo": package["goodsInfo"], "category_properties_value": {"value": {
        "1687": [{"k": "品牌", "value_id": "manual", "value_name": "手动品牌"}]}}}
    selection = {"fieldId": "1687", "fieldName": "品牌", "valueId": "596120136", "valueName": "无品牌"}
    repo, queue = ProductRepository(engine), PrecheckQueue(engine)
    locked, release, started = Event(), Event(), Event()
    try:
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO products(product_id,source_platform,title,title_status,uu_json)
                VALUES (:id,'douyin','隔离编辑测试','采集完成',CAST(:package AS jsonb))"""),
                {"id": product_id, "package": json.dumps(package, ensure_ascii=False)})
        claim = next(item for item in queue.claim(100) if item["product_id"] == product_id)

        def edit():
            with engine.begin() as conn:
                conn.execute(text("SELECT product_id FROM products WHERE product_id=:id FOR UPDATE"), {"id": product_id})
                locked.set()
                assert release.wait(10)
                conn.execute(text("""UPDATE products SET uu_json=CAST(:package AS jsonb),
                    title_status='商品库已修改' WHERE product_id=:id"""),
                    {"id": product_id, "package": json.dumps(edited, ensure_ascii=False)})

        def brand():
            started.set()
            return repo.set_default_brand(product_id, selection, expected_precheck_claim=claim)

        with ThreadPoolExecutor(max_workers=2) as pool:
            editing = pool.submit(edit)
            assert locked.wait(10)
            applying = pool.submit(brand)
            try:
                assert started.wait(10)
                assert not applying.done()
            finally:
                release.set()
            editing.result(timeout=15)
            assert applying.result(timeout=15) == "stale"
        with engine.connect() as conn:
            assert conn.execute(text("SELECT uu_json FROM products WHERE product_id=:id"),
                                {"id": product_id}).scalar_one() == edited
        assert queue.complete(claim, {"status": "ready", "issues": []}) is False
    finally:
        release.set()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM products WHERE product_id=:id"), {"id": product_id})
