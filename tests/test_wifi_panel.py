"""Native Wi-Fi actions through the real Unix control protocol."""
from pathlib import Path
import os,socket,subprocess,tempfile,threading,unittest
from urllib.parse import parse_qs

ROOT=Path(__file__).resolve().parents[1]

class WiFiPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.state=self.path/'state.tsv';self.channel=self.path/'control.sock'
        self.state.write_text('paperos-services-v1\nnet\ttrue\tfalse\ttrue\t192.168.5.8\tHome\tfalse\t-\n'
            'wifi\t0\t-35\t密码\tHome\t486f6d65\n'
            'wifi-saved\t0\tHome\t486f6d65\ttrue\ttrue\t-35\n'
            'wifi-saved\t1\tOffice\t4f6666696365\tfalse\tfalse\t0\n')
        self.commands=[];self.stop=threading.Event();self.server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.server.bind(str(self.channel));self.server.listen(4);self.server.settimeout(.05)
        def receive():
            while not self.stop.is_set():
                try:client,_=self.server.accept()
                except socket.timeout:continue
                with client:
                    client.settimeout(2);raw=b''
                    while b'\r\n\r\n' not in raw:raw+=client.recv(4096)
                    header,body=raw.split(b'\r\n\r\n',1)
                    length=int(next(x.split(b':',1)[1] for x in header.split(b'\r\n') if x.lower().startswith(b'content-length:')))
                    while len(body)<length:body+=client.recv(4096)
                    self.commands.append(parse_qs(body.decode(),keep_blank_values=True))
                    client.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nOK\n')
        self.thread=threading.Thread(target=receive);self.thread.start()
    def tearDown(self):
        self.stop.set();self.thread.join(3);self.server.close();self.tmp.cleanup()
    def render(self,*taps):
        args=[str(ROOT/'build/host/paperos'),'--font',str(ROOT/'assets/NotoSansCJKsc-Regular.otf'),
            '--screen','network','--services-file',str(self.state),'--services-socket',str(self.channel),
            '--app-root',str(self.path/'apps'),'--allow-commands','--render',str(self.path/'image.pgm')]
        for x,y in taps:args+=['--tap',str(x),str(y)]
        subprocess.run(args,check=True,capture_output=True,env={**os.environ,'TZ':'CST-8'},timeout=5)
        return (self.path/'image.pgm').read_bytes()
    def test_saved_offline_network_connects_without_a_password_prompt(self):
        self.render((300,270),(300,420),(300,335))
        self.assertEqual(self.commands,[{'cmd':['network-connect'],'ssid':['4f6666696365'],'saved':['true']}])
    def test_forget_requires_two_deliberate_taps(self):
        self.render((300,270),(300,420),(300,510));self.assertEqual(self.commands,[])
        self.render((300,270),(300,420),(300,510),(300,510))
        self.assertEqual(self.commands,[{'cmd':['network-forget'],'ssid':['4f6666696365']}])
    def test_nearby_saved_network_opens_its_profile(self):
        self.render((300,340),(300,335))
        self.assertEqual(self.commands,[{'cmd':['network-connect'],'ssid':['486f6d65'],'saved':['true']}])
    def test_saved_tab_retains_networks_when_no_scan_is_available(self):
        self.state.write_text('\n'.join(line for line in self.state.read_text().splitlines() if not line.startswith('wifi\t'))+'\n')
        nearby=self.render();saved=self.render((300,270));self.assertNotEqual(nearby,saved)
        self.render((300,270),(300,420),(300,335))
        self.assertEqual(self.commands[0]['ssid'],['4f6666696365'])

if __name__=='__main__':unittest.main()
