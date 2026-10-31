# 商品云库直连中控店铺 Session（候选）

商品库后端以独立软件身份调用中控，不依赖 Worker、设备配对或店铺选择。先读取软件获授权的
店铺列表，自动识别中控存档为 `captured` / `valid` 的抖店作为后续预检候选；这些状态不代表
平台实时登录成功。预检执行、商品分配和平台类目接口不属于本次实现。

中控契约对应 AIdashboard `application-shop-session-v1.md`：通过 HTTPS 访问
`GET /internal/applications/v1/shops` 和单店 `GET .../shops/{shop_id}/session`，携带
`X-Application-ID` 及该软件独有的 Bearer Token。只在后端内存使用 Session，校验返回的店铺 ID、
平台、版本、Cookie 和 `Cache-Control: no-store`；不会把 Cookie 或 Token 返回页面/RPA、写入
商品库、URL、日志或 Git。TLS 校验不能关闭，拒绝重定向，响应大小和超时时间有界。

商品库的 `GET /api/v1/central/status` 走既有商品库访问鉴权，不允许用 RPA 凭据访问，仅返回
`state`（`not_configured` / `connected` / `unavailable`）、授权店铺数量、候选抖店数量和可选
固定错误原因；未连接时数量为 null。`connected` 仅表示中控店铺列表读取成功，不表示 Session
有效、签名器已连接或平台预检成功。不会向页面暴露单店 Session API。

## 部署前置

1. 中控 Session API 候选必须先完成独立安全/集成审查、Two-Gate 与正式发布，并核验生产 HTTPS、
   反向代理、软件 Token、管理员和明确的店铺授权范围。中控的草稿 PR 与 CI 不等于已上线。
2. 在 NAS 保存独立应用 Token 到受保护的文件，确保商品 API 的非 root 用户只读；Token 不复用
   商品 API 或 RPA 的访问凭据。`deploy/compose.central.yaml` 是可选覆盖配置，必须与当前实际
   商品库 Compose 合并检查，确认已有数据库、RPA、网络和卷不变后再发布。应用配置有问题只使
   此连接不可用，不能阻止原商品与 RPA 接口启动。
3. 分离的签名器目前在 NAS 的隔离网络；需要在预检集成时按授权连接商品 API 并安全共享签名
   密钥。此配置不声称签名器或平台请求已经联通。
4. 先在隔离环境使用合成 Session 验证读取与拒绝，之后经允许进行真实店铺的小范围联调，禁止
   输出 Cookie、Token 或原始返回。记录可撤销授权和回滚方式。不会触发真实平台预检或写数据库。

## 本次范围

只新增默认关闭的直接客户端、连接状态及契约测试；不修改商品查询、商品编辑、RPA、手机采集、
生产数据库或 UI。合成测试和 CI 通过不等于真实中控 / NAS / 平台端到端成功。
