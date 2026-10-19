#!/bin/sh
set -eu
APP=${PAPEROS_APP_DIR:?}
DATA=${PAPEROS_DATA_DIR:?}
CACHE=/mnt/us/paperos/app-cache/org.paperos.koreader
MOUNT=/run/paperos/koreader-runtime
mkdir -p "$DATA" "$DATA/plugins" "$CACHE" "$MOUNT" /mnt/us/documents/Reading-Samples
if [ -f "$DATA/session.log" ]; then
    tail -c 262144 "$DATA/session.log" > "$DATA/previous-session.log"
fi
exec >"$DATA/session.log" 2>&1
EXPECTED=$(cat "$APP/runtime.sha256")
case "$EXPECTED" in *[!0-9a-f]*|"") echo "Invalid KOReader runtime digest"; exit 2;; esac
[ "${#EXPECTED}" -eq 64 ] || exit 2
[ -x "$APP/paperos-overlay" ] || { echo "PaperOS overlay helper is not executable"; exit 2; }
IMAGE="$CACHE/$EXPECTED.ext3"
if [ ! -f "$IMAGE" ]; then
    PARTIAL="$IMAGE.partial.$$"
    trap 'rm -f "$PARTIAL"' EXIT
    gzip -dc "$APP/runtime.ext3.gz" > "$PARTIAL"
    ACTUAL=$(sha256sum "$PARTIAL"); ACTUAL=${ACTUAL%% *}
    if [ "$ACTUAL" != "$EXPECTED" ]; then echo "KOReader runtime integrity check failed"; exit 2; fi
    mv "$PARTIAL" "$IMAGE"
    trap - EXIT
fi
ACTUAL=$(sha256sum "$IMAGE"); ACTUAL=${ACTUAL%% *}
if [ "$ACTUAL" != "$EXPECTED" ]; then echo "KOReader runtime integrity check failed"; exit 2; fi
if ! mountpoint -q "$MOUNT"; then
    mount -t ext3 -o loop,ro,nosuid,nodev "$IMAGE" "$MOUNT"
fi
cleanup() { cd /; umount "$MOUNT" || true; }
trap cleanup EXIT
export KO_HOME="$DATA"
export EXT_FONT_DIR=/usr/share/paperos
export TMPDIR=/tmp
export LD_LIBRARY_PATH="$MOUNT/gnu:$MOUNT/koreader/libs"
if [ ! -f "$DATA/settings.reader.lua" ]; then
    cat > "$DATA/settings.reader.lua" <<'LUA'
return {
    ["language"] = "zh_CN",
    ["home_dir"] = "/mnt/us/documents/Reading-Samples",
    ["lastdir"] = "/mnt/us/documents/Reading-Samples",
    ["cre_font"] = "Noto Sans CJK SC",
    ["font_size"] = 24,
    ["show_unsupported"] = false,
    ["update_all_book_metadata"] = false,
}
LUA
fi
cd "$MOUNT/koreader"
"$MOUNT/gnu/ld-linux.so.3" --library-path "$LD_LIBRARY_PATH" ./luajit "$APP/bootstrap.lua" "${PAPEROS_KOREADER_BOOK:-/mnt/us/documents/Reading-Samples}"
