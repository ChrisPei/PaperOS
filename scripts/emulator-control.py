"""Control only this workspace's local KT3 emulator through its Unix QMP socket."""
import argparse
import json
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parents[1]
MACHINE = Path("/home/chris/kindle-build/paperos-emulator")

class QMP:
    def __enter__(self):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(5)
        self.socket.connect(str(MACHINE / "control.sock"))
        self.stream = self.socket.makefile("rwb", buffering=0)
        if "QMP" not in json.loads(self.stream.readline()):
            raise ValueError("Unexpected QMP greeting")
        self.sequence = 0
        self.call("qmp_capabilities")
        return self
    def __exit__(self, *args):
        self.stream.close(); self.socket.close()
    def call(self, command, **arguments):
        self.sequence += 1
        self.stream.write(json.dumps({"execute": command, "arguments": arguments, "id": self.sequence}).encode() + b"\n")
        while True:
            response = json.loads(self.stream.readline())
            if response.get("id") == self.sequence:
                if "error" in response:
                    raise ValueError(response["error"])
                return response["return"]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "capture", "tap", "stop"])
    parser.add_argument("--name", default="emulator")
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    args = parser.parse_args()
    with QMP() as qmp:
        if args.action == "status":
            print(json.dumps(qmp.call("query-status")))
        elif args.action == "stop":
            qmp.call("quit")
        elif args.action == "capture":
            if not args.name.replace("-", "").replace("_", "").isalnum():
                parser.error("Use a simple screenshot name")
            destination = ROOT / "preview" / (args.name + ".ppm")
            destination.parent.mkdir(exist_ok=True)
            qmp.call("screendump", filename=str(destination))
            print(destination)
        else:
            if not (0 <= args.x < 600 and 0 <= args.y < 800):
                parser.error("Touch coordinates must be inside 600x800")
            absolute = [{"type": "abs", "data": {"axis": axis, "value": value}} for axis, value in [("x", args.x * 32767 // 599), ("y", args.y * 32767 // 799)]]
            qmp.call("input-send-event", events=absolute + [{"type": "btn", "data": {"button": "left", "down": True}}])
            qmp.call("input-send-event", events=[{"type": "btn", "data": {"button": "left", "down": False}}])
            print("Injected emulator touch event")
