import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("paperos_bridge",ROOT/"bridge/bridge.py")
bridge=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=bridge
spec.loader.exec_module(bridge)

class StatusTests(unittest.TestCase):
    def test_completion_is_not_inferred_from_inactivity(self):
        events=[{"type":"event_msg","payload":{"type":"task_started"}}]
        self.assertEqual(bridge.codex_state(events,100,500),"unknown")
        events.append({"type":"event_msg","payload":{"type":"task_complete"}})
        self.assertEqual(bridge.codex_state(events,100,500),"completed")

    def test_resuming_after_question_clears_waiting(self):
        events=[{"type":"response_item","payload":{"type":"custom_tool_call","name":"request_user_input_async"}}]
        self.assertEqual(bridge.codex_state(events,100,110),"waiting")
        events.append({"type":"response_item","payload":{"type":"reasoning"}})
        self.assertEqual(bridge.codex_state(events,100,110),"running")

    def test_readonly_codex_adapter_does_not_publish_transcripts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); rollout=root/"rollout.jsonl"
            secret="private prompt and credential that must not leave the computer"
            rollout.write_text(json.dumps({"type":"event_msg","payload":{"type":"task_complete","last_agent_message":secret}})+"\n")
            with closing(sqlite3.connect(root/"state_5.sqlite")) as c, c:
                c.execute("CREATE TABLE threads(id TEXT,title TEXT,rollout_path TEXT,updated_at INTEGER,archived INTEGER)")
                c.execute("INSERT INTO threads VALUES(?,?,?,?,0)",("one","Test title",str(rollout),int(time.time())))
            snapshot=bridge.Registry([bridge.CodexLocal(root)]).snapshot()
            encoded=json.dumps(snapshot)
            self.assertNotIn(secret,encoded)
            self.assertNotIn(str(rollout),encoded)
            self.assertEqual(snapshot["agents"][0]["state"],"completed")

    def test_missing_cowork_state_stays_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"session_one.json"
            p.write_text(json.dumps({"id":"one","title":"A task"}))
            agents,_=bridge.CoworkLocal(d).collect()
            self.assertEqual(agents[0].state,"unknown")

    def test_stale_push_is_not_reported_as_running(self):
        registry=bridge.Registry(ttl=5)
        registry.put(bridge.Agent("one","Cowork","A task","running",int(time.time())-6))
        self.assertEqual(registry.snapshot()["agents"][0]["state"],"unknown")

    def test_native_protocol_preserves_unicode_and_escapes_controls(self):
        snapshot={"generated_at":100,"agents":[{"id":"one","source":"Cowork","title":"会议\t记录\n下一行","state":"waiting","updated_at":99}]}
        lines=bridge.tsv(snapshot).decode().splitlines()
        self.assertEqual(len(lines),2)
        self.assertEqual(len(lines[1].split("\t")),5)
        self.assertIn("会议 记录 下一行",lines[1])

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.registry=bridge.Registry()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),bridge.make_handler(self.registry,"test-token"))
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True); self.worker.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join()
    def post(self,row,token="test-token"):
        req=urllib.request.Request(self.base+"/v1/agents",data=json.dumps(row).encode(),headers={"Authorization":"Bearer "+token})
        return urllib.request.urlopen(req,timeout=2)
    def test_token_required_for_push(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.post({"id":"one","source":"Cowork","state":"running"},"wrong")
        self.assertEqual(context.exception.code,401)
    def test_valid_status_reaches_native_endpoint(self):
        with self.post({"id":"one","source":"Cowork","title":"会议记录","state":"waiting"}) as response:
            self.assertEqual(response.status,200)
        with urllib.request.urlopen(self.base+"/v1/agents.tsv",timeout=2) as response:
            text=response.read().decode()
        self.assertIn("Cowork\t会议记录\twaiting",text)
    def test_invalid_state_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.post({"id":"one","source":"Cowork","state":"execute-a-command"})
        self.assertEqual(context.exception.code,400)

if __name__=="__main__": unittest.main()
