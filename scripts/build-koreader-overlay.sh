#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
PAPEROS_MUSL_PREFIX=${PAPEROS_MUSL_PREFIX:-/home/chris/kindle-build/output-kt3/host/bin/arm-buildroot-linux-musleabi-}
PAPEROS_READER_OUT="$PAPEROS_ROOT/build/koreader-overlay"
make -C "$PAPEROS_ROOT/native" ROOT="$PAPEROS_ROOT" OUT="$PAPEROS_READER_OUT" \
  CC="${PAPEROS_MUSL_PREFIX}gcc" AR="${PAPEROS_MUSL_PREFIX}ar" RANLIB="${PAPEROS_MUSL_PREFIX}ranlib" \
  KINDLE=1 LDFLAGS="-Wl,--gc-sections -s" \
  CFLAGS="-Os -std=c11 -Wall -Wextra -mcpu=cortex-a9 -mfloat-abi=soft -ffunction-sections -fdata-sections"
mkdir -p "$PAPEROS_ROOT/dist/koreader.papp"
cp "$PAPEROS_READER_OUT/paperos" "$PAPEROS_ROOT/dist/koreader.papp/paperos-overlay"
