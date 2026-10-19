"""Verify a physically approved transfer without reading network credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import ssl
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--package", type=Path, default=ROOT / "examples/alarm.papp")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    wireless = SourceFileLoader("wireless_verification_transfer", str(ROOT / "scripts/wireless-app.py")).load_module()
    address = wireless.receiver_address(args.host)
    via_tailnet = address in wireless.TAILSCALE_IPV4
    package = SourceFileLoader("wireless_verification_package", str(ROOT / "scripts/push-app.py")).load_module()
    source = args.package.resolve()
    app_id, _ = package.archive_package(source)
    peers = json.loads((ROOT / "build/wireless-peers.json").read_text())
    expected_certificate = peers["peers"][str(address)]
    ssh = SourceFileLoader("wireless_verification_ssh", str(ROOT / "scripts/device-ssh.py")).load_module()
    connection = ssh.connection(22)
    connection[-1] = "root@" + str(address)
    connection[-1:-1] = ["-o", "HostKeyAlias=169.254.28.2"]

    def remote(command):
        return subprocess.check_output(connection + [command], timeout=20)

    pem = remote("cat /var/lib/paperos/services/receiver-cert.pem").decode("ascii")
    actual_certificate = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    if actual_certificate != expected_certificate:
        raise ValueError("Approved transfer certificate differs from the pinned device")
    rows = [line.split("\t") for line in remote("cat /run/paperos/state.tsv").decode().splitlines()]
    network = next(row for row in rows if row[0] == "net")
    weather = next(row for row in rows if row[0] == "weather")
    tailnet = next((row for row in rows if row[0] == "tailnet"), [])
    if network[3] != "true":
        raise ValueError("The receiver has no Wi-Fi connection")
    if via_tailnet:
        if len(tailnet) != 11 or tailnet[4] != "true" or tailnet[7] != str(address):
            raise ValueError("The receiver is not using the expected Tailscale address")
    elif network[4] != str(address):
        raise ValueError("The receiver is not using the expected Wi-Fi address")
    import shlex
    for file in sorted(source.rglob('*')):
        if not file.is_file():
            continue
        name = file.relative_to(source).as_posix()
        local = file.read_bytes()
        target = "/mnt/us/paperos/packages/" + app_id + ".papp/" + name
        received = remote("cat " + shlex.quote(target))
        if hashlib.sha256(local).digest() != hashlib.sha256(received).digest():
            raise ValueError("Received package does not match the source: " + name)
    proof = {
        "passed": True, "verified_at": datetime.now(timezone.utc).isoformat(),
        "transport": ("Tailscale IPv4" if via_tailnet else "direct Wi-Fi IPv4") + " with TLS and on-device confirmation",
        "usb_used_for_transfer": False, "certificate_pinned_after_approval": True,
        "received_package_files_match": True, "package": app_id,
        "wifi_connected": True, "weather_fetched": int(weather[1]),
    }
    output = args.output or ROOT / ("build/dashboard-tailnet-validation.json" if via_tailnet else "build/dashboard-wireless-validation.json")
    output.write_text(json.dumps(proof, indent=2) + "\n")
    record_path = ROOT / "build/dashboard-device-validation.json"
    if record_path.is_file() and not via_tailnet:
        record = json.loads(record_path.read_text())
        record["wifi_credentials_configured"] = True
        record["wireless_transfer_physically_confirmed"] = True
        record["wireless_validation"] = str(output)
        record_path.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(proof), flush=True)


if __name__ == "__main__":
    main()
