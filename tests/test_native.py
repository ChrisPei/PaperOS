"""Exercise the real C executable: HTTP status input, offline cache, touch and notes."""
import importlib.util
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("native_test_bridge", ROOT / "bridge/bridge.py")
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.note = self.directory / "note.txt"
    def tearDown(self):
        self.temp.cleanup()
    def render(self, *args, arm=False, token="", expected=0, ime=None):
        output = self.directory / ("arm.pgm" if arm else "host.pgm")
        binary = Path(os.environ.get("PAPEROS_TEST_ARM", str(ROOT / "dist/paperos-kt3"))) if arm else ROOT / "build/host/paperos"
        command = (["qemu-arm-static"] if arm else []) + [str(binary), "--font", str(ROOT / "assets/NotoSansCJKsc-Regular.otf"), "--render", str(output), "--note", str(self.note), *args]
        env = {**os.environ, "TZ": "CST-8", "PAPEROS_BRIDGE_TOKEN": token}
        if ime is not None:
            env['PAPEROS_IME_HELPER'] = str(ime)
        result = subprocess.run(command, env=env, capture_output=True, timeout=12)
        self.assertEqual(result.returncode, expected, result.stderr.decode(errors="replace"))
        return output.read_bytes() if expected == 0 else result.stderr

    def test_notes_preserve_unicode_and_save_when_input_service_unavailable(self):
        self.note.write_text("你好", encoding="utf-8")
        self.render("--screen", "notes", "--tap", "100", "650", "--tap", "450", "650")
        self.assertEqual(self.note.read_text(encoding="utf-8"), "你好")
        self.assertEqual(list(self.directory.glob("note.txt.tmp.*")), [])
        reloaded = self.render("--screen", "notes")
        self.assertTrue(reloaded.startswith(b"P5\n600 800\n255\n"))

    def test_authenticated_http_feed_matches_file_and_preserves_offline_cache(self):
        registry = bridge.Registry()
        registry.put(bridge.Agent("one", "Cowork", "会议记录", "waiting", 100))
        # Preserve the test state even though the fixture timestamp is old.
        registry.ttl = 10**12
        token = "native-integration-test"
        server = ThreadingHTTPServer(("127.0.0.1", 0), bridge.make_handler(registry, token, True))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            feed = self.directory / "agents.tsv"
            feed.write_bytes(bridge.tsv(registry.snapshot()))
            from_file = self.render("--screen", "agents", "--feed", str(feed))
            online = self.render("--screen", "agents", "--url", f"http://127.0.0.1:{server.server_port}/v1/agents.tsv", token=token)
            self.assertEqual(online, from_file)
            denied_with_cache = self.render("--screen", "agents", "--feed", str(feed), "--url", f"http://127.0.0.1:{server.server_port}/v1/agents.tsv", token="wrong")
            denied_empty = self.render("--screen", "agents", "--url", f"http://127.0.0.1:{server.server_port}/v1/agents.tsv", token="wrong")
            self.assertNotEqual(denied_with_cache, denied_empty)
            self.assertNotEqual(denied_with_cache, online)
        finally:
            server.shutdown(); server.server_close(); worker.join()

    def test_truncated_invalid_and_oversized_feeds_are_rejected(self):
        feed = self.directory / "bad.tsv"
        for content in ["paperos-v1\t0\t1\n", "paperos-v1\t0\t0junk\n", "paperos-v1\t0\t1\none\tCodex\tTask\tbogus\t0\n", "paperos-v1\t0\t48\n" + "one\tCodex\tTask\tunknown\t0\n"*49]:
            with self.subTest(content=content[:50]):
                feed.write_text(content)
                self.assertIn(b"Invalid agent feed", self.render("--screen", "agents", "--feed", str(feed), expected=2))

    def test_arm_build_renders_the_same_app_as_host(self):
        fixture = str(ROOT / "tests/fixtures/agents.tsv")
        host = self.render("--screen", "agents", "--feed", fixture)
        arm = self.render("--screen", "agents", "--feed", fixture, arm=True)
        self.assertEqual(host, arm)

    def test_uninstalling_alarm_provider_removes_its_home_widget(self):
        installed = self.directory / 'apps'
        packages = self.directory / 'packages'
        packages.mkdir()
        shutil.copytree(ROOT / 'examples/alarm.papp', packages / 'alarm.papp')
        flags = ('--app-root', str(installed), '--packages', str(packages))
        before = self.render(*flags)
        self.render(*flags, '--tap', '300', '760', '--tap', '440', '190', '--tap', '200', '260', '--tap', '160', '375', '--tap', '80', '760')
        populated = self.render(*flags)
        self.assertTrue(before != populated, 'Installing a provider must add its home widget')
        self.assertTrue((installed / 'org.paperos.alarm/run.sh').is_file())
        self.render(*flags, '--tap', '300', '760', '--tap', '200', '260', '--tap', '450', '375', '--tap', '450', '375', '--tap', '80', '760')
        after = self.render(*flags)
        self.assertFalse((installed / 'org.paperos.alarm').exists())
        self.assertTrue(before == after, 'An uninstalled provider must leave no widget behind')

    def test_notes_do_not_start_a_private_input_engine(self):
        helper = self.directory / 'unexpected-ime'
        marker = self.directory / 'engine-started'
        helper.write_text(f'#!/bin/sh\ntouch {marker}\nexit 1\n')
        helper.chmod(0o755)
        self.render('--screen', 'notes', ime=helper)
        self.assertFalse(marker.exists())

    def test_live_validation_arguments_reject_invalid_or_render_only_runs(self):
        for value in ("0", "601", "-1", "12junk"):
            with self.subTest(value=value):
                self.assertIn(b"Invalid run duration", self.render("--run-seconds", value, expected=2))
        self.assertIn(b"Live validation options", self.render("--run-seconds", "120", expected=2))

if __name__ == "__main__":
    unittest.main()
