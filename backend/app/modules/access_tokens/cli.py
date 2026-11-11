"""Run inside the backend container as an administrator; secrets print once."""
import argparse
import json
import sys
import time

from app.core.config import get_settings
from app.core.security.scoped_tokens import MASTER, PERMISSIONS, TokenStore


def main():
    parser = argparse.ArgumentParser(description="商品库 Token 管理")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("permissions", help="列出可分配权限")
    sub.add_parser("list", help="列出 Token 元数据，不显示密钥")
    create = sub.add_parser("create", help="创建 Token；完整 Token 仅显示本次")
    create.add_argument("--name", required=True)
    create.add_argument("--permissions", required=True, help="逗号分隔的权限，或 *")
    create.add_argument("--group", action="append", dest="groups", help="允许的分组 UUID 或 ungrouped，可重复")
    create.add_argument("--expires-days", type=int, help="多少天后到期；不填写表示长期")
    update = sub.add_parser("update", help="设置指定 Token 的权限等信息")
    update.add_argument("id")
    update.add_argument("--name")
    update.add_argument("--permissions")
    update.add_argument("--group", action="append", dest="groups")
    update.add_argument("--all-groups", action="store_true")
    update.add_argument("--expires-days", type=int)
    update.add_argument("--no-expiry", action="store_true")
    revoke = sub.add_parser("revoke", help="撤销 Token")
    revoke.add_argument("id")
    args = parser.parse_args()
    store = TokenStore(get_settings().configured_scoped_token_store())
    if args.command == "permissions":
        result = {"items": [{"id": k, "description": v} for k, v in PERMISSIONS.items()]}
    elif args.command == "list":
        result = {"items": store.list(MASTER)}
    elif args.command == "create":
        if args.expires_days is not None and args.expires_days <= 0:
            parser.error("--expires-days 必须大于 0")
        expiry = int(time.time()) + args.expires_days * 86400 if args.expires_days is not None else None
        record, token = store.create(MASTER, args.name, args.permissions.split(","), args.groups, expiry)
        result = {"token": token, "record": record}
    elif args.command == "update":
        if args.groups and args.all_groups or args.expires_days is not None and args.no_expiry:
            parser.error("不能同时指定相互冲突的选项")
        if args.expires_days is not None and args.expires_days <= 0:
            parser.error("--expires-days 必须大于 0")
        changes = {}
        if args.name is not None: changes["name"] = args.name
        if args.permissions is not None: changes["permissions"] = args.permissions.split(",")
        if args.groups is not None: changes["groupIds"] = args.groups
        if args.all_groups: changes["groupIds"] = None
        if args.expires_days is not None: changes["expiresAt"] = int(time.time()) + args.expires_days * 86400
        if args.no_expiry: changes["expiresAt"] = None
        result = {"record": store.update(MASTER, args.id, changes)}
    else:
        store.revoke(MASTER, args.id)
        result = {"revoked": args.id}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Token 操作失败：" + str(error), file=sys.stderr)
        raise SystemExit(1) from None
