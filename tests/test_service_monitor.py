"""A resumed network daemon must not retain the service monitor's flock."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ServiceMonitorTests(unittest.TestCase):
    def test_child_daemon_does_not_hold_monitor_lock_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'run').mkdir()
            backend = work / 'backend'
            backend.write_text('#!/bin/sh\nsleep 30 &\nprintf "%s\\n" "$!" > "' + str(work / 'daemon.pid')
                               + '"\nif [ -e /proc/self/fd/8 ]; then echo inherited; else echo closed; fi > "'
                               + str(work / 'descriptor') + '"\n')
            backend.chmod(0o755)
            monitor = work / 'monitor'
            source = (ROOT / 'os/rootfs-overlay/usr/sbin/paperos-services-monitor').read_text()
            monitor.write_text(source.replace('/run/paperos', str(work / 'run'))
                               .replace('/usr/sbin/paperos-services', str(backend)))
            process = subprocess.Popen(['/bin/sh', str(monitor)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if (work / 'descriptor').exists():
                        break
                    if process.poll() is not None:
                        self.fail(process.stderr.read().decode())
                    time.sleep(.01)
                self.assertEqual((work / 'descriptor').read_text().strip(), 'closed')
                with (work / 'run/services-monitor.lock').open('r') as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    process.terminate()
                    process.wait(timeout=5)
                    daemon = int((work / 'daemon.pid').read_text())
                    os.kill(daemon, 0)
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stderr.close()
                if (work / 'daemon.pid').exists():
                    try:
                        os.kill(int((work / 'daemon.pid').read_text()), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
