import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.modules.central.client import CentralApplicationClient, CentralConnectionError
from app.modules.prechecks.runner import PrecheckRunner


TASK_ID = UUID("8e55252f-5035-40b2-9673-d990a8f6e001")
TOKEN = "synthetic-central-token-0123456789abcdef"


@pytest.fixture
def settings(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text(TOKEN, encoding="ascii")
    return Settings(_env_file=None, central_application_enabled=True,
                    central_application_base_url="https://central.test",
                    central_application_token_file=token_file,
                    worker_precheck_enabled=True)


def detail(*, edited=True):
    return {"product": {"source_platform": "douyin", "title": "测试商品",
                        "title_status": "商品库已修改" if edited else "采集完成",
                        "main_image_url": "https://example.invalid/main.jpg"},
            "images": [], "skus": [{"current_price": "9.90"}],
            "sourceCategoryId": "1000001535", "sourceAttributes": [],
            "targetCategory": [], "targetAttributes": []}


def success_result(items=None):
    return {"kind": "douyin.category_schema", "category_id": "1000001535",
            "device_id": "device-1", "local_shop_id": "local-1", "platform_shop_id": "shop-1",
            "http_status": 200, "platform_code": 0, "items": items or []}


def make_runner(settings, handler, product_detail=None):
    runner = object.__new__(PrecheckRunner)
    runner.central = CentralApplicationClient(settings, transport=httpx.MockTransport(handler))
    runner.lookup = None
    runner.worker_precheck_enabled = True
    runner.service = SimpleNamespace(repository=Mock(detail=Mock(return_value=product_detail or detail())))
    runner.queue = Mock()
    runner.queue.complete.return_value = True
    return runner


def delivery_context(revision=7):
    return SimpleNamespace(task_id=TASK_ID, product_id="12345678", revision=revision,
                           device_id="device-1", category_id="1000001535",
                           local_shop_id="local-1", platform_shop_id="shop-1")


def test_submit_once_then_direct_result_uses_product_rules(settings):
    requests = []
    items = [{"id": "brand", "label": "品牌", "required": True, "type": "text"}]

    def handler(request):
        assert request.headers["X-Application-ID"] == "product-library"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.url.path.startswith("/internal/applications/v1/worker-prechecks")
        assert request.method == "POST"  # no result polling
        requests.append(json.loads(request.content))
        return httpx.Response(202, json={"task_id": str(TASK_ID), "status": "pending"})

    runner = make_runner(settings, handler)
    claim = {"product_id": "12345678", "revision": 7, "attempts": 1}
    with patch("app.modules.prechecks.service.schema_auto", side_effect=AssertionError("unexpected direct request")):
        runner.process(claim)
        runner.queue.claim_worker_result.return_value = ("claimed", claim)
        assert runner.accept_worker_delivery(delivery_context(),
            SimpleNamespace(status="success", result=success_result(items)), "a" * 64)
    assert len(requests) == 1 and requests[0]["delivery"] == "product"
    assert requests[0]["input"] == {"category_id": "1000001535", "title": "测试商品"}
    runner.queue.wait_for_worker.assert_called_once_with(claim)
    result_claim, result = runner.queue.complete.call_args.args
    assert result_claim == claim
    assert result["status"] == "needs_completion" and result["issues"] == ["品牌未填写"]


@pytest.mark.parametrize(("status", "result", "expected"), [
    ("failed", {"error_stage": "platform", "platform_code": "10008"}, "平台预检失败（代码 10008）"),
    ("failed", {"error_stage": "session", "safe_error_code": "RPA_BRIDGE_UNAVAILABLE", "platform_code": None},
     "读取本机店铺会话未完成"),
    ("failed", {"error_stage": "session", "safe_error_code": "RPA_SESSION_UNAVAILABLE", "platform_code": None},
     "读取本机店铺会话未完成"),
    ("failed", {"error_stage": "session", "safe_error_code": "RPA_SHOP_IDENTITY_UNCONFIRMED", "platform_code": None},
     "读取本机店铺会话未完成"),
    ("failed", {"error_stage": "session", "safe_error_code": "UNRECOGNIZED_CODE", "platform_code": None},
     "读取本机店铺会话未完成"),
    ("failed", {"error_stage": "session", "platform_code": None}, "读取本机店铺会话未完成"),
    ("failed", {"error_stage": "platform", "platform_code": "<private>"}, "平台预检失败"),
])
def test_terminal_failure_is_visible_without_redispatch(settings, status, result, expected):
    runner = make_runner(settings, lambda request: pytest.fail("unexpected request"))
    claim = {"product_id": "12345678", "revision": 2, "attempts": 1}
    runner.queue.claim_worker_result.return_value = ("claimed", claim)
    identity = {key: value for key, value in success_result().items() if key != "items"}
    runner.accept_worker_delivery(delivery_context(2), SimpleNamespace(status=status, result={**identity, **result}), "a" * 64)
    runner.queue.defer_worker.assert_not_called()
    assert runner.queue.complete.call_args.args[1]["issues"] == [expected]


def test_late_and_duplicate_results_do_not_repeat_product_processing(settings):
    runner = make_runner(settings, lambda request: pytest.fail("unexpected request"))
    claim = {"product_id": "12345678", "revision": 1, "attempts": 1}
    runner.queue.claim_worker_result.side_effect = [("claimed", claim), ("duplicate", None), ("stale", None)]
    terminal = SimpleNamespace(status="success", result=success_result())
    assert runner.accept_worker_delivery(delivery_context(1), terminal, "a" * 64)
    assert runner.accept_worker_delivery(delivery_context(1), terminal, "a" * 64)
    assert not runner.accept_worker_delivery(delivery_context(1), terminal, "a" * 64)
    runner.queue.complete.assert_called_once()


def test_network_failure_is_deferred_but_auth_and_conflict_fail_closed(settings):
    claim = {"product_id": "12345678", "revision": 1, "attempts": 1}
    for http_status in (401, 409, 503):
        runner = make_runner(settings, lambda request: httpx.Response(http_status))
        runner.process(claim)
        if http_status == 503:
            runner.queue.defer_worker.assert_called_once_with(claim)
            runner.queue.complete.assert_not_called()
        else:
            runner.queue.defer_worker.assert_not_called()
            assert runner.queue.complete.call_args.args[1]["status"] == "failed"
            assert runner.queue.complete.call_args.args[1]["issues"] == [
                "预检服务未授权" if http_status == 401 else "预检任务内容不一致，请重新预检"]


def test_result_stream_supports_large_schema_but_rejects_over_limit(settings):
    result = success_result([{"id": "large", "name": "x" * (1024 * 1024 + 10)}])
    def handler(request):
        return httpx.Response(200, json={"task_id": str(TASK_ID), "status": "success",
                                        "result": result, "error_code": None, "error_message": None})
    client = CentralApplicationClient(settings, transport=httpx.MockTransport(handler))
    assert len(client.read_worker_precheck(TASK_ID).result["items"][0]["name"]) > 1024 * 1024
    result["items"][0]["name"] = "x" * (4 * 1024 * 1024 + 20 * 1024)
    with pytest.raises(CentralConnectionError, match="invalid_response"):
        client.read_worker_precheck(TASK_ID)


def test_central_task_identity_mismatch_is_rejected(settings):
    client = CentralApplicationClient(settings, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"task_id": "8e55252f-5035-40b2-9673-d990a8f6e002",
                                                "status": "success", "result": success_result(),
                                                "error_code": None, "error_message": None})))
    with pytest.raises(CentralConnectionError, match="invalid_response"):
        client.read_worker_precheck(TASK_ID)


