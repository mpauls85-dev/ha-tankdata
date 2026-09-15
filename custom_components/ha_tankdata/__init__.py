"""TankData integration."""

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .configuration import consumers, is_consumer
from .const import ACTIONS, DOMAIN
from .migration import migrate
from .model import new_tank, number
from .runtime import TankRuntime
from .store import TankStore

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_migrate_entry(hass, entry):
    return await migrate(hass, entry)


async def async_setup(hass, config):
    from .panel import async_setup_panel

    await async_setup_panel(hass)

    async def handle(call):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if (
            entry is None
            or is_consumer(entry)
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
    if is_consumer(entry):
        tank = hass.config_entries.async_get_entry(entry.data["tank_entry_id"])
        if tank is None or is_consumer(tank):
            raise ConfigEntryError("The assigned tank no longer exists")
        if (
            tank.version != 2
            or not hasattr(tank, "runtime_data")
            or not tank.runtime_data.active
        ):
            raise ConfigEntryNotReady("Waiting for the assigned tank")
        entry.runtime_data = tank.runtime_data
        entry.runtime_data.excluded_sources.discard(entry.data["source_id"])
        await hass.config_entries.async_forward_entry_setups(
            entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
        )
        await refresh_sources(tank.runtime_data)
        entry.async_on_unload(entry.add_update_listener(_reload))
        return True
    if entry.version != 2:
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
    await entry.runtime_data.recover_approved()
    entry.runtime_data.notify_proposals()
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
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
    )
    try:
        await entry.runtime_data.start()
    except Exception:
        await entry.runtime_data.stop()
        await hass.config_entries.async_unload_platforms(
            entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
        )
        raise
    entry.async_on_unload(entry.add_update_listener(_reload))
    for child in consumers(hass, entry.entry_id).values():
        await hass.config_entries.async_reload(child.entry_id)
    return True


async def refresh_sources(runtime):
    async with runtime.reconfigure_lock:
        await runtime.stop()
        runtime.active = True
        await runtime.start()


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    result = await hass.config_entries.async_unload_platforms(
        entry, [Platform.SENSOR, Platform.BINARY_SENSOR]
    )
    if result and not is_consumer(entry):
        await entry.runtime_data.stop()
        for child in consumers(hass, entry.entry_id, include_disabled=True).values():
            if child.state == ConfigEntryState.LOADED:
                await hass.config_entries.async_unload(child.entry_id)
    elif result and entry.runtime_data.active:
        # Exclude this consumer during unload; setup removes the exclusion.
        entry.runtime_data.excluded_sources.add(entry.data["source_id"])
        await refresh_sources(entry.runtime_data)
    return result


async def async_remove_entry(hass, entry):
    from homeassistant.components import frontend

    from .panel import PANEL_PATH

    if not any(
        other.entry_id != entry.entry_id and not is_consumer(other)
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        frontend.async_remove_panel(hass, PANEL_PATH)
