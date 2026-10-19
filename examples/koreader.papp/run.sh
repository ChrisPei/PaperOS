#!/bin/sh
set -eu
APP=${PAPEROS_APP_DIR:?}
DATA=${PAPEROS_DATA_DIR:?}
CACHE=/mnt/us/paperos/app-cache/org.paperos.koreader
MOUNT=/run/paperos/koreader-runtime
mkdir -p "$DATA" "$CACHE" "$MOUNT" /mnt/us/documents/Reading-Samples
if [ -f "$DATA/session.log" ]; then
    tail -c 262144 "$DATA/session.log" > "$DATA/previous-session.log"
fi
exec >"$DATA/session.log" 2>&1
EXPECTED=$(cat "$APP/runtime.sha256")
IMAGE="$CACHE/$EXPECTED.ext3"
if [ ! -f "$IMAGE" ]; then
    gzip -dc "$APP/runtime.ext3.gz" > "$IMAGE.partial"
    ACTUAL=$(sha256sum "$IMAGE.partial"); ACTUAL=${ACTUAL%% *}
    if [ "$ACTUAL" != "$EXPECTED" ]; then rm -f "$IMAGE.partial"; exit 2; fi
    mv "$IMAGE.partial" "$IMAGE"
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
