#!/bin/sh
set -eu
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
arm-linux-gnueabi-gcc -std=gnu11 -Os -static -Wall -Wextra -Werror \
    -fstack-protector-strong -Wl,-z,noexecstack \
    "$PAPEROS_ROOT/native/bootstrap.c" -o "$PAPEROS_ROOT/dist/paperos-bootstrap"
qemu-arm-static "$PAPEROS_ROOT/dist/paperos-bootstrap" --check
sha256sum "$PAPEROS_ROOT/dist/paperos-bootstrap"
