from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings
from app.core.security.scoped_tokens import (LEGACY_RPA, MASTER, Principal, TokenInvalid,
                                             TokenStore, TokenStoreUnavailable)

bearer = HTTPBearer(auto_error=False)


def require_api_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    settings = get_settings()
    expected = settings.configured_token()
    if not expected:
        raise HTTPException(503, "商品服务访问凭据未配置")
    if not credentials:
        raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"})
    if compare_digest(credentials.credentials.encode(), expected.encode()):
        principal = MASTER
    elif credentials.credentials.startswith("pdc_"):
        try:
            principal = TokenStore(settings.configured_scoped_token_store()).authenticate(credentials.credentials)
        except TokenInvalid:
            raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"}) from None
        except TokenStoreUnavailable:
            raise HTTPException(503, "Token 权限服务暂不可用") from None
    else:
        raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"})
    request.state.request_log_token_id = principal.token_id or "legacy-admin"
    return principal


def require_permission(permission: str):
    def check(principal: Annotated[Principal, Depends(require_api_access)]) -> Principal:
        if not principal.has(permission):
            raise HTTPException(403, "当前 Token 没有此操作的权限")
        return principal
    return check


def require_group_writes() -> None:
    if not get_settings().enable_group_writes:
        raise HTTPException(403, "当前商品服务未启用分组写入")


def require_product_writes() -> None:
    if not get_settings().enable_product_writes:
        raise HTTPException(403, "当前商品服务未启用商品编辑")


def require_rpa_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    settings = get_settings()
    expected = settings.configured_rpa_token()
    admin = settings.configured_token()
    if not expected or (admin and compare_digest(expected.encode(), admin.encode())):
        raise HTTPException(503, "RPA 只读访问凭据未配置或与管理凭据重复")
    if not credentials:
        raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"})
    if compare_digest(credentials.credentials.encode(), expected.encode()):
        principal = LEGACY_RPA
    elif credentials.credentials.startswith("pdc_"):
        try:
            principal = TokenStore(settings.configured_scoped_token_store()).authenticate(credentials.credentials)
        except TokenInvalid:
            raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"}) from None
        except TokenStoreUnavailable:
            raise HTTPException(503, "Token 权限服务暂不可用") from None
        if not principal.has("rpa.read"):
            raise HTTPException(403, "当前 Token 没有 RPA 读取权限")
    else:
        raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"})
    request.state.request_log_token_id = principal.token_id or "legacy-rpa"
    return principal
