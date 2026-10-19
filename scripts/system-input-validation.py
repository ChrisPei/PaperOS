"""Real guest touch test for the shared keyboard in two independent applications."""
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def validate(directory, ssh, transport, qmp, console):
    # Observe UI transitions over serial. This avoids making fast USB gadget
    # polling part of the correctness criterion for the keyboard itself.
    def command(text):
        return console.command(text)

    def contents(path):
        marker = 'INPUT_VALUE_' + uuid.uuid4().hex[:8]
        value = command(f'printf "{marker}:"; cat {path}; printf ":{marker}"')
        return value.split(marker + ':', 1)[1].split(':' + marker, 1)[0]

    def until(command, seconds=12):
        deadline = time.monotonic() + seconds
        last = ''
        while time.monotonic() < deadline:
            try:
                return console.command(command)
            except RuntimeError as error:
                last = str(error)
            time.sleep(0.15)
        raise RuntimeError('Guest condition failed: ' + command + '\n' + last)

    def tap(x, y):
        absolute = [{'type': 'abs', 'data': {'axis': axis, 'value': value}} for axis, value in
                    (('x', x * 32767 // 599), ('y', y * 32767 // 799))]
        qmp(directory, 'input-send-event', {'events': absolute + [{'type': 'btn', 'data': {'button': 'left', 'down': True}}]})
        time.sleep(0.08)
        qmp(directory, 'input-send-event', {'events': [{'type': 'btn', 'data': {'button': 'left', 'down': False}}]})
        time.sleep(0.22)

    until('test -S /run/paperos/input.sock && pidof paperos-inputd >/dev/null && pidof paperos >/dev/null')
    hashes = ssh('sha256sum /usr/bin/paperos /usr/sbin/paperos-inputd /usr/bin/paperos-input /etc/init.d/S55paperos-input').stdout
    command('mkdir -p /var/lib/paperos/apps/.data/org.paperos.notes; printf "" > /var/lib/paperos/apps/.data/org.paperos.notes/note.txt; printf "" > /var/log/paperos-keyboard.log')
    tap(440, 400)
    until('test "$(pidof paperos | wc -w)" -eq 2')
    tap(100, 220)
    until('grep -q "PaperOS interface ready" /var/log/paperos-keyboard.log && test "$(pidof paperos | wc -w)" -eq 3')
    for x, y in ((410, 706), (438, 595), (326, 651), (45, 651), (495, 595)):
        tap(x, y)
    time.sleep(0.3)
    qmp(directory, 'screendump', {'filename': str(directory / 'system-keyboard.ppm')})
    tap(65, 544)
    tap(532, 32)
    until('test "$(pidof paperos | wc -w)" -eq 2')
    tap(450, 650)
    note = contents('/var/lib/paperos/apps/.data/org.paperos.notes/note.txt')
    if note != '你好':
        raise ValueError('Notes did not receive/save the original Chinese engine result: ' + repr(note))
    tap(300, 748)
    until('test "$(pidof paperos | wc -w)" -eq 1')
    command('/usr/bin/paperos --install /mnt/us/paperos/packages/input-demo.papp; printf "" > /var/log/paperos-keyboard.log')
    tap(90, 748)
    tap(440, 400)
    until('grep -q "PaperOS interface ready" /var/log/paperos-keyboard.log && pidof paperos-input >/dev/null')
    # This application's entry is only a Shell call to the shared input client.
    for x, y in ((129, 762), (45, 595), (298, 762), (60, 762), (45, 595), (532, 32)):
        tap(x, y)
    until('test "$(pidof paperos | wc -w)" -eq 1 && ! pidof paperos-input >/dev/null')
    value = contents('/var/lib/paperos/apps/.data/org.paperos.input-demo/text.txt')
    if value != 'q 1':
        raise ValueError('The independent Shell app did not receive the shared keyboard text: ' + repr(value))
    command('test -S /run/paperos/input.sock && pidof paperos-inputd >/dev/null')
    # Exercise USB again after the UI test, including guest-originated traffic.
    command('ping -c 1 -W 2 169.254.28.1 >/dev/null')
    return {'system_keyboard_service_started_at_boot': True,
            'notes_received_and_saved_original_chinese_input': True,
            'independent_shell_application_used_same_keyboard': True,
            'keyboard_closed_and_launcher_reacquired_touch': True,
            'program_sha256': {line.split()[1]: line.split()[0] for line in hashes.splitlines()},
            'default_input_service_sha256': {line.split()[1]: line.split()[0] for line in hashes.splitlines()}['/etc/init.d/S55paperos-input']}
