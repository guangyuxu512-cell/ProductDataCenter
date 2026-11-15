from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from app.core.config import get_settings
from app.core.database.session import get_database_engine
from app.core.security.access import require_api_access, require_group_writes, require_permission
from app.core.security.scoped_tokens import Principal
from app.modules.products.schemas import ProductIds
from .queue import PrecheckQueue
from .group_rules import GroupRules, GroupRuleStore, RulesConflict, RulesUnavailable

router = APIRouter(prefix="/api/v1/prechecks", tags=["product-prechecks"],
                   dependencies=[Depends(require_api_access)])


def _queue() -> PrecheckQueue:
    if not get_settings().auto_precheck_enabled:
        raise HTTPException(503, "自动预检尚未启用")
    return PrecheckQueue(get_database_engine())


def _rules_authority(principal: Principal) -> None:
    if principal.groups is not None:
        raise HTTPException(403, "限定分组的 Token 不能管理自动分组规则")
    if not all(principal.has(permission) for permission in ("group.read", "group.assign", "precheck.run", "precheck.group_rules")):
        raise HTTPException(403, "当前 Token 没有管理自动分组规则的权限")


def _rule_store() -> GroupRuleStore:
    return GroupRuleStore(get_settings().configured_precheck_group_rules())


@router.get("/group-rules", response_model=GroupRules)
def get_group_rules(principal: Annotated[Principal, Depends(require_api_access)]):
    _rules_authority(principal)
    try:
        return _rule_store().read()
    except RulesUnavailable:
        raise HTTPException(503, "自动分组规则存储不可用") from None


@router.put("/group-rules", response_model=GroupRules, dependencies=[Depends(require_group_writes)])
def set_group_rules(body: GroupRules, principal: Annotated[Principal, Depends(require_api_access)]):
    _rules_authority(principal)
    ids = {value for rule in body.rules for value in (rule.source, rule.passed, rule.incomplete)
           if value not in {"all", "ungrouped", "keep"}}
    try:
        if ids:
            with get_database_engine().connect() as conn:
                found = set(conn.execute(text("SELECT group_id::text FROM product_groups "
                                              "WHERE group_id::text=ANY(CAST(:ids AS text[]))"),
                                         {"ids": list(ids)}).scalars())
            if found != ids:
                raise HTTPException(400, "选择的分组不存在，请刷新后重新选择")
        return _rule_store().save(body)
    except RulesConflict:
        raise HTTPException(409, "规则已被其他操作修改，请刷新后重试") from None
    except RulesUnavailable:
        raise HTTPException(503, "自动分组规则存储不可用") from None


@router.post("/query", dependencies=[Depends(require_permission("precheck.read"))])
def query_results(body: ProductIds, principal: Annotated[Principal, Depends(require_api_access)]):
    try:
        queue = _queue()
        return {"items": queue.results(body.productIds) if principal.groups is None else queue.results(body.productIds, allowed_groups=principal.groups)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "自动预检状态暂不可用") from None


@router.post("/run", dependencies=[Depends(require_permission("precheck.run"))])
def run_prechecks(body: ProductIds, principal: Annotated[Principal, Depends(require_api_access)]):
    """Put manual single/batch requests onto the automatic check queue."""
    try:
        queue = _queue()
        items = queue.enqueue(body.productIds) if principal.groups is None else queue.enqueue(body.productIds, allowed_groups=principal.groups)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "预检请求暂不可用，商品数据未受影响") from None
    queued = {item["productId"] for item in items}
    return {"items": items, "missing": [item for item in body.productIds if item not in queued]}
