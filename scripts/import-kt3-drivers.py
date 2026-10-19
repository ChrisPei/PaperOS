"""Read selected matching drivers from the public reference firmware, not a device."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KERNEL = "3.10.53-lab126"
MODULES = [
    "kernel/drivers/video/mxc/mxc_epdc_fb.ko",
    "extra/mxc_epdc_eink.ko",
    "kernel/drivers/input/touchscreen/zforce2.ko",
    "kernel/drivers/input/serio/serport.ko",
    "kernel/drivers/usb/gadget/libcomposite.ko",
    "kernel/drivers/usb/gadget/g_ether.ko",
    "kernel/drivers/usb/gadget/g_mass_storage.ko",
    "extra/dhd.ko",
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=Path("/home/chris/kindle-build/recovery-kt3/rootfs.img"))
    args = parser.parse_args()
    if not args.reference.is_file() or args.reference.stat().st_size != 460800000:
        parser.error("Expected the extracted public KT3 5.16.2.1.1 root filesystem")
    destination = ROOT / "build" / "kt3-drivers"
    records = []
    for relative in MODULES:
        target = destination / "lib/modules" / KERNEL / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["debugfs", "-R", f"dump -p /lib/modules/{KERNEL}/{relative} {target}", str(args.reference)], check=True, capture_output=True)
        data = target.read_bytes()
        if not data.startswith(b"\x7fELF\x01"):
            raise ValueError("Expected an ELF32 kernel module")
        info = subprocess.check_output(["arm-linux-gnueabi-readelf", "-p", ".modinfo", str(target)], text=True)
        expected_license = "proprietary" if relative == "extra/mxc_epdc_eink.ko" else "GPL"
        if f"license={expected_license}" not in info or KERNEL not in info:
            raise ValueError(f"Unexpected module license/kernel identity: {relative}")
        records.append({"path": relative, "license": expected_license, "observed_sha256": hashlib.sha256(data).hexdigest(), "modinfo": info})
        print(f"Imported {relative}: {len(data)} bytes")
    firmware = []
    for relative in ("opt/brcm_4343w/wifi/firmware/fw_bcmdhd_sr.bin",
                     "opt/brcm_4343w/wifi/nvram/nvram.txt"):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["debugfs", "-R", f"dump /{relative} {target}", str(args.reference)],
                       check=True, capture_output=True)
        data = target.read_bytes()
        if not data or len(data) > 2 * 1024 * 1024:
            raise ValueError("Invalid matching Wi-Fi firmware/configuration")
        firmware.append({"path": relative, "bytes": len(data),
                         "observed_sha256": hashlib.sha256(data).hexdigest(),
                         "license": "Vendor firmware/configuration; local device validation only"})
    (destination / "sources.json").write_text(json.dumps({"source": "Public Amazon KT3 5.16.2.1.1 reference firmware", "kernel": KERNEL, "modules": records,
                                                          "wifi_firmware": firmware}, indent=2) + "\n")

if __name__ == "__main__":
    main()
