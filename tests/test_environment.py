"""Verify the actual target HA APIs, without replacing them with stubs."""

import inspect

from homeassistant.config_entries import ConfigEntry, ConfigSubentryFlow
from homeassistant.const import __version__
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


async def test_target_runtime(tmp_path):
    assert __version__ == "2026.9.2"
    assert "runtime_data" in ConfigEntry.__annotations__
    assert (
        "subentry"
        in inspect.signature(ConfigSubentryFlow.async_update_and_abort).parameters
    )
    hass = HomeAssistant(str(tmp_path))
    store = Store(hass, 1, "tankdata_environment_test")
    await store.async_save({"events": [{"id": "test", "liters": 12.5}]})
    assert await Store(hass, 1, "tankdata_environment_test").async_load() == {
        "events": [{"id": "test", "liters": 12.5}]
    }
    await hass.async_stop()
