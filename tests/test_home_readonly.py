import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway = load('readonly_gateway', ROOT / 'home_gateway/gateway.py')
snapshot = load('readonly_snapshot', ROOT / 'home_gateway/custom_components/paperos_export/snapshot.py')
KEY = 'k' * 43  # Test fixture only; production uses 256 random bits.
ENTITY = 'sensor.selected_temperature'


class ReadOnlyGatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.scope = {'entities': [ENTITY], 'token_sha256': hashlib.sha256(KEY.encode()).hexdigest()}
        (self.root / 'scope.json').write_text(json.dumps(self.scope))
        self.snapshot = {'version': 1, 'at': time.time(), 'states': {
            ENTITY: {'state': '24.8', 'unit': '°C', 'admin_secret': 'must-not-leak'},
            'sensor.unselected': {'state': '999', 'unit': 'W'},
        }}
        self.write_snapshot()
        (self.root / 'private-file').write_text('not-a-metric')
        self.server = gateway.Gateway(('127.0.0.1', 0), self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def write_snapshot(self):
        (self.root / 'export.json').write_text(json.dumps(self.snapshot))

    def request(self, method='GET', path='/api/states/' + ENTITY, token=KEY):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        headers = {} if token is None else {'Authorization': 'Bearer ' + token}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        self.assertNotIn(KEY.encode(), raw)
        self.assertNotIn(b'must-not-leak', raw)
        return status, json.loads(raw) if raw else {}

    def test_selected_state_has_only_the_value_and_unit(self):
        status, data = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(data, {'entity_id': ENTITY, 'state': '24.8',
                                'attributes': {'unit_of_measurement': '°C'}})

    def test_missing_forged_and_original_ha_credentials_are_rejected(self):
        for key in (None, 'wrong', 'a' * 43, 'original-ha-access-token'):
            with self.subTest(key=key):
                self.assertEqual(self.request(token=key)[0], 401)

    def test_unselected_metrics_listing_controls_files_and_proxy_paths_are_denied(self):
        for path in ('/api/states/sensor.unselected', '/api/states', '/api/config',
                     '/api/websocket', '/api/services/switch/turn_on', '/desktop/',
                     '/private-file', '/scope.json', '/export.json', '/../../etc/passwd',
                     '/api/states/../scope.json', '/api/states/' + ENTITY + '?other=1',
                     '/api/states/%73ensor.selected_temperature', 'http://127.0.0.1:8123/api/'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 403)

    def test_all_mutating_methods_are_blocked_even_with_correct_key(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT', 'HEAD'):
            for path in ('/api/states/' + ENTITY, '/api/services/switch/turn_on'):
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.request(method, path)[0], 405)

    def test_stale_missing_and_malformed_export_fail_closed(self):
        self.snapshot['at'] = time.time() - 91
        self.write_snapshot()
        self.assertEqual(self.request()[0], 503)
        (self.root / 'export.json').write_text('invalid json')
        self.assertEqual(self.request()[0], 503)
        (self.root / 'export.json').unlink()
        self.assertEqual(self.request()[0], 503)

    def test_unavailable_sensor_does_not_turn_into_zero(self):
        self.snapshot['states'][ENTITY]['state'] = 'unavailable'
        self.write_snapshot()
        self.assertEqual(self.request()[1]['state'], 'unavailable')

    def test_scope_cannot_be_expanded_by_request_or_snapshot_contents(self):
        (self.root / 'scope.json').write_text(json.dumps({**self.scope, 'entities': [ENTITY, 'sensor.unselected']}))
        self.assertEqual(self.request(path='/api/states/sensor.unselected')[0], 403)


class ExporterTests(unittest.TestCase):
    def test_exporter_fetches_only_selected_states_and_strips_other_attributes(self):
        calls = []
        def get_state(entity):
            calls.append(entity)
            return SimpleNamespace(state='55', attributes={'unit_of_measurement': '%',
                                                         'latitude': 10, 'token': 'secret'})
        result = snapshot.build_snapshot([ENTITY], get_state)
        self.assertEqual(calls, [ENTITY])
        self.assertEqual(result['states'], {ENTITY: {'state': '55', 'unit': '%'}})
        self.assertNotIn('secret', json.dumps(result))

    def test_allow_list_rejects_duplicates_paths_and_oversize(self):
        for entities in ([], [ENTITY] * 2, ['../../etc/passwd'], ['person.location'], [ENTITY] * 13):
            with self.assertRaises(ValueError):
                snapshot.selected_entities({'entities': entities})

    def test_atomic_export_contains_no_partial_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'export.json'
            data = snapshot.build_snapshot([ENTITY], lambda _: None)
            snapshot.write_snapshot(path, data)
            self.assertEqual(json.loads(path.read_text()), data)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
