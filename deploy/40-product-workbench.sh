#!/bin/sh
set -eu
test -s /run/secrets/web_htpasswd
PRODUCT_API_TOKEN="$(tr -d '\r\n' < /run/secrets/product_api_token)"
case "$PRODUCT_API_TOKEN" in
  ''|*[!a-zA-Z0-9_-]*) echo '商品服务 Token 必须为非空 URL-safe 字符串' >&2; exit 1;;
esac
export PRODUCT_API_TOKEN
envsubst '${PRODUCT_API_TOKEN}' < /etc/product-workbench/nginx.conf.template > /etc/nginx/conf.d/default.conf
