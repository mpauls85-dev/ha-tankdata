"""Deterministic tank ledger, independent of Home Assistant."""

from copy import deepcopy
from datetime import datetime
from math import isclose, isfinite

KINDS = {"observation", "refill", "withdrawal", "correction", "consumption", "reset"}


def number(value, *, positive=False):
    """Reject booleans, non-finite and negative amounts."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a number")
    if not isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError("Invalid amount")
    return float(value)


def timestamp(value):
    """Require timezone-aware ISO timestamps."""
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must have a timezone")
    return parsed


def new_tank(capacity, initial):
    capacity = number(capacity, positive=True)
    initial = number(initial)
    if initial > capacity:
        raise ValueError("Initial stock exceeds capacity")
    from .analysis import defaults

    return {
        "capacity": capacity,
        "initial": initial,
        "events": [],
        "sources": {},
        "analysis": defaults(),
    }


def replay(data):
    """Replay in append order; resets deactivate prior correction effects only."""
    base = new_tank(data["capacity"], data["initial"])
    events = data["events"]
    reset = max((i for i, e in enumerate(events) if e["kind"] == "reset"), default=-1)
    stock, consumed, runtime = base["initial"], 0.0, 0.0
    seen = set()
    previous = None
    for index, event in enumerate(events):
        event_id, kind = event["id"], event["kind"]
        if not isinstance(event_id, str) or not event_id or event_id in seen:
            raise ValueError("Invalid or duplicate event id")
        seen.add(event_id)
        at = timestamp(event["at"])
        if previous is not None and at < previous:
            raise ValueError("Events out of order")
        previous = at
        if kind not in KINDS:
            raise ValueError("Unknown event kind")
        liters = number(event["liters"])
        if "total_cost" in event:
            if kind != "refill" or liters <= 0:
                raise ValueError("Cost requires a positive refill")
            number(event["total_cost"])
        if kind in {"observation", "correction"} and liters > base["capacity"]:
            raise ValueError("Measurement exceeds capacity")
        if kind == "reset" and liters != 0:
            raise ValueError("Reset amount must be zero")
        if kind == "refill":
            stock += liters
        elif kind in {"withdrawal", "consumption"}:
            stock -= liters
            if kind == "consumption":
                consumed += liters
                runtime += number(event.get("runtime_seconds", 0))
        elif kind == "correction" and index > reset:
            stock = liters
    return {
        "stock": stock,
        "percent": stock / base["capacity"] * 100,
        "consumed": consumed,
        "runtime": runtime,
        "out_of_bounds": (
            stock < 0
            and not isclose(stock, 0, abs_tol=1e-9)
            or stock > base["capacity"]
            and not isclose(stock, base["capacity"], rel_tol=1e-12, abs_tol=1e-9)
        ),
    }


def validate(data):
    if set(data) != {"capacity", "initial", "events", "sources", "analysis"}:
        raise ValueError("Unknown tank data format")
    if not isinstance(data["events"], list) or not isinstance(data["sources"], dict):
        raise ValueError("Invalid ledger structure")
    from .analysis import validate_analysis

    validate_analysis(data)
    state = replay(data)
    if not all(isfinite(state[k]) for k in ("stock", "percent", "consumed", "runtime")):
        raise ValueError("Tank totals overflow")
    # Local import keeps the numerical module usable without HA dependencies.
    from .consumption import validate_basis, validate_interval

    for event in data["events"]:
        if "source_id" in event:
            validate_interval(event)

    for source_id, basis in data["sources"].items():
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("Invalid source id")
        validate_basis(basis)
    return data


def append(data, event, *, manual=True):
    """Return a candidate; never mutate committed state."""
    for existing in data["events"]:
        if existing["id"] == event["id"]:
            # Server timestamp is not part of a caller's idempotency request.
            if {k: v for k, v in existing.items() if k != "at"} != {
                k: v for k, v in event.items() if k != "at"
            }:
                raise ValueError("Event id already used with different content")
            return deepcopy(data)
    result = deepcopy(data)
    result["events"].append(deepcopy(event))
    state = replay(result)
    if manual and event["kind"] not in {"observation", "reset"}:
        if state["out_of_bounds"]:
            raise ValueError("Resulting stock is outside tank capacity")
    return result
