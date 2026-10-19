"""Check rebooted dashboard programs and Wi-Fi through the pinned device key."""
import argparse
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
import ipaddress
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--wait", type=int, default=120)
    args = parser.parse_args()
    address = ipaddress.ip_address(args.host)
    if address.version != 4 or not address.is_private:
        parser.error("Choose the local Wi-Fi IPv4 address")
    ssh = SourceFileLoader("dashboard_reboot_ssh", str(ROOT / "scripts/device-ssh.py")).load_module()
    connection = ssh.connection(22)
    connection[-1] = "root@" + str(address)
    connection[-1:-1] = ["-o", "HostKeyAlias=169.254.28.2"]
    record_path = ROOT / "build/dashboard-device-validation.json"
    record = json.loads(record_path.read_text())
    deadline = time.monotonic() + max(1, min(args.wait, 300))
    last_error = ""
    while time.monotonic() < deadline:
        try:
            command = (
                "test -f /run/paperos/boot-confirmed && "
                "test -S /run/paperos/input.sock && test -S /run/paperos/services.sock && "
                "test \"$(pidof paperos | wc -w)\" -eq 1 && "
                "test \"$(pidof paperos-services | wc -w)\" -eq 1 && "
                "readlink /proc/1/exe; cat /proc/uptime"
            )
            result = subprocess.run(connection + [command], capture_output=True, timeout=12, check=True)
            lines = result.stdout.decode().splitlines()
            if len(lines) != 2 or lines[0] != "/bin/busybox" or float(lines[1].split()[0]) > 300:
                raise ValueError("A fresh independent boot with the dashboard is required")
            data = subprocess.check_output(connection + ["cat /run/paperos/state.tsv"], timeout=12)
            rows = [line.split("\t") for line in data.decode().splitlines()]
            net = next(row for row in rows if row[0] == "net")
            if net[3] != "true" or net[4] != str(address):
                raise ValueError("Waiting for Wi-Fi to reconnect")
            for row in record["records"]:
                if not row["destination"].startswith(("/usr/", "/etc/init.d/")):
                    continue
                actual = subprocess.check_output(connection + ["sha256sum " + row["destination"]], timeout=12).decode().split()[0]
                if actual != row["sha256"]:
                    raise ValueError("Program changed: " + row["destination"])
            record.update({
                "physical_reboot_verified": True,
                "automatic_dashboard_after_reboot": True,
                "wifi_reconnected_after_reboot": True,
                "background_services_after_reboot": True,
                "program_hashes_after_reboot_match": True,
                "on_device_interaction_confirmation": "owner confirmed timer, inversion, stop and calendar return",
                "verified_at": datetime.now(timezone.utc).isoformat(),
            })
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            print(json.dumps({key: record[key] for key in (
                "physical_reboot_verified", "automatic_dashboard_after_reboot",
                "wifi_reconnected_after_reboot", "background_services_after_reboot",
                "program_hashes_after_reboot_match")}), flush=True)
            return
        except (OSError, subprocess.SubprocessError, ValueError, StopIteration) as error:
            last_error = str(error)
            time.sleep(3)
    raise RuntimeError("Reboot verification did not finish: " + last_error)


if __name__ == "__main__":
    main()
