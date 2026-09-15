from test_consumption import config, step

from custom_components.ha_tankdata.consumption import calculate


def test_start_stop_and_multiple_intervals():
    cfg = config("running", rate_lph=60)
    basis, _ = step(None, "off", 0, cfg=cfg)
    total = runtime = 0
    for seconds, value in [
        (60, "on"),
        (120, "on"),
        (180, "off"),
        (240, "on"),
        (300, "off"),
    ]:
        basis, interval = step(basis, value, seconds, cfg=cfg)
        total += interval["liters"]
        runtime += interval["runtime_seconds"]
    assert total == 3
    assert runtime == 180


def test_running_timer_unknown_and_parameter_change():
    cfg = config("running", rate_lph=60)
    basis, _ = step(None, "on", 0, cfg=cfg)
    basis, interval = calculate(
        cfg, basis, None, None, "2026-09-15T00:05:00Z", tick=True
    )
    assert interval["liters"] == 5
    assert interval["runtime_seconds"] == 300
    unknown, interval = step(basis, "unknown", 360, cfg=cfg)
    assert interval is None
    assert step(unknown, "on", 420, cfg=cfg)[1] is None
    assert step(basis, "on", 360, cfg=config("running", rate_lph=30))[1] is None
    assert step(None, "on", 360, cfg=cfg)[1] is None
