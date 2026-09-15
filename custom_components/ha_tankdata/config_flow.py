"""Native tank configuration."""

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigSubentryFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN
from .consumption import MODES, validate_config
from .model import new_tank


class TankConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        return {"consumer": ConsumerFlow}

    async def async_step_user(self, user_input=None):
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
            step_id="user",
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


class ConsumerFlow(ConfigSubentryFlow):
    async def async_step_user(self, user_input=None):
        return await self._form("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._form("reconfigure", user_input)

    async def _form(self, step, user_input):
        errors = {}
        defaults = (
            dict(self._get_reconfigure_subentry().data) if step == "reconfigure" else {}
        )
        if user_input is not None:
            defaults = user_input
            try:
                validate_config(user_input)
            except ValueError, KeyError, TypeError:
                errors["base"] = "invalid_consumer"
            else:
                if step == "reconfigure":
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        data=user_input,
                        title=user_input["name"],
                    )
                return self.async_create_entry(
                    title=user_input["name"], data=user_input
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
