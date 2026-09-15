"""TankData integration."""

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import ACTIONS, DOMAIN
from .model import new_tank, number
from .runtime import TankRuntime
from .store import TankStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass, config):
    from .panel import async_setup_panel

    await async_setup_panel(hass)

    async def handle(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state != ConfigEntryState.LOADED
        ):
            raise HomeAssistantError("TankData entry is not loaded")
        try:
            await entry.runtime_data.book(
                ACTIONS[call.service],
                call.data.get("liters", 0),
                call.data.get("event_id"),
            )
        except (ValueError, TypeError, OSError) as err:
            raise HomeAssistantError(str(err)) from err

    for action, kind in ACTIONS.items():
        fields = {vol.Required("config_entry_id"): str}
        if kind is not None:
            fields[vol.Optional("event_id")] = vol.All(str, vol.Length(min=1, max=128))
        if kind not in {None, "reset"}:
            fields[vol.Required("liters")] = lambda v: number(v)
        hass.services.async_register(DOMAIN, action, handle, schema=vol.Schema(fields))
    return True


async def async_setup_entry(hass, entry):
    from .panel import async_show_panel

    await async_show_panel(hass)
    if entry.version != 1:
        raise ConfigEntryError("Unsupported TankData config version")
    store = TankStore(hass, entry.entry_id)
    try:
        data = await store.load()
        if data is None:
            data = new_tank(entry.data["capacity"], entry.data["initial"])
            await store.save(data)
        if (data["capacity"], data["initial"]) != (
            entry.data["capacity"],
            entry.data["initial"],
        ):
            raise ValueError("Tank definition differs from saved ledger")
    except (ValueError, TypeError, KeyError, OSError, HomeAssistantError) as err:
        raise ConfigEntryError("TankData storage could not be loaded safely") from err
    entry.runtime_data = TankRuntime(hass, entry, store, data)
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    if device is not None and device.config_subentry_id is not None:
        # Version 0.1.0 shared the tank device across consumer subentries.
        registry.async_update_device(device.id, new_config_subentry_id=None)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        entry_type=None,
        manufacturer="TankData",
    )
    if device is not None:
        registry.async_update_device(device.id, entry_type=None)
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    try:
        await entry.runtime_data.start()
    except Exception:
        await entry.runtime_data.stop()
        await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
        raise
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    result = await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
    if result:
        await entry.runtime_data.stop()
    return result


async def async_remove_entry(hass, entry):
    from homeassistant.components import frontend

    from .panel import PANEL_PATH

    if not any(
        other.entry_id != entry.entry_id
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        frontend.async_remove_panel(hass, PANEL_PATH)
