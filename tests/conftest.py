"""Real Home Assistant objects with isolated temporary configuration."""

import shutil
from pathlib import Path

import pytest
from homeassistant import auth, loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry, device_registry, entity_registry


@pytest.fixture
async def hass(tmp_path):
    shutil.copytree(Path("custom_components"), tmp_path / "custom_components")
    instance = HomeAssistant(str(tmp_path))
    loader.async_setup(instance)
    device_registry.async_setup(instance)
    await area_registry.async_load(instance)
    await device_registry.async_load(instance)
    await entity_registry.async_load(instance)
    instance.auth = await auth.auth_manager_from_config(instance, [], [])
    instance.config_entries = ConfigEntries(instance, {})
    await instance.config_entries.async_initialize()
    yield instance
    await instance.async_stop()
    if getattr(instance, "http", None) is not None:
        await instance.http.stop()


async def create_tank(hass, name="Tank", initial=500):
    result = await hass.config_entries.flow.async_init(
        "ha_tankdata",
        context={"source": "user"},
        data={"name": name, "capacity": 1000, "initial": initial},
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state.value == "loaded", entry.reason
    return entry
