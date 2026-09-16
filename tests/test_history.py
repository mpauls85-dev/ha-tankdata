"""Runs preserve ledger evidence, boundaries and stable pagination."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import create_tank
from test_analysis import cfg
from test_ha import add_consumer

from custom_components.ha_tankdata.history import grouped_history, history_page
from custom_components.ha_tankdata.model import new_tank
from custom_components.ha_tankdata.panel import get_history

START = datetime(2026, 9, 16, 10, tzinfo=timezone.utc)


def event(index, sid="burner", *, rate=10, stop=False, gap=0):
    start = START + timedelta(seconds=index * 30 + gap)
    return {
        "id": f"{sid}-{index}",
        "kind": "consumption",
        "source_id": sid,
        "at": (start + timedelta(seconds=30)).isoformat(),
        "start": start.isoformat(),
        "end": (start + timedelta(seconds=30)).isoformat(),
        "liters": rate / 120,
        "runtime_seconds": 30,
        "input_before": rate,
        "input_after": 0 if stop else rate,
        "config": {**cfg(), "rate_lph": rate},
    }


def data_for(events):
    data = new_tank(1000, 500)
    data["events"] = events
    data["sources"] = {
        e["source_id"]: {"at": e["end"]}
        for e in events
        if "source_id" in e and "end" in e
    }
    return data


def test_run_grows_with_stable_id_and_stops_without_mutating_ledger():
    data = data_for([event(i) for i in range(100)])
    before = deepcopy(data)
    page = history_page(data, {"burner": True}, {"burner": cfg()}, limit=1)
    run = page["events"][0]
    assert page["count"] == 1 and page["before"] == 0
    assert run["count"] == 100 and run["runtime_seconds"] == 3000
    assert run["liters"] == pytest.approx(100 / 12)
    assert run["status"] == "running" and run["id"] == "burner-0"
    assert "members" not in run
    assert data == before
    data["events"].append(event(100, stop=True))
    ended = history_page(data, {"burner": False}, {"burner": cfg()})["events"][0]
    assert ended["id"] == run["id"] and ended["count"] == 101
    assert ended["status"] == "finished"
    details = history_page(data, {}, {}, run_id=run["id"], limit=50)
    older = history_page(
        data, {}, {}, run_id=run["id"], limit=50, before=details["before"]
    )
    assert details["events"] == list(reversed(data["events"][-50:]))
    assert older["events"] == list(reversed(data["events"][1:51]))


@pytest.mark.parametrize("boundary", ["gap", "rate", "stop", "manual", "config"])
def test_boundaries_split_runs(boundary):
    first, second = event(0), event(1)
    events = [first, second]
    if boundary == "gap":
        second.update(start=(START + timedelta(seconds=31)).isoformat())
    elif boundary == "rate":
        events[1] = event(1, rate=11)
    elif boundary == "stop":
        first["input_after"] = 0
    elif boundary == "manual":
        events.insert(
            1, {"id": "refill", "kind": "refill", "liters": 100, "at": first["end"]}
        )
    else:
        second["config"]["entity_id"] = "binary_sensor.changed"
    rows = grouped_history(data_for(events), {}, {})
    assert len([r for r in rows if r["kind"] == "run"]) == 2
    assert sum(r["liters"] for r in rows if r["kind"] == "run") == pytest.approx(
        sum(e["liters"] for e in events if "source_id" in e and "end" in e)
    )


def test_sources_interleave_without_splitting_and_pages_do_not_duplicate():
    data = data_for([event(0), event(0, "other"), event(1), event(1, "other")])
    latest = history_page(data, {}, {}, limit=1)
    assert latest["events"][0]["source_id"] == "other"
    assert latest["events"][0]["count"] == 2
    data["events"].append(event(2, "other"))
    older = history_page(data, {}, {}, limit=1, before=latest["before"])
    assert older["events"][0]["source_id"] == "burner"
    assert older["events"][0]["count"] == 2
    assert older["before"] == 0


def test_gap_restart_unknown_and_changed_config_never_claim_active_run():
    data = data_for([event(0)])
    assert (
        grouped_history(data, {"burner": None}, {"burner": cfg()})[0]["status"]
        == "interrupted"
    )
    data["sources"]["burner"]["at"] = event(2)["end"]
    assert (
        grouped_history(data, {"burner": True}, {"burner": cfg()})[0]["status"]
        == "interrupted"
    )
    data["sources"]["burner"]["at"] = event(0)["end"]
    assert (
        grouped_history(data, {"burner": True}, {"burner": {**cfg(), "rate_lph": 11}})[
            0
        ]["status"]
        == "interrupted"
    )


def test_legacy_and_counter_remain_individual_and_missing_run_rejected():
    old = {"id": "old", "kind": "consumption", "at": START.isoformat(), "liters": 1}
    counter = event(0)
    counter["config"]["mode"] = "counter"
    data = data_for([old, counter])
    assert [r["kind"] for r in grouped_history(data, {}, {})] == ["consumption"] * 2
    with pytest.raises(ValueError):
        history_page(data, {}, {}, run_id="missing")


async def test_grouped_api_in_loaded_ha_and_reload_preserves_events(hass):
    tank = await create_tank(hass)
    sid = await add_consumer(hass, tank, cfg())
    runtime = tank.runtime_data
    start = datetime.now(timezone.utc) + timedelta(seconds=1)
    for i in range(4):
        await runtime.ingest(
            sid,
            "on" if i < 3 else "off",
            None,
            (start + timedelta(seconds=i * 30)).isoformat(),
        )
    before = deepcopy(runtime.data["events"])
    connection = Mock(user=SimpleNamespace(is_admin=True))
    get_history(
        hass,
        connection,
        {"id": 1, "config_entry_id": tank.entry_id, "limit": 1, "grouped": True},
    )
    run = connection.send_result.call_args.args[1]["events"][0]
    assert run["count"] == 1 and run["status"] == "finished"
    assert before[0]["steps"] == 3
    get_history(
        hass,
        connection,
        {"id": 2, "config_entry_id": tank.entry_id, "limit": 50, "run_id": run["id"]},
    )
    assert connection.send_result.call_args.args[1]["events"] == list(reversed(before))
    assert await hass.config_entries.async_reload(tank.entry_id)
    assert tank.runtime_data.data["events"] == before
