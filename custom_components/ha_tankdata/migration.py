"""Move consumer ownership without changing device, entity or ledger IDs."""

from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .configuration import consumers
from .const import DOMAIN


async def migrate(hass, entry):
    if entry.version > 2:
        return False
    if entry.version == 2:
        return True
    devices, entities = dr.async_get(hass), er.async_get(hass)
    parent = devices.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    if parent and parent.config_subentry_id is not None:
        devices.async_update_device(parent.id, new_config_subentry_id=None)
    for sid, sub in tuple(entry.subentries.items()):
        child = consumers(hass, entry.entry_id, include_disabled=True).get(sid)
        if child is None:
            child = ConfigEntry(
                version=2,
                minor_version=1,
                domain=DOMAIN,
                title=sub.title,
                data={
                    "kind": "consumer",
                    "tank_entry_id": entry.entry_id,
                    "source_id": sid,
                    "config": dict(sub.data),
                },
                source="import",
                unique_id=f"consumer:{entry.entry_id}:{sid}",
                options={},
                discovery_keys=MappingProxyType({}),
                subentries_data=[],
                disabled_by=entry.disabled_by,
            )
            await hass.config_entries.async_add(child)
        for device in list(dr.async_entries_for_config_entry(devices, entry.entry_id)):
            if device.config_subentry_id == sid:
                devices.async_update_device(
                    device.id,
                    new_config_entry_id=child.entry_id,
                    new_config_subentry_id=None,
                    entry_type=None,
                )
        for entity in list(er.async_entries_for_config_entry(entities, entry.entry_id)):
            if entity.config_subentry_id == sid:
                entities.async_update_entity(
                    entity.entity_id,
                    config_entry_id=child.entry_id,
                    config_subentry_id=None,
                )
        hass.config_entries.async_remove_subentry(entry, sid)
    hass.config_entries.async_update_entry(entry, version=2)
    return True
