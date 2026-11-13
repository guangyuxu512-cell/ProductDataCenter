# 商品库域名入口与图片路由

商品库网页和 API 的新入口为 `https://pdc.mysiyuai.top/`；桌面客户端默认使用该地址。网页沿用独立的 Basic 账号密码，AI 和 RPA 继续分别使用各自的 Bearer Token。原服务器 IP 入口保留，已有客户端不需要同步切换。

商品上传图片仍保存在 NAS 的图片服务，已返回的公网图片 URL 不改写。为使新域名的 `/rpa/v1/product-images/` 也能访问图片，服务器入口将这一前缀指向现有图片专用服务，并剥离客户端 Authorization；其他 RPA 和管理接口保持原有鉴权。配置模板新增 `PDC_IMAGE_STORAGE_ORIGIN`，发布时填写经过验证、仅可访问图片服务的内部地址。

Cloudflare 的配置规则 `PDC Python API compatibility` 只针对 `pdc.mysiyuai.top` 的 `/api/v1/`、以 `Python-urllib/` 开头的 User-Agent 且携带 Bearer 请求头的请求，关闭浏览器完整性检查，避免默认 Python 客户端被误拦截。该规则不验证 Token：后端仍负责认证、操作权限和写入开关；其他域名、路径和客户端不受此规则影响。

## 2026-11-13 实际部署核验

- 服务器商品 API 运行 `bd1a0d2930843039ec21722447c924fece3e35ce`，Web 运行 `dbc2703bf34338568755dabd06fba5c9101200ac`；本机 Windows 客户端为 `94bf1ed05585875b677bc69c8028730630f603b4`。域名读取商品和分组、RPA 分组均返回 200；无凭据管理请求返回 401。
- 域名上传实测 201，返回的既有图片地址与域名图片路径均返回 200、内容一致。原公网 443 入口的商品图片路径已由 NAS 旧网页端口改为直连图片专用服务；维护服务器入口时需保留这一转发，不能改回旧网页端口。
- NAS 旧商品网页及商品接口转发已停用，图片文件和图片专用服务保留。采集系统仍在使用的数据库桥接保留，不能以商品库清理为由删除。历史测试数据库容器和数据卷未删除；零容器的旧项目登记因项目路径包含图片目录而保留。
- 旧商品数据库备份已转存并校验；未修改服务器上的商品数据、RPA 凭据或中控店铺登录状态。

## 2026-11-13 图片上传链路修复

- 现象：同一张约 1.9 MB 图片经服务器 IP 入口上传成功，经 Cloudflare Tunnel 的 QUIC 连接长时间未完成；NAS 存储本身可写。
- 服务器 cloudflared 服务通过 `/etc/systemd/system/cloudflared.service.d/60-pdc-upload-transport.conf` 固定 `TUNNEL_TRANSPORT_PROTOCOL=http2`，保留原有 tunnel、路由和认证配置。回退时移除该 drop-in 后执行 `systemctl daemon-reload` 并重启 `cloudflared`，应先确认备用入口可用。
- 正式配置生效后，域名上传约 1.9 MB 和 5.9 MB 图片均返回 201；返回 URL 与域名图片路径读取返回 200、文件内容一致。网页实际执行主图本地替换并确认草稿图片更新，测试草稿已放弃。
- 使用仅含 `image.upload` 权限的临时 AI Token，默认 `Python-urllib/3.12` 请求经域名上传返回 201；无上传权限返回 403、无效 Token 返回 401。临时 Token 均已撤销，测试图片已从 NAS 清理。
- 本次为服务器 tunnel 和 Cloudflare 匹配规则调整，未重新发布商品库 API 或 Web 镜像，未更改商品数据和既有图片。
