"""Real KT3-kernel, framebuffer, touch, input, timer and TLS admission tests."""
from concurrent.futures import ThreadPoolExecutor
from importlib.machinery import SourceFileLoader
import json
from pathlib import Path
import time
from PIL import Image

ROOT = Path('/mnt/d/kindle')


def validate(directory, ssh, qmp, console, tls_port):
    def command(value):
        return console.command(value)

    def until(value, timeout=15):
        deadline = time.monotonic() + timeout
        error = ''
        while time.monotonic() < deadline:
            try:
                return command(value)
            except RuntimeError as exc:
                error = str(exc)
                time.sleep(.15)
        raise RuntimeError(value + '\n' + error)

    def tap(x, y):
        events = [{'type': 'abs', 'data': {'axis': axis, 'value': value}} for axis, value in
                  (('x', x * 32767 // 599), ('y', y * 32767 // 799))]
        qmp(directory, 'input-send-event', {'events': events + [{'type': 'btn', 'data': {'button': 'left', 'down': True}}]})
        time.sleep(.09)
        qmp(directory, 'input-send-event', {'events': [{'type': 'btn', 'data': {'button': 'left', 'down': False}}]})
        time.sleep(.3)

    def capture(name):
        target = directory / (name + '.ppm')
        qmp(directory, 'screendump', {'filename': str(target)})
        with Image.open(target) as image:
            image.save(directory / (name + '.png'))
        return target

    def config():
        return json.loads(ssh('cat /var/lib/paperos/services/state.json').stdout)

    until('test -S /run/paperos/services.sock && pidof paperos-services >/dev/null && test -S /run/paperos/input.sock')
    hashes = ssh('sha256sum /usr/bin/paperos /usr/sbin/paperos-services /etc/init.d/S60paperos-services /etc/init.d/S45paperos-wifi /usr/sbin/paperos-services-monitor').stdout
    capture('dashboard-home')
    tap(140, 124)
    until('test "$(pidof paperos | wc -w)" -eq 2')
    capture('dashboard-alarm')
    tap(480, 165)
    capture('dashboard-time-settings')
    tap(60, 72)  # cancel time settings without altering the guest RTC
    tap(240, 600)
    tap(250, 565)
    until('test "$(pidof paperos | wc -w)" -eq 3 && grep -q "PaperOS interface ready" /var/log/paperos-keyboard.log')
    for x, y in ((410, 706), (438, 595), (326, 651), (45, 651), (495, 595)):
        tap(x, y)
    tap(65, 544)
    capture('dashboard-keyboard-before-reminder')
    command('/usr/sbin/paperos-services ctl timer-start seconds 3')
    until("grep -q '^alert' /run/paperos/state.tsv")
    phase_one = capture('dashboard-reminder-phase-one')
    first_pixel = Image.open(phase_one).convert('L').getpixel((8, 8))
    changed = False
    for index in range(12):
        time.sleep(.45)
        phase = capture('dashboard-reminder-phase-two')
        other = Image.open(phase).convert('L').getpixel((8, 8))
        if abs(first_pixel - other) > 200:
            changed = True
            break
    if not changed:
        raise ValueError('The real framebuffer did not alternate black and white')
    tap(120, 665)
    until('test "$(pidof paperos | wc -w)" -eq 3')
    capture('dashboard-keyboard-after-reminder')
    tap(530, 32)
    until('test "$(pidof paperos | wc -w)" -eq 2')
    tap(155, 655)
    state = config()
    if not state['Alarms'] or not state['Alarms'][0]['Label'].endswith('你好'):
        raise ValueError('Chinese input was not preserved across the full-screen reminder')
    tap(530, 363)
    if config()['Alarms'][0]['Enabled']:
        raise ValueError('Alarm toggle did not disable the new alarm')
    tap(300, 751)
    until('test "$(pidof paperos | wc -w)" -eq 1')
    command('/usr/sbin/paperos-services ctl timer-start seconds 3')
    tap(450, 120)
    until('test "$(pidof paperos | wc -w)" -eq 2')
    until("grep -q '^alert' /run/paperos/state.tsv")
    capture('dashboard-calendar-interrupted')
    tap(450, 665)
    state = config()
    if state['Active'] is not None or state['Snooze']['State'] != 'running' or state['Snooze']['Duration'] != 300:
        raise ValueError('Snooze did not preserve the scheduled reminder')
    capture('dashboard-calendar-returned')
    tap(300, 751)
    until('test "$(pidof paperos | wc -w)" -eq 1')
    command('/usr/sbin/paperos-services ctl alarm-disarm')
    command('/usr/sbin/paperos-services ctl timer-start seconds 30; PAPEROS_PREVIOUS_SERVICE=$(pidof paperos-services); kill -KILL "$PAPEROS_PREVIOUS_SERVICE"; sleep 3')
    until('test -S /run/paperos/services.sock && pidof paperos-services >/dev/null')
    if config()['Timer']['State'] != 'running':
        raise ValueError('Watchdog restart did not restore the running countdown')
    command('/usr/sbin/paperos-services ctl alarm-disarm')

    # A simulated USB LAN exercises the real ARM TLS receiver without pretending
    # that QEMU emulates the physical Broadcom wireless radio.
    command('/etc/init.d/S60paperos-services stop')
    command('( /usr/sbin/paperos-services --simulate --simulate-ip 169.254.28.2 </dev/null >/var/log/paperos-services-test.log 2>&1 & )')
    until('test -S /run/paperos/services.sock && pidof paperos-services >/dev/null')
    command('/usr/sbin/paperos-services ctl receive-enable enabled true')
    until("netstat -lnt | grep -q ':8765'")
    source = directory / 'wireless-test.papp'
    source.mkdir()
    (source / 'manifest.conf').write_text('id=org.paperos.wireless-test\nname=无线测试\nversion=1.0\nexec=run.sh\n')
    (source / 'run.sh').write_text('#!/bin/sh\nexit 0\n')
    sender = SourceFileLoader('paperos_sender_test', str(ROOT / 'scripts/wireless-app.py')).load_module()
    sender.PEERS = directory / 'sender-peers.json'
    with ThreadPoolExecutor(max_workers=1) as worker:
        attempt = worker.submit(sender.transfer, source, '127.0.0.1', 50, tls_port)
        until("grep -q '^transfer' /run/paperos/state.tsv", 25)
        capture('dashboard-receive-confirmation')
        command('test ! -e /mnt/us/paperos/packages/org.paperos.wireless-test.papp')
        tap(110, 665)
        try:
            attempt.result(timeout=12)
            raise ValueError('Rejected sender reported success')
        except RuntimeError:
            pass
        command('test ! -e /mnt/us/paperos/packages/org.paperos.wireless-test.papp')
        attempt = worker.submit(sender.transfer, source, '127.0.0.1', 50, tls_port)
        until("grep -q '^transfer' /run/paperos/state.tsv", 25)
        tap(450, 665)
        attempt.result(timeout=15)
    command('test -f /mnt/us/paperos/packages/org.paperos.wireless-test.papp/manifest.conf && test ! -e /var/lib/paperos/apps/org.paperos.wireless-test')
    tap(300, 760)
    tap(440, 190)
    tap(200, 260)
    tap(150, 375)
    command('test -f /var/lib/paperos/apps/org.paperos.wireless-test/run.sh')
    capture('dashboard-received-package-installed')
    command('/usr/sbin/paperos-services ctl receive-enable enabled false; /usr/sbin/paperos-services ctl network-enable enabled false')
    command('PAPEROS_TEST_PID=$(pidof paperos-services); kill "$PAPEROS_TEST_PID"; sleep 1; /etc/init.d/S60paperos-services start')
    until('test -S /run/paperos/services.sock && test "$(pidof paperos-services | wc -w)" -eq 1')
    return {
        'services_started_on_kt3_kernel': True,
        'watchdog_restores_service_and_countdown': True,
        'clock_widget_launches_independent_alarm_app': True,
        'time_settings_can_be_cancelled': True,
        'system_keyboard_preserved_chinese_during_timer_interrupt': True,
        'full_screen_black_white_alternation': True,
        'timer_continues_after_switching_to_calendar': True,
        'stop_and_snooze_restore_previous_application': True,
        'encrypted_wireless_transfer_requires_touch_approval': True,
        'rejection_does_not_admit_package': True,
        'approved_bundle_installs_through_app_library': True,
        'wifi_radio_hardware_verified': False,
        'program_sha256': {line.split()[1]: line.split()[0] for line in hashes.splitlines()},
    }
