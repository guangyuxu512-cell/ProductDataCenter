# 商品云库 V1 交付说明

## 架构与数据库归属

```
frontend/src/
  app/                 路由和 Provider
  pages/               商品库页面入口
  features/            商品列表、筛选、分组和详情
  entities/            中控 ProductInfoCell / ProductImage / 平台组件
  shared/              中控原有 UI、布局组件、样式；API 客户端
  stores/              中控主题 Store
backend/app/
  core/                配置、数据库连接、鉴权、异常和日志
  modules/products/    HTTP 接口、业务服务、Repository、查询和导出
```

生产沿用手机项目现有 NAS PostgreSQL 数据库和数据目录，Compose 不包含 PostgreSQL 服务。本项目不新建数据库，不执行 `create_all`、Alembic 或任何启动 DDL。采集项目继续拥有 `schema_migrations` 和既有迁移链。本候选依赖已部署的 0001～0008 表/索引；不能据此断言现场仍只有这 8 个版本，发布前应读取现场版本和定义。

本服务访问 `products`、`product_skus`、`product_images`、`product_groups`。手机项目继续配对、调度、上传、清洗入库。仅新增独立商品读取/分组管理入口；没有迁走历史数据、移除旧商品页或切换采集上传目标。后续接管数据写入需单独确定迁移归属，不能让两个项目各自修改同一表结构。

## 查询适配

手机后端为 Node.js，中控后端为 Python，因此复用 SQL 和行为约定，不直接把 Node 模块塞进 FastAPI。

- Python 查询生成器与固定版本 `product-query-v1.mjs` 做逐用例 SQL/参数比对。
- 保留 `pg_trgm` 表达式、精确 ID、平台前缀标准化、四字段条件、通配符、排序以及现有索引路径。
- 列表不读取 `uu_json`；列表和计数拆开，在同一个 PostgreSQL `REPEATABLE READ READ ONLY` 快照执行。
- 翻页复用计数；筛选变化或手动刷新重新计数。保留当前 OFFSET 行为，没有冒充已完成游标分页。
- 前端用字符串保留 19 位 ID；金额保留 Decimal 序列化字符串。
- 时间按 Asia/Shanghai 输入和显示；结束秒使用下一秒的排他上界，保留微秒记录。
- 独立接口前缀 `/api/v1`，不替换采集项目原接口。

原项目曾做的 30 万商品压测不能算作本次 FastAPI 端到端成绩。SQL 对照和 PG16 功能测试通过后，仍需用恢复的真实分布重新测 API 延迟、连接池和多用户并发，不能直接承诺同样的 P95。

## API

全部业务接口需要 Bearer Token；未配置时返回 503，缺失或错误时 401。

| 方法和路径 | 用途 |
| --- | --- |
| GET `/api/v1/capabilities` | 写入能力开关 |
| GET `/api/v1/products` | 轻量列表，兼容原筛选参数及 includeTotal |
| GET `/api/v1/products/{id}` | 商品、SKU 和图片 URL，不返回完整 UU |
| GET `/api/v1/products/{id}/images/{kind}/{position}` | 经校验的原有本地图片读取 |
| GET/POST `/api/v1/product-groups` | 分组列表/新增 |
| PATCH/DELETE `/api/v1/product-groups/{uuid}` | 重命名/删除，删除保留商品 |
| PATCH `/api/v1/products/group` | 批量移入分组或未分组 |
| POST `/api/v1/products/export-uu` | 最多 200 个商品的 UU ZIP |

分组写接口还检查 `BACKEND_ENABLE_GROUP_WRITES`，默认 false。UU 导出优先读取已存在版本文件，验证 JSON 和已保存 SHA-256；没有文件时使用数据库中的 UU，并在 manifest 明确来源。目录只读挂载，文件读取限制在数据根目录内。V1 不自动拉取图片二进制。

## 权限与页面

