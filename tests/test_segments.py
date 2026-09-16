"""Durable segment compaction, migration and recovery."""

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from conftest import create_tank
from homeassistant.exceptions import HomeAssistantError
from test_analysis import cfg, history
from test_ha import add_consumer
from test_history import data_for, event

from custom_components.ha_tankdata.analysis import propose
from custom_components.ha_tankdata.insights import calendar_summary, costs
from custom_components.ha_tankdata.model import replay, validate
from custom_components.ha_tankdata.segments import append_consumption, compact_legacy
from custom_components.ha_tankdata.store import TankStore


def numeric_equal(left, right):
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            numeric_equal(left[key], right[key])
    elif isinstance(left, list):
        assert len(left) == len(right)
        for a, b in zip(left, right, strict=True):
            numeric_equal(a, b)
    elif isinstance(left, (int, float)) and not isinstance(left, bool):
        assert right == pytest.approx(left, abs=1e-8)
    else:
        assert left == right


def legacy_events(events):
    data = data_for(events)
    # The historical source cursor is independent of the migrated event array.
    data["sources"] = {}
    data["initial"] = 1000
    data["analysis"]["settings"]["initial_price"] = 1.2
    return data


def test_many_updates_become_one_durable_segment_with_same_hourly_statistics():
    data = legacy_events([event(i, stop=i == 499) for i in range(500)])
    before = deepcopy(data)
    compact = compact_legacy(data)
    assert len(compact["events"]) == 1
    segment = compact["events"][0]
    assert segment["steps"] == 500 and segment["max_step_seconds"] == 30
    assert segment["runtime_seconds"] == 15000  # Longer than max_gap_seconds.
    assert segment["input_after"] == 0
    assert len(json.dumps(compact)) < len(json.dumps(data)) / 50
    numeric_equal(replay(data), replay(compact))
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for period in ["day", "week", "month", "year", "all"]:
        numeric_equal(
            calendar_summary(
                data, {"burner": cfg()}, now, period, "2026-09-16", "Europe/Berlin"
            ),
            calendar_summary(
                compact, {"burner": cfg()}, now, period, "2026-09-16", "Europe/Berlin"
            ),
        )
    assert compact_legacy(compact) == compact
    assert data == before


def test_interleaved_sources_compact_and_keep_their_own_totals_and_costs():
    events = []
    for i in range(100):
        events.extend([event(i), event(i, "other", rate=11)])
    data = legacy_events(events)
    compact = compact_legacy(data)
    assert len(compact["events"]) == 2
    assert {e["source_id"] for e in compact["events"]} == {"burner", "other"}
    now = datetime(2026, 9, 17, tzinfo=timezone.utc)
    for sid in [None, "burner", "other"]:
        numeric_equal(
            calendar_summary(data, {}, now, anchor="2026-09-16", source_id=sid),
            calendar_summary(compact, {}, now, anchor="2026-09-16", source_id=sid),
        )


@pytest.mark.parametrize(
    "boundary", ["gap", "stop", "rate", "observation", "refill", "correction", "reset"]
)
def test_compaction_preserves_meaningful_boundaries(boundary):
    first, second = event(0), event(1)
    events = [first]
    if boundary == "gap":
        second = event(1, gap=1)
    elif boundary == "stop":
        first["input_after"] = 0
    elif boundary == "rate":
        second = event(1, rate=11)
    else:
        events.append(
            {
                "id": "manual",
                "at": first["at"],
                "kind": boundary,
                "liters": 0 if boundary == "reset" else 10,
            }
        )
    events.append(second)
    data = legacy_events(events)
    compact = compact_legacy(data)
    assert len(compact["events"]) == len(events)
    assert [e["id"] for e in compact["events"]] == [e["id"] for e in events]
    numeric_equal(replay(data), replay(compact))
    numeric_equal(costs(data), costs(compact))


def test_depleted_stock_keeps_cost_knowledge_boundaries():
    data = legacy_events([event(i) for i in range(4)])
    data["initial"] = 0.2
    compact = compact_legacy(data)
    assert len(compact["events"]) == 3
    numeric_equal(
        calendar_summary(
            data, {}, datetime(2026, 9, 17, tzinfo=timezone.utc), anchor="2026-09-16"
        ),
        calendar_summary(
            compact, {}, datetime(2026, 9, 17, tzinfo=timezone.utc), anchor="2026-09-16"
        ),
    )


