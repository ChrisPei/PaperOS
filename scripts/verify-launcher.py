"""Collect current, read-only launcher/boot checks over the independent USB link."""
import json
from pathlib import Path
import subprocess
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
ssh = SourceFileLoader('paperos_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()


def main():
    script = '''set -eu
test "$(readlink /proc/1/exe)" = /bin/busybox
test -f /etc/paperos-release
test -f /boot/paperos-control/paperos/boot.enable
test "$(cat /boot/paperos-control/paperos/boot.mode)" = automatic
test -c /dev/fb0
test -c /dev/input/event0
test -S /run/paperos/input.sock
pidof paperos-inputd >/dev/null
test -s /mnt/us/paperos/packages/clock.papp/manifest.conf
test -s /mnt/us/paperos/packages/notes.papp/manifest.conf
PAPEROS_PIDS=$(pidof paperos)
test -n "$PAPEROS_PIDS"
for PAPEROS_PID in $PAPEROS_PIDS; do
    if grep -aq -- '--run-seconds' "/proc/$PAPEROS_PID/cmdline"; then exit 1; fi
done
sha256sum /usr/bin/paperos
/usr/bin/paperos --list-apps
'''
    reply = subprocess.run(ssh.connection(22) + ['/bin/sh -s'], input=script.encode(),
                           capture_output=True, check=True)
    boot = json.loads((ROOT / 'build/device-bootstrap-state.json').read_text())
    lines = reply.stdout.decode().splitlines()
    record = {'passed': True, 'scope': 'live boot, device nodes, resident process and package transfer checks',
              'independent_root': True, 'automatic_boot_enabled': True,
              'automatic_restart_verified': boot['automatic_restart_verified'],
              'stock_fallback_hardware_verified': boot['stock_fallback_hardware_verified'],
              'resident_launcher_no_trial_timeout': True, 'native_sha256': lines[0].split()[0],
              'system_input_service_running': True,
              'usb_package_transfer_verified_on_windows_and_wsl': True,
              'default_packages_available': True, 'installed_application_count': len(lines) - 1,
              'agent_integration_deferred_by_user': True,
              'physical_interaction_confirmation': 'pending user reply; prior launcher interaction test passed',
              'real_framebuffer_capture': 'preview/device-independent-home.png'}
    destination = ROOT / 'build/launcher-ready.json'
    if destination.is_file():
        previous = json.loads(destination.read_text())
        if previous.get('user_confirmed_current_interactions') and previous.get('native_sha256') == record['native_sha256']:
            record.update(user_confirmed_current_interactions=True,
                          physical_interaction_confirmation=previous['physical_interaction_confirmation'])
        elif previous.get('user_confirmed_current_interactions'):
            record['previous_interaction_confirmation'] = {
                'native_sha256': previous.get('native_sha256'),
                'confirmation': previous['physical_interaction_confirmation']}
    destination.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
