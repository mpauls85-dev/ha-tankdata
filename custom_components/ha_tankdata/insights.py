"""Pure statistics, weighted inventory costs and evidence-based forecasts."""

from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

from .model import replay, timestamp


def costs(data):
    stock = data["initial"]
    price = data["analysis"]["settings"]["initial_price"]
    known = stock == 0 or price is not None
    value = stock * (price or 0)
    expenses = []
    consumption = {}
    reset = max(
        (i for i, e in enumerate(data["events"]) if e["kind"] == "reset"), default=-1
    )
    for i, event in enumerate(data["events"]):
        kind, liters = event["kind"], event["liters"]
        if kind == "refill":
            cost = event.get("total_cost")
            expenses.append({"at": event["at"], "cost": cost})
            if liters:
                if stock <= 0:
                    known, value, stock = True, 0.0, 0.0
                known = known and cost is not None
                value += cost or 0
                stock += liters
        elif kind in {"consumption", "withdrawal"}:
            cost = (
                value / stock * liters
                if known and stock > 0 and liters <= stock
                else (0 if liters == 0 else None)
            )
            if kind == "consumption":
                consumption[event["id"]] = cost
            value = max(0, value * (stock - liters) / stock) if stock > 0 else 0
            stock -= liters
            if stock < 0:
                known = False
        elif kind == "correction" and i > reset:
            if liters > stock:
                known = False
            value = value * liters / stock if stock > 0 else 0
            stock = liters
    return {
        "inventory_value": value if known and stock >= 0 else None,
        "unit_price": value / stock if known and stock > 0 else None,
        "consumption": consumption,
        "expenses": expenses,
    }


def coverage(intervals, start, end, source_id):
    segments = sorted(
        (max(start, timestamp(i["start"])), min(end, timestamp(i["end"])))
        for i in intervals
        if i["source_id"] == source_id
        and timestamp(i["end"]) > start
        and timestamp(i["start"]) < end
    )
    cursor, seconds, largest_gap = start, 0.0, 0.0
    for left, right in segments:
        largest_gap = max(largest_gap, (left - cursor).total_seconds())
        seconds += max(0, (right - max(left, cursor)).total_seconds())
        cursor = max(cursor, right)
    largest_gap = max(largest_gap, (end - cursor).total_seconds())
    return seconds / (end - start).total_seconds(), largest_gap


def summarize(data, configs, now, days=30, tz="UTC", source_id=None):
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    start_day = today - timedelta(days=days - 1)
    start = datetime.combine(start_day, datetime.min.time(), zone)
    previous_start = start - timedelta(days=days)
    cost_data = costs(data)
    buckets = {}
    for index in range(days):
        day = start_day + timedelta(days=index)
        buckets[day.isoformat()] = {
            "date": day.isoformat(),
            "liters": 0.0,
            "runtime_hours": 0.0,
            "cost": 0.0,
            "cost_complete": True,
            "coverage": None,
        }
    previous = 0.0
    per_source = {}
    for event in data["events"]:
        if event["kind"] != "consumption" or (
            source_id and event.get("source_id") != source_id
        ):
            continue
        left, right = (
            timestamp(event.get("start", event["at"])),
            timestamp(event.get("end", event["at"])),
        )
        if right == left:
            left = right - timedelta(microseconds=1)
        total_seconds = (right - left).total_seconds()
        prior = (
            max(0, (min(right, start) - max(left, previous_start)).total_seconds())
            / total_seconds
        )
        previous += event["liters"] * prior
        cursor, finish = max(left, start), min(right, now)
        while cursor < finish:
            date = cursor.astimezone(zone).date()
            midnight = datetime.combine(
                date + timedelta(days=1), datetime.min.time(), zone
            ).astimezone(timezone.utc)
            stop = min(finish, midnight)
            part = (stop - cursor).total_seconds() / total_seconds
            bucket = buckets.get(date.isoformat())
            if bucket:
                liters = event["liters"] * part
                bucket["liters"] += liters
                bucket["runtime_hours"] += event.get("runtime_seconds", 0) * part / 3600
                cost = cost_data["consumption"].get(event["id"])
                if cost is None and liters:
                    bucket["cost_complete"] = False
                else:
                    bucket["cost"] += (cost or 0) * part
                sid = event.get("source_id", "unknown")
                per_source[sid] = per_source.get(sid, 0) + liters
            cursor = stop
    sources = [source_id] if source_id else list(configs)
    for bucket in buckets.values():
        left = datetime.combine(
            datetime.fromisoformat(bucket["date"]).date(), datetime.min.time(), zone
        ).astimezone(timezone.utc)
        right = min(
            now,
            datetime.combine(
                left.astimezone(zone).date() + timedelta(days=1),
                datetime.min.time(),
                zone,
            ).astimezone(timezone.utc),
        )
        if sources and right > left:
            bucket["coverage"] = min(
                coverage(data["analysis"]["intervals"], left, right, sid)[0]
                for sid in sources
            )
        if not bucket["cost_complete"]:
            bucket["cost"] = None
    daily = list(buckets.values())
    expenses = [
        e["cost"] for e in cost_data["expenses"] if start <= timestamp(e["at"]) <= now
    ]
    return {
        "days": daily,
        "liters": sum(b["liters"] for b in daily),
        "previous_liters": previous,
        "runtime_hours": sum(b["runtime_hours"] for b in daily),
        "by_source": per_source,
        "cost": sum(b["cost"] for b in daily)
        if all(b["cost"] is not None for b in daily)
        else None,
        "expenses": sum(expenses) if all(v is not None for v in expenses) else None,
        "inventory_value": cost_data["inventory_value"],
        "unit_price": cost_data["unit_price"],
    }


def forecast(data, configs, now, tz="UTC"):
    report = summarize(data, configs, now, 31, tz)
    complete = [
        d
        for d in report["days"][:-1]
        if d["coverage"] is not None and d["coverage"] >= 0.99
    ]
    if len(complete) < 7 or any(
        d["coverage"] is None or d["coverage"] < 0.99 for d in report["days"][-8:-1]
    ):
        return {
            "available": False,
            "reason": "Mindestens sieben vollständige aktuelle Messtage erforderlich.",
        }
    values = [d["liters"] for d in complete]
    rate = mean(values)
    if rate <= 0:
        return {
            "available": False,
            "reason": "Zuletzt kein Verbrauch: kein belastbares Leerstandsdatum.",
        }
    stock = max(0, replay(data)["stock"])
    reserve = data["analysis"]["settings"]["reserve_liters"]
    spread = pstdev(values)

    def date_for(amount):
        days = max(0, amount) / rate
        return (now + timedelta(days=days)).date().isoformat() if days <= 3650 else None

    return {
        "available": True,
        "daily_liters": rate,
        "next_7": rate * 7,
        "next_30": rate * 30,
        "low_30": max(0, rate - spread) * 30,
        "high_30": (rate + spread) * 30,
        "days_remaining": stock / rate,
        "empty_date": date_for(stock),
        "reserve_date": date_for(stock - reserve),
        "sample_days": len(values),
        "method": (
            "Mittelwert vollständiger Tage der letzten 30 Tage; keine Wetterprognose."
        ),
    }
