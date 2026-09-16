"""Bundled management panel and read-only ledger API."""

from hashlib import sha256
from pathlib import Path

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .configuration import consumers, is_consumer
from .const import DOMAIN, VERSION
from .geometry import fill_height
from .history import history_page
from .insights import calendar_summary, forecast, summarize
from .model import replay

PANEL_PATH = "tankdata"
STATIC_PATH = "/ha_tankdata_static"


async def async_setup_panel(hass):
    """Register process-wide resources once, independently of individual tanks."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_PATH, str(Path(__file__).parent / "frontend"), True
            ),
            StaticPathConfig(
                "/ha_tankdata_brand", str(Path(__file__).parent / "brand"), True
            ),
        ]
    )
    websocket_api.async_register_command(hass, get_tanks)
    websocket_api.async_register_command(hass, get_history)
    websocket_api.async_register_command(hass, manage)
    await async_show_panel(hass)


async def async_show_panel(hass):
    if PANEL_PATH in hass.data.get(frontend.DATA_PANELS, {}):
        return
    asset = Path(__file__).parent / "frontend" / "tankdata-panel.js"
    digest = await hass.async_add_executor_job(
        lambda: sha256(asset.read_bytes()).hexdigest()[:12]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name="tankdata-panel",
        sidebar_title="TankData",
        sidebar_icon="mdi:storage-tank",
        module_url=f"{STATIC_PATH}/tankdata-panel.js?v={digest}",
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
        if is_consumer(entry):
            continue
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
            tank["settings"] = runtime.data["analysis"]["settings"]
            tank["fill_height"] = fill_height(
                tank["stock"], tank["settings"]["geometry"], tank["capacity"]
            )
            tank["proposals"] = runtime.data["analysis"]["proposals"]
            tank["forecast"] = forecast(
                runtime.data, runtime.configs(), dt_util.utcnow(), hass.config.time_zone
            )
            tank["statistics"] = calendar_summary(
                runtime.data,
                runtime.configs(),
                dt_util.utcnow(),
                tz=hass.config.time_zone,
            )
            for sid, subentry in consumers(
                hass, entry.entry_id, include_disabled=True
            ).items():
                tank["consumers"].append(
                    {
                        "id": sid,
                        "name": subentry.title,
                        "config": dict(subentry.data["config"]),
                        "entry_id": subentry.entry_id,
                        "valid": runtime.source_valid(sid),
                        "running": runtime.source_running(sid),
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
        vol.Optional("grouped", default=False): bool,
        vol.Optional("run_id"): str,
    }
)
@websocket_api.require_admin
@callback
def get_history(hass, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if (
        entry is None
        or is_consumer(entry)
        or entry.domain != DOMAIN
        or entry.state != ConfigEntryState.LOADED
    ):
        connection.send_error(msg["id"], "not_loaded", "Tank is not loaded")
        return
    runtime = entry.runtime_data
    if msg.get("grouped") or "run_id" in msg:
        try:
            result = history_page(
                runtime.data,
                {sid: runtime.source_running(sid) for sid in runtime.configs()},
                runtime.configs(),
                limit=msg["limit"],
                before=msg.get("before"),
                run_id=msg.get("run_id"),
            )
            connection.send_result(msg["id"], result)
        except ValueError as error:
            connection.send_error(msg["id"], "invalid_request", str(error))
        return
    events = runtime.data["events"]
    end = min(msg.get("before", len(events)), len(events))
    start = max(0, end - msg["limit"])
    connection.send_result(
        msg["id"],
        {"events": list(reversed(events[start:end])), "before": start},
    )


@websocket_api.websocket_command(
    {
        "type": "ha_tankdata/manage",
        vol.Required("config_entry_id"): str,
        vol.Required("operation"): vol.In(["settings", "book", "decide", "statistics"]),
        vol.Optional("parameters", default={}): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def manage(hass, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if (
        entry is None
        or entry.domain != DOMAIN
        or is_consumer(entry)
        or entry.state != ConfigEntryState.LOADED
    ):
        connection.send_error(msg["id"], "not_loaded", "Tank ist nicht geladen")
        return
    runtime, params = entry.runtime_data, msg["parameters"]
    try:
        operation = msg["operation"]
        result = None
        if operation == "settings":
            await runtime.save_settings(params)
        elif operation == "decide":
            if set(params) != {"proposal_id", "decision"}:
                raise ValueError("Ungültige Entscheidung")
            await runtime.decide(**params)
        elif operation == "book":
            if set(params) - {
                "kind",
                "liters",
                "event_id",
                "total_cost",
                "unit",
            } or params.get("kind") not in {
                "refill",
                "withdrawal",
                "observation",
                "correction",
                "reset",
            }:
                raise ValueError("Ungültige Buchung")
            await runtime.book(**params)
        else:
            days = params.get("days", 30)
            sid = params.get("source_id")
            if (
                type(days) is not int
                or not 1 <= days <= 366
                or sid is not None
                and sid not in runtime.configs()
            ):
                raise ValueError("Ungültiger Zeitraum oder Verbraucher")
            if "period" in params:
                if set(params) - {"period", "anchor", "source_id"}:
                    raise ValueError("Ungültige Statistikparameter")
                result = calendar_summary(
                    runtime.data,
                    runtime.configs(),
                    dt_util.utcnow(),
                    params["period"],
                    params.get("anchor"),
                    hass.config.time_zone,
                    sid,
                )
            else:
                result = summarize(
                    runtime.data,
                    runtime.configs(),
                    dt_util.utcnow(),
                    days,
                    hass.config.time_zone,
                    sid,
                )
        connection.send_result(msg["id"], result)
    except (ValueError, TypeError, KeyError) as error:
        connection.send_error(msg["id"], "invalid_request", str(error))
