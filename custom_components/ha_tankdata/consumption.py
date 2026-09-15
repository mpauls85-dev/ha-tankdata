"""Pure source calculations. Persist input and configuration with every interval."""

from collections.abc import Mapping
from math import isclose

from .model import number, timestamp

MODES = {"counter", "flow", "running", "power"}


def validate_config(config):
    if not isinstance(config, Mapping):
        raise ValueError("Invalid consumer configuration")
    if not all(
        isinstance(config.get(key), str) for key in ("name", "mode", "entity_id")
    ):
        raise ValueError("Invalid consumer identity")
    if config["mode"] not in MODES:
        raise ValueError("Unknown source type")
    if not config["name"].strip() or not config["entity_id"].startswith(
        ("sensor.", "binary_sensor.", "switch.", "input_boolean.")
    ):
        raise ValueError("Invalid source")
    if config["mode"] in {"running", "power"}:
        number(config["rate_lph"], positive=True)
        if config["rate_lph"] > config["max_rate_lph"]:
            raise ValueError("Configured rate exceeds maximum")
    if config["mode"] != "running" and not config["entity_id"].startswith("sensor."):
        raise ValueError("Numeric sensor required")
    if config["mode"] == "power":
        number(config["on_threshold_w"], positive=True)
        number(config["off_threshold_w"])
        if config["on_threshold_w"] <= config["off_threshold_w"]:
            raise ValueError("On threshold must exceed off threshold")
    number(config["max_gap_seconds"], positive=True)
    number(config["max_rate_lph"], positive=True)
    return dict(config)


def parse(value, unit, config, previous=None):
    try:
        if config["mode"] == "running":
            return {"on": config["rate_lph"], "off": 0}[value]
        parsed = number(float(value))
        if config["mode"] == "power":
            watts = number(parsed * {"W": 1, "kW": 1000}[unit])
            if watts >= config["on_threshold_w"]:
                return config["rate_lph"]
            if watts <= config["off_threshold_w"]:
                return 0
            return previous["value"] if previous else None
        if config["mode"] == "counter":
            return number(parsed * {"L": 1, "l": 1, "m³": 1000}[unit])
        rate = number(
            parsed * {"L/h": 1, "l/h": 1, "L/min": 60, "l/min": 60, "m³/h": 1000}[unit]
        )
        return rate if rate <= config["max_rate_lph"] else None
    except ValueError, TypeError, KeyError, OverflowError:
        return None


def calculate(config, previous, value, unit, at, *, tick=False, reported_at=None):
    """Return next basis and optional interval; stale updates have no effect."""
    validate_config(config)
    now = timestamp(at)
    if previous and timestamp(previous["at"]) >= now:
        return previous, None
    valid_previous = previous
    if previous and (
        previous["config"] != config
        or (
            now - timestamp(previous.get("reported_at", previous["at"]))
        ).total_seconds()
        > config["max_gap_seconds"]
    ):
        valid_previous = None
    parsed = (
        previous["value"]
        if tick and previous
        else parse(value, unit, config, valid_previous)
    )
    if tick and valid_previous is None:
        parsed = None
    basis = {"config": dict(config), "at": at, "value": parsed}
    basis["raw_value"] = previous.get("raw_value") if tick and previous else value
    basis["unit"] = previous.get("unit") if tick and previous else unit
    if config["mode"] != "counter":
        basis["reported_at"] = (
            previous.get("reported_at", at) if tick and previous else reported_at or at
        )
        if (now - timestamp(basis["reported_at"])).total_seconds() > config[
            "max_gap_seconds"
        ]:
            basis["value"] = None
            return basis, None
    if (
        not previous
        or previous["config"] != config
        or parsed is None
        or previous["value"] is None
    ):
        return basis, None
    seconds = (now - timestamp(previous["at"])).total_seconds()
    if seconds > config["max_gap_seconds"]:
        return basis, None
    if config["mode"] == "counter":
        liters = parsed - previous["value"]
    else:
        if (now - timestamp(previous["reported_at"])).total_seconds() > config[
            "max_gap_seconds"
        ]:
            return basis, None
        liters = previous["value"] * seconds / 3600
    if liters < 0 or liters > config["max_rate_lph"] * seconds / 3600:
        return basis, None
    return basis, {
        "liters": liters,
        "runtime_seconds": (
            seconds
            if config["mode"] in {"running", "power"} and previous["value"] > 0
            else 0
        ),
        "start": previous["at"],
        "end": at,
        "input_before": previous["value"],
        "input_after": parsed,
        "raw_before": previous.get("raw_value"),
        "raw_after": basis["raw_value"],
        "unit_before": previous.get("unit"),
        "unit_after": basis["unit"],
        "config": dict(config),
    }


def validate_basis(basis):
    validate_config(basis["config"])
    timestamp(basis["at"])
    if basis["config"]["mode"] != "counter":
        if timestamp(basis["reported_at"]) > timestamp(basis["at"]):
            raise ValueError("Report time exceeds integration cursor")
    if basis["value"] is not None:
        number(basis["value"])


def validate_interval(event):
    """Check persisted calculated volumes against the retained numerical basis."""
    config = validate_config(event["config"])
    if event["kind"] != "consumption" or not isinstance(event["source_id"], str):
        raise ValueError("Invalid calculated event")
    seconds = (timestamp(event["end"]) - timestamp(event["start"])).total_seconds()
    if not 0 < seconds <= config["max_gap_seconds"]:
        raise ValueError("Invalid consumption interval")
    before, after = number(event["input_before"]), number(event["input_after"])
    expected = (
        after - before if config["mode"] == "counter" else before * seconds / 3600
    )
    runtime = seconds if config["mode"] in {"running", "power"} and before > 0 else 0
    if (
        expected < 0
        or not isclose(expected, event["liters"], abs_tol=1e-9)
        or not isclose(runtime, number(event["runtime_seconds"]), abs_tol=1e-9)
    ):
        raise ValueError("Calculated consumption differs from saved inputs")
