"""Receiver address policy: LAN and Tailscale CGNAT, with public targets rejected."""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
wireless = SourceFileLoader('wireless_address_tests', str(ROOT / 'scripts/wireless-app.py')).load_module()


class WirelessAddressTests(unittest.TestCase):
    def test_lan_loopback_and_tailnet_ipv4(self):
        for address in ('192.168.50.2', '10.0.0.2', '172.16.0.2', '127.0.0.1', '100.64.0.1', '100.127.255.254'):
            with self.subTest(address=address):
                self.assertEqual(str(wireless.receiver_address(address)), address)

    def test_public_outside_tailnet_and_unsafe_targets_rejected(self):
        for address in ('8.8.8.8', '1.1.1.1', '100.63.255.255', '100.128.0.1', '0.0.0.0', '224.0.0.1', '::1', 'example.com'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                wireless.receiver_address(address)


if __name__ == '__main__':
    unittest.main()
