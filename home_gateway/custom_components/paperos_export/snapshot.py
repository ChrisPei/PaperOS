"""The exporter copies only selected values and units, never all HA attributes."""
import json
import os
from pathlib import Path
import re
import tempfile
import time

ENTITY = re.compile(r'^(sensor|binary_sensor|light|switch|fan|climate)\.[a-z0-9_]{1,128}$')


def selected_entities(data):
    entities = data.get('entities', [])
    if (not isinstance(entities, list) or not 1 <= len(entities) <= 12
            or any(not isinstance(e, str) or not ENTITY.fullmatch(e) for e in entities)
            or len(set(entities)) != len(entities)):
        raise ValueError('Invalid selected metrics')
    return tuple(entities)


def build_snapshot(entities, get_state):
    states = {}
    for entity in entities:
        state = get_state(entity)
        states[entity] = {
            'state': str(state.state)[:128] if state is not None else 'unavailable',
            'unit': str(state.attributes.get('unit_of_measurement') or '')[:32] if state is not None else '',
        }
    return {'version': 1, 'at': int(time.time()), 'states': states}


def write_snapshot(path, snapshot):
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.export-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(snapshot, output, ensure_ascii=False, separators=(',', ':'))
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o644)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
