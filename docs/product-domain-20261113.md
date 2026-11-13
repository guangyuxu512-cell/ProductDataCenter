# 商品库域名入口与图片路由

商品库网页和 API 的新入口为 `https://pdc.mysiyuai.top/`；桌面客户端默认使用该地址。网页沿用独立的 Basic 账号密码，AI 和 RPA 继续分别使用各自的 Bearer Token。原服务器 IP 入口保留，已有客户端不需要同步切换。

商品上传图片仍保存在 NAS 的图片服务，已返回的公网图片 URL 不改写。为使新域名的 `/rpa/v1/product-images/` 也能访问图片，服务器入口将这一前缀指向现有图片专用服务，并剥离客户端 Authorization；其他 RPA 和管理接口保持原有鉴权。配置模板新增 `PDC_IMAGE_STORAGE_ORIGIN`，发布时填写经过验证、仅可访问图片服务的内部地址。

Cloudflare 对默认 `Python-urllib` User-Agent 可能返回 403（1010）；AI 客户端可设置 `User-Agent: PDC-AI-Client/1.0`，并按原有方式携带对应权限的 Token。实际网络和凭据验证以部署后的检查结果为准。
