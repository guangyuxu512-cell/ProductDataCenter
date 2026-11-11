# 商品库 Token 管理（不依赖前端）

商品库 API 可为 AI 或 RPA 分别签发 Token。管理接口使用原有 HTTPS 地址和 `Authorization: Bearer <Token>`；商品、分组、图片、预检和 RPA 的原有接口路径不变。旧管理 Token 和旧 RPA Token 保持兼容。旧管理 Token 仍拥有已开启功能的管理权限，应只保存在可信的安全凭据位置。

## 怎样由本人创建

在有服务器管理员权限的电脑终端中执行以下命令。`control-center-dev` 是此工作环境已有的 SSH 别名；如果在其他电脑操作，请使用服务器管理员提供的 SSH 连接方式。

```powershell
# 列出可分配的权限
ssh control-center-dev "docker exec pdc-server-production-product-api-1 python -m app.modules.access_tokens.cli permissions"

# 为 Muse 创建全权限商品库 Token，90 天到期
ssh control-center-dev "docker exec pdc-server-production-product-api-1 python -m app.modules.access_tokens.cli create --name Muse --permissions '*' --expires-days 90"

# 列出已签发 Token（不会显示完整 Token）
ssh control-center-dev "docker exec pdc-server-production-product-api-1 python -m app.modules.access_tokens.cli list"

# 修改权限、撤销：将 TOKEN_ID 换成 list 返回的 id
ssh control-center-dev "docker exec pdc-server-production-product-api-1 python -m app.modules.access_tokens.cli update TOKEN_ID --permissions product.read,group.read"
ssh control-center-dev "docker exec pdc-server-production-product-api-1 python -m app.modules.access_tokens.cli revoke TOKEN_ID"
```

`create` 只在终端输出一次完整 Token。直接复制到目标 AI 的安全凭据框；不要放进聊天、命令参数、日志、仓库或截图。`list`、`update` 和 `revoke` 只使用公开的 Token ID。可用 `--group 分组UUID` 指定允许的分组，多次指定代表多个分组；`--group ungrouped` 包含未分组商品。未指定 `--group` 为全部分组。`update --all-groups` 取消分组限制，`update --no-expiry` 取消到期时间。

例如，只允许查看商品与分组：

```powershell
ssh control-center-dev "docker exec pdc-server-production-product-api-1 python -m app.modules.access_tokens.cli create --name Reader --permissions product.read,group.read --expires-days 30"
```

## 让 AI 管理 Token

具有相应权限的 AI 可以直接调用以下接口：

| 接口 | 所需权限 | 用途 |
| --- | --- | --- |
| `GET /api/v1/tokens/permissions` | 任意有效管理 API Token | 查询权限目录及当前可分配范围 |
| `GET /api/v1/tokens` | `token.read` | 列出自己直接发放的 Token；旧管理 Token 可查看全部 |
| `POST /api/v1/tokens` | `token.create` | 创建 Token，响应中的完整 Token 只出现一次 |
| `PATCH /api/v1/tokens/{id}` | `token.update` | 修改自己直接发放的 Token |
| `DELETE /api/v1/tokens/{id}` | `token.revoke` | 撤销自己直接发放的 Token |

创建请求示例（`expiresAt` 是 UTC Unix 秒；省略或为 null 表示无到期时间）：

```json
{"name":"Reader","permissions":["product.read","group.read"],"groupIds":null,"expiresAt":null}
```

AI 不能分配超过自身的权限或分组范围，也不能发放比自身有效期更长的 Token。上级 Token 被撤销、过期或缩减权限后，下级 Token 的有效权限随之收紧；发放者只能修改或撤销自己直接发放的 Token。完整 Token 在响应中只返回一次，响应标记 `no-store`，并且不应通过会留下明文的聊天、日志或普通工具输出转交。是否能直接写入目标 AI 的安全凭据框取决于该工具的能力。

## 权限与边界

- `product.read/create/update/delete/export`：分别控制读取、新建、编辑、删除和导出商品；编辑快照需要 `product.update`。
- `group.read/create/update/delete/assign`：分别控制查看、创建、重命名、删除分组以及移动商品。限定分组的 Token 不能创建新分组；可在允许的分组中新建商品时传 `groupId`。
- `image.upload`、`precheck.read`、`precheck.run`、`category.read`、`central.read`：分别控制图片上传、预检结果、发起预检、类目查询及中控连接状态。
- `rpa.read`：访问现有 RPA 只读接口；旧 RPA Token 仍然只适用于 RPA。图片公网 URL 本身仍可不带 Token 读取，分组权限不改变已公开的图片 URL。
- `token.read/create/update/revoke`：分别控制查看、发放、修改、撤销下级 Token。`*` 在创建或修改时展开为当前全部权限，不会自动获得未来新增的权限。

拥有权限还须满足原有服务端功能开关，例如商品写入关闭时，`product.update` 也不能绕过开关。`GET /api/v1/capabilities` 返回当前 Token 的权限和分组范围。用户手动填写的 Token 不应写入任何公开日志或 URL。

Token 摘要、权限和撤销记录存放在独立 SQLite 文件中，不创建或修改采集方拥有的 PostgreSQL 商品表。生产默认使用现有持久目录 `/category-cache/scoped-api-tokens.sqlite3`，也可使用 `BACKEND_SCOPED_TOKEN_STORE_FILE` 指定其他持久路径。文件及备份须限制权限并纳入独立备份；从旧备份恢复可能使已撤销凭证重新生效，恢复后应先全部撤销并重新签发。类目缓存刷新不得删除该凭证文件。

## 2026-11-12 服务器发布记录

- 正式 API 和 Web 均运行 `35c96b75c1ed0983ed87f7243e4f773d9dff1f36` 镜像；该合并提交与通过检查的功能分支文件树一致。服务器商品数据库、现有 RPA 凭据和 NAS 图片存储保持原有配置。
- 发布前重新备份并校验服务器数据库，将此前新备份恢复到不联网的独立 PostgreSQL，验证分组隔离、委派边界、撤销和旧 RPA 读取；独立空 PostgreSQL 的集成测试通过。主分支 GitHub 后端、前端、容器和 Windows 检查通过。
- 发布后通过公网入口实际创建临时 Token、读取商品和预检、更改权限、验证拒绝越权、撤销并验证失效；另以真实分组只读验证商品和 RPA 的跨分组拒绝。临时 Token 已撤销。旧管理凭据、旧 RPA 分组读取以及已有公网图片读取正常。
- 使用仅有 `image.upload` 权限的临时 Token 实际上传一张 68 字节测试 PNG；返回的 HTTPS 地址无凭据读取为 HTTP 200、`image/png`，内容与上传一致。测试图片保存在既有 NAS 存储，未关联或修改任何商品；临时 Token 已撤销。
- Token 注册表每小时由 `pdc-scoped-token-backup-20261112.timer` 备份到服务器 `/root/pdc-server-backups/token-registry`；首次备份与 SQLite 完整性检查通过。数据库备份与 Token 注册表备份相互独立。
- 服务器本机运行仓库容器检查时，局域网来源限制的一项断言得到 200 而非预期 403；该完整脚本在 GitHub CI 通过。随后使用独立 Docker 网络分别验证非信任来源拒绝、可信来源访问、Basic 网页与 Token 管理代理隔离，并复测本机发布端口的非信任访问返回 403。生产 Web 使用 Basic 模式；以上补充测试不把该次脚本失败记作通过。
