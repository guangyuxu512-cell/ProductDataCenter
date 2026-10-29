# 商品云库

独立的商品工作台：使用中控的页面外壳、布局、主题和组件，读取手机采集项目现有的 NAS 商品库。代码保留在原 ProductDataCenter 仓库；历史 Electron 安装产物未覆盖。

## V1 范围

- 商品列表与详情：主图、标题、完整 ID 复制、平台、分组、店铺、类目、价格、SKU 和秒级采集时间。
- 平台 / 分组 / 未分组 / 关键词 / 精确商品 ID / 开始和结束时间筛选。
- 表格内部横纵滚动、固定表头和底部分页，翻页复用总数，无商品列表定时轮询。
- 分组新增、重命名、删除、批量移动；删除分组保留商品。服务端默认关闭写入，可通过部署配置启用。
- 单件和批量导出 UU；保持已有 UU 文件字节和版本信息，不自动下载图片。

商品编辑、导入、选品工作流、跨平台类目/属性映射、抖店预检、AI 改图以及 RPA 云数据包接口后续分阶段接入。V1 没有这些能力的演示按钮。

## 复用基线

| 来源 | 精确版本 | 使用内容 |
| --- | --- | --- |
| AIdashboard | `6bacc73a690c1e9c1e5735824703e41ce270abfe` | Vue/TypeScript、Naive UI、Pinia、TanStack Query、AppShell、公共组件、Token、四套主题；FastAPI 后端基础模块 |
| mobile-product-collector | `4d79329d15b3b30c6a69b4bb91801e3091b00670` | NAS 商品字段、优化 SQL、分组和时间筛选语义、UU 导出约定；历史迁移仅作测试夹具 |
| ProductDataCenter | `7a0d1deb915b245fdfd622720a470ace2e1c6a81` | 保留原仓库及安装包历史；新增前后端源码 |

49 个原样复用文件的校验记录在 `docs/source-baseline.json`。商品页面数据绑定和详情字段进行了适配，公共组件和样式文件没有重设计。

## 本地运行

需要 Python 3.12+、Node 22 和 pnpm 11.25.0。

```sh
pnpm install --frozen-lockfile
python -m pip install -e './backend[dev]'
```

复制 `backend/.env.example` 为 `backend/.env`，填写**隔离数据库**地址和随机 Token。第一次先使用现有 NAS 备份恢复的隔离库，不用生产库做开发数据。

```sh
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8180
```

复制 `frontend/.env.example` 为 `frontend/.env.local`，填写同一个 Token，仅由 Vite 服务端注入，不使用 `VITE_` 前缀暴露到浏览器。

```sh
pnpm --dir frontend dev
```

打开 `http://127.0.0.1:4180/#/products`。实际数据来自已配置的 API；服务未连接时显示错误，不生成模拟商品。浏览器测试使用的夹具只位于 `frontend/e2e`。

## Windows 项目目录

工作目标是 `D:\商品云库`。本候选在云端工作区建立，没有访问或修改该 Windows 目录。空目录可通过以下方式接收分支（已有文件时先核对，不覆盖）：

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
git clone --branch codex/product-workbench-v1 https://github.com/guangyuxu512-cell/ProductDataCenter.git "D:\商品云库"
Remove-Item Env:GIT_LFS_SKIP_SMUDGE
```

跳过历史安装包的 LFS 下载不影响新源码运行。

## 验证与部署

```sh
python scripts/verify-source-baseline.py
# 在 backend 目录
python -m pytest
# 仅显式指定空隔离库 product_workbench_test 后执行
python -m pytest -m integration
# 在仓库根目录
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend exec playwright install chromium
pnpm --dir frontend test:e2e
```

GitHub Actions 分开验证 PostgreSQL 16、浏览器交互和两个 Docker 镜像。详细的数据库归属、部署步骤及限制见 [V1 交付说明](docs/product-workbench-v1.md)。

