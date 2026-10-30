#!/bin/sh
set -eu
PRODUCT_API_TOKEN="$(tr -d '\r\n' < /run/secrets/product_api_token)"
case "$PRODUCT_API_TOKEN" in
  ''|*[!a-zA-Z0-9_-]*) echo '商品服务 Token 必须为非空 URL-safe 字符串' >&2; exit 1;;
esac
case "${WEB_ACCESS_MODE:-basic}" in
  basic)
    test -s /run/secrets/web_htpasswd
    WEB_AUTH_DIRECTIVES='auth_basic "ProductDataCenter"; auth_basic_user_file /run/secrets/web_htpasswd;'
    WEB_NETWORK_DIRECTIVES=''
    ;;
  lan)
    # Restrict anonymous human access to a single explicitly configured private
    # IPv4 network. The independently authenticated /rpa/v1/ route is unchanged.
    trusted_cidr="${WEB_TRUSTED_CIDR:-192.168.0.0/24}"
    if ! printf '%s\n' "$trusted_cidr" | awk -F '[./]' '
      NF != 5 { exit 1 }
      { for (i=1; i<=5; i++) if ($i !~ /^[0-9]+$/) exit 1 }
      $1 > 255 || $2 > 255 || $3 > 255 || $4 > 255 || $5 > 32 { exit 1 }
      !($1 == 10 && $5 >= 8 || $1 == 172 && $2 >= 16 && $2 <= 31 && $5 >= 12 || $1 == 192 && $2 == 168 && $5 >= 16) { exit 1 }
    '; then
      echo 'WEB_TRUSTED_CIDR 必须是 RFC1918 私有 IPv4 网段' >&2
      exit 1
    fi
    WEB_AUTH_DIRECTIVES='auth_basic off;'
    WEB_NETWORK_DIRECTIVES="allow 127.0.0.1; allow ${trusted_cidr}; deny all;"
    ;;
  *) echo 'WEB_ACCESS_MODE 只能是 basic 或 lan' >&2; exit 1;;
esac
export PRODUCT_API_TOKEN WEB_AUTH_DIRECTIVES WEB_NETWORK_DIRECTIVES
envsubst '${PRODUCT_API_TOKEN} ${WEB_AUTH_DIRECTIVES} ${WEB_NETWORK_DIRECTIVES}' < /etc/product-workbench/nginx.conf.template > /etc/nginx/conf.d/default.conf
