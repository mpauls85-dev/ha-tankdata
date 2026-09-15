"""Cross-feature regressions and failure recovery."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from conftest import create_tank
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from test_consumption import config
from test_ha import add_consumer, call

from custom_components.ha_tankdata.model import replay, validate
from custom_components.ha_tankdata.store import TankStore


async def test_concurrent_books_and_recovery(hass):
    entry = await create_tank(hass)
    await asyncio.gather(
        *(
            call(hass, entry, "record_refill", liters=1, event_id=f"parallel-{i}")
            for i in range(10)
        )
    )
    assert replay(entry.runtime_data.data)["stock"] == 510
    assert len(entry.runtime_data.data["events"]) == 10
    before = deepcopy(entry.runtime_data.data)
    with patch.object(
        entry.runtime_data.store.store,
        "async_save",
        AsyncMock(side_effect=OSError("disk full")),
    ):
        with pytest.raises(HomeAssistantError):
            await call(hass, entry, "record_withdrawal", liters=5)
    assert entry.runtime_data.data == before
    await call(hass, entry, "record_withdrawal", liters=5)
    assert entry.runtime_data.available
    assert replay(entry.runtime_data.data)["stock"] == 505
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert replay(entry.runtime_data.data)["stock"] == 505


async def test_correction_closes_running_interval_atomically(hass):
    entry = await create_tank(hass)
    sid = await add_consumer(hass, entry, config("running", rate_lph=60))
    start = dt_util.utcnow() + timedelta(seconds=1)
    with patch(
        "custom_components.ha_tankdata.runtime.dt_util.utcnow", return_value=start
    ):
        await entry.runtime_data.ingest(sid, "on", None, start.isoformat())
    correction_at = start + timedelta(seconds=60)
    with patch(
        "custom_components.ha_tankdata.runtime.dt_util.utcnow",
        return_value=correction_at,
    ):
        await call(hass, entry, "apply_correction", liters=400, event_id="measure")
    assert replay(entry.runtime_data.data)["stock"] == 400
    assert replay(entry.runtime_data.data)["consumed"] == 1
    with patch(
        "custom_components.ha_tankdata.runtime.dt_util.utcnow",
        return_value=start + timedelta(seconds=120),
    ):
        await entry.runtime_data.ingest(
            sid, "off", None, (start + timedelta(seconds=120)).isoformat()
        )
    assert replay(entry.runtime_data.data)["stock"] == 399
    assert replay(entry.runtime_data.data)["consumed"] == 2
    events = entry.runtime_data.data["events"]
    assert [e["kind"] for e in events] == ["consumption", "correction", "consumption"]


@pytest.mark.parametrize("mode", ["flow", "running", "power"])
async def test_reload_during_operation_does_not_bridge_downtime(hass, mode):
    cfg = config(mode, rate_lph=60, on_threshold_w=20, off_threshold_w=10)
    entry = await create_tank(hass)
    sid = await add_consumer(hass, entry, cfg)
    value, unit = {
        "flow": ("60", "L/h"),
        "running": ("on", None),
        "power": ("20", "W"),
    }[mode]
    start = dt_util.utcnow() + timedelta(seconds=1)
    await entry.runtime_data.ingest(sid, value, unit, start.isoformat())
    assert await hass.config_entries.async_reload(entry.entry_id)
    await entry.runtime_data.ingest(
        sid, value, unit, (start + timedelta(seconds=60)).isoformat()
    )
    assert replay(entry.runtime_data.data)["consumed"] == 0
    await entry.runtime_data.ingest(
        sid, value, unit, (start + timedelta(seconds=120)).isoformat()
    )
    assert replay(entry.runtime_data.data)["consumed"] == 1


async def test_actual_source_listener_and_cleanup(hass):
    entry = await create_tank(hass)
    await add_consumer(hass, entry, config(max_rate_lph=1e12))
    hass.states.async_set("sensor.source", "10", {"unit_of_measurement": "L"})
    await hass.async_block_till_done()
    hass.states.async_set("sensor.source", "11", {"unit_of_measurement": "L"})
    await hass.async_block_till_done()
    assert replay(entry.runtime_data.data)["consumed"] == 1
    assert await hass.config_entries.async_reload(entry.entry_id)
    hass.states.async_set("sensor.source", "12", {"unit_of_measurement": "L"})
    await hass.async_block_till_done()
    assert replay(entry.runtime_data.data)["consumed"] == 2
    assert len(entry.runtime_data.unsubscribers) == 3
    old_runtime = entry.runtime_data
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert not old_runtime.active
    assert not old_runtime.unsubscribers
    assert Path(old_runtime.store.store.path).exists()


async def test_corrupted_derived_volume_is_rejected(hass):
    entry = await create_tank(hass)
    sid = await add_consumer(hass, entry)
    start = dt_util.utcnow() + timedelta(seconds=1)
    await entry.runtime_data.ingest(sid, 10, "L", start.isoformat())
    await entry.runtime_data.ingest(
        sid, 11, "L", (start + timedelta(seconds=60)).isoformat()
    )
    invalid = deepcopy(entry.runtime_data.data)
    invalid["events"][-1]["liters"] = 900
    with pytest.raises(ValueError, match="differs"):
        validate(invalid)


async def test_future_store_prevents_setup_without_overwrite(hass):
    entry = await create_tank(hass)
    store = entry.runtime_data.store
    await hass.config_entries.async_unload(entry.entry_id)
    path = Path(store.store.path)
    raw = json.loads(path.read_text())
    raw["version"] = 99
    content = json.dumps(raw)
    path.write_text(content)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert path.read_text() == content


async def test_counter_startup_waits_for_first_source_report(hass):
    entry = await create_tank(hass)
    sid = await add_consumer(hass, entry)
    start = dt_util.utcnow() - timedelta(seconds=60)
    await entry.runtime_data.ingest(sid, 10, "L", start.isoformat())
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.runtime_data.data["sources"][sid]["value"] == 10
    await entry.runtime_data.ingest(sid, 11, "L", dt_util.utcnow().isoformat())
    assert replay(entry.runtime_data.data)["consumed"] == 1


async def test_cancelled_caller_cannot_release_an_inflight_write(hass):
    entry = await create_tank(hass)
    runtime = entry.runtime_data
    started, release = asyncio.Event(), asyncio.Event()
    original_save = runtime.store.save

    async def delayed_save(data):
        started.set()
        await release.wait()
        await original_save(data)

    with patch.object(runtime.store, "save", delayed_save):
        first = asyncio.create_task(runtime.book("refill", 1, "cancelled-caller"))
        await started.wait()
        first.cancel()
        second = asyncio.create_task(runtime.book("refill", 2, "second-caller"))
        await asyncio.sleep(0)
        assert runtime.lock.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
    assert replay(runtime.data)["stock"] == 503
    assert await runtime.store.load() == runtime.data
    await runtime.book("refill", 1, "cancelled-caller")
    assert replay(runtime.data)["stock"] == 503


@pytest.mark.parametrize("fixture", ["phase3_store.json", "phase4_store.json"])
async def test_previous_real_store_loads_unchanged(hass, fixture):
    raw = json.loads((Path("tests/fixtures") / fixture).read_text())
    entry_id = raw["key"].removeprefix("ha_tankdata.")
    store = TankStore(hass, entry_id)
    path = Path(store.store.path)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(raw))
    loaded = await store.load()
    assert loaded == raw["data"]
    await store.save(loaded)
    assert await TankStore(hass, entry_id).load() == loaded