def test_missing_category_is_checked_locally_without_worker_or_platform(settings):
    local = detail()
    local["sourceCategoryId"] = None
    runner = make_runner(settings, lambda request: pytest.fail("unexpected central request"), local)
    claim = {"product_id": "12345678", "revision": 1, "attempts": 1}
    with patch("app.modules.prechecks.service.schema_auto", side_effect=AssertionError("unexpected platform request")):
        runner.process(claim)
    assert runner.queue.complete.call_args.args[1]["status"] == "needs_category"
    assert runner.queue.complete.call_args.args[1]["issues"] == ["类目未选择"]


def test_default_brand_still_advances_revision_and_new_result_is_correct(settings):
    item = {"id": "1687", "label": "品牌", "required": True,
            "additions": {"ui_type": "select", "diy_type": 0},
            "options": [{"value_id": "596120136", "value_name": "无品牌"}]}
    product = detail(edited=False)
    runner = make_runner(settings, lambda request: pytest.fail("unexpected request"), product)
    repo = runner.service.repository
    repo.detail.side_effect = lambda _: deepcopy(product)
    def save_brand(*args, **kwargs):
        if product["sourceAttributes"]:
            return "unchanged"
        product["sourceAttributes"] = [{"id": "1687", "name": "品牌",
                                        "valueItems": [{"valueId": "596120136", "name": "无品牌"}]}]
        return "updated"
    repo.set_default_brand.side_effect = save_brand
    first = {"product_id": "12345678", "revision": 1, "attempts": 1}
    runner.queue.claim_worker_result.return_value = ("claimed", first)
    runner.accept_worker_delivery(delivery_context(1), SimpleNamespace(status="success", result=success_result([item])), "a" * 64)
    runner.queue.complete.assert_not_called()  # updating the package invalidated this claim
    assert repo.set_default_brand.call_args.kwargs["expected_precheck_claim"] == first
    second = {"product_id": "12345678", "revision": 2, "attempts": 1}
    runner.queue.claim_worker_result.return_value = ("claimed", second)
    runner.accept_worker_delivery(delivery_context(2), SimpleNamespace(status="success", result=success_result([item])), "b" * 64)
    assert runner.queue.complete.call_args.args[0]["revision"] == 2
    assert runner.queue.complete.call_args.args[1]["status"] == "ready"


def test_stale_claim_does_not_publish_worker_schema_or_result(settings):
    item = {"id": "1687", "label": "品牌", "required": True,
            "additions": {"ui_type": "select", "diy_type": 0},
            "options": [{"value_id": "596120136", "value_name": "无品牌"}]}
    runner = make_runner(settings, lambda request: pytest.fail("unexpected request"), detail(edited=False))
    runner.service.repository.set_default_brand.return_value = "stale"
    claim = {"product_id": "12345678", "revision": 1, "attempts": 1}
    runner.queue.claim_worker_result.return_value = ("claimed", claim)
    with pytest.raises(RuntimeError, match="precheck changed"):
        runner.accept_worker_delivery(delivery_context(1), SimpleNamespace(status="success", result=success_result([item])), "a" * 64)
    runner.queue.complete.assert_not_called()
    runner.queue.defer_worker.assert_not_called()
    runner.queue.retry.assert_called_once_with(claim)
