"""Private product maintenance over the workspace's existing pinned SSH link."""
import argparse
from importlib.machinery import SourceFileLoader
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='192.0.2.20')
    parser.add_argument('--command',required=True)
    args=parser.parse_args()
    if args.host.startswith('-') or any(c.isspace() for c in args.host):
        parser.error('Invalid device address')
    root=Path(__file__).resolve().parents[1]
    module=SourceFileLoader('home_command_ssh',str(root/'scripts/device-ssh.py')).load_module()
    command=module.connection(22)
    command[-1]='root@'+args.host
    command[-1:-1]=['-o','HostKeyAlias=169.254.28.2']
    result=subprocess.run(command+[args.command],input=sys.stdin.buffer.read(),capture_output=True,timeout=40)
    # The caller must capture stdout: private configs may contain credentials.
    sys.stdout.buffer.write(result.stdout)
    if result.returncode:
        print('Device maintenance command failed',file=sys.stderr)
    return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