def test_calibration_evidence_survives_compaction():
    data = history(cfg())
    compact = compact_legacy(data)
    assert len(compact["events"]) == 3  # Observation, run, observation.
    assert propose(data, {"burner": cfg()}) == propose(compact, {"burner": cfg()})


@pytest.mark.parametrize(
    "damage", ["liters", "runtime_seconds", "max_step_seconds", "steps", "input_before"]
)
def test_corrupt_segments_rejected(damage):
    data = compact_legacy(legacy_events([event(i) for i in range(150)]))
    data["events"][0][damage] = {
        "liters": 999,
        "runtime_seconds": 1,
        "max_step_seconds": 4000,
        "steps": 1,
        "input_before": 99,
    }[damage]
    with pytest.raises(ValueError):
        validate(data)


@pytest.mark.parametrize("version", [1, 2])
async def test_store_upgrade_backs_up_original_and_confirms_v3(hass, version):
    store = TankStore(hass, "upgrade")
    data = legacy_events([event(i) for i in range(100)])
    if version == 1:
        del data["analysis"]
    path = Path(store.store.path)
    path.parent.mkdir(exist_ok=True)
    content = json.dumps(
        {"version": version, "minor_version": 1, "key": store.store.key, "data": data}
    ).encode()
    path.write_bytes(content)
    migrated = await store.load()
    assert len(migrated["events"]) == 1 and store.needs_migration
    assert path.read_bytes() == content
    # A swallowed write failure must not count as a successful migration.
    with patch.object(store.store, "async_save", AsyncMock(return_value=None)):
        with pytest.raises(HomeAssistantError):
            await store.save(migrated)
    assert path.read_bytes() == content
    backups = list(path.parent.glob(path.name + ".before-v3-*"))
    assert len(backups) == 1 and backups[0].read_bytes() == content
    await store.save(migrated)
    assert json.loads(path.read_bytes())["version"] == 3
    assert await TankStore(hass, "upgrade").load() == migrated
    assert len(list(path.parent.glob(path.name + ".before-v3-*"))) == 1


async def test_active_run_failed_write_retry_and_reload(hass):
    tank = await create_tank(hass)
    sid = await add_consumer(hass, tank, cfg())
    runtime = tank.runtime_data
    start = datetime.now(timezone.utc) + timedelta(seconds=1)
    for i in range(101):
        await runtime.ingest(
            sid, "on", None, (start + timedelta(seconds=i * 18)).isoformat()
        )
    assert len(runtime.data["events"]) == 1
    assert runtime.data["events"][0]["runtime_seconds"] == 1800
    assert replay(runtime.data)["consumed"] == pytest.approx(5)
    saved = deepcopy(runtime.data)
    at = (start + timedelta(seconds=1830)).isoformat()
    with patch.object(
        runtime.store.store, "async_save", AsyncMock(side_effect=OSError("disk full"))
    ):
        with pytest.raises(OSError):
            await runtime.ingest(sid, "off", None, at)
    assert runtime.data == saved
    await runtime.ingest(sid, "off", None, at)
    committed = deepcopy(runtime.data)
    await runtime.ingest(sid, "off", None, at)
    assert runtime.data == committed
    assert committed["events"][0]["steps"] == 101
    assert await hass.config_entries.async_reload(tank.entry_id)
    assert tank.runtime_data.data["events"] == committed["events"]
    later = (start + timedelta(seconds=1900)).isoformat()
    await tank.runtime_data.ingest(sid, "on", None, later)
    await tank.runtime_data.ingest(
        sid, "off", None, (start + timedelta(seconds=1930)).isoformat()
    )
    assert len(tank.runtime_data.data["events"]) == 2


def test_incremental_and_migration_produce_same_segments():
    original = legacy_events([event(i) for i in range(100)])
    data = deepcopy(original)
    data["events"] = []
    for item in original["events"]:
        data = append_consumption(data, item)
    assert data == compact_legacy(original)
