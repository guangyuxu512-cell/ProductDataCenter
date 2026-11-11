from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security.access import require_api_access, require_permission
from app.core.security.scoped_tokens import (PERMISSIONS, Principal, TokenDenied, TokenInputError,
                                             TokenInvalid, TokenNotFound, TokenStore, TokenStoreUnavailable)

router = APIRouter(prefix="/api/v1/tokens", tags=["access-tokens"], dependencies=[Depends(require_api_access)])


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(min_length=1, max_length=50)
    groupIds: list[str] | None = Field(default=None, max_length=200)
    expiresAt: int | None = None


class TokenUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    permissions: list[str] | None = Field(default=None, max_length=50)
    groupIds: list[str] | None = Field(default=None, max_length=200)
    expiresAt: int | None = None


def _store():
    return TokenStore(get_settings().configured_scoped_token_store())


def _call(operation, *args):
    try:
        return operation(*args)
    except TokenInputError as error:
        raise HTTPException(422, str(error)) from None
    except TokenDenied as error:
        raise HTTPException(403, str(error)) from None
    except TokenNotFound:
        raise HTTPException(404, "Token 不存在") from None
    except TokenInvalid:
        raise HTTPException(401, "访问未授权", headers={"WWW-Authenticate": "Bearer"}) from None
    except TokenStoreUnavailable:
        raise HTTPException(503, "Token 权限服务暂不可用") from None


@router.get("/permissions")
def permissions(response: Response, principal: Annotated[Principal, Depends(require_api_access)]):
    response.headers["Cache-Control"] = "no-store"
    return {"items": [{"id": key, "description": description, "canGrant": principal.has(key)}
                      for key, description in PERMISSIONS.items()],
            "groupIds": sorted(principal.groups) if principal.groups is not None else None,
            "expiresAt": principal.expires_at}


@router.get("")
def list_tokens(response: Response, principal: Annotated[Principal, Depends(require_permission("token.read"))]):
    response.headers["Cache-Control"] = "no-store"
    return {"items": _call(_store().list, principal)}


@router.post("", status_code=201)
def create_token(body: TokenCreate, response: Response,
                 principal: Annotated[Principal, Depends(require_permission("token.create"))]):
    response.headers["Cache-Control"] = "no-store"
    record, secret = _call(_store().create, principal, body.name, body.permissions, body.groupIds, body.expiresAt)
    return {"token": secret, "record": record}


@router.patch("/{token_id}")
def update_token(token_id: str, body: TokenUpdate, response: Response,
                 principal: Annotated[Principal, Depends(require_permission("token.update"))]):
    response.headers["Cache-Control"] = "no-store"
    return {"record": _call(_store().update, principal, token_id, body.model_dump(exclude_unset=True))}


@router.delete("/{token_id}", status_code=204)
def revoke_token(token_id: str, principal: Annotated[Principal, Depends(require_permission("token.revoke"))]):
    _call(_store().revoke, principal, token_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
