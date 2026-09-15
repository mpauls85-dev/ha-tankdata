import pytest
from test_consumption import config, step

from custom_components.ha_tankdata.consumption import validate_config


def power():
    return config("power", rate_lph=60, on_threshold_w=20, off_threshold_w=10)


def test_hysteresis_exact_thresholds_and_noise():
    cfg = power()
    basis, _ = step(None, 15, 0, "W", cfg)
    assert basis["value"] is None
    total = 0
    for seconds, watts, expected in [
        (60, 20, 60),
        (120, 19, 60),
        (180, 11, 60),
        (240, 10, 0),
        (300, 15, 0),
        (360, 21, 60),
        (361, 9, 0),
    ]:
        basis, interval = step(basis, watts, seconds, "W", cfg)
        assert basis["value"] == expected
        if interval:
            total += interval["liters"]
    assert total == pytest.approx(3 + 1 / 60)


def test_power_outage_restart_units_and_gap():
    cfg = power()
    basis, _ = step(None, 0.02, 0, "kW", cfg)
    assert basis["value"] == 60
    invalid, interval = step(basis, "unavailable", 60, "W", cfg)
    assert interval is None
    assert step(invalid, 15, 120, "W", cfg)[0]["value"] is None
    assert step(None, 15, 120, "W", cfg)[0]["value"] is None
    assert step(basis, 15, 4000, "W", cfg)[0]["value"] is None
    assert step(basis, 20, 60, "V", cfg)[1] is None


@pytest.mark.parametrize("on,off", [(10, 10), (9, 10), (20, -1)])
def test_invalid_hysteresis(on, off):
    with pytest.raises(ValueError):
        validate_config({**power(), "on_threshold_w": on, "off_threshold_w": off})
