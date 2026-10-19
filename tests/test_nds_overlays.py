"""Regression: the standalone DS screen must dispatch system alert controls.

Executes the real ARM UI under QEMU without loading a ROM/JIT, against an
isolated real PaperOS backend. Actual game rendering is a physical-device gate.
"""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]


class NDSOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.state = self.directory / 'run/state.tsv'
        self.channel = self.directory / 'run/services.sock'
        self.service = subprocess.Popen([
            str(ROOT / 'build/host/paperos-services'), '--simulate',
            '--root', str(self.directory / 'data'), '--run-dir', str(self.directory / 'run'),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.state.exists() and self.channel.exists():
                break
            if self.service.poll() is not None:
                self.fail('isolated backend exited')
            time.sleep(.025)
        self.assertTrue(self.channel.exists())

    def tearDown(self):
        self.service.terminate()
        self.service.wait(timeout=5)
        self.temporary.cleanup()

    def command(self, name, **values):
        body = urlencode({'cmd': name, **values}).encode()
        with socket.socket(socket.AF_UNIX) as channel:
            channel.settimeout(4)
            channel.connect(str(self.channel))
            channel.sendall(b'POST /command HTTP/1.0\r\nHost: paperos\r\n'
                            b'Content-Type: application/x-www-form-urlencoded\r\nContent-Length: '
                            + str(len(body)).encode() + b'\r\n\r\n' + body)
            reply = b''
            while block := channel.recv(4096):
                reply += block
        self.assertIn(b' 200 ', reply.split(b'\r\n', 1)[0])

    def reminder(self):
        self.command('timer-start', seconds='1')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if '\nalert\t' in self.state.read_text():
                return
            time.sleep(.025)
        self.fail('countdown did not deliver its reminder')

    def tap(self, x):
        output = self.directory / 'nds.pgm'
        result = subprocess.run([
            'qemu-arm-static', str(ROOT / 'build/nds/player/paperos-nds'),
            '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'),
            '--nds-rom', str(self.directory / 'not-imported.nds'),
            '--nds-data', str(self.directory / 'game-data'), '--standalone',
            '--services-file', str(self.state), '--services-socket', str(self.channel),
            '--render', str(output), '--allow-commands', '--tap', str(x), '665',
        ], capture_output=True, env={**os.environ, 'TZ': 'CST-8'}, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertTrue(output.read_bytes().startswith(b'P5\n600 800\n255\n'))

    def test_stop_alert_from_game_preserves_lock(self):
        self.command('lock-now')
        self.reminder()
        self.tap(120)
        state = self.state.read_text()
        self.assertNotIn('\nalert\t', state)
        self.assertIn('\nlock\ttrue\t', state)

    def test_snooze_alert_from_game_preserves_unlocked_state(self):
        self.reminder()
        self.tap(450)
        state = self.state.read_text()
        self.assertNotIn('\nalert\t', state)
        self.assertIn('\nlock\tfalse\t', state)


if __name__ == '__main__':
    unittest.main()
