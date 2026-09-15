"""Flat config entries with stable links to the tank ledger."""

from .const import DOMAIN


def is_consumer(entry):
    return entry.data.get("kind") == "consumer"


def consumers(hass, tank_id, *, include_disabled=False):
    return {
        entry.data["source_id"]: entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if is_consumer(entry)
        and entry.data["tank_entry_id"] == tank_id
        and (include_disabled or entry.disabled_by is None)
    }
