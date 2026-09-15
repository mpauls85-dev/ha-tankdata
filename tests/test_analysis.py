from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from conftest import create_tank
from test_ha import add_consumer

from custom_components.ha_tankdata.analysis import add_coverage, propose
from custom_components.ha_tankdata.consumption import calculate
from custom_components.ha_tankdata.geometry import fill_height, to_liters
from custom_components.ha_tankdata.insights import costs, forecast, summarize
from custom_components.ha_tankdata.model import append, new_tank, validate

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def history(config, days=1, sid="burner"):
    data = new_tank(13000, 12000)
    data["analysis"]["settings"]["measurement_tolerance_liters"] = 1
    data = append(
        data,
        {
            "id": "first",
            "at": START.isoformat(),
            "kind": "observation",
            "liters": 12000,
        },
    )
    basis, _ = calculate(config, None, "on", None, START.isoformat())
    for hour in range(1, days * 24 + 1):
        at = (START + timedelta(hours=hour)).isoformat()
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
        data,
        {
            "id": "last",
            "at": at,
            "kind": "observation",
            "liters": 12000 - days * 24 * config["rate_lph"] * 1.1,
        },
    )
    return data


def cfg():
    return {
        "name": "Burner",
        "mode": "running",
        "entity_id": "binary_sensor.burner",
        "rate_lph": 10,
        "max_gap_seconds": 3600,
        "max_rate_lph": 100,
    }


@pytest.mark.parametrize(
    "shape", ["rectangle", "vertical_cylinder", "horizontal_cylinder", "sphere"]
)
def test_geometry_roundtrip(shape):
    g = {"shape": shape, "height_cm": 200}
    for liters in [0, 1300, 6500, 11700, 13000]:
        height = fill_height(liters, g, 13000) * 200
        assert to_liters(height, "cm", g, 13000) == pytest.approx(liters, abs=1e-7)
    assert to_liters(10, "%", g, 13000) == 1300
    if shape == "horizontal_cylinder":
        assert fill_height(1300, g, 13000) == pytest.approx(0.1564756, abs=1e-6)


def test_table_and_invalid_geometry():
    g = {"shape": "table", "height_cm": 100, "points": [[0, 0], [50, 200], [100, 1000]]}
    assert to_liters(75, "cm", g, 1000) == 600
    assert fill_height(600, g, 1000) == 0.75
    for value, unit in [(101, "cm"), (101, "%"), (-1, "L"), (float("nan"), "L")]:
        with pytest.raises(ValueError):
            to_liters(value, unit, g, 1000)


def test_weighted_costs_and_unknown_prices():
    data = new_tank(1000, 100)
    data["analysis"]["settings"]["initial_price"] = 1
    data = append(
        data,
        {
            "id": "a",
            "at": START.isoformat(),
            "kind": "refill",
            "liters": 100,
            "total_cost": 200,
        },
    )
    data = append(
        data, {"id": "b", "at": START.isoformat(), "kind": "consumption", "liters": 20}
    )
    result = costs(data)
    assert result["inventory_value"] == 270
    assert result["consumption"]["b"] == 30
    data["analysis"]["settings"]["initial_price"] = None
    assert costs(data)["consumption"]["b"] is None
    data["analysis"]["settings"]["initial_price"] = 0
    assert costs(data)["consumption"]["b"] == 20


def test_proposal_evidence_and_exclusions():
    config = cfg()
    data = history(config)
    validate(data)
    proposal = propose(data, {"burner": config})
    assert proposal["new_rate"] == 11
    assert proposal["evidence"]["runtime_hours"] == 24
    assert len(data["analysis"]["intervals"]) == 1
    assert propose(data, {"burner": config, "other": config}) is None
    assert propose(data, {"burner": {**config, "rate_lph": 12}}) is None
    data["analysis"]["intervals"][0]["start"] = (START + timedelta(hours=1)).isoformat()
    assert propose(data, {"burner": config}) is None


def test_forecast_requires_coverage_and_statistics_split_days():
    config = cfg()
    data = history(config, 8)
    now = START + timedelta(days=8, hours=12)
    report = summarize(data, {"burner": config}, now, 9)
    assert report["liters"] == 1920
    assert report["days"][0]["liters"] == 240
    prediction = forecast(data, {"burner": config}, now)
    assert prediction["next_7"] == 1680
    assert prediction["next_30"] == 7200
    data["analysis"]["intervals"] = []
    assert not forecast(data, {"burner": config}, now)["available"]


