"""Run automatic prechecks in the product service; no separate worker to install."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

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
        """Poll one idempotent task without holding a product queue lease."""
        category_id = str(detail["sourceCategoryId"])
        title = detail["product"].get("title") or "商品"
        # Preserve the same validation as the existing synchronous schema API.
        schema_body = AutoSchemaBody(categoryId=category_id, title=title)
        try:
            ticket = self.central.submit_worker_precheck(claim, schema_body.categoryId, schema_body.title)
            state = self.central.read_worker_precheck(ticket.task_id)
        except CentralConnectionError as error:
            if error.reason == "upstream_unavailable":
                self.queue.defer_worker(claim)
            else:
                message = {"authentication_failed": "预检服务未授权",
                           "idempotency_conflict": "预检任务内容不一致，请重新预检",
                           "invalid_configuration": "预检服务配置不可用",
                           "not_configured": "预检服务尚未启用",
                           "invalid_response": "预检服务返回无效结果"}.get(error.reason, "预检服务连接不可用")
                self.queue.complete(claim, _worker_failure(claim, message))
            return
        if state.status in {"pending", "running"}:
            self.queue.defer_worker(claim, running=state.status == "running")
            return
        if state.status == "lost":
            self.queue.defer_worker(claim, running=True, waiting_result=True)
            return
        if state.status == "failed":
            self.queue.complete(claim, _worker_failure(claim, _worker_failure_message(state)))
            return
        try:
            schema = read_worker_schema(state.result, expected_category_id=category_id)
        except WorkerSchemaResultError:
            self.queue.complete(claim, _worker_failure(claim, "平台预检结果无效或超过允许大小"))
            return
        if not claim["product_id"].startswith("manual:"):
            status = str(detail["product"].get("title_status") or "")
            if not status.endswith("商品库已修改"):
                selection = no_brand_selection(schema.attributes)
                if selection:
                    outcome = self.service.repository.set_default_brand(
                        claim["product_id"], selection, force=False, mark_modified=False,
                        expected_precheck_claim=claim)
                    if outcome in {"updated", "stale"}:
                        # A saved package advanced revision, or a newer claim won.
                        return
        result = check_product(claim["product_id"], self.service, self.central, self.lookup,
                               schema_override=schema)
        self.queue.complete(claim, result)

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
