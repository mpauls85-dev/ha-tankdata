"""Controlled source events through a fully started HA process."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from math import isclose
from pathlib import Path

from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util


async def add_consumer(hass, tank, data):
    flow = await hass.config_entries.flow.async_init(
        "ha_tankdata", context={"source": "user"}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"next_step_id": "consumer"}
    )
    return await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"tank_entry_id": tank.entry_id, **data}
    )


async def main():
    hass = HomeAssistant("/config")
    loader.async_setup(hass)
    assert await async_from_config_dict({"homeassistant": {}}, hass)
    await hass.async_start()
    try:
        from custom_components.ha_tankdata.model import replay

        result = await hass.config_entries.flow.async_init(
            "ha_tankdata",
            context={"source": "user"},
            data={"name": "Source acceptance", "capacity": 1000, "initial": 500},
        )
        entry = result["result"]
        await hass.async_block_till_done()
        config = {
            "name": "Counter",
            "entity_id": "sensor.test_counter",
            "mode": "counter",
            "max_gap_seconds": 3600,
            "max_rate_lph": 100,
        }
        for entity_id in ("sensor.test_counter", "sensor.other_counter"):
            result = await add_consumer(hass, entry, {**config, "entity_id": entity_id})
            assert result["type"] == "create_entry"
            await hass.async_block_till_done()
        base = dt_util.utcnow() + timedelta(seconds=1)
        for seconds, value in [(0, "10"), (60, "11"), (60, "11"), (120, "12")]:
            at = base + timedelta(seconds=seconds)
            state = State(
                "sensor.test_counter",
                value,
                {"unit_of_measurement": "L"},
                last_updated=at,
                last_reported=at,
            )
            hass.bus.async_fire(
                "state_changed",
                {"entity_id": state.entity_id, "new_state": state, "old_state": None},
            )
            await hass.async_block_till_done()
        assert replay(entry.runtime_data.data)["consumed"] == 2
        saved = deepcopy(entry.runtime_data.data["events"])
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert entry.runtime_data.data["events"] == saved
        child = next(iter(entry.runtime_data.consumers.values()))
        result = await hass.config_entries.flow.async_init(
            "ha_tankdata",
            context={"source": "reconfigure", "entry_id": child.entry_id},
            data={**config, "entity_id": "sensor.replaced"},
        )
        assert result["type"] == "abort"
        await hass.async_block_till_done()
        await hass.config_entries.async_remove(child.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.data["events"] == saved
        assert len(entry.runtime_data.unsubscribers) == 3
        flow = {**config, "mode": "flow", "entity_id": "sensor.flow"}
        result = await add_consumer(hass, entry, flow)
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        base = dt_util.utcnow() + timedelta(seconds=1)
        for seconds, value in [(0, "60"), (60, "30"), (180, "0")]:
            at = base + timedelta(seconds=seconds)
            state = State(
                "sensor.flow",
                value,
                {"unit_of_measurement": "L/h"},
                last_updated=at,
                last_reported=at,
            )
            hass.bus.async_fire(
                "state_changed",
                {"entity_id": state.entity_id, "new_state": state, "old_state": None},
            )
            await hass.async_block_till_done()
        assert replay(entry.runtime_data.data)["consumed"] == 4
        saved = deepcopy(entry.runtime_data.data["events"])
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert entry.runtime_data.data["events"] == saved
        running = {
            **config,
            "mode": "running",
            "entity_id": "binary_sensor.running",
            "rate_lph": 60,
        }
        result = await add_consumer(hass, entry, running)
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        base = dt_util.utcnow() + timedelta(seconds=1)
        for seconds, value in [(0, "off"), (60, "on"), (180, "off")]:
            at = base + timedelta(seconds=seconds)
            state = State(
                "binary_sensor.running", value, last_updated=at, last_reported=at
            )
            hass.bus.async_fire(
                "state_changed",
                {"entity_id": state.entity_id, "new_state": state, "old_state": None},
            )
            await hass.async_block_till_done()
        assert replay(entry.runtime_data.data)["consumed"] == 6
        assert replay(entry.runtime_data.data)["runtime"] == 120
        saved = deepcopy(entry.runtime_data.data["events"])
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert entry.runtime_data.data["events"] == saved
        power = {
            **config,
            "mode": "power",
            "entity_id": "sensor.power",
            "rate_lph": 60,
            "on_threshold_w": 20,
            "off_threshold_w": 10,
        }
        result = await add_consumer(hass, entry, power)
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        base = dt_util.utcnow() + timedelta(seconds=1)
        for seconds, value in [(0, "15"), (60, "20"), (120, "15"), (180, "10")]:
            at = base + timedelta(seconds=seconds)
            state = State(
                "sensor.power",
                value,
                {"unit_of_measurement": "W"},
                last_updated=at,
                last_reported=at,
            )
            hass.bus.async_fire(
                "state_changed",
                {"entity_id": state.entity_id, "new_state": state, "old_state": None},
            )
            await hass.async_block_till_done()
        assert replay(entry.runtime_data.data)["consumed"] == 8
        assert replay(entry.runtime_data.data)["runtime"] == 240
        saved = deepcopy(entry.runtime_data.data["events"])
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert entry.runtime_data.data["events"] == saved
        timer = {
            **config,
            "mode": "running",
            "entity_id": "binary_sensor.timer",
            "rate_lph": 60,
            "max_gap_seconds": 120,
        }
        hass.states.async_set("binary_sensor.timer", "on")
        result = await add_consumer(hass, entry, timer)
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        print(
            "Testing real 30-second timer with an unchanged running source", flush=True
        )
        await asyncio.sleep(31)
        await hass.async_block_till_done()
        total = replay(entry.runtime_data.data)["consumed"]
        assert 8.49 < total < 8.54, total
        hass.states.async_set("binary_sensor.timer", "off")
        await hass.async_block_till_done()
        for action, payload in [
            ("apply_correction", {"liters": 400}),
            ("record_refill", {"liters": 100}),
            ("record_withdrawal", {"liters": 10}),
            ("record_observation", {"liters": 490}),
            ("recalculate", {}),
            ("reset_calibration", {}),
        ]:
            await hass.services.async_call(
                "ha_tankdata",
                action,
                {"config_entry_id": entry.entry_id, **payload},
                blocking=True,
            )
        state = replay(entry.runtime_data.data)
        assert isclose(state["stock"], 590 - state["consumed"], abs_tol=1e-8)
        saved = deepcopy(entry.runtime_data.data["events"])
        for _ in range(2):
            await hass.services.async_call(
                "ha_tankdata",
                "recalculate",
                {"config_entry_id": entry.entry_id},
                blocking=True,
            )
        assert entry.runtime_data.data["events"] == saved
        assert await hass.config_entries.async_reload(entry.entry_id)
        assert entry.runtime_data.data["events"] == saved
        Path("/config/phase8_expected.json").write_text(
            json.dumps(
                {
                    e.entry_id: e.runtime_data.data["events"]
                    for e in hass.config_entries.async_entries("ha_tankdata")
                    if e.data.get("kind") != "consumer"
                }
            )
        )
        print(
            "SOURCE ACCEPTANCE PASSED: four modes, real timer, manual events and reload"
        )
    finally:
        await hass.async_stop()


asyncio.run(main())
