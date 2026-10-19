"""Render the actual shared C keyboard with public sample text, never device notes."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'build/host'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pgm-only', action='store_true')
    args = parser.parse_args()
    if not args.pgm_only:
        from PIL import Image
    preview = ROOT / 'preview'
    preview.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='paperos-keyboard-preview-') as temporary:
        work = Path(temporary)
        sample = work / 'sample.txt'
        sample.write_text('把想法记下来。\n\n键盘只占底部，正文留在上方。\n中文、英文和符号都在熟悉的位置。\n\n', encoding='utf-8')
        scenarios = {
            'keyboard-chinese': ([(410, 706), (438, 595), (326, 651), (45, 651), (495, 595)], ['--multiline']),
            'keyboard-english': ([], ['--multiline', '--english']),
            'keyboard-numbers': ([(60, 762)], ['--multiline', '--english']),
            'keyboard-password': ([], ['--password']),
        }
        for name, (taps, flags) in scenarios.items():
            socket = work / (name + '.sock')
            pgm = preview / (name + '.pgm')
            ui = work / name
            command = [str(BIN / 'paperos'), '--font', str(ROOT / 'assets/NotoSansCJKsc-Regular.otf'), '--render', str(pgm)]
            for x, y in taps:
                command += ['--tap', str(x), str(y)]
            ui.write_text('#!/bin/sh\nexec ' + shlex.quote(command[0]) + ' "$@" ' + shlex.join(command[1:]) + '\n')
            ui.chmod(0o755)
            env = {**os.environ, 'PAPEROS_INPUT_SOCKET': str(socket)}
            if os.environ.get('PAPEROS_TEST_ORIGINAL_IME'):
                env['PAPEROS_IME_HELPER'] = os.environ['PAPEROS_TEST_ORIGINAL_IME']
            service = subprocess.Popen([str(BIN / 'paperos-inputd'), '--socket', str(socket), '--ui', str(ui)], env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 3
                while not socket.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                initial = work / (name + '.txt')
                initial.write_text('PaperOS-123' if '--password' in flags else sample.read_text(), encoding='utf-8')
                reply = subprocess.run([str(BIN / 'paperos-input'), '--title', '输入密码' if '--password' in flags else '编辑笔记',
                                        '--text-file', str(initial), *flags], env=env, capture_output=True, timeout=15)
                if reply.returncode != 1 or not pgm.is_file():
                    raise RuntimeError('Keyboard preview failed: ' + name + repr(reply.stderr))
                if not args.pgm_only:
                    with Image.open(pgm) as image:
                        image.save(preview / (name + '.png'))
            finally:
                service.terminate()
                service.communicate(timeout=4)
    print('Actual C keyboard previews rendered in ' + str(preview))


if __name__ == '__main__':
    main()
