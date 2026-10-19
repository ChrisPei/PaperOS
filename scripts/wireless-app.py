"""TLS app transfer with a certificate/package code confirmed on the Kindle."""
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import tempfile
import time
from urllib.parse import urlencode
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
PEERS = ROOT / 'build/wireless-peers.json'
TAILSCALE_IPV4 = ipaddress.ip_network('100.64.0.0/10')


def receiver_address(host):
    address = ipaddress.ip_address(host)
    if address.version != 4 or address.is_unspecified or address.is_multicast or not (address.is_private or address in TAILSCALE_IPV4):
        raise ValueError('Choose the Wi-Fi or Tailscale IPv4 address shown in PaperOS settings')
    return address


def confirmation_code(certificate, digest, nonce):
    raw = hashlib.sha256(certificate + b'\0' + digest.encode('ascii') + b'\0' + nonce.encode('ascii')).digest()
    return f'{int.from_bytes(raw[:4], "big") % 1000000:06d}'


def transfer(source, host, timeout=600, port=8765):
    address = receiver_address(host)
    package = SourceFileLoader('paperos_package_transfer', str(ROOT / 'scripts/push-app.py')).load_module()
    _, payload = package.archive_package(source)
    digest = hashlib.sha256(payload).hexdigest()
    nonce = secrets.token_hex(16)
    certificate = ssl.get_server_certificate((str(address), port), timeout=8)
    der = ssl.PEM_cert_to_DER_cert(certificate)
    fingerprint = hashlib.sha256(der).hexdigest()
    saved = json.loads(PEERS.read_text()) if PEERS.exists() else {}
    previous = saved.get('peers', {}).get(str(address))
    if previous and previous != fingerprint:
        raise ValueError('The receiver certificate changed. Verify the device before pairing it again.')
    # Bootstrap trust is bound to the code shown on both screens. The actual
    # upload verifies this exact certificate, never a global unverified context.
    context = ssl.create_default_context(cadata=certificate)
    context.check_hostname = False
    context.minimum_version = ssl.TLSVersion.TLSv1_2

    def request(method, path, body=None, headers=None):
        connection = http.client.HTTPSConnection(str(address), port, context=context, timeout=90)
        try:
            connection.connect()
            actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if actual != fingerprint:
                raise ValueError('Receiver changed during transfer')
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('Receiver response too large')
            if response.status not in (200, 202):
                raise RuntimeError(f'Receiver rejected request ({response.status}): ' + raw.decode('utf-8', 'replace')[:240])
            return json.loads(raw)
        finally:
            connection.close()

    result = request('POST', '/upload', payload, {
        'Content-Type': 'application/octet-stream',
        'X-PaperOS-SHA256': digest, 'X-PaperOS-Nonce': nonce
    })
    code = confirmation_code(der, digest, nonce)
    print(f'校验码：{code}。请在 Kindle 核对相同校验码，并点击「确认接收」。', flush=True)
    deadline = time.monotonic() + timeout
    query = urlencode({'id': result['id'], 'nonce': nonce})
    while time.monotonic() < deadline:
        result = request('GET', '/status?' + query)
        phase = result['status']
        if phase == 'received':
            saved.setdefault('peers', {})[str(address)] = fingerprint
            saved['default_host'] = str(address)
            PEERS.parent.mkdir(exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix='.wireless-', dir=PEERS.parent)
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump(saved, output, indent=2)
                os.replace(temporary, PEERS)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            print('已接收。在 Kindle「应用 → 接收的应用包」中选择安装或更新。', flush=True)
            return
        if phase in ('rejected', 'expired', 'failed'):
            raise RuntimeError('接收未完成：' + phase)
        time.sleep(1)
    raise TimeoutError('等待 Kindle 确认超时；应用尚未安装')
