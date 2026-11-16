"""Run automatic prechecks in the product service; no separate worker to install."""
import logging
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from fastapi import Response

from app.modules.category_lookup.api import AutoSchemaBody, PredictResponse, _usable_image_url, prediction_input, schema_auto
from app.modules.category_lookup.client import DouyinCategoryClient, LookupError, normalize_predictions
from app.modules.central.client import CentralApplicationClient, CentralConnectionError
from app.modules.products.repository import ProductRepository
from app.modules.products.brand_defaults import no_brand_selection
from app.modules.products.service import ProductService
from .queue import PrecheckQueue, SESSION_READ_INCOMPLETE_MESSAGE
from .group_rules import GroupRuleStore
from .service import _main_image, check_product
from .worker_schema import WorkerSchemaResultError, read_worker_schema

log = logging.getLogger(__name__)


def _worker_request(product_id: str, detail: dict, repository):
    row = detail["product"]
    platform = row["source_platform"]
    title = (row.get("title") or "").strip()
    prediction = not detail["targetCategory"] and (
        platform == "pinduoduo" or (platform == "douyin" and product_id.startswith("manual:")))
    if prediction and not detail.get("sourceCategoryId"):
        if platform == "pinduoduo":
            rows = repository.export_rows([product_id])
            if not rows:
                return None
            title, image_url, _ = prediction_input(rows[0])
        else:
            image_url = _usable_image_url(_main_image(detail))
        return ("predict", "0", title, image_url) if title and image_url else None
    category = (detail.get("sourceCategoryId") if platform == "douyin" else
                detail["targetCategory"][-1]["id"] if platform == "pinduoduo" and detail["targetCategory"] else None)
    if category:
        return "schema", str(category), title or "商品", None
    return None


