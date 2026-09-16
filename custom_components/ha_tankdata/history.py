"""Read-only run summaries over the original consumption ledger."""

from .model import timestamp


def grouped_history(data, running, configs):
    """Keep source runs intact across pages without changing any ledger event."""
    rows, pending = [], {}
    for index, event in enumerate(data["events"]):
        sid = event.get("source_id")
        config = event.get("config", {})
        eligible = (
            event["kind"] == "consumption"
            and sid
            and config.get("mode") in {"running", "power"}
            and all(k in event for k in ("start", "end", "input_before", "input_after"))
            and event.get("runtime_seconds", 0) > 0
        )
        if not eligible:
            rows.append({**event, "position": index})
            if event["kind"] != "consumption":
                pending.clear()
            else:
                pending.pop(sid, None)
            continue
        row = pending.get(sid)
        last = row["members"][-1] if row else None
        if not (
            last
            and timestamp(last["end"]) == timestamp(event["start"])
            and last["input_after"] > 0
            and last["config"] == config
        ):
            row = {
                "id": event["id"],
                "kind": "run",
                "source_id": sid,
                "position": index,
                "at": event["at"],
                "start": event["start"],
                "end": event["end"],
                "liters": 0.0,
                "runtime_seconds": 0.0,
                "members": [],
                "count": 0,
                "status": "interrupted",
            }
            rows.append(row)
            pending[sid] = row
        row["members"].append(event)
        row["count"] += 1
        row["liters"] += event["liters"]
        row["runtime_seconds"] += event["runtime_seconds"]
        row["end"] = event["end"]
        row["status"] = "finished" if event["input_after"] == 0 else "interrupted"
    for sid, row in pending.items():
        last = row["members"][-1]
        basis = data["sources"].get(sid, {})
        if (
            running.get(sid) is True
            and last["input_after"] > 0
            and configs.get(sid) == last["config"]
            and basis.get("at")
            and timestamp(basis["at"]) == timestamp(last["end"])
        ):
            row["status"] = "running"
    return rows


def history_page(data, running, configs, *, limit=50, before=None, run_id=None):
    rows = grouped_history(data, running, configs)
    if run_id is not None:
        row = next((r for r in rows if r["kind"] == "run" and r["id"] == run_id), None)
        if row is None:
            raise ValueError("Lauf nicht gefunden")
        members = row["members"]
        end = min(len(members), len(members) if before is None else before)
        start = max(0, end - limit)
        return {
            "events": list(reversed(members[start:end])),
            "before": start,
            "count": len(members),
        }
    end = len(data["events"]) if before is None else before
    eligible = [row for row in rows if row["position"] < end]
    selected = eligible[-limit:]
    return {
        "events": [
            {k: v for k, v in row.items() if k not in {"members", "position"}}
            for row in reversed(selected)
        ],
        "before": selected[0]["position"] if len(eligible) > limit else 0,
        "count": len(rows),
    }
