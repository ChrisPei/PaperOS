"""Render the implemented native dashboard and real cached forecast, not mock HTML."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid
from urllib.parse import urlencode
from PIL import Image

ROOT = Path('/mnt/d/kindle')
WORK = ROOT / 'build/dashboard-preview'
RUNTIME = Path('/home/chris/kindle-build') / ('dashboard-preview-' + uuid.uuid4().hex[:12])


def command(name, **values):
    body = urlencode({'cmd': name, **values}).encode()
    with socket.socket(socket.AF_UNIX) as channel:
        channel.connect(str(RUNTIME / 'services.sock'))
        channel.sendall(b'POST /command HTTP/1.0\r\nHost: paperos\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: '
                        + str(len(body)).encode() + b'\r\n\r\n' + body)
        result = b''
        while block := channel.recv(4096):
            result += block
    if b' 200 ' not in result.split(b'\r\n', 1)[0]:
        raise RuntimeError(result.decode())


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    apps = WORK / 'apps'
    data = WORK / ('data-' + uuid.uuid4().hex[:12])
    data.mkdir(exist_ok=True)
    binary = ROOT / 'build/host/paperos'
    for name in ('alarm', 'calendar', 'weather', 'mihome', 'notes'):
        subprocess.run([str(binary), '--app-root', str(apps), '--install', str(ROOT / 'examples' / (name + '.papp'))], check=True)
    fetch = subprocess.run([str(ROOT / 'build/host/paperos-services'), '--fetch-weather', str(data / 'weather-seed.json')],
                           capture_output=True, timeout=25)
    if fetch.returncode:
        print('Forecast currently unavailable; preview will show the real empty/cache state.', flush=True)
    service = subprocess.Popen([str(ROOT / 'build/host/paperos-services'), '--simulate', '--root', str(data),
                                '--run-dir', str(RUNTIME), '--apps', str(apps), '--packages', str(WORK / 'packages')],
                               stdout=subprocess.DEVNULL, stderr=(WORK / 'service.log').open('wb'))
    out = ROOT / 'preview/dashboard'
    out.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(40):
            if (RUNTIME / 'state.tsv').exists() and (RUNTIME / 'services.sock').exists():
                break
            if service.poll() is not None:
                raise RuntimeError((WORK / 'service.log').read_text())
            time.sleep(.1)
        def render(screen, name=None, *extra):
            name = name or screen
            pgm = out / (name + '.pgm')
            subprocess.run([str(binary), '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'), '--screen', screen,
                            '--app-root', str(apps), '--services-file', str(RUNTIME / 'state.tsv'), '--render', str(pgm), *extra],
                           check=True, env={**os.environ, 'TZ': 'CST-8'})
            with Image.open(pgm) as image:
                image.save(out / (name + '.png'))
        for screen in ('home', 'widgets', 'alarm', 'timer', 'calendar', 'weather', 'settings', 'network', 'mihome'):
            render(screen)
        command('timer-start', seconds='1')
        for _ in range(40):
            if '\nalert\t' in (RUNTIME / 'state.tsv').read_text():
                break
            time.sleep(.1)
        render('home', 'reminder-white')
        render('home', 'reminder-black', '--alert-invert')
        record = {'native_rendered': True, 'screens': [p.name for p in out.glob('*.png')],
                  'forecast_fetched': fetch.returncode == 0, 'service_log': str(WORK / 'service.log')}
        (ROOT / 'build/dashboard-preview.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record), flush=True)
    finally:
        service.terminate()
        service.wait(timeout=5)


if __name__ == '__main__':
    main()
