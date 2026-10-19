"""Send private home configuration through PaperOS's existing pinned SSH channel."""
import argparse
from importlib.machinery import SourceFileLoader
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='192.0.2.20')
    args = parser.parse_args()
    if args.host.startswith('-') or any(c.isspace() for c in args.host):
        parser.error('Invalid device address')
    payload = sys.stdin.buffer.read(32769)
    if len(payload) > 32768:
        raise SystemExit('Home configuration exceeds the size limit')
    ssh = SourceFileLoader('home_device_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()
    command = ssh.connection(22)
    command[-1] = 'root@' + args.host
    command[-1:-1] = ['-o', 'HostKeyAlias=169.254.28.2']
    result = subprocess.run(command + ['/usr/sbin/paperos-services import-mihome'],
                            input=payload, capture_output=True, timeout=20)
    if result.returncode:
        print('未能连接 Kindle，请唤醒后重试。', file=sys.stderr)
        return 1
    print('家庭显示配置已通过加密连接保存到 Kindle。')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
