# 商品云库桌面客户端与局域网免登录

## 范围

- Windows x64 Electron 使用现有 NAS 网页前端，默认连接 `http://192.168.0.102:3612/`，不打包数据库、API 凭据、手机能力或 RPA 凭据。业务后端继续运行于 NAS。
- Electron 参照中控窗口采用独立进程、隔离上下文、沙箱和禁止 Node 的网页环境，不暴露 IPC。仅允许站内导航，其他窗口与跳转被拒绝。网络不可用时提供重试或退出。
- 局域网 HTTP 无 Clipboard API 时，用户点击复制可退回浏览器原生复制；组件布局与样式不变。原组件来源及适配原因见 `source-baseline.json`。
- Windows 安装包由 GitHub Windows CI 构建、实际运行隔离网页测试，产物带提交 SHA 和 SHA-256。下载或构建产物不等于完成 NAS 发布和真实 Windows 安装验收。

## 访问方式和限制

部署默认仍为 `WEB_ACCESS_MODE=basic`。要按本次需求移除浏览器弹窗，部署配置显式设置 `WEB_ACCESS_MODE=lan`，并设置 `WEB_TRUSTED_CIDR` 为客户端实际所在的私有 IPv4 网段，例如 `192.168.0.0/24`。此模式中网页、静态资源及 `/api/` 只允许该网段和本机访问；不改变 `/rpa/v1/` 的来源限制和独立 Bearer Token。

免登录意味着**可信网段内任何能连到网页的设备都能读取商品，并可使用已开启的分组写入**。RPA 的 `/rpa/v1/` 路径仍然只读且校验原 Token；但是处于可信网段的 RPA 电脑也能以无凭证方式访问网页接口，不能宣称对该电脑实施了严格的只读隔离。需要隔离时再接员工认证或为不同设备实施网络隔离。

网页代理不会将客户端提供的 Bearer 凭证替换为管理凭证，原 RPA 凭证无法直接作为管理接口凭证。RPA 不需要更换 Token 或重新配置。注意无凭证的可信网段客户端仍可访问网页开放的接口。

部署前必须核实 NAS 是否有公网转发或反向代理，以及 Docker 中 Nginx 实际看到的客户端来源 IP；如果代理使外网请求表现为可信 IP，以上网段规则不能阻止外网访问。不要把匿名网页入口接到公网，后续需要外网时先接员工登录与 HTTPS。当前客户端 HTTP 地址只允许私有 IP/localhost；其他地址使用 HTTPS。若 Docker 代理导致正常局域网用户的来源 IP 不在网段内，保持 Basic 模式并先调整网络配置，不通过放宽为公网解决。

## 构建及回退

在 `desktop` 目录使用 `pnpm install --frozen-lockfile`、`pnpm test`、`pnpm package:win`；CI 在 Windows 构建 NSIS 包。需要变更服务地址时，可在启动进程前配置 `PRODUCT_WORKBENCH_URL` 为无路径和凭据的服务根地址。它不改变 NAS 或 RPA 配置。

正式发布依项目既有流程先备份、隔离验证、核实 RPA 测试窗口，随后仅更新网页服务并保留现有 API、数据库、RPA Token、端口与采集服务。切回 `WEB_ACCESS_MODE=basic` 并重建网页容器可恢复旧认证；原 htpasswd 文件保留。无数据库迁移。

测试范围必须区分：桌面单元测试、打包及隔离运行，Docker 双模式与 RPA 鉴权回归，NAS 真实访问及 Windows 安装各自独立验收。不得以 CI 或导入镜像代替真实 NAS 和 Windows 验收。
