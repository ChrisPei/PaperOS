"""Regressions for the native KOReader helper and store update identity."""
from pathlib import Path
import importlib.util,json,tarfile,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('paperos_catalog',ROOT/'scripts/build-app-catalog.py')
catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)

class KOReaderPackageTests(unittest.TestCase):
    def test_archiver_keeps_native_overlay_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=root/'reader.papp';app.mkdir()
            (app/'run.sh').write_text('#!/bin/sh\nexit 0\n')
            (app/'paperos-overlay').write_bytes(b'\x7fELF'+bytes(60))
            (app/'runtime.ext3.gz').write_bytes(b'compressed data')
            archive=root/'app.tar.gz';catalog.archive_app(app,archive)
            with tarfile.open(archive) as t:
                self.assertEqual(t.getmember('reader.papp/paperos-overlay').mode,0o755)
                self.assertEqual(t.getmember('reader.papp/run.sh').mode,0o755)
                self.assertEqual(t.getmember('reader.papp/runtime.ext3.gz').mode,0o644)

    def test_port_version_updates_the_existing_application_identity(self):
        release=json.loads((ROOT/'os/koreader-release.json').read_text())
        fields=dict(line.split('=',1) for line in (ROOT/'examples/koreader.papp/manifest.conf').read_text().splitlines() if '=' in line)
        self.assertEqual(fields['id'],'org.paperos.koreader')
        self.assertEqual(fields['version'],release['port_version'])
        self.assertTrue(fields['version'].startswith(release['upstream_version']+'.'))
        self.assertIn('glibc',{s['name'] for s in release['gnu_sources']})
        self.assertIn('gcc-14',{s['name'] for s in release['gnu_sources']})

if __name__=='__main__':unittest.main()
