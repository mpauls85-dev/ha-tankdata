"""Bundled management panel and read-only ledger API."""

from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, VERSION
from .model import replay

PANEL_PATH = "tankdata"
STATIC_PATH = "/ha_tankdata_static"


async def async_setup_panel(hass):
    """Register process-wide resources once, independently of individual tanks."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_PATH, str(Path(__file__).parent / "frontend"), True)]
    )
    websocket_api.async_register_command(hass, get_tanks)
    websocket_api.async_register_command(hass, get_history)
    await async_show_panel(hass)


async def async_show_panel(hass):
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="tankdata-panel",
        sidebar_title="TankData",
        sidebar_icon="mdi:storage-tank",
        module_url=f"{STATIC_PATH}/tankdata-panel.js?v={VERSION}",
        require_admin=True,
        config_panel_domain=DOMAIN,
    )


@websocket_api.websocket_command({"type": "ha_tankdata/get_tanks"})
@websocket_api.require_admin
@callback
def get_tanks(hass, connection, msg):
    tanks = []
    registry = dr.async_get(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        device = registry.async_get_device_by_identifier(
            (DOMAIN, entry.entry_id), entry.entry_id
        )
        tank = {
            "id": entry.entry_id,
            "name": entry.title,
            "device_id": device.id if device else None,
            "status": entry.state.value,
            "capacity": entry.data["capacity"],
            "consumers": [],
        }
        if entry.state == ConfigEntryState.LOADED:
            runtime = entry.runtime_data
            tank.update(replay(runtime.data))
            tank["event_count"] = len(runtime.data["events"])
            for sid, subentry in entry.subentries.items():
                tank["consumers"].append(
                    {
                        "id": sid,
                        "name": subentry.title,
                        "config": dict(subentry.data),
                        "valid": runtime.source_valid(sid),
                    }
                )
        tanks.append(tank)
    connection.send_result(msg["id"], {"tanks": tanks, "version": VERSION})


@websocket_api.websocket_command(
    {
        "type": "ha_tankdata/get_history",
        vol.Required("config_entry_id"): str,
        vol.Optional("before"): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=50): vol.All(int, vol.Range(min=1, max=200)),
    }
)
@websocket_api.require_admin
@callback
def get_history(hass, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state != ConfigEntryState.LOADED
    ):
        connection.send_error(msg["id"], "not_loaded", "Tank is not loaded")
        return
    events = entry.runtime_data.data["events"]
    end = min(msg.get("before", len(events)), len(events))
    start = max(0, end - msg["limit"])
    connection.send_result(
        msg["id"],
        {"events": list(reversed(events[start:end])), "before": start},
    )
