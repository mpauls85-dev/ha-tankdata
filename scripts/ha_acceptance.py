"""Run inside the official HA container with an isolated /config directory.

Run twice: first create/book, then verify process restart and persisted history.
"""

import asyncio
import json
from pathlib import Path

from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.core import HomeAssistant


async def main():
    hass = HomeAssistant("/config")
    loader.async_setup(hass)
    await async_from_config_dict({"homeassistant": {"name": "TankData Test"}}, hass)
    await hass.async_start()
    try:
        entries = hass.config_entries.async_entries("ha_tankdata")
        marker = Path("/config/expected.json")
        if not entries:
            for name in ("Acceptance A", "Acceptance B"):
                result = await hass.config_entries.flow.async_init(
                    "ha_tankdata",
                    context={"source": "user"},
                    data={"name": name, "capacity": 1000, "initial": 500},
                )
                assert result["type"] == "create_entry", result
            await hass.async_block_till_done()
            entries = hass.config_entries.async_entries("ha_tankdata")
            a, b = entries
            for action, payload in [
                ("record_refill", {"liters": 100, "event_id": "one"}),
                ("record_refill", {"liters": 100, "event_id": "one"}),
                ("record_observation", {"liters": 590}),
                ("record_withdrawal", {"liters": 10}),
                ("apply_correction", {"liters": 580}),
                ("recalculate", {}),
                ("reset_calibration", {}),
            ]:
                await hass.services.async_call(
                    "ha_tankdata",
                    action,
                    {"config_entry_id": a.entry_id, **payload},
                    blocking=True,
                )
            from custom_components.ha_tankdata.model import replay

            assert replay(a.runtime_data.data)["stock"] == 590
            assert replay(b.runtime_data.data)["stock"] == 500
            expected = {e.entry_id: e.runtime_data.data for e in entries}
            marker.write_text(json.dumps(expected))
        else:
            expected = json.loads(marker.read_text())
        for entry in entries:
            assert entry.state.value == "loaded", entry.reason
            assert entry.runtime_data.data == expected[entry.entry_id]
            assert await hass.config_entries.async_reload(entry.entry_id)
            assert entry.runtime_data.data == expected[entry.entry_id]
        await hass.async_block_till_done()
        states = [
            s
            for s in hass.states.async_all("sensor")
            if s.attributes.get("event_count") is not None
        ]
        assert len(states) == 6, [(s.entity_id, s.state) for s in states]
        print(
            "ACCEPTANCE PASSED: two tanks, actions, entities, reload, persisted ledger"
        )
    finally:
        await hass.async_stop()


asyncio.run(main())
