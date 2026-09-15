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

from .consumption import calculate, validate_config
from .model import append, replay, timestamp

_LOGGER = logging.getLogger(__name__)


class TankRuntime:
    def __init__(self, hass, entry, store, data):
        self.hass, self.entry, self.store, self.data = hass, entry, store, data
        self.lock = asyncio.Lock()
        self.listeners = set()
        self.available = True
        self.active = True
        self.unsubscribers = []
        self.failed_sources = set()

    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    def source_valid(self, source_id):
        if source_id not in self.entry.subentries:
            return False
        basis = self.data["sources"].get(source_id)
        if basis is None or basis["value"] is None:
            return False
        config = dict(self.entry.subentries[source_id].data)
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
        config = dict(self.entry.subentries[source_id].data)
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
        if interval and interval["liters"] > 0:
            candidate = append(
                candidate,
                {
                    "id": f"{source_id}:{at}",
                    "at": dt_util.utcnow().isoformat(),
                    "kind": "consumption",
                    "source_id": source_id,
                    **interval,
                },
                manual=False,
            )
        return candidate

    async def book(self, kind, liters=0, event_id=None):
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
            if any(e["id"] == event["id"] for e in self.data["events"]):
                append(self.data, event)  # Validate content of duplicate request.
                return
            candidate = self.data
            # Close known time intervals before setting an absolute stock.
            # Commit consumption and manual event atomically under one lock.
            for sid, subentry in self.entry.subentries.items():
                if subentry.data["mode"] != "counter":
                    candidate = self.advance(
                        candidate, sid, None, None, event["at"], tick=True
                    )
            event["at"] = dt_util.utcnow().isoformat()
            await self.commit(append(candidate, event))

    async def ingest(
        self, source_id, value, unit, at, *, tick=False, rebase=False, reported_at=None
    ):
        async with self.lock:
            if not self.active or source_id not in self.entry.subentries:
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
        for source_id, subentry in self.entry.subentries.items():
            config = validate_config(subentry.data)

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
        if self.entry.subentries:
            self.unsubscribers.append(
                async_track_time_interval(self.hass, self.tick, timedelta(seconds=30))
            )

    async def tick(self, now):
        for source_id, subentry in self.entry.subentries.items():
            if subentry.data["mode"] == "counter":
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