V1 是一个 NAS 商品目录的独立入口，没有沿用中控的团队/租户授权模型，也不自动导入中控其他团队的数据。不能把它直接挂在公网而省略鉴权，或宣称拥有中控跨团队访问隔离。

NAS Web 入口使用已有反向代理 HTTPS，容器 Nginx 检查挂载的 htpasswd。Nginx 向私有 API 注入 Token，Token 不进浏览器构建。部署默认仅绑定 `127.0.0.1:3612`。允许访问的人员范围由反向代理账号管理；如果需要原中控用户/团队权限，下一阶段先接权限再扩大可见数据。

中控 228px 导航、54px 顶栏、公共控件、表格、底部分页、弹窗和四套主题原样使用。页面字段改为手机商品库字段，未支持的编辑/预检/AI 不显示可执行按钮。测试截图使用隔离合成商品，不是生产数据。

## NAS 发布步骤（本轮未执行）

1. 核对 Candidate/CI、运行中采集任务、数据库迁移记录和真实数据根目录。留存现有 Compose、数据库 custom-format dump、源码/镜像及校验值。
2. 将备份恢复到隔离 PostgreSQL 16，验证本服务列表/详情、时间、分组事务、UU 文件、原手机任务查询。需要测试的分组操作只在隔离库执行。
3. 从精确 SHA 构建 `deploy/api.Dockerfile` 和 `deploy/web.Dockerfile`。复制 `deploy/.env.example` 到仓库外配置目录，填入现有 NAS 数据库地址和网络名；不创建替代生产库。
4. 使用独立数据库账号，初始仅授予商品相关表 SELECT。完整的 `postgresql+psycopg://` 连接写入仓库外凭据文件，由 `DATABASE_URL_FILE` 引用，不放进 Compose 环境值。连接文件和 Token 文件需容器 `1026:100` 能读（例如属主/组 `1026:100`、`0440`）；数据目录只读，htpasswd 需 Nginx 能读。禁止把这些文件放入 Git。配置同时给出 URL 和 URL_FILE 时拒绝启动，凭据错误不回显连接内容。
5. 使用唯一 SHA 镜像标签部署两套新容器，与采集项目并行，不重建旧采集 API/数据库。首次 `BACKEND_ENABLE_GROUP_WRITES=false`。
6. 核验真实商品数量、平台/分组/秒级时间、图片/SKU 和 UU 导出原文件校验值，检查登录保护、资源、刷新路由和无外层滚动。`/health` 仅证明进程存活，不能代替数据库验收。
7. 如启用分组管理，授予分组表 INSERT/UPDATE/DELETE 和商品 `group_id` 更新所需权限（含已有触发器所需权限），在隔离库用相同角色通过测试后再启用开关。不开商品正文编辑。
8. 出现问题停止新容器、恢复旧入口；V1 无 schema 变更，不执行数据库降级，不覆盖发布期间其他会话合法产生的数据。

## 验证范围

- 本地：源码复用校验、SQL 差异测试、认证/错误/UU 导出测试，Vue lint/单测/类型检查/构建，隔离浏览器交互。
- CI：全新 PostgreSQL 16 使用手机项目 0001～0008 原 SQL 建库，验证秒级筛选、快照一致性及分组 CRUD；这不是恢复真实 NAS 备份。
- CI：两套 Docker 构建后运行 `scripts/container-smoke.py`，使用生产 Compose 启动临时 PG16 和新服务，验证 `1026:100` 读取凭据文件、Web Basic/API Bearer 鉴权、列表/详情、UU 原始字节、默认写禁用和最小权限分组 CRUD。测试只删除本轮随机名称的容器/网络；这仍不能代替 DSM 运行和真实备份恢复验证。
- 尚未执行：真实 NAS 备份恢复、生产配置、生产部署、真实手机采集、APK 操作、中控商品数据迁移、RPA 接入、独立人工审查。

最终可声明范围以对应提交的 CI 结果为准，失败或未运行的检查不能记作通过。
