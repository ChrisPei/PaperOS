"""Export a NAS-admin-defined subset of HA state to an isolated read-only app."""
import asyncio
from datetime import timedelta
import json
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .snapshot import build_snapshot, selected_entities, write_snapshot

DOMAIN = 'paperos_export'
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


async def async_setup(hass, config):
    root = Path(hass.config.path('paperos-readonly'))
    raw = await hass.async_add_executor_job((root / 'scope.json').read_text)
    entities = selected_entities(json.loads(raw))
    lock = asyncio.Lock()

    async def export(_now=None):
        async with lock:
            # Read hass.states only on HA's event loop. There are no service calls.
            data = build_snapshot(entities, hass.states.get)
            await hass.async_add_executor_job(write_snapshot, root / 'export.json', data)

    await export()
    cancel = async_track_time_interval(hass, export, timedelta(seconds=30),
                                      name='paperos_selected_metrics', cancel_on_shutdown=True)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, lambda _event: cancel())
    hass.data[DOMAIN] = {'selected_count': len(entities), 'cancel': cancel}
    return True