async def test_confirmed_rate_persisted_and_idempotent(hass):
    tank = await create_tank(hass)
    sid = await add_consumer(hass, tank, cfg())
    runtime = tank.runtime_data
    config = runtime.configs()[sid]
    data = history(config, sid=sid)
    # Keep the immutable test tank definition, use its valid stock range.
    data["capacity"], data["initial"] = 1000, 500
    for event in data["events"]:
        if event["kind"] == "observation":
            event["liters"] -= 11500
    proposal = propose(data, {sid: config})
    data["analysis"]["proposals"].append(proposal)
    await runtime.commit(data)
    before = deepcopy(data["events"])
    assert runtime.configs()[sid]["rate_lph"] == 10
    await runtime.decide(proposal["id"], "later")
    assert runtime.configs()[sid]["rate_lph"] == 10
    await runtime.decide(proposal["id"], "accept")
    await hass.async_block_till_done()
    assert runtime.configs()[sid]["rate_lph"] == 11
    await runtime.decide(proposal["id"], "accept")
    assert runtime.data["events"] == before
    assert await hass.config_entries.async_reload(tank.entry_id)
    assert tank.runtime_data.data["analysis"]["proposals"][0]["status"] == "applied"
    assert tank.runtime_data.data["events"] == before


@pytest.mark.parametrize(
    "decision", ["reject", "recover", "conflict", "write_gap", "manual"]
)
async def test_calibration_decision_restart_and_conflict(hass, decision):
    tank = await create_tank(hass)
    sid = await add_consumer(hass, tank, cfg())
    runtime = tank.runtime_data
    data = history(runtime.configs()[sid], sid=sid)
    data["capacity"], data["initial"] = 1000, 500
    for event in data["events"]:
        if event["kind"] == "observation":
            event["liters"] -= 11500
    proposal = propose(data, runtime.configs())
    data["analysis"]["proposals"].append(proposal)
    if decision in {"recover", "conflict"}:
        proposal["status"] = "approved"
        proposal["confirmed_at"] = (START + timedelta(days=1)).isoformat()
    if decision in {"write_gap", "manual"}:
        proposal["status"] = "applied"
        proposal["confirmed_at"] = (START + timedelta(days=1)).isoformat()
    await runtime.commit(data)
    if decision == "manual":
        child = runtime.consumers[sid]
        hass.config_entries.async_update_entry(
            child, data={**child.data, "calibration_id": proposal["id"]}
        )
        await hass.async_block_till_done()
    if decision == "reject":
        await runtime.decide(proposal["id"], "reject")
        with pytest.raises(ValueError):
            await runtime.decide(proposal["id"], "accept")
    elif decision == "conflict":
        child = runtime.consumers[sid]
        hass.config_entries.async_update_entry(
            child,
            data={**child.data, "config": {**child.data["config"], "rate_lph": 12}},
        )
        await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(tank.entry_id)
    result = tank.runtime_data.data["analysis"]["proposals"][0]
    assert (
        result["status"]
        == {
            "reject": "rejected",
            "recover": "applied",
            "conflict": "stale",
            "write_gap": "applied",
            "manual": "applied",
        }[decision]
    )
    assert (
        tank.runtime_data.configs()[sid]["rate_lph"]
        == {"reject": 10, "recover": 11, "conflict": 12, "write_gap": 11, "manual": 10}[
            decision
        ]
    )


async def test_measurement_and_price_booking_reload(hass):
    tank = await create_tank(hass)
    runtime = tank.runtime_data
    options = deepcopy(runtime.data["analysis"]["settings"])
    options.update(
        geometry={"shape": "horizontal_cylinder", "height_cm": 200}, initial_price=1
    )
    await runtime.save_settings(options)
    await runtime.book("refill", 100, "priced", total_cost=120)
    await runtime.book("refill", 100, "priced", total_cost=120)
    await runtime.book("observation", 10, "measured", unit="%")
    assert runtime.data["events"][-1]["liters"] == 100
    assert costs(runtime.data)["inventory_value"] == 620
    before = deepcopy(runtime.data)
    for price in [-1, float("nan")]:
        with pytest.raises(ValueError):
            await runtime.book("refill", 100, total_cost=price)
    assert runtime.data == before
    assert await hass.config_entries.async_reload(tank.entry_id)
    assert tank.runtime_data.data == before


def test_dst_calendar_day_allocates_23_actual_hours():
    data = new_tank(1000, 1000)
    data = append(
        data,
        {
            "id": "dst",
            "kind": "consumption",
            "liters": 23,
            "at": "2026-03-29T22:00:00Z",
            "start": "2026-03-28T23:00:00Z",
            "end": "2026-03-29T22:00:00Z",
            "runtime_seconds": 23 * 3600,
        },
    )
    report = summarize(
        data, {}, datetime(2026, 3, 30, 10, tzinfo=timezone.utc), 2, "Europe/Berlin"
    )
    assert report["days"][0]["liters"] == 23
    assert report["days"][1]["liters"] == 0
