"""Native tank configuration."""

from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers import selector

from .configuration import is_consumer
from .const import DOMAIN
from .consumption import MODES, validate_config
from .model import new_tank


class TankConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        if user_input is not None and "capacity" in user_input:
            return await self.async_step_tank(user_input)
        return self.async_show_menu(step_id="user", menu_options=["tank", "consumer"])

    async def async_step_tank(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                new_tank(user_input["capacity"], user_input["initial"])
                if not user_input["name"].strip():
                    raise ValueError("Empty name")
            except ValueError, TypeError:
                errors["base"] = "invalid_tank"
            else:
                return self.async_create_entry(
                    title=user_input["name"], data=user_input
                )
        return self.async_show_form(
            step_id="tank",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required("name"): str,
                    vol.Required("capacity"): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0.001, step="any", mode="box", unit_of_measurement="L"
                        )
                    ),
                    vol.Required("initial"): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, step="any", mode="box", unit_of_measurement="L"
                        )
                    ),
                }
            ),
        )

    async def async_step_consumer(self, user_input=None):
        return await self._form("consumer", user_input)

    async def async_step_reconfigure(self, user_input=None):
        if not is_consumer(self._get_reconfigure_entry()):
            return self.async_abort(reason="tank_fixed")
        return await self._form("reconfigure", user_input)

    async def _form(self, step, user_input):
        errors = {}
        defaults = (
            dict(self._get_reconfigure_entry().data["config"])
            if step == "reconfigure"
            else {}
        )
        tanks = {
            e.entry_id: e.title
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if not is_consumer(e)
        }
        if not tanks:
            return self.async_abort(reason="no_tanks")
        if user_input is not None:
            defaults = user_input
            try:
                config = {k: v for k, v in user_input.items() if k != "tank_entry_id"}
                validate_config(config)
                if (
                    step != "reconfigure"
                    and user_input.get("tank_entry_id") not in tanks
                ):
                    raise ValueError("Tank missing")
            except ValueError, KeyError, TypeError:
                errors["base"] = "invalid_consumer"
            else:
                if step == "reconfigure":
                    entry = self._get_reconfigure_entry()
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={**entry.data, "config": config},
                        title=config["name"],
                    )
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_create_entry(
                    title=config["name"],
                    data={
                        "kind": "consumer",
                        "tank_entry_id": user_input["tank_entry_id"],
                        "source_id": uuid4().hex,
                        "config": config,
                    },
                )
        fields = {
            vol.Required("name", default=defaults.get("name", "Verbraucher")): str,
            vol.Required(
                "mode", default=defaults.get("mode", "counter")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": mode,
                            "label": {
                                "counter": "Kumulativer Zähler",
                                "flow": "Durchfluss",
                                "running": "Laufzustand",
                                "power": "Elektrische Leistung",
                            }[mode],
                        }
                        for mode in sorted(MODES)
                    ],
                    mode="dropdown",
                )
            ),
            vol.Required(
                "entity_id",
                **(
                    {"default": defaults["entity_id"]}
                    if "entity_id" in defaults
                    else {}
                ),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor", "binary_sensor", "switch", "input_boolean"]
                )
            ),
        }
        if step != "reconfigure":
            fields[
                vol.Required(
                    "tank_entry_id",
                    **(
                        {"default": defaults["tank_entry_id"]}
                        if "tank_entry_id" in defaults
                        else {}
                    ),
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in tanks.items()],
                    mode="dropdown",
                )
            )
        for key, default in [("max_gap_seconds", 3600), ("max_rate_lph", 100)]:
            fields[vol.Required(key, default=defaults.get(key, default))] = vol.All(
                vol.Coerce(float), vol.Range(min=0.001)
            )
        fields[vol.Optional("rate_lph", default=defaults.get("rate_lph", 1))] = vol.All(
            vol.Coerce(float), vol.Range(min=0.001)
        )
        for key, default in [("on_threshold_w", 20), ("off_threshold_w", 10)]:
            fields[vol.Optional(key, default=defaults.get(key, default))] = vol.All(
                vol.Coerce(float), vol.Range(min=0)
            )
        return self.async_show_form(
            step_id=step, data_schema=vol.Schema(fields), errors=errors
        )
