from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

bearer = HTTPBearer(auto_error=False)


def require_api_access(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = get_settings().configured_token()
    if not expected:
        raise HTTPException(503, "商品服务访问凭据未配置")
    if not credentials or not compare_digest(credentials.credentials.encode(), expected.encode()):
        raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"})


def require_group_writes() -> None:
    if not get_settings().enable_group_writes:
        raise HTTPException(403, "当前商品服务未启用分组写入")
