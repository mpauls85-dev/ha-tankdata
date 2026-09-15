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
    assert raw["version"] == 1


async def add_consumer(hass, entry, data=None):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "consumer"), context={"source": "user"}, data=data or config()
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    return list(entry.subentries)[-1]


async def test_subentry_lifecycle(hass):
    entry = await create_tank(hass)
    sid = await add_consumer(hass, entry)
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    at = dt_util.utcnow() + timedelta(seconds=1)
    await entry.runtime_data.ingest(sid, 10, "L", at.isoformat())
    await entry.runtime_data.ingest(
        sid, 11, "L", (at + timedelta(seconds=60)).isoformat()
    )
    assert replay(entry.runtime_data.data)["consumed"] == 1
    saved = deepcopy(entry.runtime_data.data["events"])
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.runtime_data.data["events"] == saved
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "consumer"),
        context={"source": "reconfigure", "subentry_id": sid},
        data=config(entity_id="sensor.changed"),
    )
    assert result["type"] == "abort"
    await hass.async_block_till_done()
    assert entry.subentries[sid].data["entity_id"] == "sensor.changed"
    hass.config_entries.async_remove_subentry(entry, sid)
    await hass.async_block_till_done()
    assert entry.runtime_data.data["events"] == saved
    assert not entry.subentries


async def test_consumer_devices_and_upgrade(hass):
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entry = await create_tank(hass)
    first = await add_consumer(hass, entry)
    second = await add_consumer(
        hass, entry, config(name="Second", entity_id="sensor.second")
    )
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    def check():
        parent = devices.async_get_device_by_identifier(
            ("ha_tankdata", entry.entry_id), entry.entry_id
        )
        assert parent.config_subentry_id is None
        registered = er.async_entries_for_config_entry(entities, entry.entry_id)
        assert len(registered) == 5
        for entity in registered:
            assert hass.states.get(entity.entity_id).state not in {
                "unavailable",
                "unknown",
            }
            device = devices.async_get(entity.device_id)
            assert device.config_subentry_id == entity.config_subentry_id
            if entity.config_subentry_id:
                assert device.via_device_id == parent.id
            else:
                assert device.id == parent.id
        return parent, registered

    parent, registered = check()
    await call(hass, entry, "record_refill", liters=25, event_id="before-upgrade")
    saved = deepcopy(entry.runtime_data.data["events"])
    ids = {e.unique_id: e.entity_id for e in registered}
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Reproduce the old release's persisted parent ownership and entity links.
    devices.async_update_device(parent.id, new_config_subentry_id=first)
    for entity in registered:
        if entity.config_subentry_id:
            entities.async_update_entity(entity.entity_id, device_id=parent.id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    _, restored = check()
    assert {e.unique_id: e.entity_id for e in restored} == ids
    assert entry.runtime_data.data["events"] == saved
    hass.config_entries.async_remove_subentry(entry, second)
    await hass.async_block_till_done()
    assert len(er.async_entries_for_config_entry(entities, entry.entry_id)) == 4
    assert devices.async_get(parent.id).config_subentry_id is None
