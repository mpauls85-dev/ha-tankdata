"""Isolated Docker acceptance: analysis, consent and process restart."""

import asyncio
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
        from custom_components.ha_tankdata.analysis import add_coverage, propose
        from custom_components.ha_tankdata.consumption import calculate
        from custom_components.ha_tankdata.insights import forecast
        from custom_components.ha_tankdata.model import append, new_tank

        marker = Path("/config/features-passed")
        if not marker.exists():
            result = await hass.config_entries.flow.async_init(
                "ha_tankdata",
                context={"source": "user"},
                data={
                    "name": "Feature acceptance",
                    "capacity": 13000,
                    "initial": 12000,
                },
            )
            await hass.async_block_till_done()
            tank = result["result"]
            flow = await hass.config_entries.flow.async_init(
                "ha_tankdata", context={"source": "user"}
            )
            flow = await hass.config_entries.flow.async_configure(
                flow["flow_id"], {"next_step_id": "consumer"}
            )
            config = {
                "name": "Acceptance burner",
                "entity_id": "binary_sensor.acceptance",
                "mode": "running",
                "rate_lph": 10,
                "max_gap_seconds": 3600,
                "max_rate_lph": 100,
            }
            flow = await hass.config_entries.flow.async_configure(
                flow["flow_id"], {"tank_entry_id": tank.entry_id, **config}
            )
            await hass.async_block_till_done()
            sid = flow["result"].data["source_id"]
            runtime = tank.runtime_data
            config = runtime.configs()[sid]
            data = new_tank(13000, 12000)
            data["analysis"]["settings"].update(
                initial_price=1.1,
                geometry={"shape": "horizontal_cylinder", "height_cm": 200},
            )
            start = dt_util.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - timedelta(days=8)
            data = append(
                data,
                {
                    "id": "first",
                    "at": start.isoformat(),
                    "kind": "observation",
                    "liters": 12000,
                },
            )
            basis, _ = calculate(config, None, "on", None, start.isoformat())
            for hour in range(1, 193):
                at = (start + timedelta(hours=hour)).isoformat()
                basis, interval = calculate(config, basis, "on", None, at)
                add_coverage(data, sid, interval)
                data = append(
                    data,
                    {
                        "id": str(hour),
                        "at": at,
                        "kind": "consumption",
                        "source_id": sid,
                        **interval,
                    },
                    manual=False,
                )
            data = append(
                data, {"id": "last", "at": at, "kind": "observation", "liters": 9888}
            )
            proposal = propose(data, runtime.configs())
            assert proposal and proposal["new_rate"] == 11
            data["analysis"]["proposals"].append(proposal)
            await runtime.commit(data)
            runtime.notify_proposals()
            assert forecast(data, runtime.configs(), dt_util.utcnow())["next_7"] == 1680
            before = deepcopy(data["events"])
            await runtime.decide(proposal["id"], "later")
            assert runtime.configs()[sid]["rate_lph"] == 10
            await runtime.decide(proposal["id"], "accept")
            await hass.async_block_till_done()
            assert runtime.configs()[sid]["rate_lph"] == 11
            assert runtime.data["events"] == before
            await runtime.book("refill", 100, "priced", total_cost=120)
            await runtime.book("refill", 100, "priced", total_cost=120)
            await runtime.book("observation", 10, "percent", unit="%")
            assert runtime.data["events"][-1]["liters"] == 1300
            marker.write_text(tank.entry_id)
        tank = hass.config_entries.async_get_entry(marker.read_text())
        assert tank.state.value == "loaded", tank.reason
        assert await hass.config_entries.async_reload(tank.entry_id)
        runtime = tank.runtime_data
        assert runtime.data["analysis"]["proposals"][0]["status"] == "applied"
        assert next(iter(runtime.configs().values()))["rate_lph"] == 11
        assert len([e for e in runtime.data["events"] if e["id"] == "priced"]) == 1
        assert runtime.data["events"][-1]["liters"] == 1300
        print(
            "FEATURE ACCEPTANCE PASSED: geometry, pricing, forecast, "
            "consent, reload/restart"
        )
    finally:
        await hass.async_block_till_done()
        await hass.async_stop()


asyncio.run(main())
