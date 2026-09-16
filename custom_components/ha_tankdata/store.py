"""HA Store with strict corruption handling and confirmed disk writes."""

import json
import os
from hashlib import sha256
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .model import validate


class TankStore:
    def __init__(self, hass, entry_id):
        self.hass = hass
        self.store = Store(hass, 3, f"ha_tankdata.{entry_id}", atomic_writes=True)
        self.needs_migration = False
        self.legacy_content = None

    def _read(self):
        path = Path(self.store.path)
        try:
            content = path.read_bytes()
            raw = json.loads(content)
        except FileNotFoundError:
            return None
        if not isinstance(raw, dict):
            raise ValueError("Invalid TankData store envelope")
        if (raw.get("version"), raw.get("minor_version", 1)) not in {
            (1, 1),
            (2, 1),
            (3, 1),
        }:
            raise ValueError("Unsupported TankData store version")
        if raw.get("key") != self.store.key:
            raise ValueError("TankData store key mismatch")
        data = raw["data"]
        if raw["version"] == 1:
            if set(data) != {"capacity", "initial", "events", "sources"}:
                raise ValueError("Invalid legacy data")
            from .analysis import defaults

            data = {**data, "analysis": defaults()}
        validate(data)
        self.needs_migration = raw["version"] < 3
        self.legacy_content = content if self.needs_migration else None
        if self.needs_migration:
            if any("segment" in event for event in data["events"]):
                raise ValueError("Legacy store contains unsupported segments")
            from .segments import compact_legacy

            return compact_legacy(data)
        return data

    def _backup_legacy(self):
        content = self.legacy_content
        if content is None:
            return
        path = Path(self.store.path)
        if path.read_bytes() != content:
            raise ValueError("Legacy store changed during migration")
        backup = path.with_name(
            path.name + ".before-v3-" + sha256(content).hexdigest()[:12]
        )
        try:
            with backup.open("xb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        except FileExistsError:
            if backup.read_bytes() != content:
                raise ValueError("Migration backup differs from original") from None

    async def load(self):
        # Preflight prevents HA's generic corrupt-file recovery from creating
        # an apparently new, empty tank. Read the disk, not a cached pending write.
        return await self.hass.async_add_executor_job(self._read)

    async def save(self, data):
        validate(data)
        await self.hass.async_add_executor_job(self._backup_legacy)
        await self.store.async_save(data)
        # HA 2026.9 Store logs some write failures instead of propagating them.
        # Confirm durable content before acknowledging a booking.
        if await self.load() != data or self.needs_migration:
            raise HomeAssistantError("TankData storage write was not confirmed")
