# Muse 连接现有商品库管理接口

此文档描述服务器上运行的 API 版本 `e118b13`。这里的 OpenAPI 文件只是现有接口的静态说明，不新增服务，也不会自动部署。

- 地址：`https://119.29.188.118:19001`
- 鉴权：请求头 `Authorization: Bearer <管理 Token>`。使用 Muse 的安全凭据输入框保存 Token，不要写入提示词、代码仓库或聊天记录。网页的用户名和密码与 API Token 是两种凭据。
- [现有管理接口 OpenAPI 说明](muse-management-openapi-e118b13.json)：用于支持导入 OpenAPI 的连接器。如果连接器只支持同步读取，需要在 Muse 一侧增加调用现有 HTTP 写接口的能力，不能单靠 Token 实现写入。
- 使用独立的管理 Token；RPA 接口使用另一份只读凭据，两者不能互换。该管理凭据可以修改和删除数据，应仅授权可信的连接器。

## 可调用的操作

| 操作 | 现有接口 |
| --- | --- |
| 查询当前开启的能力 | `GET /api/v1/capabilities` |
| 列分组、新建分组 | `GET`、`POST /api/v1/product-groups`；新建请求体为 `{"name":"分组名"}` |
| 重命名、删除分组 | `PATCH`、`DELETE /api/v1/product-groups/{group_id}` |
| 查商品、按分组筛选 | `GET /api/v1/products`，可用 `groupId`、`q`、`productId`、`limit`、`offset` 等参数 |
| 创建手动商品、查详情 | `POST /api/v1/products`、`GET /api/v1/products/{product_id}` |
| 编辑商品 | 先 `GET /api/v1/products/{product_id}/edit`，将响应 `version` 作为 `expectedVersion`，再 `PATCH /api/v1/products/{product_id}`；冲突时重新读取，不覆盖他人修改 |
| 移动商品到分组 | `PATCH /api/v1/products/group`，请求体为 `{"productIds":["商品ID"],"groupId":"分组UUID"}` |
| 删除商品 | `POST /api/v1/products/delete`，请求体为 `{"productIds":["商品ID"]}`，每次最多 200 件 |
| 执行和读取预检 | `POST /api/v1/prechecks/run`、`POST /api/v1/prechecks/query`，请求体均为 `{"productIds":["商品ID"]}`；预检是异步队列 |
| 上传图片 | `POST /api/v1/product-images`，直接提交图片二进制并设置对应的 `Content-Type`；使用返回 URL 更新商品草稿后保存 |
| 导出 UU 数据包 | `POST /api/v1/products/export-uu`，请求体为 `{"productIds":["商品ID"]}`，响应为 ZIP |

商品列表、分组和预检可以先作为只读连通测试。涉及写入和删除时，调用方必须按照用户意图明确选择目标。当前服务的 `importProducts` 能力关闭；类目查询仍依赖店铺授权和平台接口，不能保证对所有类目请求成功。

手机采集和 RPA 使用各自的现有入口；迁移后不需要在 Muse 中填写它们的凭据。上线情况以服务器实际运行版本为准。
