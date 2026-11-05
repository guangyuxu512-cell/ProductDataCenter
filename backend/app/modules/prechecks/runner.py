"""Run automatic prechecks in the product service; no separate worker to install."""
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

from fastapi import Response

from app.modules.category_lookup.api import AutoSchemaBody, schema_auto
from app.modules.category_lookup.client import DouyinCategoryClient
from app.modules.central.client import CentralApplicationClient
from app.modules.products.repository import ProductRepository
from app.modules.products.brand_defaults import no_brand_selection
from app.modules.products.service import ProductService
from .queue import PrecheckQueue
from .service import check_product

log = logging.getLogger(__name__)


class PrecheckRunner:
    def __init__(self, engine, settings):
        self.queue = PrecheckQueue(engine)
        self.service = ProductService(ProductRepository(engine), settings)
        self.central = CentralApplicationClient(settings)
        self.lookup = DouyinCategoryClient(settings)
        self.stop_event = Event()
        self.thread = Thread(target=self.run, daemon=True, name="product-precheck")

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def process(self, claim):
        try:
            detail = self.service.repository.detail(claim["product_id"])
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
                self.queue.retry(claim)
            except Exception:
                log.warning("无法保存自动预检状态；稍后将重新领取")

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
