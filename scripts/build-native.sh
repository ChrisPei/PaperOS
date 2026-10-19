#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
make -C "$PAPEROS_ROOT/native" ROOT="$PAPEROS_ROOT" OUT="$PAPEROS_ROOT/build/host"
make -C "$PAPEROS_ROOT/native" ROOT="$PAPEROS_ROOT" OUT="$PAPEROS_ROOT/build/arm" \
    CC=arm-linux-gnueabi-gcc AR=arm-linux-gnueabi-ar RANLIB=arm-linux-gnueabi-ranlib \
    KINDLE=1 LDFLAGS=-static CFLAGS="-O2 -std=c11 -Wall -Wextra -mcpu=cortex-a9 -mfloat-abi=soft"
mkdir -p "$PAPEROS_ROOT/dist"
cp "$PAPEROS_ROOT/build/arm/paperos" "$PAPEROS_ROOT/dist/paperos-kt3"
cp "$PAPEROS_ROOT/build/arm/paperos-inputd" "$PAPEROS_ROOT/dist/paperos-inputd"
cp "$PAPEROS_ROOT/build/arm/paperos-input" "$PAPEROS_ROOT/dist/paperos-input"
cp "$PAPEROS_ROOT/build/arm/libpaperos-input.a" "$PAPEROS_ROOT/dist/libpaperos-input.a"
file "$PAPEROS_ROOT/dist/paperos-kt3"
bash "$PAPEROS_ROOT/scripts/build-services.sh"
