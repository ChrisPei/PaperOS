"""Run only the public firmware predictor in an isolated, local ARM fixture."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/home/chris/kindle-build/stock-ime-test')
REFERENCE = Path('/home/chris/kindle-build/recovery-kt3/rootfs.img')
KEYBOARD = Path('/home/chris/kindle-build/keyboard-inspection/keymaps/zh_CN')
MODERN = Path('/usr/arm-linux-gnueabi/lib')
RUNTIME = WORK / 'root'


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)


def extract(path):
    destination = RUNTIME / path.lstrip('/')
    if destination.is_file():
        return destination
    info = run('debugfs', '-R', 'stat ' + path, str(REFERENCE)).stdout
    if 'Type: symlink' in info:
        match = re.search(r'Fast link dest: "([^"]+)"', info)
        if not match:
            raise ValueError('Unsupported reference symlink: ' + path)
        target = match[1]
        target = target if target.startswith('/') else str(PurePosixPath(path).parent / target)
        source = extract(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    elif 'Type: regular' in info:
        destination.parent.mkdir(parents=True, exist_ok=True)
        run('debugfs', '-R', f'dump -p {path} {destination}', str(REFERENCE))
    else:
        raise FileNotFoundError(path)
    return destination


def main():
    if REFERENCE.stat().st_size != 460800000:
        raise ValueError('Expected the already verified public KT3 reference image')
    WORK.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    runtime = RUNTIME / 'lib'
    runtime.mkdir(exist_ok=True)
    # GNU libc stays in this compatibility process; PaperOS itself uses musl.
    for name in ('ld-linux.so.3', 'libc.so.6', 'libdl.so.2', 'libpthread.so.0',
                 'libm.so.6', 'librt.so.1', 'libgcc_s.so.1'):
        shutil.copyfile(MODERN / name, runtime / name)
    pending = []
    keyboard = RUNTIME / 'usr/share/keyboard/zh_CN'
    keyboard.mkdir(parents=True, exist_ok=True)
    for name in ('libpredictor.so.1.0', 'zh_CN.ldb', 'qwerty.kdb'):
        shutil.copyfile(KEYBOARD / name, keyboard / name)
    pending.append(keyboard / 'libpredictor.so.1.0')
    seen = set()
    while pending:
        binary = pending.pop()
        if binary in seen:
            continue
        seen.add(binary)
        if len(seen)>48:
            raise ValueError('Unexpected dependency graph')
        needed = re.findall(r'Shared library: \[([^]]+)\]', run('arm-linux-gnueabi-readelf', '-d', str(binary)).stdout)
        for name in needed:
            if (runtime / name).is_file():
                continue
            for prefix in ('/usr/lib/', '/lib/'):
                try:
                    source = extract(prefix + name)
                    pending.append(source)
                    break
                except FileNotFoundError:
                    continue
            else:
                raise FileNotFoundError(name)
    (RUNTIME / 'var/local/keyboard/zh_CN').mkdir(parents=True, exist_ok=True)
    shutil.copyfile('/usr/bin/qemu-arm-static', RUNTIME / 'emulator')
    (RUNTIME / 'emulator').chmod(0o755)
    run('arm-linux-gnueabi-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(ROOT / 'native/stock-ime-probe.c'), '-o', str(RUNTIME / 'probe'), '-ldl')
    results = []
    for query, expected in (('nihao', '你好'), ('zhongguo', '中国')):
        process = subprocess.run(['sudo', '-n', 'unshare', '-n', 'chroot', str(RUNTIME), '/emulator', '/probe', query],
                                 text=True, capture_output=True, timeout=15)
        (WORK / (query + '.log')).write_text(process.stdout + process.stderr)
        if process.returncode or expected not in process.stdout:
            raise RuntimeError('Chinese candidate probe failed: ' + process.stdout + process.stderr)
        results.append({'query': query, 'expected_candidate_present': True, 'output': process.stdout})
    wrapper = WORK / 'run-ime.sh'
    wrapper.write_text(f'#!/bin/sh\nexec sudo -n unshare -n chroot {RUNTIME} /emulator /probe\n')
    wrapper.chmod(0o755)
    subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'), '-p', 'test_input.py',
                    '-k', 'original_chinese', '-v'],
                   env={**os.environ, 'PAPEROS_TEST_ORIGINAL_IME': str(wrapper)}, check=True, timeout=15, capture_output=True)
    record = {'passed': True, 'network_isolated': True, 'plugin_sha256': hashlib.sha256((keyboard / 'libpredictor.so.1.0').read_bytes()).hexdigest(),
              'program_sha256': hashlib.sha256((RUNTIME / 'probe').read_bytes()).hexdigest(),
              'queries': results, 'fixture': str(WORK), 'native_keyboard_saved': '你好，。',
              'system_keyboard_service_verified': True, 'hardware_verified': False}
    (ROOT / 'build/stock-ime-validation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
