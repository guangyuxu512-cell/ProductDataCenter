import json
import logging
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_STATE_KEY = "request_id"
_REQUEST_USER_ID_STATE_KEY = "request_log_user_id"
_REQUEST_TEAM_ID_STATE_KEY = "request_log_team_id"
_REQUEST_ERROR_CODE_STATE_KEY = "request_log_error_code"

request_logger = logging.getLogger("app.request")
request_logger.setLevel(logging.INFO)
request_logger.propagate = False
if not request_logger.handlers:
    request_handler = logging.StreamHandler()
    request_handler.setFormatter(logging.Formatter("%(message)s"))
    request_logger.addHandler(request_handler)


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, _REQUEST_ID_STATE_KEY, None)
    if isinstance(request_id, str):
        return request_id

    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
    setattr(request.state, _REQUEST_ID_STATE_KEY, request_id)
    return request_id


def set_request_user_id(request: Request, user_id: UUID) -> None:
    setattr(request.state, _REQUEST_USER_ID_STATE_KEY, str(user_id))


def set_request_team_id(request: Request, team_id: UUID) -> None:
    setattr(request.state, _REQUEST_TEAM_ID_STATE_KEY, str(team_id))


def set_request_error_code(request: Request, error_code: str) -> None:
    setattr(request.state, _REQUEST_ERROR_CODE_STATE_KEY, error_code)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = get_request_id(request)
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            set_request_error_code(request, "INTERNAL_ERROR")
            self._log_request(
                request,
                request_id=request_id,
                status_code=500,
                latency_ms=self._latency_ms(started_at),
            )
            raise

        response.headers[REQUEST_ID_HEADER] = request_id
        self._log_request(
            request,
            request_id=request_id,
            status_code=response.status_code,
            latency_ms=self._latency_ms(started_at),
        )
        return response

    @staticmethod
    def _latency_ms(started_at: float) -> int:
        return round((perf_counter() - started_at) * 1000)

    @staticmethod
    def _log_request(
        request: Request,
        *,
        request_id: str,
        status_code: int,
        latency_ms: int,
    ) -> None:
        fields: dict[str, Any] = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "latency": latency_ms,
        }
        route = request.scope.get("route")
        tags = getattr(route, "tags", None)
        if tags:
            fields["module"] = tags[0]
        for field, state_key in (
            ("user_id", _REQUEST_USER_ID_STATE_KEY),
            ("team_id", _REQUEST_TEAM_ID_STATE_KEY),
            ("error_code", _REQUEST_ERROR_CODE_STATE_KEY),
        ):
            value = getattr(request.state, state_key, None)
            if isinstance(value, str):
                fields[field] = value
        request_logger.info(json.dumps(fields, ensure_ascii=False, separators=(",", ":")))
