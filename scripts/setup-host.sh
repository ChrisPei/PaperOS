#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo "Run this host dependency installer as root inside the Ubuntu WSL distribution." >&2
    exit 1
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential git curl wget rsync file patch bc cpio flex bison \
    python3 python3-venv python3-pip ninja-build pkg-config \
    libglib2.0-dev libpixman-1-dev libslirp-dev zlib1g-dev libfdt-dev \
    libncurses-dev libssl-dev libarchive-dev libgmp-dev nettle-dev \
    unzip xz-utils bzip2 lzop e2fsprogs dosfstools \
    gcc-arm-linux-gnueabi g++-arm-linux-gnueabi qemu-user-static

