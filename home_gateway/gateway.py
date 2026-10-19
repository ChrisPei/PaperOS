"""Serve only an immutable allow-list of exported states; no HA or NAS client."""
import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time

ENTITY = re.compile(r'^(sensor|binary_sensor|light|switch|fan|climate)\.[a-z0-9_]{1,128}$')
TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')
MAX_FILE = 65536
MAX_AGE = 90


def read_json(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError('Export exceeds limit')
    return json.loads(raw)


class Scope:
    def __init__(self, data):
        entities = data.get('entities', [])
        digest = data.get('token_sha256', '')
        if (not 1 <= len(entities) <= 12 or len(set(entities)) != len(entities)
                or any(not isinstance(e, str) or not ENTITY.fullmatch(e) for e in entities)
                or not re.fullmatch(r'[a-f0-9]{64}', digest)):
            raise ValueError('Invalid read-only scope')
        self.entities = frozenset(entities)
        self.digest = digest

    def authorized(self, header):
        if not isinstance(header, str) or not header.startswith('Bearer '):
            return False
        token = header[7:]
        return bool(TOKEN.fullmatch(token)) and hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), self.digest)

    def response(self, method, path, header, snapshot):
        if not self.authorized(header):
            return 401, {'error': 'unauthorized'}
        if method != 'GET':
            return 405, {'error': 'read_only'}
        prefix = '/api/states/'
        entity = path[len(prefix):] if path.startswith(prefix) else ''
        if entity not in self.entities:
            return 403, {'error': 'outside_selected_metrics'}
        try:
            age = time.time() - snapshot['at']
            item = snapshot['states'][entity]
            state, unit = item['state'], item['unit']
            if (not -10 <= age <= MAX_AGE or snapshot.get('version') != 1
                    or not isinstance(state, str) or len(state) > 128
                    or not isinstance(unit, str) or len(unit) > 32):
                raise ValueError('Unavailable export')
        except (KeyError, TypeError, ValueError):
            return 503, {'error': 'export_unavailable'}
        # No attributes, tokens, paths, registry data, or actions are forwarded.
        return 200, {'entity_id': entity, 'state': state,
                     'attributes': {'unit_of_measurement': unit}}


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, root):
        self.root = Path(root)
        self.scope = Scope(read_json(self.root / 'scope.json'))
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # The HTTP server must not log request headers or credentials.
        pass


class Handler(BaseHTTPRequestHandler):
    server_version = 'PaperOSReadOnly/1'
    sys_version = ''

    def log_message(self, *args):
        pass

    def handle_metric(self):
        # Do not open even the fixed export file for unauthenticated callers.
        header = self.headers.get('Authorization', '')
        snapshot = {}
        if self.server.scope.authorized(header) and self.command == 'GET':
            try:
                snapshot = read_json(self.server.root / 'export.json')
            except (OSError, ValueError):
                pass
        status, body = self.server.scope.response(self.command, self.path, header, snapshot)
        raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        if status == 405:
            self.send_header('Allow', 'GET')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)
        self.close_connection = True

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = handle_metric


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='/data')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    with Gateway((args.host, args.port), args.root) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
