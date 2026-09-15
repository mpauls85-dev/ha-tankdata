"""Upgrade stored native subentries without losing ledger identity."""

from copy import deepcopy
from types import MappingProxyType

from conftest import create_tank
from homeassistant.config_entries import ConfigSubentry
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from test_consumption import config
from test_ha import call

from custom_components.ha_tankdata.configuration import consumers


async def test_flat_migration_preserves_registry_and_ledger(hass):
    tank = await create_tank(hass)
    await call(hass, tank, "record_refill", liters=25, event_id="delivery")
    saved = deepcopy(tank.runtime_data.data)
    assert await hass.config_entries.async_unload(tank.entry_id)
    sub = ConfigSubentry(
        data=MappingProxyType(config()),
        subentry_type="consumer",
        title="Burner",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(tank, sub)
    hass.config_entries.async_update_entry(tank, version=1)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    parent = devices.async_get_device_by_identifier(
        ("ha_tankdata", tank.entry_id), tank.entry_id
    )
    device = devices.async_get_or_create(
        config_entry_id=tank.entry_id,
        config_subentry_id=sub.subentry_id,
        identifiers={("ha_tankdata", f"{tank.entry_id}_{sub.subentry_id}")},
        name="Burner",
        via_device_id=parent.id,
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    entity = entities.async_get_or_create(
        "sensor",
        "ha_tankdata",
        f"{tank.entry_id}_{sub.subentry_id}_consumed",
        config_entry=tank,
        config_subentry_id=sub.subentry_id,
        device_id=device.id,
        suggested_object_id="existing_burner",
    )
    assert await hass.config_entries.async_setup(tank.entry_id)
    await hass.async_block_till_done()
    children = consumers(hass, tank.entry_id)
    assert len(children) == 1
    child = children[sub.subentry_id]
    assert child.state.value == "loaded"
    assert tank.version == 2 and not tank.subentries
    assert child.data["config"] == config()
    assert tank.runtime_data.data["events"] == saved["events"]
    restored = entities.async_get(entity.entity_id)
    assert restored.unique_id == entity.unique_id
    assert restored.config_entry_id == child.entry_id
    assert restored.config_subentry_id is None
    assert restored.device_id == device.id
    assert devices.async_get(device.id).config_entry_id == child.entry_id
    assert devices.async_get(device.id).entry_type is None
    assert devices.async_get(device.id).via_device_id == parent.id
    assert len(er.async_entries_for_config_entry(entities, tank.entry_id)) == 3
    assert await hass.config_entries.async_reload(tank.entry_id)
    await hass.async_block_till_done()
    assert len(consumers(hass, tank.entry_id)) == 1
    assert tank.runtime_data.data["events"] == saved["events"]
    assert hass.states.get(entity.entity_id).state == "0"
