# 商品云库开发约定

- 前端复用 AIdashboard 的 Vue 3 / TypeScript 架构和公共组件；不另建视觉规范，不修改布局尺寸、间距、主题和 Token。参考版本及逐文件校验在 `docs/source-baseline.json`。
- 后端使用中控同类 Python / FastAPI / SQLAlchemy / Pydantic 架构。商品查询来自 mobile-product-collector 已优化的 SQL；查询变化须验证精确 ID、平台、分组、中文和秒级日期语义。
- 生产使用现有手机项目 NAS PostgreSQL 数据库。V1 不建立新生产库、不运行 DDL、不接管迁移；`backend/tests/fixtures/collector` 仅用于空的隔离测试库。
- 手机配对、设备调度、采集任务、可靠接收、PDD 转换、中控直传仍由采集项目管理。不在本项目启动这些后台循环。
- 商品组删除保留商品，人工分组不被采集重写。UU 导出优先保留原文件字节；不自动下载图片或整套资料。
- 本阶段默认只读；分组写入需运行配置启用。没有启用的编辑、导入、预检和 AI 功能不得显示假成功。
- 任何生产发布独立执行，先备份并在恢复的隔离库核对；本地测试和 GitHub CI 不等于 NAS 部署或真实采集验收。
- 不提交凭据、用户原始包、真实数据库备份、node_modules、构建缓存。既有安装包和 Git LFS 历史保留。
- 检查：`python scripts/verify-source-baseline.py`、后端 `python -m pytest`、隔离 PG16 `python -m pytest -m integration`、前端 lint / test / build / test:e2e。

