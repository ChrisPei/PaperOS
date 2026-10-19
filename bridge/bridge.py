"""Local, read-only Cowork/Codex status bridge for PaperOS.

No prompts, credentials, tool arguments, or conversation bodies are published.
The local-file adapters are observational and explicitly label their confidence.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, asdict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from urllib.parse import urlparse

STATES = {"running", "waiting", "completed", "failed", "idle", "stopped", "unknown"}
MAX_AGENTS = 48
MAX_REQUEST = 65536

def clean(value, limit=180):
    return " ".join(str(value or "").split())[:limit]

def epoch(value):
    if isinstance(value, (int, float)):
        return int(value / 1000 if value > 100_000_000_000 else value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return 0

@dataclass
class Agent:
    id: str
    source: str
    title: str
    state: str
    updated_at: int
    confidence: str = "reported"

    @classmethod
    def from_dict(cls, row):
        if not isinstance(row, dict) or row.get("state") not in STATES:
            raise ValueError("state must be a supported agent state")
        ident = clean(row.get("id"), 80)
        if not ident or not re.fullmatch(r"[\w.:-]+", ident):
            raise ValueError("id must contain only letters, digits, _, ., : or -")
        source = clean(row.get("source"), 20)
        if not source:
            raise ValueError("source is required")
        return cls(ident, source, clean(row.get("title") or ident), row["state"], epoch(row.get("updated_at")) or int(time.time()))

def read_events(path, limit=1024*1024):
    """Bounded tail read. JSON values are only inspected for event type/status."""
    try:
        with path.open("rb") as f:
            size = path.stat().st_size
            f.seek(max(0, size-limit))
            raw = f.read(limit)
        if size > limit:
            raw = raw.split(b"\n", 1)[-1]
        result = []
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(item, dict):
                result.append(item)
        return result
    except OSError:
        return []

def codex_state(events, modified_at, now):
    observed = "unknown"
    activity = False
    for event in events:
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        typ = payload.get("type", "")
        if typ in {"task_complete", "task_completed", "turn_complete", "turn_completed"}:
            observed = "failed" if payload.get("status") == "failed" or payload.get("error") else "completed"
        elif typ in {"turn_aborted", "task_aborted", "turn_interrupted"}:
            observed = "stopped"
        elif typ in {"task_started", "turn_started", "user_message"}:
            observed, activity = "running", True
        elif event.get("type") == "response_item":
            if typ in {"reasoning", "function_call", "custom_tool_call"}:
                observed, activity = "running", True
                name = payload.get("name", "")
                if "request_user_input" in name:
                    observed = "waiting"
            elif typ == "message" and payload.get("role") == "assistant" and payload.get("phase") == "final_answer":
                observed = "completed"
        elif typ == "error":
            observed = "failed"
    if observed == "running" and now-modified_at > 300:
        return "unknown"  # inactivity cannot prove that a task completed
    if observed == "unknown" and activity and now-modified_at <= 300:
        return "running"
    return observed

class CodexLocal:
    def __init__(self, root):
        self.root = Path(root)

    def collect(self):
        dbs = sorted(self.root.glob("state_*.sqlite"), key=lambda p:p.stat().st_mtime, reverse=True)
        if not dbs:
            return [], "No local Codex database found"
        now = int(time.time())
        agents = []
        with closing(sqlite3.connect(dbs[0].resolve().as_uri()+"?mode=ro", uri=True, timeout=1)) as connection:
            connection.execute("PRAGMA query_only=ON")
            cols = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
            required = {"id", "title", "rollout_path", "updated_at", "archived"}
            if not required.issubset(cols):
                return [], "Unrecognized local Codex metadata schema"
            rows = connection.execute("SELECT id,title,rollout_path,updated_at FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 20").fetchall()
        for ident, title, path, updated in rows:
            rollout = Path(path)
            if not rollout.is_file():
                continue
            modified = int(rollout.stat().st_mtime)
            state = codex_state(read_events(rollout), modified, now)
            agents.append(Agent(str(ident), "Codex", clean(title or "Untitled"), state, max(int(updated), modified), "inferred-from-local-events"))
        return agents, "Local session events; runtime state is inferred"

STATUS_MAP = {
    "running":"running", "in_progress":"running", "inProgress":"running", "active":"running",
    "waiting":"waiting", "waiting_for_input":"waiting", "needs_input":"waiting", "awaiting_approval":"waiting",
    "completed":"completed", "complete":"completed", "done":"completed", "success":"completed",
    "failed":"failed", "error":"failed", "idle":"idle", "paused":"stopped", "cancelled":"stopped",
}

class CoworkLocal:
    def __init__(self, root):
        self.root = Path(root) if root else None

    def collect(self):
        if not self.root or not self.root.is_dir():
            return [], "Cowork session folder unavailable"
        agents = []
        candidates = []
        # Deliberately exclude plugin manifests, settings, account and auth files.
        for pattern in ("**/local_session_*.json", "**/session_*.json", "**/session.json", "**/sessions.json"):
            candidates.extend(self.root.glob(pattern))
        for path in sorted(set(candidates), key=lambda p:p.stat().st_mtime, reverse=True)[:32]:
            if any(part in {"skills", "plugins", "sentry"} for part in path.parts) or path.stat().st_size > MAX_REQUEST:
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            items = item if isinstance(item, list) else item.get("sessions", [item]) if isinstance(item, dict) else []
            for row in items:
                if not isinstance(row, dict):
                    continue
                ident = row.get("sessionId") or row.get("id")
                if not ident:
                    continue
                raw_state = row.get("status") or row.get("state")
                if isinstance(raw_state, dict):
                    raw_state = raw_state.get("type")
                state = STATUS_MAP.get(raw_state, "unknown")
                stamp = epoch(row.get("updatedAt") or row.get("lastActivityAt")) or int(path.stat().st_mtime)
                if state == "running" and time.time()-stamp > 300:
                    state = "unknown"
                title = row.get("title") or row.get("name") or "Cowork session"
                agents.append(Agent(clean(ident,80), "Cowork", clean(title), state, stamp, "local-metadata"))
        return agents, "Local metadata adapter; unsupported records are left unknown"

class Registry:
    def __init__(self, providers=(), store=None, ttl=300):
        self.providers = list(providers)
        self.store = Path(store) if store else None
        self.ttl = ttl
        self.pushed = {}
        self.lock = threading.RLock()
        self.cached = None
        self.cached_at = 0.0
        if self.store and self.store.is_file():
            try:
                for row in json.loads(self.store.read_text(encoding="utf-8")):
                    agent = Agent.from_dict(row)
                    self.pushed[(agent.source,agent.id)] = agent
            except (OSError, ValueError, TypeError):
                pass

    def put(self, agent):
        with self.lock:
            if len(self.pushed) >= MAX_AGENTS and (agent.source,agent.id) not in self.pushed:
                raise ValueError("Agent limit reached")
            self.pushed[(agent.source,agent.id)] = agent
            self.cached_at = 0
            if self.store:
                self.store.parent.mkdir(parents=True, exist_ok=True)
                fd, path = tempfile.mkstemp(dir=self.store.parent, prefix=".agent-state-")
                try:
                    with os.fdopen(fd,"w",encoding="utf-8") as f:
                        json.dump([asdict(a) for a in self.pushed.values()],f,ensure_ascii=False)
                        f.flush(); os.fsync(f.fileno())
                    os.replace(path,self.store)
                finally:
                    if os.path.exists(path): os.unlink(path)

    def snapshot(self):
        with self.lock:
            now = time.time()
            if self.cached and now-self.cached_at < 2:
                return self.cached
            collected = {}
            diagnostics = []
            for provider in self.providers:
                try:
                    agents, note = provider.collect()
                    diagnostics.append({"provider":type(provider).__name__,"detail":note})
                    for agent in agents:
                        collected[(agent.source,agent.id)] = agent
                except (OSError, sqlite3.Error, ValueError) as error:
                    diagnostics.append({"provider":type(provider).__name__,"detail":type(error).__name__})
            for key, item in self.pushed.items():
                agent = Agent(**asdict(item))
                if agent.state in {"running", "waiting"} and now-agent.updated_at > self.ttl:
                    agent.state = "unknown"
                collected[key] = agent
            priority = {"waiting":0,"running":1,"failed":2,"unknown":3,"stopped":4,"idle":5,"completed":6}
            agents = sorted(collected.values(),key=lambda a:(priority[a.state],-a.updated_at))[:MAX_AGENTS]
            self.cached = {"version":1,"generated_at":int(now),"agents":[asdict(a) for a in agents],"providers":diagnostics}
            self.cached_at = now
            return self.cached

def tsv(snapshot):
    lines = [f"paperos-v1\t{snapshot['generated_at']}\t{len(snapshot['agents'])}"]
    for row in snapshot["agents"]:
        lines.append("\t".join([clean(row["id"],80), clean(row["source"],20), clean(row["title"]), row["state"], str(row["updated_at"])]))
    return ("\n".join(lines)+"\n").encode("utf-8")

def make_handler(registry, token="", require_read_token=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PaperOSBridge/0.1"
        def log_message(self, fmt, *args):
            pass  # Tokens and request data are not written to logs.
        def authorized(self):
            received = self.headers.get("Authorization","")
            return bool(token) and hmac.compare_digest(received,"Bearer "+token)
        def reply(self, code, body, content_type="application/json; charset=utf-8"):
            if isinstance(body,dict): body=json.dumps(body,ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            path=urlparse(self.path).path
            if path=="/health":
                return self.reply(200,{"ok":True,"service":"paperos-bridge"})
            if require_read_token and not self.authorized():
                return self.reply(401,{"error":"Authentication required"})
            if path=="/v1/agents": return self.reply(200,registry.snapshot())
            if path=="/v1/agents.tsv": return self.reply(200,tsv(registry.snapshot()),"text/tab-separated-values; charset=utf-8")
            return self.reply(404,{"error":"Not found"})
        def do_POST(self):
            if urlparse(self.path).path!="/v1/agents": return self.reply(404,{"error":"Not found"})
            if not self.authorized(): return self.reply(401,{"error":"Authentication required"})
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=MAX_REQUEST: return self.reply(413,{"error":"Invalid body size"})
                agent=Agent.from_dict(json.loads(self.rfile.read(length)))
                registry.put(agent)
            except (ValueError,TypeError): return self.reply(400,{"error":"Invalid agent record"})
            return self.reply(200,{"ok":True,"id":agent.id})
    return Handler

def default_cowork_root():
    local=Path(os.environ.get("LOCALAPPDATA",str(Path.home()/"AppData/Local")))
    candidates=list((local/"Packages").glob("Claude_*/LocalCache/Roaming/Claude/local-agent-mode-sessions"))
    candidates.append(Path(os.environ.get("APPDATA",str(Path.home()/"AppData/Roaming")))/"Claude/local-agent-mode-sessions")
    return next((str(p) for p in candidates if p.is_dir()),"")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--bind",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8086)
    parser.add_argument("--codex-home",default=str(Path.home()/".codex"))
    parser.add_argument("--cowork-root",default=default_cowork_root())
    parser.add_argument("--token-file",type=Path)
    parser.add_argument("--export",type=Path,help="Write a one-shot native TSV snapshot and exit")
    args=parser.parse_args()
    token=args.token_file.read_text(encoding="utf-8").strip() if args.token_file else os.environ.get("PAPEROS_BRIDGE_TOKEN","")
    local_only=args.bind in {"127.0.0.1","localhost","::1"}
    if not local_only and len(token)<24: parser.error("LAN binding requires a token file containing at least 24 characters")
    registry=Registry([CodexLocal(args.codex_home),CoworkLocal(args.cowork_root)],Path(__file__).parent/"data/pushed.json")
    if args.export:
        args.export.parent.mkdir(parents=True,exist_ok=True)
        args.export.write_bytes(tsv(registry.snapshot())); print(f"Wrote {args.export}"); return
    server=ThreadingHTTPServer((args.bind,args.port),make_handler(registry,token,not local_only))
    print(f"PaperOS Bridge: http://{args.bind}:{args.port} (read-only local adapters)",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=="__main__": main()
