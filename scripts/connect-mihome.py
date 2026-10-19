"""A one-time loopback-only browser wizard; no passwords or tokens in the UI/logs."""
import argparse
import html
import http.server
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None

def home_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('请输入家庭中枢的 HTTP 或 HTTPS 地址')
    return value.rstrip('/')

def home_candidates(states):
    result = []
    kinds = {'temperature': 'temperature', 'humidity': 'humidity', 'carbon_dioxide': 'co2', 'pm25': 'pm25'}
    for state in states:
        entity = state.get('entity_id', '')
        domain = entity.split('.', 1)[0]
        attributes = state.get('attributes') or {}
        kind = 'state'
        if domain == 'sensor':
            kind = kinds.get(attributes.get('device_class'))
            if not kind:
                try:
                    if not math.isfinite(float(state.get('state', ''))):
                        continue
                except (ValueError, TypeError):
                    continue
                if not attributes.get('unit_of_measurement'):
                    continue
                kind = 'metric'
        elif domain not in ('binary_sensor', 'light', 'switch', 'fan', 'climate'):
            continue
        if len(result) >= 1000:
            break
        result.append({'Entity': entity, 'Label': str(attributes.get('friendly_name') or entity)[:64],
                       'Room': '', 'Kind': kind, 'Display': str(state.get('state', ''))[:48],
                       'Unit': str(attributes.get('unit_of_measurement') or '')[:16]})
    return sorted(result, key=lambda item: (item['Kind'] == 'state', item['Label']))

