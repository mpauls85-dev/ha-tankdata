from copy import deepcopy

import pytest

from custom_components.ha_tankdata.model import append, new_tank, replay, validate


def event(kind, liters=0, id="a", at="2026-09-15T00:00:00+00:00"):
    return {"id": id, "kind": kind, "liters": liters, "at": at}


def test_mixed_history_and_reset():
    tank = new_tank(1000, 500)
    for i, (kind, amount) in enumerate(
        [
            ("refill", 100),
            ("withdrawal", 20),
            ("observation", 570),
            ("correction", 570),
            ("consumption", 30),
        ]
    ):
        tank = append(tank, event(kind, amount, str(i)))
    assert replay(tank)["stock"] == 540
    assert replay(tank)["consumed"] == 30
    assert replay(tank) == replay(deepcopy(tank))
    reset = append(tank, event("reset", id="reset"))
    assert replay(reset)["stock"] == 550
    assert reset["events"][:-1] == tank["events"]
    reset = append(reset, event("correction", 600, "new"))
    assert replay(reset)["stock"] == 600


def test_idempotence_and_conflict():
    tank = append(new_tank(100, 0), event("refill", 10))
    assert append(tank, event("refill", 10, at="2026-09-16T00:00:00Z")) == tank
    with pytest.raises(ValueError):
        append(tank, event("refill", 11))


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, None, "10"])
def test_invalid_numbers(value):
    with pytest.raises(ValueError):
        new_tank(100, value)


def test_limits_and_preserve_automatic_consumption():
    assert replay(new_tank(100, 0))["percent"] == 0
    assert replay(new_tank(100, 100))["percent"] == 100
    with pytest.raises(ValueError):
        new_tank(0, 0)
    with pytest.raises(ValueError):
        append(new_tank(100, 99), event("refill", 2))
    with pytest.raises(ValueError):
        append(new_tank(100, 1), event("withdrawal", 2))
    tank = append(new_tank(100, 1), event("consumption", 2), manual=False)
    assert replay(tank)["stock"] == -1
    assert replay(tank)["out_of_bounds"]


def test_invalid_history():
    tank = append(new_tank(100, 50), event("refill", 1))
    before = deepcopy(tank)
    with pytest.raises(ValueError):
        append(tank, event("refill", 1, "b", "2020-01-01T00:00:00Z"))
    with pytest.raises(ValueError):
        append(tank, event("refill", 1, "b", "2026-09-15T00:00:00"))
    assert tank == before
    tank["events"].append(tank["events"][0])
    with pytest.raises(ValueError):
        validate(tank)


@pytest.mark.parametrize(
    "kind,amount",
    [("other", 0), ("observation", 101), ("correction", 101), ("reset", 1)],
)
def test_invalid_event(kind, amount):
    with pytest.raises(ValueError):
        append(new_tank(100, 50), event(kind, amount))


def test_decimal_rounding_at_capacity_is_not_a_real_overflow():
    tank = append(new_tank(0.3, 0.2), event("refill", 0.1))
    assert replay(tank)["stock"] == pytest.approx(0.3)
    assert not replay(tank)["out_of_bounds"]
