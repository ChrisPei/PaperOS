"""Build and boot a file-backed KT3 test machine. Contains no physical flash command."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = Path("/home/chris/kindle-build")
MACHINE = WORK / "paperos-emulator"
REFERENCE = WORK / "recovery-kt3/imx6sl_heisenberg"

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def prepare(rebuild=False):
    rootfs = ROOT / "dist/paperos-kt3-rootfs.ext3"
    kernel = REFERENCE / "uImage"
    if not rootfs.is_file() or not kernel.is_file():
        raise ValueError("Build the root filesystem and extract the public reference kernel first")
    MACHINE.mkdir(parents=True, exist_ok=True)
    if (MACHINE / "disk.img").exists():
        if not rebuild or (MACHINE / "control.sock").exists():
            raise ValueError("Stop the existing emulator before rebuilding its test disk")
        if MACHINE.is_symlink() or not (MACHINE / "disk.img").is_file():
            raise ValueError("Expected a regular disk file in the test directory")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (MACHINE / "disk.img").rename(MACHINE / f"disk.previous-{stamp}.img")
        if (MACHINE / "serial.log").exists():
            (MACHINE / "serial.log").rename(MACHINE / f"serial.previous-{stamp}.log")
    staged = MACHINE / "emulator-rootfs.ext3"
    shutil.copyfile(rootfs, staged)
    env = MACHINE / "paperos.env"
    env.write_text((ROOT / "os/rootfs-overlay/etc/paperos.env").read_text() + "\nPAPEROS_EMULATOR=1\n")
    options = MACHINE / "modprobe-emulator.conf"
    options.write_text("options mxc_epdc_fb builtin_firmware=y\noptions zforce2 bpbc=0 deviceType=1\n")
    for operation in ["rm /etc/paperos.env", f"write {env} /etc/paperos.env", "mkdir /etc/modprobe.d", f"write {options} /etc/modprobe.d/paperos-emulator.conf"]:
        subprocess.run(["debugfs", "-w", "-R", operation, str(staged)], check=True, capture_output=True)
    sys.path.insert(0, str(ROOT / "tools/eink-emulator"))
    from eink_emulator.images import imx6_mmc
    imx6_mmc.build(MACHINE / "disk.img", kernel, staged, layout="heisenberg")
    record = {"model": "kindle-basic-2016", "machine": "imx6sl-eanab", "memory": "512M", "inputs": {str(p): digest(p) for p in [rootfs, kernel, REFERENCE / "u-boot.bin"]}, "emulator_only_changes": ["PAPEROS_EMULATOR=1", "builtin display waveform", "synthetic device identity", "blank virtual local/user-storage partitions"]}
    (MACHINE / "inputs.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Created file-backed emulator disk: {MACHINE / 'disk.img'}")

def start():
    qemu = WORK / "qemu-eink/build/qemu-system-arm"
    if not (MACHINE / "disk.img").is_file():
        raise ValueError("Prepare a test disk first")
    if (MACHINE / "control.sock").exists():
        raise ValueError("A QMP socket already exists; inspect the existing test machine first")
    command = [str(qemu), "-name", "PaperOS-KT3", "-machine", "imx6sl-eanab,idme-serial=G000K90000000001", "-m", "512M", "-bios", str(REFERENCE / "u-boot.bin"), "-drive", f"file={MACHINE / 'disk.img'},if=sd,index=1,format=raw", "-chardev", f"socket,id=serial0,path={MACHINE / 'serial.sock'},server=on,wait=off,logfile={MACHINE / 'serial.log'}", "-serial", "chardev:serial0", "-monitor", "none", "-qmp", f"unix:{MACHINE / 'control.sock'},server=on,wait=off", "-display", "none", "-nic", "none", "-no-reboot", "-daemonize", "-pidfile", str(MACHINE / "qemu.pid"), "-D", str(MACHINE / "qemu.log")]
    subprocess.run(command, check=True, cwd=qemu.parent)
    print(f"Started KT3 emulator; console: {MACHINE / 'serial.log'}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    if args.start:
        start()
    else:
        prepare(args.rebuild)
