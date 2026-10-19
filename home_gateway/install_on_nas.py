"""Run inside HA's /config bind mount. Payload contains no HA or device keys."""
import hashlib
import json
import os
from pathlib import Path
import py_compile
import re
import shutil


def install(payload):
    root = Path('/config')
    configuration = root / 'configuration.yaml'
    assert configuration.is_file() and (root / 'custom_components/xiaomi_home/manifest.json').is_file()
    original = configuration.read_bytes()
    assert not re.search(rb'^paperos_export\s*:', original, re.MULTILINE), 'Exporter already configured; inspect before updating'
    destinations = [root / 'custom_components/paperos_export', root / 'paperos-readonly',
                    root / 'paperos-readonly-project', root / '.paperos-readonly-backup']
    assert not any(p.exists() for p in destinations), 'Preserve existing PaperOS files'
    for directory in destinations:
        directory.mkdir(parents=True, mode=0o755)
    backup = root / '.paperos-readonly-backup/configuration.yaml'
    backup.write_bytes(original)
    backup.chmod(0o600)
    for relative, content in payload['files'].items():
        assert relative in {
            'custom_components/paperos_export/__init__.py',
            'custom_components/paperos_export/manifest.json',
            'custom_components/paperos_export/snapshot.py',
            'paperos-readonly/gateway.py', 'paperos-readonly/scope.json',
            'paperos-readonly-project/compose.yaml',
        }, 'Unexpected installation path'
        destination = root / relative
        destination.write_text(content, encoding='utf-8')
        destination.chmod(0o644)
        if destination.suffix == '.py':
            py_compile.compile(str(destination), doraise=True)
    updated = original + b'\n# PaperOS: export only selected metrics; no control endpoint.\npaperos_export:\n'
    temporary = configuration.with_name('.configuration-paperos-new.yaml')
    temporary.write_bytes(updated)
    shutil.copymode(configuration, temporary)
    os.replace(temporary, configuration)
    proof = {'version': 1, 'configuration_before_sha256': hashlib.sha256(original).hexdigest(),
             'configuration_after_sha256': hashlib.sha256(updated).hexdigest(),
             'selected_count': len(json.loads(payload['files']['paperos-readonly/scope.json'])['entities']),
             'kindle_ha_credentials_on_nas': False,
             'files': {name: hashlib.sha256(value.encode()).hexdigest() for name, value in payload['files'].items()}}
    (root / '.paperos-readonly-backup/installation.json').write_text(json.dumps(proof, indent=2))
    print('PAPEROS_READONLY_EXPORT_INSTALLED', proof['selected_count'], 'NO_HA_CREDENTIALS', flush=True)


if __name__ == '__main__':
    raise SystemExit('Use the generated installer payload from secure-mihome.py')
