# RPA 商品只读接口 V1

RPA 通过商品云库读取分组和 UU；无商品或分组写入权限。只提供接口，RPA 界面、任务调度、店铺映射和执行结果回写不属于本次变更。

## 鉴权与网络

- `/rpa/v1/` 使用独立 Bearer Token。未配置或与网页管理 Token 相同会返回 503；错误或缺失凭据返回 401。
- 网页 `/api/` 默认保持 Basic 认证和管理 Token 注入；可按 `product-desktop-lan-v1.md` 选择局域网免登录。RPA 路径透传调用方的 Authorization，不注入管理 Token。局域网免登录不代表可信网段内的 RPA 主机无法访问网页开放的接口。
- 默认不启用。部署时使用独立强随机 Token 文件，示例 `docker compose -f deploy/compose.yaml -f deploy/compose.rpa.yaml ...`，`RPA_TOKEN_FILE` 指向仓库外文件，确保容器 UID 1026 能读取。删除或替换该文件并重建服务即可撤销或轮换。不得把凭据放入 Git、URL、RPA 渲染进程或日志。
- RPA 客户端放 Electron 主进程；仅在可信网络或经过正确认证的 HTTPS 链路传输，不应将现有 NAS HTTP 端口直接暴露公网。跨设备访问的网络、TLS、凭据分发由部署时核实，本次不新开公网。

## 契约

使用 `Authorization: Bearer <RPA_TOKEN>`：

1. `GET /rpa/v1/product-groups`：`groups[]` 包含 `groupId`、`name`、`productCount`。
2. `GET /rpa/v1/product-groups/{groupId}/products?limit=50&offset=0&include_total=true`：`items[]` 只包含 `product_id`、`source_platform`、`source_product_id`、`title`、`main_image_url`；附 `total`、`limit`、`offset`。limit 为 1～200。不存在分组为 404。ID 都是字符串，`product_id` 是后续取 UU 的内部键。
3. `GET /rpa/v1/products/{product_id}/uu`：返回 UU 的原始 JSON 字节，并在 `X-UU-SHA256` 返回内容的 SHA-256。可传 `expected_sha256`；当前内容不一致时返回 409、`RPA_UU_VERSION_CHANGED`，不返回新版本内容。UU 缺失为 404，文件哈希异常或 UU 不可用为 409。无需下载图片。

UU 优先返回 NAS 已保存的 UU 文件原始字节；没有文件时使用现有数据库 UU JSON 文本，二者统一以实际返回字节计算 SHA-256。此前导出 ZIP 接口保持不变；RPA 首次读取应保存实际 UU 内容和 SHA-256，再将相同内容用于本次任务。不要仅保存 SHA 后在重试时无条件读取新版本。

分组商品沿用现有查询：`captured_at DESC NULLS LAST, updated_at DESC, product_id`。分页使用原有 OFFSET；不同页之间若发生采集、编辑或分组变化，顺序和集合可能变化，V1 不保证跨请求数据库快照。RPA 应在执行开始时固定实际读取到的商品和 UU 内容；需要在高并发变更期间严格固定全组成员时，须另行设计服务端快照，不能声称现有分页已满足。

## 验证与发布

针对独立凭据、只读隔离、19 位 ID、缺失 UU、原始字节和版本不匹配设测试。CI 容器演练覆盖 Nginx 透传、分组、UU 和拒绝写入。上线前依仓库约定备份生产并在恢复的隔离库验证；用隔离商品验证 UU 与实际 RPA 解析器兼容。生产当前未开启本接口，未经网络和鉴权验收不分发真实凭据。
