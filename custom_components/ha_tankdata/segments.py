"""Compact constant-rate runs without retaining individual sensor updates."""

from copy import deepcopy
from math import isclose

from .model import replay, timestamp, validate


def eligible(event):
    config = event.get("config", {})
    return (
        event["kind"] == "consumption"
        and bool(event.get("source_id"))
        and config.get("mode") in {"running", "power"}
        and event.get("input_before") == config.get("rate_lph")
        and event.get("input_after") in {0, config.get("rate_lph")}
        and event.get("runtime_seconds", 0) > 0
        and "start" in event
        and "end" in event
    )


def segment(event):
    result = deepcopy(event)
    if not result.get("segment"):
        result.update(
            segment=True,
            steps=1,
            max_step_seconds=(
                timestamp(event["end"]) - timestamp(event["start"])
            ).total_seconds(),
        )
    return result


def join(previous, event):
    """Both intervals must prove a continuous, unchanged configured rate."""
    if not (
        eligible(previous)
        and eligible(event)
        and previous["source_id"] == event["source_id"]
        and previous["config"] == event["config"]
        and previous["input_after"] == event["input_before"]
        and timestamp(previous["end"]) == timestamp(event["start"])
    ):
        return None
    result, next_part = segment(previous), segment(event)
    result["end"] = event["end"]
    result["input_after"] = event["input_after"]
    for key in ("raw_after", "unit_after"):
        if key in event:
            result[key] = event[key]
        else:
            result.pop(key, None)
    result["liters"] += event["liters"]
    result["runtime_seconds"] += event["runtime_seconds"]
    result["steps"] += next_part["steps"]
    result["max_step_seconds"] = max(
        result["max_step_seconds"], next_part["max_step_seconds"]
    )
    return result


def append_consumption(data, event):
    """Update a source's segment atomically with its already advanced cursor."""
    result = deepcopy(data)
    events = result["events"]
    compact = eligible(event)
    # Do not move consumption across other sources at a depleted stock boundary:
    # that would change which original interval had unknown valuation.
    if compact and replay(data)["stock"] >= event["liters"]:
        for index in range(len(events) - 1, -1, -1):
            previous = events[index]
            if previous["kind"] != "consumption":
                break
            if previous.get("source_id") == event["source_id"]:
                merged = join(previous, event)
                if merged is not None:
                    events[index] = merged
                    return result
                break
    events.append(segment(event) if compact else deepcopy(event))
    return result


def compact_legacy(data):
    """Single pass migration; manual events and original source cursors survive."""
    validate(data)
    result = deepcopy(data)
    result["events"] = []
    pending = {}
    stock = data["initial"]
    reset = max(
        (i for i, e in enumerate(data["events"]) if e["kind"] == "reset"), default=-1
    )
    for index, event in enumerate(data["events"]):
        kind = event["kind"]
        if kind == "refill":
            stock += event["liters"]
        elif kind in {"consumption", "withdrawal"}:
            stock -= event["liters"]
        elif kind == "correction" and index > reset:
            stock = event["liters"]
        if kind != "consumption":
            pending.clear()
        sid = event.get("source_id")
        position = pending.get(sid)
        if eligible(event):
            merged = (
                join(result["events"][position], event)
                if position is not None and stock >= 0
                else None
            )
            if merged is not None:
                result["events"][position] = merged
                continue
            pending[sid] = len(result["events"])
            result["events"].append(segment(event))
        else:
            pending.pop(sid, None)
            result["events"].append(deepcopy(event))
    validate(result)
    old, new = replay(data), replay(result)
    if any(
        not isclose(old[key], new[key], rel_tol=1e-10, abs_tol=1e-8)
        for key in ("stock", "consumed", "runtime")
    ):
        raise ValueError("Segment migration changed tank totals")
    return result
