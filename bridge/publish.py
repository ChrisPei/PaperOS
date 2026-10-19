"""Push status metadata from a Cowork/Codex hook or your own agent."""
import argparse,json,time,urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--url",default="http://127.0.0.1:8086")
    p.add_argument("--token-file",required=True,type=Path)
    p.add_argument("--id",required=True)
    p.add_argument("--source",required=True)
    p.add_argument("--title",required=True)
    p.add_argument("--state",required=True,choices=["running","waiting","completed","failed","idle","stopped"])
    a=p.parse_args()
    data=json.dumps({"id":a.id,"source":a.source,"title":a.title,"state":a.state,"updated_at":int(time.time())}).encode()
    req=urllib.request.Request(a.url.rstrip('/')+"/v1/agents",data=data,headers={"Content-Type":"application/json","Authorization":"Bearer "+a.token_file.read_text().strip()})
    with urllib.request.urlopen(req,timeout=3) as response: print(response.status)

if __name__=="__main__": main()
