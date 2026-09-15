import pytest
from test_consumption import config, step

from custom_components.ha_tankdata.consumption import calculate


def test_flow_rectangles_and_zero():
    cfg = config("flow")
    basis, _ = step(None, 60, 0, "L/h", cfg)
    basis, interval = step(basis, 30, 60, "L/h", cfg)
    assert interval["liters"] == 1
    basis, interval = step(basis, 0, 180, "L/h", cfg)
    assert interval["liters"] == 1
    _, interval = step(basis, 60, 240, "L/h", cfg)
    assert interval["liters"] == 0


@pytest.mark.parametrize("unit,value", [("L/min", 1), ("l/h", 60), ("m³/h", 0.06)])
def test_flow_units(unit, value):
    cfg = config("flow")
    basis, _ = step(None, value, 0, unit, cfg)
    _, interval = step(basis, value, 60, unit, cfg)
    assert interval["liters"] == pytest.approx(1)


def test_flow_gaps_invalid_and_restart():
    cfg = config("flow", max_gap_seconds=120)
    basis, _ = step(None, 60, 0, "L/h", cfg)
    assert step(basis, 60, 121, "L/h", cfg)[1] is None
    assert step(basis, 60, 60, "kg/h", cfg)[1] is None
    invalid, interval = step(basis, "unavailable", 60, "L/h", cfg)
    assert interval is None
    assert step(invalid, 60, 90, "L/h", cfg)[1] is None
    assert step(None, 60, 90, "L/h", cfg)[1] is None
    assert step(basis, 60, 0, "L/h", cfg) == (basis, None)


def test_timer_does_not_refresh_report_validity():
    cfg = config("flow", max_gap_seconds=60)
    basis, _ = step(None, 60, 0, "L/h", cfg)
    basis, interval = calculate(
        cfg, basis, None, None, "2026-09-15T00:00:30Z", tick=True
    )
    assert interval["liters"] == 0.5
    assert basis["reported_at"] == "2026-09-15T00:00:00+00:00"
    basis, interval = calculate(
        cfg, basis, None, None, "2026-09-15T00:01:01Z", tick=True
    )
    assert interval is None
    assert basis["value"] is None
