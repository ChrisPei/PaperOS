import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('paperos_home_setup', ROOT / 'scripts/connect-mihome.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

class HomeSetupTests(unittest.TestCase):
    def test_selects_display_metrics_and_excludes_person_locations(self):
        states = [
            {'entity_id': 'sensor.room', 'state': '22.1', 'attributes': {'device_class': 'temperature', 'unit_of_measurement': '°C'}},
            {'entity_id': 'light.room', 'state': 'off'},
            {'entity_id': 'device_tracker.phone', 'state': 'home', 'attributes': {'latitude': 1}},
            {'entity_id': 'person.someone', 'state': 'home'},
            {'entity_id': 'sensor.invalid', 'state': 'NaN', 'attributes': {'unit_of_measurement': 'W'}},
        ]
        result = setup.home_candidates(states)
        self.assertEqual([item['Entity'] for item in result], ['sensor.room', 'light.room'])
        self.assertEqual([item['Kind'] for item in result], ['temperature', 'state'])

    def test_rejects_credentials_embedded_in_server_url(self):
        for value in ('file:///etc/passwd', 'http://user:password@server', 'https://server/?token=secret'):
            with self.assertRaises(ValueError):
                setup.home_url(value)

    def test_device_transfer_keeps_tokens_out_of_argv_and_preserves_expiry(self):
        wizard = setup.Wizard('http://127.0.0.1:8123', '192.0.2.20', '')
        wizard.client_id = 'http://localhost:8770/'
        wizard.tokens = {'access_token': 'test-access', 'refresh_token': 'test-refresh', '_expires_at': 1234}
        item = {'Entity': 'sensor.room', 'Label': '温度', 'Room': '', 'Kind': 'temperature'}
        with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            wizard.install([item])
        command = run.call_args.args[0]
        payload = json.loads(run.call_args.kwargs['input'])
        self.assertNotIn('test-access', ' '.join(command))
        self.assertEqual(payload['ExpiresAt'], 1234)
        self.assertEqual(payload['RefreshToken'], 'test-refresh')
