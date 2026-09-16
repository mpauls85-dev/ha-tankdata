"""Isolated HA process migration; run twice against the same test directory."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from homeassistant import loader
from homeassistant.bootstrap import async_from_config_dict
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


async def main():
    hass = HomeAssistant("/config")
    loader.async_setup(hass)
    assert await async_from_config_dict({"homeassistant": {}}, hass)
    await hass.async_start()
    try:
        from custom_components.ha_tankdata.analysis import add_coverage
        from custom_components.ha_tankdata.consumption import calculate
        from custom_components.ha_tankdata.model import append, new_tank, replay

        marker = Path("/config/segments-passed.json")
        if not marker.exists():
            result = await hass.config_entries.flow.async_init(
                "ha_tankdata",
                context={"source": "user"},
                data={"name": "Segment acceptance", "capacity": 1000, "initial": 500},
            )
            await hass.async_block_till_done()
            tank = result["result"]
            config = {
                "name": "Burner",
                "mode": "running",
                "entity_id": "binary_sensor.test_burner",
                "rate_lph": 10,
                "max_rate_lph": 100,
                "max_gap_seconds": 300,
            }
            flow = await hass.config_entries.flow.async_init(
                "ha_tankdata", context={"source": "user"}
            )
            flow = await hass.config_entries.flow.async_configure(
                flow["flow_id"], {"next_step_id": "consumer"}
            )
            flow = await hass.config_entries.flow.async_configure(
                flow["flow_id"], {"tank_entry_id": tank.entry_id, **config}
            )
            await hass.async_block_till_done()
            sid = flow["result"].data["source_id"]
            data = new_tank(1000, 500)
            start = dt_util.utcnow() - timedelta(hours=2)
            basis, _ = calculate(config, None, "on", None, start.isoformat())
            for i in range(1, 101):
                at = (start + timedelta(seconds=18 * i)).isoformat()
                basis, interval = calculate(
                    config, basis, "off" if i == 100 else "on", None, at
                )
                add_coverage(data, sid, interval)
                data = append(
                    data,
                    {
                        "id": str(i),
                        "kind": "consumption",
                        "at": at,
                        "source_id": sid,
                        **interval,
                    },
                    manual=False,
                )
            data["sources"][sid] = basis
            store = tank.runtime_data.store.store
            assert await hass.config_entries.async_unload(tank.entry_id)
            path = Path(store.path)
            original = json.dumps(
                {"version": 2, "minor_version": 1, "key": store.key, "data": data}
            ).encode()
            await hass.async_add_executor_job(path.write_bytes, original)
            assert await hass.config_entries.async_setup(tank.entry_id)
            await hass.async_block_till_done()
            runtime = tank.runtime_data
            assert len(runtime.data["events"]) == 1
            assert abs(replay(runtime.data)["consumed"] - 5) < 1e-8
            raw = json.loads(await hass.async_add_executor_job(path.read_bytes))
            assert raw["version"] == 3
            backups = await hass.async_add_executor_job(
                lambda: list(path.parent.glob(path.name + ".before-v3-*"))
            )
            assert len(backups) == 1
            assert await hass.async_add_executor_job(backups[0].read_bytes) == original
            # A new independent run is persisted as one additional segment.
            start = dt_util.utcnow() + timedelta(seconds=1)
            for i in range(101):
                await runtime.ingest(
                    sid,
                    "off" if i == 100 else "on",
                    None,
                    (start + timedelta(seconds=18 * i)).isoformat(),
                )
            assert len(runtime.data["events"]) == 2
            saved = {
                "entry_id": tank.entry_id,
                "events": deepcopy(runtime.data["events"]),
            }
            await hass.async_add_executor_job(marker.write_text, json.dumps(saved))
        saved = json.loads(await hass.async_add_executor_job(marker.read_text))
        tank = hass.config_entries.async_get_entry(saved["entry_id"])
        assert tank.state.value == "loaded", tank.reason
        assert await hass.config_entries.async_reload(tank.entry_id)
        assert tank.runtime_data.data["events"] == saved["events"]
        assert abs(replay(tank.runtime_data.data)["consumed"] - 10) < 1e-8
        print(
            "SEGMENTS ACCEPTANCE PASSED: backup, v2-to-v3 migration, "
            "100-to-1 compaction, active run, reload/process restart"
        )
    finally:
        await hass.async_block_till_done()
        await hass.async_stop()


asyncio.run(main())
