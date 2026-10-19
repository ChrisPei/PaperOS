#!/bin/sh
set -eu
: "${PAPEROS_APP_DIR:?}" "${PAPEROS_DATA_DIR:?}"
muyu_tmp=$(mktemp "$PAPEROS_DATA_DIR/.muyu.XXXXXX")
trap 'rm -f "$muyu_tmp"' EXIT
trap 'exit 1' HUP INT TERM
gzip -dc "$PAPEROS_APP_DIR/paperos-muyu.gz" > "$muyu_tmp"
chmod 700 "$muyu_tmp"
mv -f "$muyu_tmp" "$PAPEROS_DATA_DIR/paperos-muyu"
exec "$PAPEROS_DATA_DIR/paperos-muyu" --screen muyu --standalone "$@"
