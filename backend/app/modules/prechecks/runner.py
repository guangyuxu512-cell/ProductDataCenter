"""Run automatic prechecks in the product service; no separate worker to install."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from types import SimpleNamespace

from fastapi import Response

from app.modules.category_lookup.api import AutoSchemaBody, schema_auto
from app.modules.category_lookup.client import DouyinCategoryClient
from app.modules.central.client import CentralApplicationClient, CentralConnectionError
from app.modules.products.repository import ProductRepository
from app.modules.products.brand_defaults import no_brand_selection
from app.modules.products.service import ProductService
from .queue import PrecheckQueue, SESSION_READ_INCOMPLETE_MESSAGE
from .service import check_product
from .worker_schema import WorkerSchemaResultError, read_worker_schema

log = logging.getLogger(__name__)


class PrecheckRunner:
    def __init__(self, engine, settings):
        self.queue = PrecheckQueue(engine)
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
            if (getattr(self, "worker_precheck_enabled", False) and detail
                    and detail["product"]["source_platform"] == "douyin" and detail.get("sourceCategoryId")):
                worker_mode = True
                self._process_worker(claim, detail)
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

    def _process_worker(self, claim, detail):
        """Submit once; the assigned Worker returns the result to this service."""
        category_id = str(detail["sourceCategoryId"])
        title = detail["product"].get("title") or "商品"
        # Preserve the same validation as the existing synchronous schema API.
        schema_body = AutoSchemaBody(categoryId=category_id, title=title)
        try:
            self.central.submit_worker_precheck(claim, schema_body.categoryId, schema_body.title, delivery="product")
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
        if not detail or str(detail.get("sourceCategoryId") or "") != context.category_id:
            finish(_worker_failure(claim, "商品类目已变化，请重新预检"))
            return
        if terminal.status == "failed":
            finish(_worker_failure(claim, _worker_failure_message(SimpleNamespace(result=terminal.result))))
            return
        try:
            schema = read_worker_schema(terminal.result, expected_category_id=context.category_id)
        except WorkerSchemaResultError:
            finish(_worker_failure(claim, "平台预检结果无效或超过允许大小"))
            return
        if not claim["product_id"].startswith("manual:"):
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
