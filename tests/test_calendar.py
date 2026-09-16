"""Calendar boundaries, elapsed-time allocation and HA panel requests."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import create_tank

from custom_components.ha_tankdata.insights import calendar_summary
from custom_components.ha_tankdata.model import new_tank
from custom_components.ha_tankdata.panel import manage

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("period", "anchor", "count", "start", "end"),
    [
        ("day", "2026-09-16", 24, "2026-09-16", "2026-09-16"),
        ("week", "2026-01-01", 7, "2025-12-29", "2026-01-04"),
        ("month", "2024-02-12", 29, "2024-02-01", "2024-02-29"),
        ("month", "2026-02-12", 28, "2026-02-01", "2026-02-28"),
        ("month", "2026-12-12", 31, "2026-12-01", "2026-12-31"),
        ("year", "2024-02-12", 12, "2024-01-01", "2024-12-31"),
        ("all", None, 1, "2026-01-01", "2026-12-31"),
    ],
)
def test_calendar_boundaries(period, anchor, count, start, end):
    report = calendar_summary(
        new_tank(100, 100), {}, NOW, period, anchor, "Europe/Berlin"
    )
    assert len(report["days"]) == count
    assert (report["start"], report["end"]) == (start, end)


def interval_data(start, end, liters):
    data = new_tank(1000, 1000)
    data["analysis"]["settings"]["initial_price"] = 2
    data["events"] = [
        {
            "id": "burn",
            "kind": "consumption",
            "at": end,
            "start": start,
            "end": end,
            "liters": liters,
            "runtime_seconds": liters * 3600,
            "source_id": "burner",
        }
    ]
    data["analysis"]["intervals"] = [
        {"source_id": "burner", "start": start, "end": end}
    ]
    return data


@pytest.mark.parametrize(
    ("anchor", "start", "end", "hours"),
    [
        ("2026-03-29", "2026-03-28T23:00:00Z", "2026-03-29T22:00:00Z", 23),
        ("2026-10-25", "2026-10-24T22:00:00Z", "2026-10-25T23:00:00Z", 25),
    ],
)
def test_dst_hours_have_unique_offsets_and_conserve_totals(anchor, start, end, hours):
    data = interval_data(start, end, hours)
    before = deepcopy(data)
    report = calendar_summary(data, {"burner": {}}, NOW, "day", anchor, "Europe/Berlin")
    assert len(report["days"]) == hours
    assert len({b["date"] for b in report["days"]}) == hours
    assert all(b["liters"] == 1 and b["coverage"] == 1 for b in report["days"])
    assert report["liters"] == report["runtime_hours"] == hours
    assert report["cost"] == hours * 2
    assert data == before


def test_month_year_and_total_split_at_local_year_boundary():
    data = interval_data("2025-12-31T22:30:00Z", "2026-01-01T00:30:00Z", 2)
    for period, anchor, expected in [
        ("day", "2025-12-31", 0.5),
        ("month", "2025-12-01", 0.5),
        ("year", "2025-06-01", 0.5),
        ("year", "2026-06-01", 1.5),
        ("all", None, 2),
    ]:
        report = calendar_summary(
            data, {"burner": {}}, NOW, period, anchor, "Europe/Berlin"
        )
        assert report["liters"] == expected
        assert report["cost"] == expected * 2
        assert report["by_source"] == {"burner": expected}
    assert [b["liters"] for b in report["days"]] == [0.5, 1.5]


def test_current_period_future_and_unknown_costs():
    data = interval_data("2026-11-16T11:00:00Z", "2026-11-16T12:00:00Z", 1)
    data["analysis"]["settings"]["initial_price"] = None
    report = calendar_summary(data, {"burner": {}}, NOW)
    assert report["liters"] == 1
    assert report["cost"] is None
    assert sum(b["future"] for b in report["days"]) == 12
    assert report["days"][11]["coverage"] == 1
    assert report["days"][10]["coverage"] == 0
    assert report["days"][12]["coverage"] is None


def test_instant_booking_and_expenses_belong_to_correct_calendar_month():
    data = new_tank(100, 100)
    data["events"] = [
        {
            "id": "refill",
            "kind": "refill",
            "liters": 10,
            "total_cost": 20,
            "at": "2026-02-01T00:00:00Z",
        },
        {
            "id": "instant",
            "kind": "consumption",
            "liters": 1,
            "at": "2026-02-01T00:00:00Z",
        },
    ]
    january = calendar_summary(data, {}, NOW, "month", "2026-01-01")
    february = calendar_summary(data, {}, NOW, "month", "2026-02-01")
    assert january["liters"] == january["expenses"] == 0
    assert february["liters"] == 1
    assert february["expenses"] == 20


async def test_calendar_request_in_loaded_ha_and_reload(hass):
    tank = await create_tank(hass)
    connection = Mock(user=SimpleNamespace(is_admin=True))
    for params in [
        {"period": "month", "anchor": "2024-02-10"},
        {"period": "all"},
        {"days": 7},
        {"period": "day", "anchor": "invalid"},
        {"period": "invalid"},
    ]:
        connection.reset_mock()
        manage(
            hass,
            connection,
            {
                "id": 1,
                "config_entry_id": tank.entry_id,
                "operation": "statistics",
                "parameters": params,
            },
        )
        await hass.async_block_till_done()
        if "invalid" in params.values():
            assert connection.send_error.call_args.args[1] == "invalid_request"
        else:
            report = connection.send_result.call_args.args[1]
            assert len(report["days"]) == (
                29 if params.get("period") == "month" else 7 if "days" in params else 1
            )
    assert await hass.config_entries.async_reload(tank.entry_id)
    assert tank.runtime_data.data["events"] == []