class PrecheckRunner:
    def __init__(self, engine, settings):
        rules_path = settings.configured_precheck_group_rules() if settings.enable_group_writes else None
        self.queue = PrecheckQueue(engine, GroupRuleStore(rules_path) if rules_path else None)
        self.service = ProductService(ProductRepository(engine), settings)
        self.central = CentralApplicationClient(settings)
        self.lookup = DouyinCategoryClient(settings)
        self.worker_precheck_enabled = settings.worker_precheck_enabled
        self.stop_event = Event()
        self.thread = Thread(target=self.run, daemon=True, name="product-precheck")

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def process(self, claim):
        worker_mode = False
        try:
            detail = self.service.repository.detail(claim["product_id"])
            request = (_worker_request(claim["product_id"], detail, self.service.repository)
                       if getattr(self, "worker_precheck_enabled", False) and detail else None)
            if request:
                worker_mode = True
                self._process_worker(claim, *request)
                return
            if detail and detail["product"]["source_platform"] == "douyin" and not claim["product_id"].startswith("manual:"):
                category_id = detail.get("sourceCategoryId")
                status = str(detail["product"].get("title_status") or "")
                if category_id and not status.endswith("商品库已修改"):
                    schema = schema_auto(AutoSchemaBody(categoryId=category_id,
                                                        title=detail["product"].get("title") or "商品"),
                                         Response(), self.central, self.lookup)
                    selection = no_brand_selection(schema.attributes)
                    if selection and self.service.repository.set_default_brand(
                            claim["product_id"], selection, force=False, mark_modified=False) == "updated":
                        # Updating uu_json advances the durable queue revision.
                        # Do not complete this now-stale claim; the next claim
                        # checks the just-saved no-brand value.
                        return
            result = check_product(claim["product_id"], self.service, self.central, self.lookup)
            self.queue.complete(claim, result)
        except Exception:
            try:
                if worker_mode:
                    self.queue.complete(claim, _worker_failure(claim, "商品预检处理未完成"))
                else:
                    self.queue.retry(claim)
            except Exception:
                log.warning("无法保存自动预检状态；稍后将重新领取")

    def _process_worker(self, claim, operation, category_id, title, image_url):
        """Submit once; the assigned Worker returns the result to this service."""
        if operation == "schema":
            schema_body = AutoSchemaBody(categoryId=category_id, title=title)
            category_id, title = schema_body.categoryId, schema_body.title
        try:
            self.central.submit_worker_precheck(claim, category_id, title, delivery="product",
                                                operation=operation, image_url=image_url)
        except CentralConnectionError as error:
            if error.reason == "upstream_unavailable":
                # An unavailable device or service is not an active check.
                # Back off instead of redispatching every five seconds.
                self.queue.defer_worker(claim, unavailable=True)
            else:
                message = {"authentication_failed": "预检服务未授权",
                           "idempotency_conflict": "预检任务内容不一致，请重新预检",
                           "invalid_configuration": "预检服务配置不可用",
                           "not_configured": "预检服务尚未启用",
                           "invalid_response": "预检服务返回无效结果"}.get(error.reason, "预检服务连接不可用")
                self.queue.complete(claim, _worker_failure(claim, message))
            return
        self.queue.wait_for_worker(claim)

    def accept_worker_delivery(self, context, terminal, digest: str) -> bool:
        """Apply one authenticated Worker result to its matching product revision."""
        result = terminal.result
        expected = {"kind": "douyin.category_schema", "category_id": context.category_id,
                    "device_id": str(context.device_id), "local_shop_id": context.local_shop_id,
                    "platform_shop_id": context.platform_shop_id}
        if getattr(context, "operation", "schema") != "schema":
            expected["operation"] = context.operation
        if result is not None and (not isinstance(result, dict) or any(result.get(k) != v for k, v in expected.items())):
            raise ValueError("worker identity mismatch")
        if terminal.status == "success" and result is None:
            raise ValueError("worker result missing")
        receipt = {"task_id": str(context.task_id), "sha256": digest}
        state, claim = self.queue.claim_worker_result(context.product_id, context.revision, receipt)
        if state == "stale":
            return False
        if state == "duplicate":
            return True
        if state != "claimed" or claim is None:
            raise ValueError("worker result conflicts")
        try:
            explicit_expiry = (getattr(context, "session_retry_supported", False) and terminal.status == "failed"
                and terminal.error_code == "SHOP_SESSION_EXPIRED" and isinstance(result, dict)
                and result.get("error_stage") == "session"
                and result.get("safe_error_code") == "SHOP_SESSION_EXPIRED")
            if explicit_expiry:
                if not self.queue.defer_worker(claim):
                    raise RuntimeError("precheck changed while waiting for another shop")
            else:
                self._complete_worker_delivery(context, terminal, claim, receipt)
        except Exception:
            self.queue.retry(claim)
            raise
        return True

    def _complete_worker_delivery(self, context, terminal, claim: dict, receipt: dict) -> None:
        def finish(value):
            value["_worker_receipt"] = receipt
            if not self.queue.complete(claim, value):
                raise RuntimeError("precheck changed while saving")

        detail = self.service.repository.detail(claim["product_id"])
        current = _worker_request(claim["product_id"], detail, self.service.repository) if detail else None
        operation = getattr(context, "operation", "schema")
        if not current or current[0] != operation or current[1] != context.category_id:
            finish(_worker_failure(claim, "商品类目已变化，请重新预检"))
            return
        if terminal.status == "failed":
            finish(_worker_failure(claim, _worker_failure_message(SimpleNamespace(result=terminal.result))))
            return
        if operation == "predict":
            try:
                raw = terminal.result
                if (set(raw) != {"kind", "category_id", "device_id", "local_shop_id", "platform_shop_id",
                                "http_status", "platform_code", "operation", "data"}
                        or type(raw["http_status"]) is not int or raw["http_status"] != 200
                        or not ((type(raw["platform_code"]) is int and raw["platform_code"] == 0)
                                or (type(raw["platform_code"]) is str and raw["platform_code"] == "0"))):
                    raise ValueError()
                data = normalize_predictions(raw["data"])
                if detail["product"]["source_platform"] == "pinduoduo":
                    rows = self.service.repository.export_rows([claim["product_id"]])
                    _, _, version = prediction_input(rows[0])
                else:
                    version = hashlib.sha256(json.dumps([current[2], current[3]], ensure_ascii=False).encode("utf-8")).hexdigest()
                status = ("recommended" if data["recommendedId"] else
                          "needs_category_confirmation" if data["candidates"] else "no_recommendation")
                prediction = PredictResponse(status=status, sourceVersion=version, missing=[],
                    shopId=uuid5(NAMESPACE_URL, "ecommerce-worker:douyin:" + context.platform_shop_id), **data)
                result = check_product(claim["product_id"], self.service, self.central, self.lookup,
                                       prediction_override=prediction)
            except (LookupError, ValueError, TypeError, KeyError, IndexError):
                finish(_worker_failure(claim, "平台类目推荐结果无效"))
                return
            finish(result)
            return
        try:
            schema = read_worker_schema(terminal.result, expected_category_id=context.category_id)
        except WorkerSchemaResultError:
            finish(_worker_failure(claim, "平台预检结果无效或超过允许大小"))
            return
        if (detail["product"]["source_platform"] == "douyin"
                and not claim["product_id"].startswith("manual:")):
            status = str(detail["product"].get("title_status") or "")
            if not status.endswith("商品库已修改"):
                selection = no_brand_selection(schema.attributes)
                if selection:
                    outcome = self.service.repository.set_default_brand(
                        claim["product_id"], selection, force=False, mark_modified=False,
                        expected_precheck_claim=claim)
                    if outcome == "updated":
                        # The saved package advanced revision and queued a fresh check.
                        return
                    if outcome == "stale":
                        # A concurrent claimant may still be processing this revision.
                        # Re-deliver so it is never acknowledged before persistence.
                        raise RuntimeError("precheck changed while saving")
        result = check_product(claim["product_id"], self.service, self.central, self.lookup,
                               schema_override=schema)
        finish(result)

    def run(self):
        with ThreadPoolExecutor(max_workers=15, thread_name_prefix="product-check") as pool:
            active = set()
            while not self.stop_event.wait(2):
                active = {future for future in active if not future.done()}
                slots = 15 - len(active)
                if not slots:
                    continue
                try:
                    claims = self.queue.claim(slots)
                except Exception:
                    log.warning("无法读取自动预检队列，将稍后重试")
                    self.stop_event.wait(30)
                    continue
                active.update(pool.submit(self.process, claim) for claim in claims)


def _worker_failure(claim, message: str) -> dict:
    return {"productId": claim["product_id"], "status": "failed", "issues": [message], "issueDetails": []}


def _worker_failure_message(state) -> str:
    result = state.result if isinstance(state.result, dict) else {}
    stage = result.get("error_stage")
    message = {"session": SESSION_READ_INCOMPLETE_MESSAGE, "signer": "签名未完成",
               "platform": "平台预检失败", "result": "平台预检结果不可用"}.get(stage, "设备预检未完成")
    code = result.get("platform_code")
    if ((type(code) is int and 0 <= code <= 10**20)
            or (isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code))):
        message += f"（代码 {code}）"
    return message
