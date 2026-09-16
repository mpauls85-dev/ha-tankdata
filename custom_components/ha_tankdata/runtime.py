"""Serialized tank transactions and entity notifications."""

import asyncio
import logging
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .analysis import add_coverage, propose, settings
from .configuration import consumers
from .consumption import calculate, validate_config
from .geometry import to_liters
from .model import append, replay, timestamp
from .segments import append_consumption

_LOGGER = logging.getLogger(__name__)


class TankRuntime:
    def __init__(self, hass, entry, store, data):
        self.hass, self.entry, self.store, self.data = hass, entry, store, data
        self.lock = asyncio.Lock()
        self.reconfigure_lock = asyncio.Lock()
        self.listeners = set()
        self.available = True
        self.active = True
        self.unsubscribers = []
        self.failed_sources = set()
        self.excluded_sources = set()

    @property
    def consumers(self):
        return {
            sid: e
            for sid, e in consumers(self.hass, self.entry.entry_id).items()
            if sid not in self.excluded_sources
        }

    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    def source_valid(self, source_id):
        if source_id not in self.consumers:
            return False
        basis = self.data["sources"].get(source_id)
        if basis is None or basis["value"] is None:
            return False
        config = dict(self.consumers[source_id].data["config"])
        age = (
            dt_util.utcnow() - timestamp(basis.get("reported_at", basis["at"]))
        ).total_seconds()
        return basis["config"] == config and 0 <= age <= config["max_gap_seconds"]

    async def commit(self, candidate):
        # Do not release the transaction lock while an executor-backed disk write
        # is still running, even if the caller is cancelled during shutdown.
        task = asyncio.create_task(self._persist_and_publish(candidate))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _persist_and_publish(self, candidate):
        try:
            await self.store.save(candidate)
        except Exception:
            self.available = False
            self.notify()
            raise
        self.data = candidate
        self.available = True
        self.notify()

    def advance(
        self,
        data,
        source_id,
        value,
        unit,
        at,
        *,
        tick=False,
        rebase=False,
        reported_at=None,
    ):
        config = dict(self.consumers[source_id].data["config"])
        before = data["sources"].get(source_id)
        if tick and before and before["value"] is None:
            return data
        basis, interval = calculate(
            config,
            None if rebase else before,
            value,
            unit,
            at,
            tick=tick,
            reported_at=reported_at,
        )
        if basis == before:
            return data
        candidate = deepcopy(data)
        candidate["sources"][source_id] = basis
        if interval:
            add_coverage(candidate, source_id, interval)
        if interval and interval["liters"] > 0:
            candidate = append_consumption(
                candidate,
                {
                    "id": f"{source_id}:{at}",
                    "at": dt_util.utcnow().isoformat(),
                    "kind": "consumption",
                    "source_id": source_id,
                    **interval,
                },
            )
        return candidate

    async def book(self, kind, liters=0, event_id=None, *, total_cost=None, unit="L"):
        async with self.lock:
            if not self.active:
                raise ValueError("Tank is unloading")
            if kind is None:
                replay(self.data)
                self.notify()
                return
            event = {
                "id": event_id or uuid4().hex,
                "at": dt_util.utcnow().isoformat(),
                "kind": kind,
                "liters": liters,
            }
            if kind in {"observation", "correction"}:
                event["liters"] = to_liters(
                    liters,
                    unit,
                    self.data["analysis"]["settings"]["geometry"],
                    self.data["capacity"],
                )
                if unit != "L":
                    event["measurement"] = {"value": liters, "unit": unit}
            elif unit != "L":
                raise ValueError("Diese Buchung benötigt Liter")
            if total_cost is not None:
                event["total_cost"] = total_cost
            if any(e["id"] == event["id"] for e in self.data["events"]):
                append(self.data, event)  # Validate content of duplicate request.
                return
            candidate = self.data
            # Close known time intervals before setting an absolute stock.
            # Commit consumption and manual event atomically under one lock.
            for sid, subentry in self.consumers.items():
                if subentry.data["config"]["mode"] != "counter":
                    candidate = self.advance(
                        candidate, sid, None, None, event["at"], tick=True
                    )
            event["at"] = dt_util.utcnow().isoformat()
            candidate = append(candidate, event)
            if kind == "observation":
                for old in candidate["analysis"]["proposals"]:
                    if old["status"] == "pending":
                        old["status"] = "stale"
            proposal = propose(candidate, self.configs())
            if proposal and not any(
                p["id"] == proposal["id"] for p in candidate["analysis"]["proposals"]
            ):
                candidate["analysis"]["proposals"].append(proposal)
            await self.commit(candidate)
            self.notify_proposals()

    def configs(self):
        return {
            sid: dict(entry.data["config"]) for sid, entry in self.consumers.items()
        }

    def source_running(self, sid):
        if (
            not self.source_valid(sid)
            or self.consumers[sid].data["config"]["mode"] == "counter"
        ):
            return None
        return self.data["sources"][sid]["value"] > 0

    def notify_proposals(self):
        from homeassistant.components import persistent_notification

        pending = [
            p for p in self.data["analysis"]["proposals"] if p["status"] == "pending"
        ]
        notification_id = f"tankdata-calibration-{self.entry.entry_id}"
        if pending:
            persistent_notification.async_create(
                self.hass,
                "TankData hat einen Durchsatzvorschlag ermittelt. Bitte im "
                "[TankData-Dashboard](/tankdata) prüfen und bestätigen.",
                title=f"{self.entry.title}: Kalibrierung prüfen",
                notification_id=notification_id,
            )
        else:
            persistent_notification.async_dismiss(self.hass, notification_id)

    async def save_settings(self, value):
        async with self.lock:
            if not self.active:
                raise ValueError("Tank is unloading")
            candidate = deepcopy(self.data)
            candidate["analysis"]["settings"] = settings(value, candidate["capacity"])
            for proposal in candidate["analysis"]["proposals"]:
                if proposal["status"] == "pending":
                    proposal["status"] = "stale"
            await self.commit(candidate)
            self.notify_proposals()

    async def decide(self, proposal_id, decision):
        if decision not in {"accept", "reject", "later"}:
            raise ValueError("Unbekannte Entscheidung")
        async with self.lock:
            if not self.active:
                raise ValueError("Tank is unloading")
            candidate = deepcopy(self.data)
            proposal = next(
                (
                    p
                    for p in candidate["analysis"]["proposals"]
                    if p["id"] == proposal_id
                ),
                None,
            )
            if proposal is None:
                raise ValueError("Vorschlag nicht gefunden")
            if proposal["status"] == "applied" and decision == "accept":
                return
            if proposal["status"] != "pending":
                raise ValueError("Vorschlag nicht mehr offen")
            if decision == "later":
                return
            if decision == "accept":
                current = propose(candidate, self.configs())
                if current is None or current["id"] != proposal_id:
                    raise ValueError(
                        "Datengrundlage wurde geändert; Vorschlag ist veraltet"
                    )
                # Finish the observed old-rate interval before changing configuration.
                sid = proposal["source_id"]
                candidate = self.advance(
                    candidate, sid, None, None, dt_util.utcnow().isoformat(), tick=True
                )
                proposal = next(
                    p
                    for p in candidate["analysis"]["proposals"]
                    if p["id"] == proposal_id
                )
                proposal["status"] = "approved"
                proposal["confirmed_at"] = dt_util.utcnow().isoformat()
            else:
                proposal["status"] = "rejected"
                proposal["decided_at"] = dt_util.utcnow().isoformat()
            await self.commit(candidate)
            await self.recover_approved()
            self.notify_proposals()

    async def recover_approved(self):
        """Replay only durably recorded consent after an interrupted update."""
        latest = {
            p["source_id"]: p["id"]
            for p in self.data["analysis"]["proposals"]
            if p["status"] in {"approved", "applied"}
        }
        for proposal in list(self.data["analysis"]["proposals"]):
            if proposal["status"] not in {"approved", "applied"}:
                continue
            if latest[proposal["source_id"]] != proposal["id"]:
                continue
            child = self.consumers.get(proposal["source_id"])
            if proposal["status"] == "applied" and (
                child is None or child.data.get("calibration_id") == proposal["id"]
            ):
                continue
            expected = {**proposal["config"], "rate_lph": proposal["new_rate"]}
            status = "stale"
            if child and dict(child.data["config"]) in (proposal["config"], expected):
                if child.data.get("calibration_id") != proposal["id"]:
                    self.hass.config_entries.async_update_entry(
                        child,
                        data={
                            **child.data,
                            "config": expected,
                            "calibration_id": proposal["id"],
                        },
                    )
                status = "applied"
            candidate = deepcopy(self.data)
            target = next(
                p
                for p in candidate["analysis"]["proposals"]
                if p["id"] == proposal["id"]
            )
            target["status"] = status
            await self.commit(candidate)

    async def ingest(
        self, source_id, value, unit, at, *, tick=False, rebase=False, reported_at=None
    ):
        async with self.lock:
            if not self.active or source_id not in self.consumers:
                return
            candidate = self.advance(
                self.data,
                source_id,
                value,
                unit,
                at,
                tick=tick,
                rebase=rebase,
                reported_at=reported_at,
            )
            if candidate is not self.data:
                await self.commit(candidate)
            self.failed_sources.discard(source_id)

    def log_source_error(self, source_id):
        if source_id not in self.failed_sources:
            _LOGGER.exception("TankData source update failed for %s", source_id)
            self.failed_sources.add(source_id)
        self.available = False
        self.notify()

    async def start(self):
        for source_id, subentry in self.consumers.items():
            config = validate_config(subentry.data["config"])

            async def handle(event, sid=source_id):
                state = event.data.get("new_state")
                try:
                    await self.ingest(
                        sid,
                        state.state if state else None,
                        state.attributes.get("unit_of_measurement") if state else None,
                        state.last_reported.isoformat()
                        if state
                        else event.time_fired.isoformat(),
                    )
                except Exception:
                    self.log_source_error(sid)

            for tracker in (
                async_track_state_change_event,
                async_track_state_report_event,
            ):
                self.unsubscribers.append(
                    tracker(self.hass, config["entity_id"], handle)
                )
            state = self.hass.states.get(config["entity_id"])
            time_source = config["mode"] != "counter"
            if state is None and not time_source:
                # During HA startup the source may not have been restored yet.
                # Keep the durable counter baseline for its first live report.
                continue
            await self.ingest(
                source_id,
                state.state if state else None,
                state.attributes.get("unit_of_measurement") if state else None,
                (
                    dt_util.utcnow().isoformat()
                    if time_source or not state
                    else state.last_reported.isoformat()
                ),
                rebase=time_source,
                reported_at=state.last_reported.isoformat() if state else None,
            )
        if self.consumers:
            self.unsubscribers.append(
                async_track_time_interval(self.hass, self.tick, timedelta(seconds=30))
            )

    async def tick(self, now):
        for source_id, subentry in self.consumers.items():
            if subentry.data["config"]["mode"] == "counter":
                continue
            try:
                await self.ingest(source_id, None, None, now.isoformat(), tick=True)
            except Exception:
                self.log_source_error(source_id)
        self.notify()

    async def stop(self):
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        self.unsubscribers.clear()
        async with self.lock:
            self.active = False
