#!/bin/sh
set -eu
: "${APP_AUTH_HTPASSWD:?Set APP_AUTH_HTPASSWD before exposing the app}"
: "${DATABASE_URL:?Set the Railway Postgres DATABASE_URL reference}"
case "${PORT:-8080}" in *[!0-9]*|'') echo 'Invalid PORT' >&2; exit 1;; esac
export PORT="${PORT:-8080}"
mkdir -p /data/table_layouts /data/card_profiles /tmp/zeros-nginx
if [ ! -f "$TABLE_LAYOUT_PATH" ]; then
    cp /app/default_layouts/platform_1920x1080.json "$TABLE_LAYOUT_PATH"
fi
chown -R zeros:zeros /data/table_layouts /data/card_profiles
envsubst '${PORT}' < /etc/zeros/nginx.conf.template > /etc/nginx/nginx.conf
exec /usr/bin/supervisord -c /etc/zeros/supervisord.conf
