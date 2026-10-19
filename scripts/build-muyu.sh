#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
make -C "$PAPEROS_ROOT/native" ROOT="$PAPEROS_ROOT" OUT="$PAPEROS_ROOT/build/host"
PAPEROS_MUSL_PREFIX=${PAPEROS_MUSL_PREFIX:-/home/chris/kindle-build/output-kt3/host/bin/arm-buildroot-linux-musleabi-}
PAPEROS_MUYU_OUT="$PAPEROS_ROOT/build/muyu-musl-arm"
make -C "$PAPEROS_ROOT/native" ROOT="$PAPEROS_ROOT" OUT="$PAPEROS_MUYU_OUT" \
  CC="${PAPEROS_MUSL_PREFIX}gcc" AR="${PAPEROS_MUSL_PREFIX}ar" RANLIB="${PAPEROS_MUSL_PREFIX}ranlib" \
  KINDLE=1 LDFLAGS="-Wl,--gc-sections -s" \
  CFLAGS="-Os -std=c11 -Wall -Wextra -mcpu=cortex-a9 -mfloat-abi=soft -ffunction-sections -fdata-sections"
mkdir -p "$PAPEROS_ROOT/dist/muyu.papp"
cp "$PAPEROS_ROOT/examples/muyu.papp/manifest.conf" "$PAPEROS_ROOT/examples/muyu.papp/run.sh" "$PAPEROS_ROOT/dist/muyu.papp/"
gzip -n -9 -c "$PAPEROS_MUYU_OUT/paperos" > "$PAPEROS_ROOT/dist/muyu.papp/paperos-muyu.gz"
if [ -f "$PAPEROS_ROOT/dist/muyu.papp/paperos-muyu" ]; then
  rm -- "$PAPEROS_ROOT/dist/muyu.papp/paperos-muyu"
fi
chmod 755 "$PAPEROS_ROOT/dist/muyu.papp/run.sh"
file "$PAPEROS_MUYU_OUT/paperos"
wc -c "$PAPEROS_ROOT/dist/muyu.papp/paperos-muyu.gz"
