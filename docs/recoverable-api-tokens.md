# 商品库 Token 的重复查看

原有随机 Token 和权限规则保持不变。统一管理页面可在创建时传 `recoverable: true`；此时 Token 由随机 ID 和独立保护密钥派生，凭据库仍只存摘要。管理者还必须具有单独的 `token.reveal` 权限；非主管理者只能查看自己签发的直接子 Token。

部署时设置独立随机的 `BACKEND_TOKEN_RECOVERY_KEY` 或 `BACKEND_TOKEN_RECOVERY_KEY_FILE`，二者只选一项。密钥要通过保护配置保存并备份，不能提交、打印或交给浏览器。升级和重启时保持密钥：丢失或更换密钥不会使 Token 失效，但旧密钥派生的 Token 将不能再查看。未配置密钥时，可恢复创建/查看返回 503，既有 Token 签发和使用不变。

`POST /api/v1/tokens/{id}/reveal` 不缓存响应，记录查看事件但不记录令牌。旧 Token 若只保存了摘要，不能从摘要恢复，查看返回 409；不会自动轮换或改变原令牌。
