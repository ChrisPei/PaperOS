"""Keep the new limited key in RAM while provisioning and revoking old access."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Migration:
    def __init__(self, device):
        self.device = device
        self.key = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.phase = 'prepared'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        original = json.loads(self.remote('cat /var/lib/paperos/services/mihome.json'))
        self.items = original['Items']
        self.name = original['Name']
        assert original['BaseURL'] == 'http://192.0.2.10:8123'
        assert len(self.items) == 7
        self.prepare()

    def remote(self, command, data=None, timeout=45):
        # The WSL helper pins the existing device host key. Secrets go over stdin.
        script = ROOT / 'scripts/device-home-command.py'
        if os.name == 'nt':
            path = '/mnt/' + script.drive[0].lower() + script.as_posix()[2:]
            invocation = ['wsl', '-d', 'Ubuntu-24.04', '--', 'python3', path]
        else:
            invocation = ['python3', str(script)]
        result = subprocess.run(invocation + ['--host', self.device, '--command', command],
                                input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            raise ValueError('Device command failed; credentials withheld')
        return result.stdout

    def prepare(self):
        scope = {'version': 1, 'entities': [i['Entity'] for i in self.items],
                 'token_sha256': hashlib.sha256(self.key.encode()).hexdigest()}
        files = {'paperos-readonly/gateway.py': (ROOT/'home_gateway/gateway.py').read_text(),
                 'paperos-readonly/scope.json': json.dumps(scope, ensure_ascii=False),
                 'paperos-readonly-project/compose.yaml': (ROOT/'home_gateway/compose.yaml').read_text()}
        for name in ('__init__.py', 'manifest.json', 'snapshot.py'):
            relative = 'custom_components/paperos_export/' + name
            files[relative] = (ROOT/'home_gateway'/relative).read_text()
        payload = json.dumps({'files': files}, ensure_ascii=False)
        installer = (ROOT/'home_gateway/install_on_nas.py').read_text()
        installer = installer[:installer.index("if __name__ == '__main__':")]
        source = installer + '\ninstall(json.loads(' + repr(payload) + '))\n'
        packed = base64.b64encode(zlib.compress(source.encode(), 9)).decode()
        command = 'python3 -c "import base64,zlib;exec(zlib.decompress(base64.b64decode(\'' + packed + '\')))"'
        (ROOT/'build/readonly-installer-command.txt').write_text(command, encoding='utf-8')
        (ROOT/'build/readonly-scope-public.json').write_text(json.dumps(scope, ensure_ascii=False, indent=2)+'\n')
        self.installer_length = len(command)

    def request(self, path, *, token=None, values=None, method=None, base='http://192.0.2.10:8787'):
        headers = {'Accept': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        data = None
        if values is not None:
            data = urllib.parse.urlencode(values).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(base+path, headers=headers, data=data, method=method)
        try:
            with self.opener.open(request, timeout=12) as response:
                return response.status, response.read(65537)
        except urllib.error.HTTPError as error:
            return error.code, error.read(65537)

    def verify_gateway(self):
        verified = []
        for item in self.items:
            status, raw = self.request('/api/states/'+item['Entity'], token=self.key)
            if status != 200:
                raise ValueError('Read-only gateway not ready')
            state = json.loads(raw)
            if state['entity_id'] != item['Entity'] or set(state) != {'entity_id','state','attributes'}:
                raise ValueError('Unexpected gateway state')
            if set(state['attributes']) != {'unit_of_measurement'}:
                raise ValueError('Excess gateway attributes')
            verified.append(item['Kind'])
        denials = []
        for method, path, token, expected in [
                ('GET','/api/states/'+self.items[0]['Entity'],None,401),
                ('GET','/api/states/sensor.paperos_unselected_security_probe',self.key,403),
                ('GET','/api/config',self.key,403), ('GET','/desktop/',self.key,403),
                ('GET','/scope.json',self.key,403), ('GET','/../../etc/passwd',self.key,403),
                ('POST','/api/states/'+self.items[0]['Entity'],self.key,405),
                ('POST','/api/services/paperos_security_probe/no_such_service',self.key,405)]:
            status, _ = self.request(path, token=token, method=method)
            if status != expected:
                raise ValueError('Read-only gateway denial did not match')
            denials.append({'method':method,'path':path,'status':status})
        return {'selected_count':len(verified),'gateway_denials':denials}

    def migrate(self):
        with self.lock:
            if self.phase == 'migrated':
                return self.receipt
            receipt = self.verify_gateway()
            old = json.loads(self.remote('cat /var/lib/paperos/services/mihome.json'))
            if old['Items'] != self.items or not old.get('RefreshToken'):
                raise ValueError('Device bindings changed; migration stopped')
            configuration = {'Version':1, 'BaseURL':'http://192.0.2.10:8787',
                             'Token':self.key, 'RefreshToken':'', 'ClientID':'', 'ExpiresAt':0,
                             'Proxy':'http://127.0.0.1:1055','Name':self.name,'Items':self.items}
            self.remote('/usr/sbin/paperos-services import-mihome', json.dumps(configuration, ensure_ascii=False).encode())
            self.phase = 'device_switched'
            deadline = time.monotonic()+40
            while time.monotonic()<deadline:
                raw = self.remote('cat /run/paperos/mihome.tsv').decode()
                rows = [r.split('\t') for r in raw.splitlines() if r.startswith('item\t')]
                if len(rows)==len(self.items) and all(r[6:8]==['true','false'] for r in rows):
                    break
                time.sleep(1)
            else:
                raise ValueError('Device has not obtained all read-only metrics')
            # Revoke just the wizard-created session; leave browser and other users alone.
            status, _ = self.request('/auth/token', values={'token':old['RefreshToken'],'action':'revoke'}, base=old['BaseURL'])
            if status != 200:
                raise ValueError('Old HA authorization revocation did not complete')
            status, _ = self.request('/auth/token', values={'grant_type':'refresh_token',
                                     'refresh_token':old['RefreshToken'],'client_id':old['ClientID']}, base=old['BaseURL'])
            if status not in (400,401,403):
                raise ValueError('Old refresh credential still usable')
            old_access_status, _ = self.request('/api/', token=old['Token'], base=old['BaseURL'])
            if old_access_status != 401:
                raise ValueError('Old access credential still usable')
            stored = json.loads(self.remote('cat /var/lib/paperos/services/mihome.json'))
            if stored.get('RefreshToken') or stored.get('ClientID') or stored['Token']!=self.key:
                raise ValueError('Old HA credentials remain on device')
            receipt.update(verified_at=datetime.now(timezone.utc).isoformat(),
                           old_refresh_credential_revoked=True, old_access_status=old_access_status,
                           device_has_ha_authorization=False, selected_items_preserved=True,
                           gateway_upstream_ha_credentials=False, phase='migrated')
            self.phase = 'migrated'
            self.receipt = receipt
            (ROOT/'build/mihome-readonly-migration.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
            return receipt


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != '/status':
            self.reply({'error':'not_found'},404); return
        self.reply({'phase':self.server.migration.phase,'selected_count':len(self.server.migration.items),
                    'installer_characters':self.server.migration.installer_length})

    def do_POST(self):
        if (self.path not in ('/verify','/migrate') or self.headers.get('Origin')
                or self.headers.get('X-PaperOS-Provision') != '1'):
            self.reply({'error':'forbidden'},403); return
        try:
            result = self.server.migration.migrate() if self.path=='/migrate' else self.server.migration.verify_gateway()
            self.reply(result)
        except Exception:
            self.reply({'error':'Verification did not complete; no credentials logged',
                        'phase':self.server.migration.phase},409)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--device',default='192.0.2.20')
    parser.add_argument('--port',type=int,default=8772)
    args=parser.parse_args()
    migration=Migration(args.device)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.migration=migration
    print(json.dumps({'phase':'prepared','selected_count':len(migration.items),
                      'installer_characters':migration.installer_length,'control_port':args.port}),flush=True)
    try:
        server.serve_forever()
    finally:
        migration.key=''
        server.server_close()


if __name__=='__main__':
    main()
