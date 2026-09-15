"""HA Store with strict corruption handling and confirmed disk writes."""

import json
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .model import validate


class TankStore:
    def __init__(self, hass, entry_id):
        self.hass = hass
        self.store = Store(hass, 2, f"ha_tankdata.{entry_id}", atomic_writes=True)

    def _read(self):
        path = Path(self.store.path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(raw, dict):
            raise ValueError("Invalid TankData store envelope")
        if (raw.get("version"), raw.get("minor_version", 1)) not in {(1, 1), (2, 1)}:
            raise ValueError("Unsupported TankData store version")
        if raw.get("key") != self.store.key:
            raise ValueError("TankData store key mismatch")
        data = raw["data"]
        if raw["version"] == 1:
            if set(data) != {"capacity", "initial", "events", "sources"}:
                raise ValueError("Invalid legacy data")
            from .analysis import defaults

            data = {**data, "analysis": defaults()}
        return validate(data)

    async def load(self):
        # Preflight prevents HA's generic corrupt-file recovery from creating
        # an apparently new, empty tank. Read the disk, not a cached pending write.
        return await self.hass.async_add_executor_job(self._read)

    async def save(self, data):
        validate(data)
        await self.store.async_save(data)
        # HA 2026.9 Store logs some write failures instead of propagating them.
        # Confirm durable content before acknowledging a booking.
        if await self.load() != data:
            raise HomeAssistantError("TankData storage write was not confirmed")
