#!/bin/sh
set -eu
umask 077
export PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"
pg_dump -h 127.0.0.1 -U "${PGUSER:-${POSTGRES_USER:-postgres}}" -d "${PGDATABASE:-${POSTGRES_DB:-railway}}" --format=custom --no-owner --file=/tmp/zeros-backup.dump
pg_restore --list /tmp/zeros-backup.dump > /tmp/zeros-backup-list.txt
echo 'Database dump and archive listing ready.'
