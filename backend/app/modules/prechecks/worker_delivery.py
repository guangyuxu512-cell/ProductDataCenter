"""Receive a precheck result directly from its assigned Worker."""
from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.core.security.access import bearer
from app.modules.central.client import CentralApplicationClient, CentralConnectionError
from .runner import PrecheckRunner


router = APIRouter(prefix="/api/v1/worker-precheck-results", tags=["worker-precheck-results"])
MAX_BODY = 4 * 1024 * 1024 + 16 * 1024


class WorkerDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["success", "failed"]
    result: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_terminal(self) -> WorkerDelivery:
        if (self.status == "success" and (self.error_code is not None or self.error_message is not None)):
            raise ValueError("invalid success")
        if self.status == "failed" and not self.error_code:
            raise ValueError("missing error")
        return self


def _accept(task_id: UUID, device_id: UUID, token: str, body: bytes) -> dict:
    settings = get_settings()
    if not settings.auto_precheck_enabled or not settings.worker_precheck_enabled:
        raise HTTPException(503, "Worker 预检未启用")
    try:
        terminal = WorkerDelivery.model_validate_json(body)
    except (ValueError, ValidationError):
        raise HTTPException(422, "预检结果无效") from None
    central = CentralApplicationClient(settings)
    try:
        context = central.worker_delivery_context(task_id, device_id, token)
    except CentralConnectionError as error:
        if error.reason in {"worker_denied", "authentication_failed"}:
            raise HTTPException(403, "预检任务未授权") from None
        raise HTTPException(503, "预检任务验证未完成") from None
    digest = hashlib.sha256(body).hexdigest()
    if getattr(context, "superseded", False):
        # An identical, already-acknowledged expired-session result can be
        # replayed after a replacement task has been assigned, but it must not
        # overwrite the replacement's result.
        if (terminal.status == "failed" and terminal.error_code == "SHOP_SESSION_EXPIRED"
                and context.receipt_sha256 == digest):
            return {"task_id": str(task_id), "accepted": True}
        raise HTTPException(409, "预检结果与任务不一致")
    runner = PrecheckRunner(get_database_engine(), settings)
    try:
        accepted = runner.accept_worker_delivery(context, terminal, digest)
    except ValueError:
        raise HTTPException(409, "预检结果与任务不一致") from None
    except Exception:
        raise HTTPException(503, "预检结果保存未完成") from None
    return {"task_id": str(task_id), "accepted": accepted}


@router.post("/{task_id}")
async def receive_worker_result(task_id: UUID, request: Request, response: Response,
                                credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
                                device: Annotated[str | None, Header(alias="X-Device-ID")] = None):
    if credentials is None or credentials.scheme.lower() != "bearer" or not device:
        raise HTTPException(401, "预检任务未授权")
    try:
        device_id = UUID(device)
    except ValueError:
        raise HTTPException(401, "预检任务未授权") from None
    if not credentials.credentials or len(credentials.credentials) > 256:
        raise HTTPException(401, "预检任务未授权")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise HTTPException(413, "预检结果过大")
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(_accept, task_id, device_id, credentials.credentials, bytes(body))
