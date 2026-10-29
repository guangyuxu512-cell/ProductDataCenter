from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    code = "INTERNAL_ERROR"
    message = "服务器内部错误"
    status_code = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details
