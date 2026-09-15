"""Verify all previous ledgers in a new, fully bootstrapped HA process."""

import asyncio
import json
from pathlib import Path

from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry, entity_registry


async def main():
    hass = HomeAssistant("/config")
    loader.async_setup(hass)
    assert await async_from_config_dict({"homeassistant": {}}, hass)
    await hass.async_start()
    try:
        expected = json.loads(Path("/config/phase8_expected.json").read_text())
        entries = [
            e
            for e in hass.config_entries.async_entries("ha_tankdata")
            if e.data.get("kind") != "consumer"
        ]
        assert len(entries) == len(expected)
        for entry in entries:
            assert entry.state.value == "loaded", entry.reason
            assert entry.runtime_data.data["events"] == expected[entry.entry_id]
            assert await hass.config_entries.async_reload(entry.entry_id)
            assert entry.runtime_data.data["events"] == expected[entry.entry_id]
        await hass.async_block_till_done()
        registry = entity_registry.async_get(hass)
        devices = device_registry.async_get(hass)
        for entry in entries:
            registered = entity_registry.async_entries_for_config_entry(
                registry, entry.entry_id
            )
            expected_count = 3
            assert len(registered) == expected_count, (
                entry.entry_id,
                len(registered),
                expected_count,
            )
            for entity in registered:
                device = devices.async_get(entity.device_id)
                assert device.config_subentry_id == entity.config_subentry_id
        ids = [
            e.entity_id
            for entry in entries
            for e in entity_registry.async_entries_for_config_entry(
                registry, entry.entry_id
            )
            if not e.disabled
        ]
        bad = [
            eid
            for eid in ids
            if hass.states.get(eid) is None
            or hass.states.get(eid).state in {"unknown", "unavailable"}
        ]
        assert not bad, bad
        print(
            f"RESTART ACCEPTANCE PASSED: {len(entries)} tanks, all ledgers and entities"
        )
    finally:
        await hass.async_stop()


asyncio.run(main())
