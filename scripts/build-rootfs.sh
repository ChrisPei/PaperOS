#!/bin/bash
set -euo pipefail
PAPEROS_ROOT=$(cd "$(dirname "$0")/.." && pwd)
PAPEROS_WORK=${PAPEROS_BUILD_DIR:-/home/chris/kindle-build}
PAPEROS_BUILDROOT="$PAPEROS_WORK/buildroot"
PAPEROS_OUTPUT="$PAPEROS_WORK/output-kt3"
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [ "$(id -u)" -eq 0 ]; then echo "Build as your normal WSL user, not root." >&2; exit 1; fi
mkdir -p "$PAPEROS_WORK" "$PAPEROS_ROOT/dist"
if [ ! -d "$PAPEROS_BUILDROOT" ]; then
    mkdir -p "$PAPEROS_BUILDROOT"
    rsync -a --exclude=.git "$PAPEROS_ROOT/tools/buildroot/" "$PAPEROS_BUILDROOT/"
fi
python3 "$PAPEROS_ROOT/scripts/normalize-source.py" "$PAPEROS_BUILDROOT"
bash "$PAPEROS_ROOT/scripts/build-services.sh"
chmod +x "$PAPEROS_ROOT/os/rootfs-overlay/sbin/upstart" \
    "$PAPEROS_ROOT/os/rootfs-overlay/usr/sbin/paperos-session" \
    "$PAPEROS_ROOT/os/rootfs-overlay/usr/sbin/paperos-boot-guard" \
    "$PAPEROS_ROOT/os/rootfs-overlay/usr/sbin/paperos-services-monitor" \
    "$PAPEROS_ROOT/os/rootfs-overlay/etc/init.d/"S*
make -C "$PAPEROS_BUILDROOT" O="$PAPEROS_OUTPUT" BR2_EXTERNAL="$PAPEROS_ROOT/os" kt3_defconfig
if [ -f "$PAPEROS_OUTPUT/build/paperos-0.1.0/.stamp_built" ]; then
    make -C "$PAPEROS_BUILDROOT" O="$PAPEROS_OUTPUT" paperos-rebuild
fi
if [ -f "$PAPEROS_OUTPUT/build/paperos-drivers-5.16.2.1.1/.stamp_built" ]; then
    make -C "$PAPEROS_BUILDROOT" O="$PAPEROS_OUTPUT" paperos-drivers-rebuild
fi
make -C "$PAPEROS_BUILDROOT" O="$PAPEROS_OUTPUT" -j"${PAPEROS_JOBS:-12}"
cp "$PAPEROS_OUTPUT/images/rootfs.tar" "$PAPEROS_ROOT/dist/paperos-kt3-rootfs.tar"
PAPEROS_IMAGE="$PAPEROS_ROOT/dist/paperos-kt3-rootfs.ext3"
if [ -e "$PAPEROS_IMAGE" ]; then
    mv "$PAPEROS_IMAGE" "$PAPEROS_IMAGE.previous-$(date -u +%Y%m%dT%H%M%SZ)"
fi
cp "$PAPEROS_OUTPUT/images/rootfs.ext3" "$PAPEROS_IMAGE"
e2fsck -fn "$PAPEROS_IMAGE"
sha256sum "$PAPEROS_ROOT/dist/paperos-kt3-rootfs.tar" "$PAPEROS_IMAGE" > "$PAPEROS_ROOT/dist/SHA256SUMS"
echo "Independent KT3 root filesystem built. Hardware boot and recovery readiness must be verified separately."
