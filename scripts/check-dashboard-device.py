"""Read operational state without printing Wi-Fi names, passwords or nearby SSIDs."""
import json
from pathlib import Path
import subprocess
from importlib.machinery import SourceFileLoader

ROOT = Path('/mnt/d/kindle')
ssh = SourceFileLoader('dashboard_status_ssh', str(ROOT / 'scripts/device-ssh.py')).load_module()
data = subprocess.check_output(ssh.connection(22) + ['cat /run/paperos/state.tsv']).decode()
rows = [line.split('\t') for line in data.splitlines()]
net = next(row for row in rows if row[0] == 'net')
receive = next(row for row in rows if row[0] == 'receive')
state = {'connected': net[3] == 'true', 'ip': net[4], 'receiving': receive[1] == 'true',
         'airplane': net[2] == 'true', 'weather_fetched': int(next(row for row in rows if row[0] == 'weather')[1])}
(ROOT / 'build/dashboard-network-state.json').write_text(json.dumps(state, indent=2) + '\n')
print(json.dumps(state), flush=True)
