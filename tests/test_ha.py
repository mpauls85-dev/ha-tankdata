import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import create_tank
from homeassistant.exceptions import HomeAssistantError
from test_consumption import config

from custom_components.ha_tankdata.model import replay
from custom_components.ha_tankdata.store import TankStore


async def call(hass, entry, action, **data):
    await hass.services.async_call(
        "ha_tankdata",
        action,
        {"config_entry_id": entry.entry_id, **data},
        blocking=True,
    )


async def test_manual_lifecycle(hass):
    a = await create_tank(hass)
    b = await create_tank(hass, "Second", 100)
    await call(hass, a, "record_refill", liters=100, event_id="refill")
    await call(hass, a, "record_refill", liters=100, event_id="refill")
    await call(hass, a, "record_observation", liters=590)
    await call(hass, a, "record_withdrawal", liters=10)
    await call(hass, a, "apply_correction", liters=580)
    assert replay(a.runtime_data.data)["stock"] == 580
    await call(hass, a, "reset_calibration")
    await call(hass, a, "recalculate")
    assert replay(a.runtime_data.data)["stock"] == 590
    assert replay(b.runtime_data.data)["stock"] == 100
    saved = deepcopy(a.runtime_data.data)
    assert await hass.config_entries.async_reload(a.entry_id)
    assert a.runtime_data.data == saved
    assert len(hass.states.async_all("sensor")) == 6
    assert await hass.config_entries.async_unload(a.entry_id)
    with pytest.raises(HomeAssistantError):
        await call(hass, a, "recalculate")
    await call(hass, b, "record_refill", liters=1)
    assert await hass.config_entries.async_setup(a.entry_id)
    assert a.runtime_data.data == saved


async def test_failed_write_is_not_acknowledged(hass):
    entry = await create_tank(hass)
    runtime = entry.runtime_data
    before = deepcopy(runtime.data)
    runtime.store.store.async_save = AsyncMock(return_value=None)
    with pytest.raises(HomeAssistantError):
        await call(hass, entry, "record_refill", liters=1)
    assert runtime.data == before
    assert not runtime.available


@pytest.mark.parametrize(
    "content",
    [
        "{bad",
        "[]",
        "null",
        "{}",
        '{"version":2,"minor_version":1,"key":"ha_tankdata.bad","data":{}}',
        '{"version":1,"minor_version":2,"key":"ha_tankdata.bad","data":{}}',
    ],
)
async def test_corrupt_store_preserved(hass, content):
    store = TankStore(hass, "bad")
    path = Path(store.store.path)
    path.parent.mkdir(exist_ok=True)
    path.write_text(content)
    with pytest.raises((ValueError, KeyError)):
        await store.load()
    assert path.read_text() == content


async def test_invalid_config_and_disk_reload(hass):
    result = await hass.config_entries.flow.async_init(
        "ha_tankdata",
        context={"source": "user"},
        data={"name": "Bad", "capacity": 10, "initial": 11},
    )
    assert result["errors"] == {"base": "invalid_tank"}
    entry = await create_tank(hass)
    data = await TankStore(hass, entry.entry_id).load()
    assert data == entry.runtime_data.data
    raw = json.loads(Path(entry.runtime_data.store.store.path).read_text())
    assert raw["version"] == 3


async def add_consumer(hass, entry, data=None):
    result = await hass.config_entries.flow.async_init(
        "ha_tankdata", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "consumer"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"tank_entry_id": entry.entry_id, **(data or config())}
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    assert result["result"].state.value == "loaded"
    return result["result"].data["source_id"]


async def test_consumer_lifecycle(hass):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.ha_tankdata.configuration import consumers

    entry = await create_tank(hass)
    sid = await add_consumer(hass, entry)
    child = consumers(hass, entry.entry_id)[sid]
    at = dt_util.utcnow() + timedelta(seconds=1)
    await entry.runtime_data.ingest(sid, 10, "L", at.isoformat())
    await entry.runtime_data.ingest(
        sid, 11, "L", (at + timedelta(seconds=60)).isoformat()
    )
    saved = deepcopy(entry.runtime_data.data["events"])
    assert replay(entry.runtime_data.data)["consumed"] == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert child.runtime_data is entry.runtime_data
    result = await hass.config_entries.flow.async_init(
        "ha_tankdata",
        context={"source": "reconfigure", "entry_id": child.entry_id},
        data=config(entity_id="sensor.changed"),
    )
    assert result["type"] == "abort", result
    await hass.async_block_till_done()
    assert child.data["config"]["entity_id"] == "sensor.changed"
    await hass.config_entries.async_remove(child.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.data["events"] == saved
    assert not entry.runtime_data.consumers
    assert not entry.subentries
