"""Wooden-fish counters through the actual native renderer and app manager."""
from datetime import datetime
import gzip
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]


class MuyuTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.directory=Path(self.tmp.name)
        self.state=self.directory/'merit.state'
        self.binary=ROOT/'build/host/paperos'
        self.services=self.directory/'services.tsv'
        self.services.write_text('paperos-services-v1\nlock\tfalse\t300\t1\n')

    def tearDown(self):self.tmp.cleanup()

    def render(self,*taps,state=None):
        image=self.directory/'screen.pgm'
        args=[str(self.binary),'--font',str(ROOT/'assets/NotoSansCJKsc-Regular.otf'),
              '--screen','muyu','--standalone','--render',str(image),'--muyu-state',str(state or self.state),
              '--services-file',str(self.services),'--app-root',str(self.directory/'apps')]
        for x,y in taps:args+=['--tap',str(x),str(y)]
        subprocess.run(args,check=True,capture_output=True,env={**os.environ,'TZ':'CST-8'})
        return image.read_bytes().split(b'\n',3)[3]

    def test_taps_survive_process_restart(self):
        self.render((300,480),(310,470),(290,500))
        self.assertEqual(self.state.read_text().split()[1:3],['3','3'])
        saved=self.state.read_bytes()
        self.render()
        self.assertEqual(self.state.read_bytes(),saved)

    def test_direct_package_entry_opens_muyu_without_arguments(self):
        binary=self.directory/'paperos-muyu'
        shutil.copyfile(self.binary,binary);binary.chmod(0o755)
        subprocess.run([str(binary),'--font',str(ROOT/'assets/NotoSansCJKsc-Regular.otf'),
            '--render',str(self.directory/'direct.pgm'),'--muyu-state',str(self.state),
            '--services-file',str(self.services),'--tap','300','480'],check=True,capture_output=True)
        self.assertEqual(self.state.read_text().split()[1:3],['1','1'])

    def test_compressed_entry_decompresses_and_preserves_counter(self):
        package=self.directory/'compressed.papp'
        data=self.directory/'data'
        package.mkdir();data.mkdir()
        shutil.copyfile(ROOT/'examples/muyu.papp/run.sh',package/'run.sh')
        (package/'paperos-muyu.gz').write_bytes(gzip.compress(self.binary.read_bytes()))
        args=['/bin/sh',str(package/'run.sh'),'--font',str(ROOT/'assets/NotoSansCJKsc-Regular.otf'),
            '--render',str(self.directory/'compressed.pgm'),'--services-file',str(self.services),'--tap','300','480']
        environment={**os.environ,'PAPEROS_APP_DIR':str(package),'PAPEROS_DATA_DIR':str(data)}
        subprocess.run(args,check=True,capture_output=True,env=environment)
        subprocess.run(args,check=True,capture_output=True,env=environment)
        self.assertEqual((data/'merit.state').read_text().split()[1:3],['2','2'])
        self.assertEqual((data/'paperos-muyu').read_bytes(),self.binary.read_bytes())
        self.assertFalse(list(data.glob('.muyu.*')))

    def test_daily_reset_keeps_total(self):
        self.state.write_text('paperos-muyu-v1\n7 3 2000-01-01\n')
        self.render((300,480))
        self.assertEqual(self.state.read_text().split()[1:3],['8','1'])

    def test_corrupt_compressed_entry_preserves_previous_binary_and_data(self):
        package=self.directory/'bad.papp';data=self.directory/'data'
        package.mkdir();data.mkdir()
        shutil.copyfile(ROOT/'examples/muyu.papp/run.sh',package/'run.sh')
        (package/'paperos-muyu.gz').write_bytes(b'corrupt package')
        (data/'paperos-muyu').write_bytes(b'previous binary')
        (data/'merit.state').write_bytes(b'previous counter')
        result=subprocess.run(['/bin/sh',str(package/'run.sh')],capture_output=True,
            env={**os.environ,'PAPEROS_APP_DIR':str(package),'PAPEROS_DATA_DIR':str(data)})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((data/'paperos-muyu').read_bytes(),b'previous binary')
        self.assertEqual((data/'merit.state').read_bytes(),b'previous counter')
        self.assertFalse(list(data.glob('.muyu.*')))

    def test_corrupt_record_is_not_overwritten(self):
        self.state.write_bytes(b'broken counter\n')
        self.render((300,480))
        self.assertEqual(self.state.read_bytes(),b'broken counter\n')

    def test_failed_save_does_not_add_unsaved_merit(self):
        baseline=self.render()
        failed=self.render((300,480),state=self.directory/'missing/merit.state')
        self.assertEqual(baseline[170*600:280*600],failed[170*600:280*600])
        self.assertFalse((self.directory/'missing/merit.state').exists())

    def test_lock_and_outside_taps_do_not_count(self):
        self.render((30,690),(300,710))
        self.assertFalse(self.state.exists())
        self.services.write_text('paperos-services-v1\nlock\ttrue\t300\t2\n')
        self.render((300,480))
        self.assertFalse(self.state.exists())

    def test_overflow_preserves_record(self):
        day=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        self.state.write_text(f'paperos-muyu-v1\n18446744073709551615 0 {day}\n')
        before=self.state.read_bytes()
        self.render((300,480))
        self.assertEqual(self.state.read_bytes(),before)

    def test_reinstall_preserves_app_data(self):
        apps=self.directory/'apps'
        base=[str(self.binary),'--app-root',str(apps)]
        subprocess.run(base+['--install',str(ROOT/'dist/muyu.papp')],check=True,capture_output=True)
        data=apps/'.data/org.paperos.muyu'
        data.mkdir(parents=True)
        state=data/'merit.state'
        self.render((300,480),state=state)
        before=state.read_bytes()
        subprocess.run(base+['--remove','org.paperos.muyu'],check=True,capture_output=True)
        self.assertEqual(state.read_bytes(),before)
        subprocess.run(base+['--install',str(ROOT/'dist/muyu.papp')],check=True,capture_output=True)
        self.assertEqual(state.read_bytes(),before)


if __name__=='__main__':unittest.main()
