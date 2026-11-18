# AI 读取和修改商品类目与属性

`GET /api/v1/products/{商品库内部 ID}/edit` 使用现有 Bearer Token，要求 `product.update`、商品写入开关及该商品的分组权限，不新增权限。返回的 `version`、规格和 SKU 字段不变，新增以下字段：

- `category`：已保存的完整抖店类目路径，数组元素为字符串 `id` 和中文 `name`。聚水潭、拼多多返回已确认的目标类目，不把来源类目当目标。
- `sourceCategoryId`：已保存的来源末级 ID；对于聚水潭可能与抖店目标不同。
- `attributes`：已识别的已保存属性，元素为 `id`、`name`、`values`，每个值为 `id`、`name`。未填写的值不会编造，可能不出现或为 `[]`。

抖音商品的类目名称优先使用商品自身保存的完整路径，其次使用持久类目树缓存。保存的 ID 无法可靠对应中文名称时，`category` 为空数组，`sourceCategoryId` 仍可供核对；接口不会自动查询平台或伪造名称。属性来自现有商品包解析，无法识别属性 ID 时 `id` 为 `null`，该项不能原样提交为修改，应先核对类目属性表。

`PATCH /api/v1/products/{商品库内部 ID}` 使用刚读到的 `version` 作为 `expectedVersion`，可按属性 ID 只提交需要更改的项；提交某个多选属性时，`values` 需包含该属性要保留的全部值。值的 ID 支持 `id` 或原有的 `valueId`，不能同时提交不同的两者。选项值应使用类目表单里的真实选项 ID；文本或自定义值沿用 `0`。需要先通过 `/api/v1/category-lookup/schema/auto` 确认规则，不能凭名称编造品牌选项或企业名称。版本冲突时重新读取再决定是否修改。

`GET /api/v1/products/{id}` 仍可读取 `sourceAttributes`、`targetCategory` 和 `targetAttributes`；这些是现有详情投影，不代表原始包的所有特殊字段均可被解析。
