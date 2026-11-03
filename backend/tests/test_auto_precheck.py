from types import SimpleNamespace as Node
from unittest.mock import patch

from app.modules.category_lookup.api import Attribute, Option
from app.modules.prechecks.service import _missing_required, check_product


def test_required_values_match_original_id_or_unambiguous_pdd_name():
    fields = [Attribute(id="1", label="材质", required=True, options=[Option(label="塑料", value="5")]),
              Attribute(id="2", label="品牌", required=True, options=[])]
    source = [{"id": "1", "name": "材质", "values": ["塑料"]}]
    assert _missing_required(fields, source, [], "douyin") == ["品牌"]
    assert _missing_required(fields, [{"id": "99", "name": "材质", "values": ["木材"]}], [], "pinduoduo") == ["材质", "品牌"]
    assert _missing_required(fields, source, [{"id": "1", "name": "材质", "values": []}], "pinduoduo") == ["材质", "品牌"]


def test_douyin_auto_check_uses_original_category_and_lists_missing_names():
    product_id = "12345678"
    detail = {"product": {"source_platform": "douyin", "title": "商品", "main_image_url": "https://example.invalid/a"},
              "images": [], "skus": [{"current_price": "9.90"}], "sourceCategoryId": "100",
              "sourceAttributes": [{"id": "1", "name": "材质", "values": ["棉"]}],
              "targetCategory": [], "targetAttributes": []}
    fields = [Attribute(id="1", label="材质", required=True, options=[]),
              Attribute(id="2", label="品牌", required=True, options=[])]
    service = Node(repository=Node(detail=lambda _: detail))
    with patch("app.modules.prechecks.service.schema_auto", return_value=Node(attributes=fields)) as schema, \
            patch("app.modules.prechecks.service.predict") as predict:
        result = check_product(product_id, service, None, None)
    assert result["status"] == "needs_completion" and result["issues"] == ["必填属性：品牌"]
    assert schema.call_args.args[0].categoryId == "100"
    predict.assert_not_called()


def test_auto_precheck_result_api_requires_authentication_and_enabled_feature(tmp_path):
    from fastapi.testclient import TestClient
    from app.core.config import Settings, get_settings
    from app.main import create_application

    settings = Settings(data_root=tmp_path, api_token="synthetic-admin-token", auto_precheck_enabled=False)
    app = create_application()
    app.dependency_overrides[get_settings] = lambda: settings
    with patch("app.core.security.access.get_settings", return_value=settings), \
            patch("app.modules.prechecks.api.get_settings", return_value=settings), TestClient(app) as client:
        assert client.post("/api/v1/prechecks/query", json={"productIds": ["12345678"]}).status_code == 401
        response = client.post("/api/v1/prechecks/query", json={"productIds": ["12345678"]},
                               headers={"Authorization": "Bearer synthetic-admin-token"})
        assert response.status_code == 503
