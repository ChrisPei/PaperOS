"""System input IPC, actual keyboard renderer, and two independent clients."""
import os
from pathlib import Path
import shlex
import socket
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'build/host'
MAGIC = 0x50494d31


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='paperos-input-')
        self.directory = Path(self.temporary.name)
        self.path = self.directory / 'input.sock'
        self.service = None
        self.initial = self.directory / 'note.txt'
        self.initial.write_text('你好', encoding='utf-8')
        self.output = self.directory / 'result.txt'
        self.environment = {**os.environ, 'PAPEROS_INPUT_SOCKET': str(self.path), 'PAPEROS_IME_HELPER': ''}

    def tearDown(self):
        if self.service:
            self.service.terminate()
            try:
                self.service.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                self.service.kill()
                self.service.communicate()
        self.temporary.cleanup()

    def keyboard(self, taps, helper=None):
        ui = self.directory / 'keyboard'
        command = [str(BIN / 'paperos'), '"$@"', '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'),
                   '--render', str(self.directory / 'keyboard.pgm')]
        script = '#!/bin/sh\nexec ' + shlex.quote(command[0]) + ' "$@" ' + shlex.join(command[2:])
        for x, y in taps:
            script += f' --tap {x} {y}'
        ui.write_text(script + '\n')
        ui.chmod(0o755)
        self.start(ui, helper)

    def start(self, ui, helper=None):
        env = {**self.environment, 'PAPEROS_IME_HELPER': str(helper) if helper else ''}
        self.service = subprocess.Popen([str(BIN / 'paperos-inputd'), '--socket', str(self.path), '--ui', str(ui)],
                                        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 3
        while not self.path.exists() and time.monotonic() < deadline:
            if self.service.poll() is not None:
                self.fail(self.service.communicate()[1].decode())
            time.sleep(0.01)
        self.assertTrue(self.path.exists())

    def cli(self, *args, expected=0):
        result = subprocess.run([str(BIN / 'paperos-input'), *args], env=self.environment,
                                capture_output=True, timeout=8)
        self.assertEqual(result.returncode, expected, result.stderr.decode(errors='replace'))
        return result

    def connect(self, text='', flags=1):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(4)
        client.connect(str(self.path))
        title = '测试输入'.encode()
        value = text.encode()
        client.sendall(struct.pack('!5I', MAGIC, flags, 2047, len(title), len(value)) + title + value)
        return client

    def test_unicode_cursor_edit_and_cli_atomic_save(self):
        self.keyboard([(537, 706), (45, 595), (298, 762), (532, 32)])
        self.cli('--multiline', '--english', '--text-file', str(self.initial), '--output', str(self.output))
        self.assertEqual(self.output.read_text(), '你q ')
        self.assertEqual(list(self.directory.glob('result.txt.input-*')), [])
        self.assertTrue((self.directory / 'keyboard.pgm').read_bytes().startswith(b'P5\n600 800\n255\n'))

    def test_notes_calls_the_same_system_keyboard_service(self):
        self.keyboard([(537, 706), (45, 595), (298, 762), (532, 32)])
        reply = subprocess.run([str(BIN / 'paperos'), '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'),
                                '--screen', 'notes', '--note', str(self.initial), '--tap', '100', '650',
                                '--tap', '450', '650', '--render', str(self.directory / 'notes.pgm')],
                               env=self.environment, capture_output=True, timeout=8)
        self.assertEqual(reply.returncode, 0, reply.stderr.decode())
        self.assertEqual(self.initial.read_text(), '你q ')

    def test_cancel_does_not_replace_original_text_or_file(self):
        self.keyboard([(45, 595), (56, 32)])
        self.cli('--english', '--text-file', str(self.initial), '--output', str(self.initial), expected=1)
        self.assertEqual(self.initial.read_text(), '你好')

    def test_password_never_starts_predictor_and_supports_symbols_and_uppercase(self):
        marker = self.directory / 'predictor-started'
        helper = self.directory / 'forbidden-predictor'
        helper.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(marker)) + '\nexit 1\n')
        helper.chmod(0o755)
        self.keyboard([(129, 762), (60, 762), (45, 595), (382, 651),
                       (60, 706), (214, 595), (60, 762), (60, 706), (45, 651), (532, 32)], helper)
        self.cli('--password', '--output', str(self.output))
        self.assertEqual(self.output.read_text(), '1$}A')
        self.assertFalse(marker.exists())

    def test_stalled_predictor_falls_back_and_is_reaped(self):
        pidfile = self.directory / 'predictor.pid'
        helper = self.directory / 'stalled-predictor'
        helper.write_text(f'#!/usr/bin/python3\nimport os,sys,time\nopen({str(pidfile)!r},"w").write(str(os.getpid()))\nsys.stdin.readline()\ntime.sleep(30)\n')
        helper.chmod(0o755)
        self.keyboard([(45, 595), (532, 32)], helper)
        started = time.monotonic()
        self.cli('--output', str(self.output))
        self.assertLess(time.monotonic() - started, 4)
        self.assertEqual(self.output.read_text(), 'q')
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_predictor_failure_preserves_pending_text_order(self):
        helper = self.directory / 'predictor-fails-after-open'
        helper.write_text('#!/usr/bin/python3\nimport sys,time\nsys.stdin.readline()\nprint("paperos-ime-v1\\t0",flush=True)\nsys.stdin.readline()\ntime.sleep(30)\n')
        helper.chmod(0o755)
        self.keyboard([(45, 651), (45, 595), (532, 32)], helper)
        self.cli('--output', str(self.output))
        self.assertEqual(self.output.read_text(), 'aq')

    def test_only_one_session_and_disconnect_ends_keyboard_process(self):
        pidfile = self.directory / 'worker.pid'
        ui = self.directory / 'waiting-keyboard'
        ui.write_text(f'#!/usr/bin/python3\nimport os,time\nopen({str(pidfile)!r},"w").write(str(os.getpid()))\ntime.sleep(30)\n')
        ui.chmod(0o755)
        self.start(ui)
        first = self.connect()
        try:
            deadline = time.monotonic() + 3
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            with self.connect() as second:
                response = second.recv(12)
                self.assertEqual(struct.unpack('!3I', response), (MAGIC, 2, 0))
        finally:
            first.close()
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            self.fail('The disconnected keyboard worker was not reaped')

    def test_keyboard_failure_preserves_text_and_service_keeps_running(self):
        ui = self.directory / 'failed-keyboard'
        ui.write_text('#!/bin/sh\nexit 7\n')
        ui.chmod(0o755)
        self.start(ui)
        self.cli('--text-file', str(self.initial), '--output', str(self.initial), expected=2)
        self.assertEqual(self.initial.read_text(), '你好')
        self.assertIsNone(self.service.poll())

    def test_unavailable_service_preserves_original_file(self):
        self.cli('--text-file', str(self.initial), '--output', str(self.initial), expected=2)
        self.assertEqual(self.initial.read_text(), '你好')

    def test_original_key_positions_type_all_letters_without_hitting_controls(self):
        # Centers measured from the public KT3 portrait keymap, not the C layout.
        first = [(x, 595) for x in (45, 101, 157, 214, 270, 326, 382, 438, 495, 551)]
        second = [(x, 651) for x in (45, 101, 157, 214, 270, 326, 382, 438, 495)]
        third = [(x, 706) for x in (129, 185, 241, 298, 354, 410, 466)]
        self.keyboard(first + second + third + [(551, 651), (532, 32)])
        result = self.cli('--english')
        self.assertEqual(result.stdout.decode(), 'qwertyuiopasdfghjklzxcvbnm:')

    def test_return_key_inserts_newline_in_multiline_editor(self):
        self.keyboard([(45, 595), (537, 762), (45, 651), (532, 32)])
        self.assertEqual(self.cli('--english', '--multiline').stdout, b'q\na')

    def test_return_key_accepts_single_line_input(self):
        self.keyboard([(45, 595), (537, 762)])
        self.assertEqual(self.cli('--english').stdout, b'q')

    @unittest.skipUnless(os.environ.get('PAPEROS_TEST_ORIGINAL_IME'), 'Original firmware input fixture not selected')
    def test_original_chinese_engine_through_system_keyboard(self):
        self.keyboard([(410, 706), (438, 595), (326, 651), (45, 651), (495, 595),
                       (65, 544), (410, 762), (466, 762), (532, 32)], os.environ['PAPEROS_TEST_ORIGINAL_IME'])
        self.cli('--multiline', '--output', str(self.output))
        self.assertEqual(self.output.read_text(), '你好，。')


if __name__ == '__main__':
    unittest.main()
