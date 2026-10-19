"""Bounded serial/QMP control for owned, file-backed KT3 test machines."""
import json
from pathlib import Path
import re
import select
import socket
import time
import uuid


class Console:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.connect(str(self.directory / 'serial.sock'))
        self.socket.settimeout(0.5)
        self.transcript = bytearray()
        self.pending = bytearray()

    def receive(self, marker, timeout=60, forbidden=None):
        received = bytearray(self.pending)
        self.pending.clear()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if forbidden and forbidden in received:
                raise RuntimeError(received[-2200:].decode('utf-8', 'replace'))
            if marker in received:
                return received.decode('utf-8', 'replace')
            try:
                chunk = self.socket.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError('Guest serial connection ended')
            self.transcript.extend(chunk)
            received.extend(chunk)
        raise TimeoutError(received[-2200:].decode('utf-8', 'replace'))

    def send(self, data):
        for position in range(0, len(data), 4):
            ready, _, _ = select.select([self.socket], [], [], 0)
            if ready:
                chunk = self.socket.recv(65536)
                if not chunk:
                    raise RuntimeError('Guest serial connection ended')
                self.transcript.extend(chunk)
                self.pending.extend(chunk)
            self.socket.sendall(data[position:position+4])
            time.sleep(0.03)

    def command(self, command):
        marker = 'PAPEROS_RC_' + uuid.uuid4().hex[:12]
        self.send((command + f'; PAPEROS_RC=$?; printf "\\n{marker}:%s:END\\n" "$PAPEROS_RC"\n').encode())
        result = self.receive(b':END')
        found = re.search(re.escape(marker) + r':(\d+):END', result)
        if not found or int(found[1]):
            raise RuntimeError(result[-2200:])
        if '# ' not in result.split(marker, 1)[1]:
            self.receive(b'# ', 10)
        return result.split(marker)[0]

    def close(self):
        self.socket.close()
        (self.directory / 'console.txt').write_bytes(self.transcript)


def qmp(directory, command, arguments=None):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(5)
    connection.connect(str(Path(directory) / 'control.sock'))
    stream = connection.makefile('rwb', buffering=0)
    json.loads(stream.readline())
    for text in ('qmp_capabilities', command):
        request = {'execute': text}
        if text == command and arguments is not None:
            request['arguments'] = arguments
        stream.write(json.dumps(request).encode() + b'\n')
        while True:
            result = json.loads(stream.readline())
            if 'error' in result:
                raise RuntimeError(str(result))
            if 'return' in result:
                break
    stream.close()
    connection.close()