class Wizard:
    def __init__(self, server, device, proxy):
        self.server = home_url(server)
        self.device, self.proxy = device, proxy
        self.nonce = secrets.token_urlsafe(32)
        self.tokens = None
        self.items = []
        self.client_id = ''
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, values=None, authenticated=False):
        headers = {'Accept': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self.tokens['access_token']
        data = None
        if values is not None:
            data = urllib.parse.urlencode(values).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = urllib.request.Request(self.server + path, data=data, headers=headers)
        with self.opener.open(request, timeout=20) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('中枢回复过大，请减少集成设备后重试')
            return json.loads(raw)

    def install(self, selected):
        config = {'Version': 1, 'BaseURL': self.server, 'Token': self.tokens['access_token'],
                  'RefreshToken': self.tokens['refresh_token'], 'ClientID': self.client_id,
                  'ExpiresAt': self.tokens.get('_expires_at', 0),
                  'Proxy': self.proxy, 'Name': '我的家庭',
                  'Items': [{k: item[k] for k in ('Entity', 'Label', 'Room', 'Kind')} for item in selected]}
        helper = ROOT / 'scripts/device-home-config.py'
        if os.name == 'nt':
            wsl_helper = '/mnt/' + helper.drive[0].lower() + helper.as_posix()[2:]
            command = ['wsl', '-d', 'Ubuntu-24.04', '--', 'python3', wsl_helper]
        else:
            command = ['python3', str(helper)]
        result = subprocess.run(command + ['--host', self.device], input=json.dumps(config, ensure_ascii=False).encode(),
                                capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError('Kindle 尚未连接：请短按电源键唤醒、进入主页，然后重试保存。')

def page(title, body):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>PaperOS 家庭显示</title><style>body{font:17px system-ui;max-width:820px;margin:48px auto;padding:0 24px;color:#17231e;background:#f4f6f2}'
            'h1{font-size:30px}p{line-height:1.7;color:#536157}a,button{display:inline-block;padding:13px 22px;background:#183e2a;color:white;border:0;border-radius:8px;text-decoration:none;font:inherit;cursor:pointer}'
            'label{display:flex;gap:14px;background:white;border:1px solid #dce3d9;border-radius:8px;padding:16px;margin:9px 0}small{display:block;color:#657266;margin-top:5px}input{width:20px;height:20px}footer{margin:28px 0;color:#657266}</style>'
            '<h1>' + html.escape(title) + '</h1>' + body + '</html>')

def make_handler(wizard):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, content, status=200):
            encoded = content.encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)

        def redirect(self, target):
            self.send_response(302);self.send_header('Location', target);self.send_header('Cache-Control', 'no-store');self.end_headers()

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == '/callback':
                query = urllib.parse.parse_qs(parsed.query)
                if query.get('state', [''])[0] != wizard.nonce:
                    self.send(page('连接无效', '<p>请从本窗口重新连接家庭中枢。</p>'), 400);return
                try:
                    wizard.tokens = wizard.request('/auth/token', {'grant_type': 'authorization_code', 'code': query.get('code', [''])[0], 'client_id': wizard.client_id})
                    if not wizard.tokens.get('access_token') or not wizard.tokens.get('refresh_token'):
                        raise ValueError('中枢未返回完整授权')
                    wizard.tokens['_expires_at'] = int(time.time()) + int(wizard.tokens.get('expires_in', 1800))
                    wizard.items = home_candidates(wizard.request('/api/states', authenticated=True))
                except Exception:
                    self.send(page('暂未连接', '<p>未完成家庭授权或无法读取设备，请从连接首页重试。</p><a href="/">返回</a>'), 400);return
                self.redirect('/select');return
            if parsed.path == '/select' and wizard.tokens:
                body = '<p>勾选最多 12 项显示在 Kindle。这里只读取状态，不会开关设备。</p><form method="post" action="/save"><input type="hidden" name="nonce" value="' + wizard.nonce + '">'
                for item in wizard.items:
                    body += '<label><input type="checkbox" name="entity" value="' + html.escape(item['Entity'], quote=True) + '"><span>' + html.escape(item['Label']) + '<small>' + html.escape(item['Entity'] + ' · ' + item['Display'] + ' ' + item['Unit']) + '</small></span></label>'
                if not wizard.items:
                    body += '<p>尚无可显示的指标。请先在 Home Assistant 添加官方 Xiaomi Home 集成并完成米家授权，然后重新连接。</p>'
                body += '<button type="submit">保存到 PaperOS</button></form><footer>在电脑完成一次配置，Kindle 负责查看。授权可以在 Home Assistant 个人资料中撤销。</footer>'
                self.send(page('选择要看的家庭信息', body));return
            if parsed.path != '/':
                self.send(page('页面不存在', '<a href="/">返回连接首页</a>'), 404);return
            auth = wizard.server + '/auth/authorize?' + urllib.parse.urlencode({'client_id': wizard.client_id, 'redirect_uri': wizard.client_id + 'callback', 'state': wizard.nonce})
            self.send(page('连接 PaperOS 家庭显示', '<p>中枢：' + html.escape(wizard.server) + '</p><p>先在中枢完成米家绑定，再连接并选择想在 Kindle 看到的指标。账号密码直接在 Home Assistant 登录页输入。</p><p>连接会沿用所登录 Home Assistant 账户的访问权限，并将授权保存在 Kindle，用于自动更新家庭信息。PaperOS 定期读取选定的设备状态；授权可在中枢个人资料中撤销。</p><a href="' + html.escape(auth, quote=True) + '">连接 Home Assistant</a>'))

        def do_POST(self):
            if self.path != '/save' or not wizard.tokens:
                self.send(page('未连接', '<a href="/">返回连接首页</a>'), 400);return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384:
                    raise ValueError('选择内容过大')
                values = urllib.parse.parse_qs(self.rfile.read(length).decode())
                if values.get('nonce', [''])[0] != wizard.nonce:
                    raise ValueError('连接已失效，请重新打开页面')
                entities = set(values.get('entity', []))
                selected = [item for item in wizard.items if item['Entity'] in entities]
                if not 1 <= len(selected) <= 12 or len(selected) != len(entities):
                    raise ValueError('请选择1至12个有效显示项')
                with wizard.lock:
                    wizard.install(selected)
                self.send(page('家庭显示已连接', '<p>配置已通过加密连接保存到 Kindle。打开米家应用即可查看选定的指标与设备状态。</p><p>本窗口可以关闭。</p>'))
            except ValueError as error:
                self.send(page('尚未保存', '<p>' + html.escape(str(error)) + '</p><a href="/select">返回选择页重试</a>'), 400)
            except Exception:
                self.send(page('尚未保存', '<p>连接暂时失败，请唤醒 Kindle 后重试。</p><a href="/select">重试</a>'), 400)
    return Handler

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default='http://192.0.2.10:8123')
    parser.add_argument('--device', default='192.0.2.20')
    parser.add_argument('--device-proxy', default='http://127.0.0.1:1055')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    wizard = Wizard(args.server, args.device, args.device_proxy)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(wizard))
    wizard.client_id = 'http://localhost:' + str(server.server_port) + '/'
    print('PaperOS 家庭配置：' + wizard.client_id, flush=True)
    if args.open:
        webbrowser.open(wizard.client_id)
    try:
        server.serve_forever()
    finally:
        server.server_close();wizard.tokens = None

if __name__ == '__main__':
    main()
