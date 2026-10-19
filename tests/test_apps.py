"""Package transactions, process supervision and invalid-package boundaries."""
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / 'build/host/paperos'


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.apps = self.directory / 'apps'
        self.package = self.directory / 'example.papp'
        self.package.mkdir()
        self.write_package()

    def tearDown(self):
        self.temporary.cleanup()

    def write_package(self, version='1', body='exit 0\n'):
        (self.package / 'manifest.conf').write_text(
            f'id=org.paperos.example\nname=示例应用\nversion={version}\nexec=run.sh\ndescription=集成测试\n', encoding='utf-8')
        (self.package / 'run.sh').write_text('#!/bin/sh\n' + body)
        (self.package / 'run.sh').chmod(0o644)

    def call(self, *args, expected=0):
        result = subprocess.run([str(BINARY), '--app-root', str(self.apps), *args], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stderr.decode(errors='replace'))
        return result.stdout.decode('utf-8')

    def test_install_update_launch_and_remove_preserve_app_data(self):
        self.write_package(body='printf "%s" "$PAPEROS_APP_ID" > "$PAPEROS_DATA_DIR/id"\nexit 0\n')
        self.call('--install', str(self.package))
        self.assertEqual(self.call('--list-apps'), 'org.paperos.example\t示例应用\t1\n')
        self.call('--run-app', 'org.paperos.example')
        data = self.apps / '.data/org.paperos.example/id'
        self.assertEqual(data.read_text(), 'org.paperos.example')
        self.write_package(version='2', body='exit 17\n')
        self.call('--install', str(self.package))
        self.assertIn('\t2\n', self.call('--list-apps'))
        self.call('--run-app', 'org.paperos.example', expected=17)
        self.call('--remove', 'org.paperos.example')
        self.assertEqual(self.call('--list-apps'), '')
        self.assertEqual(data.read_text(), 'org.paperos.example')

    def test_invalid_update_cannot_escape_package_or_replace_old_app(self):
        self.call('--install', str(self.package))
        outside = self.directory / 'outside'
        outside.write_text('untouched')
        (self.package / 'escape').symlink_to(outside)
        self.write_package(version='2')
        self.call('--install', str(self.package), expected=2)
        self.assertIn('\t1\n', self.call('--list-apps'))
        self.assertEqual(outside.read_text(), 'untouched')
        self.assertEqual(list(self.apps.glob('.install-*')), [])
        self.call('--remove', '../outside', expected=2)
        self.assertTrue(outside.exists())

    def test_manifest_rejects_traversal_duplicate_keys_and_binary_data(self):
        original = (self.package / 'manifest.conf').read_bytes()
        for manifest in (original.replace(b'exec=run.sh', b'exec=../run.sh'),
                         original.replace(b'id=org.paperos.example', b'id=../outside'),
                         original + b'id=another\n', original + b'\0binary'):
            with self.subTest(manifest=manifest[:50]):
                (self.package / 'manifest.conf').write_bytes(manifest)
                self.call('--install', str(self.package), expected=2)
                self.assertEqual(self.call('--list-apps'), '')

    def test_running_application_blocks_replacement_and_parent_stops_child(self):
        self.write_package(body='printf ready > "$PAPEROS_DATA_DIR/ready"\nsleep 20\n')
        self.call('--install', str(self.package))
        process = subprocess.Popen([str(BINARY), '--app-root', str(self.apps), '--run-app', 'org.paperos.example'])
        try:
            marker = self.apps / '.data/org.paperos.example/ready'
            deadline = time.monotonic() + 3
            while not marker.exists() and time.monotonic() < deadline:
                self.assertIsNone(process.poll())
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            self.call('--remove', 'org.paperos.example', expected=2)
            self.call('--install', str(self.package), expected=2)
            process.terminate()
            self.assertEqual(process.wait(timeout=4), 143)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


if __name__ == '__main__':
    unittest.main()
