import pytest

from custom_components.ha_tankdata.consumption import calculate


def config(mode="counter", **kw):
    return {
        "name": "Source",
        "mode": mode,
        "entity_id": "sensor.source",
        "max_gap_seconds": 3600,
        "max_rate_lph": 100,
        **kw,
    }


def step(previous, value, seconds, unit="L", cfg=None):
    from datetime import UTC, datetime, timedelta

    at = (datetime(2026, 9, 15, tzinfo=UTC) + timedelta(seconds=seconds)).isoformat()
    return calculate(cfg or config(), previous, value, unit, at)


def test_counter_normal_duplicate_and_restart():
    basis, interval = step(None, "10", 0)
    assert interval is None
    basis, interval = step(basis, "11", 60)
    assert interval["liters"] == 1
    assert step(basis, "12", 60) == (basis, None)
    assert step(basis, "12", 30) == (basis, None)
    import json

    restored = json.loads(json.dumps(basis))
    _, interval = step(restored, "12", 120)
    assert interval["liters"] == 1
    _, interval = step(basis, "11", 120)
    assert interval["liters"] == 0


@pytest.mark.parametrize(
    "value,unit",
    [
        ("unknown", "L"),
        ("unavailable", "L"),
        ("nan", "L"),
        ("inf", "L"),
        ("-1", "L"),
        ("10", "kg"),
        (None, None),
    ],
)
def test_counter_invalid_breaks_interval(value, unit):
    basis, _ = step(None, 10, 0)
    basis, interval = step(basis, value, 60, unit)
    assert interval is None
    basis, interval = step(basis, 12, 120)
    assert interval is None
    _, interval = step(basis, 13, 180)
    assert interval["liters"] == 1


def test_reset_jump_gap_and_config_change():
    basis, _ = step(None, 10, 0)
    for value, at in [(0, 60), (1000, 60), (11, 4000)]:
        _, interval = step(basis, value, at)
        assert interval is None
    _, interval = step(basis, 11, 60, cfg=config(entity_id="sensor.other"))
    assert interval is None
    basis, _ = step(None, 1, 0, "m³")
    _, interval = step(basis, 1.001, 60, "m³")
    assert interval["liters"] == pytest.approx(1)
