# 采集商品的来源平台与 ID

`POST /api/v1/products` 可选传入 `sourcePlatform` 和 `sourceProductId`。抖音采集传 `"sourcePlatform":"douyin"`，聚水潭传 `"sourcePlatform":"jushuitan"`；不传平台时保持旧接口的抖音默认行为。来源 ID 必须是字符串，避免长数字精度丢失；聚水潭暂时没有可靠 ID 时可省略 `sourceProductId`。

接口继续生成 `manual:` 内部主键，不改变已有商品及其 SKU、图片、分组的关联。列表优先显示来源 ID，其他接口进行修改时仍使用返回的 `productId` 内部主键。按 `GET /api/v1/products?sourceProductId=...&platform=douyin` 可精确查找；`productId` 检索也支持已有的数字来源 ID。相同平台已有来源 ID 时创建或补写返回 HTTP 409，不同平台互不去重。并发创建依靠已有数据库唯一索引保护。

对已经创建且来源 ID 为空的 `manual:` 商品，具有商品编辑权限的调用方可使用 `PATCH /api/v1/products/{内部主键}/source-identity`，例如请求体 `{"sourcePlatform":"douyin","sourceProductId":"3811680774151864442"}`。该操作只补充来源字段，不修改商品包、分组或预检队列；已有的不同来源 ID 或冲突的包内 ID 不会被覆盖。读取导出或 RPA 商品包时，历史抖音商品缺少包内 `goodsId` 的，会根据已确认的来源 ID 补出该字段，数据库原包保持不变。

`GET /api/v1/capabilities` 返回 `sourceProductIdentity: true` 表示接口支持该字段。插件应先检查能力并在创建后读回 `source_platform` 和 `source_product_id`。上游只有在实际识别到来源时才传平台与 ID，不能把内部 `manual:` 主键冒充原商品 ID。

类目需传真实的 ID 与中文名称，未核实的原始类目留空、待确认。聚水潭创建请求的 `edit.category` 可包含来源类目，也可包含采集方核实的抖店类目；仅当同一店铺的缓存树完整确认每级 ID、名称及叶子节点后，商品库才将其同时保存为抖店目标。编辑页面选择并保存的抖店类目和属性单独保存在商品包的 `douyinTarget`，不会覆盖来源类目。没有已确认的抖店目标类目时，预检按标题和主图取得候选，不能把未核实的来源编号传给抖店属性接口。来源 ID 不用于推断类目。其他客户端是否接受 `jushuitan` 取决于客户端版本，不能仅凭接口返回即视为完成 RPA 上架。
