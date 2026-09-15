"""Versioned analysis settings and conservative calibration proposals."""

import json
from copy import deepcopy
from hashlib import sha256

from .geometry import validate_geometry
from .insights import coverage
from .model import number, timestamp


def defaults():
    return {
        "settings": {
            "geometry": {"shape": "rectangle"},
            "initial_price": None,
            "reserve_liters": 0,
            "calibration_enabled": True,
            "measurement_tolerance_liters": 10,
        },
        "intervals": [],
        "proposals": [],
    }


def settings(value, capacity):
    if set(value) != set(defaults()["settings"]):
        raise ValueError("Unbekannte Einstellungen")
    result = deepcopy(value)
    result["geometry"] = validate_geometry(value["geometry"], capacity)
    for key in ("reserve_liters", "measurement_tolerance_liters"):
        result[key] = number(value[key])
    if result["reserve_liters"] > capacity:
        raise ValueError("Reserve überschreitet die Kapazität")
    if value["initial_price"] is not None:
        result["initial_price"] = number(value["initial_price"])
    if not isinstance(value["calibration_enabled"], bool):
        raise ValueError("Ungültige Kalibriereinstellung")
    return result


def validate_analysis(data):
    from .consumption import validate_config

    analysis = data["analysis"]
    if set(analysis) != {"settings", "intervals", "proposals"}:
        raise ValueError("Invalid analysis structure")
    settings(analysis["settings"], data["capacity"])
    if not isinstance(analysis["intervals"], list) or not isinstance(
        analysis["proposals"], list
    ):
        raise ValueError("Invalid analysis lists")
    for interval in analysis["intervals"]:
        if (
            not isinstance(interval["source_id"], str)
            or not interval["source_id"]
            or timestamp(interval["end"]) <= timestamp(interval["start"])
        ):
            raise ValueError("Invalid coverage interval")
    seen = set()
    for proposal in analysis["proposals"]:
        if proposal["id"] in seen or proposal["status"] not in {
            "pending",
            "rejected",
            "approved",
            "applied",
            "stale",
        }:
            raise ValueError("Invalid proposal")
        seen.add(proposal["id"])
        number(proposal["old_rate"], positive=True)
        number(proposal["new_rate"], positive=True)
        config = validate_config(proposal["config"])
        if (
            not isinstance(proposal["source_id"], str)
            or not proposal["source_id"]
            or config["mode"] not in {"running", "power"}
            or proposal["old_rate"] != config["rate_lph"]
            or proposal["new_rate"] > config["max_rate_lph"]
        ):
            raise ValueError("Invalid proposed configuration")
        evidence = proposal["evidence"]
        if timestamp(evidence["end"]) <= timestamp(evidence["start"]):
            raise ValueError("Invalid measurement period")
        number(evidence["measured_liters"], positive=True)
        number(evidence["runtime_hours"], positive=True)
        if not 0 <= number(evidence["coverage"]) <= 1:
            raise ValueError("Invalid coverage")
        timestamp(proposal["at"])
        if proposal["status"] in {"approved", "applied"}:
            timestamp(proposal["confirmed_at"])


def add_coverage(data, source_id, interval):
    intervals = data["analysis"]["intervals"]
    for previous in reversed(intervals):
        if previous["source_id"] == source_id:
            if previous["end"] == interval["start"]:
                previous["end"] = interval["end"]
                return
            break
    intervals.append(
        {"source_id": source_id, "start": interval["start"], "end": interval["end"]}
    )


def propose(data, configs):
    """Only propose an attributable, bounded rate from two real observations."""
    options = data["analysis"]["settings"]
    if not options["calibration_enabled"] or len(configs) != 1:
        return None
    sid, config = next(iter(configs.items()))
    if config["mode"] not in {"running", "power"}:
        return None
    observations = [e for e in data["events"] if e["kind"] == "observation"]
    if len(observations) < 2:
        return None
    first, last = observations[-2:]
    start, end = timestamp(first["at"]), timestamp(last["at"])
    if (end - start).total_seconds() < 86400:
        return None
    fraction, gap = coverage(data["analysis"]["intervals"], start, end, sid)
    if fraction < 0.99 or gap > config["max_gap_seconds"]:
        return None
    measured, runtime = first["liters"] - last["liters"], 0.0
    for event in data["events"]:
        at = timestamp(event["at"])
        if start < at <= end:
            if event["kind"] in {"correction", "reset"}:
                return None
            if event["kind"] == "refill":
                measured += event["liters"]
            elif event["kind"] == "withdrawal":
                measured -= event["liters"]
        if event["kind"] != "consumption":
            continue
        left, right = (
            timestamp(event.get("start", event["at"])),
            timestamp(event.get("end", event["at"])),
        )
        seconds = max(0, (min(end, right) - max(start, left)).total_seconds())
        if not seconds:
            continue
        if event.get("source_id") != sid or event.get("config") != config:
            return None
        runtime += (
            event.get("runtime_seconds", 0) * seconds / (right - left).total_seconds()
        )
    if runtime < 3600 or measured <= max(
        1, options["measurement_tolerance_liters"] * 20
    ):
        return None
    new_rate = measured / (runtime / 3600)
    old_rate = config["rate_lph"]
    if (
        not 0.02 <= abs(new_rate / old_rate - 1) <= 0.20
        or new_rate > config["max_rate_lph"]
    ):
        return None
    evidence = {
        "first": first["id"],
        "last": last["id"],
        "start": first["at"],
        "end": last["at"],
        "measured_liters": measured,
        "runtime_hours": runtime / 3600,
        "coverage": fraction,
    }
    identity = sha256(
        json.dumps([sid, config, evidence], sort_keys=True).encode()
    ).hexdigest()
    return {
        "id": identity,
        "source_id": sid,
        "config": deepcopy(config),
        "old_rate": old_rate,
        "new_rate": round(new_rate, 6),
        "at": last["at"],
        "evidence": evidence,
        "status": "pending",
    }
