"""Render the real native UI; PNG conversion does not replace the renderer."""
from pathlib import Path
import subprocess
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
def linux(path): return "/mnt/"+path.drive[0].lower()+str(path)[2:].replace("\\","/")

def main():
    out=ROOT/"preview"; out.mkdir(exist_ok=True)
    apps=ROOT/"build/preview-apps"; apps.mkdir(exist_ok=True)
    executable=["wsl","-d","Ubuntu-24.04","--",linux(ROOT/"build/host/paperos")]
    for package in ("clock.papp","notes.papp"):
        subprocess.run(executable+["--app-root",linux(apps),"--install",linux(ROOT/"examples"/package)],check=True,capture_output=True)
    for screen in ("home","agents","clock","notes","system"):
        pgm=out/(screen+".pgm")
        command=executable+["--font",linux(ROOT/"assets/NotoSansCJKsc-Regular.otf"),"--screen",screen,"--app-root",linux(apps),"--packages",linux(ROOT/"examples"),"--feed",linux(ROOT/"tests/fixtures/agents.tsv"),"--render",linux(pgm),"--note",linux(out/"note.txt")]
        if screen in ("clock","notes"):
            command.append('--standalone')
        subprocess.run(command,check=True)
        with Image.open(pgm) as image:
            image.save(out/(screen+".png"))
    print(f"Native UI previews: {out}")

if __name__=="__main__": main()
