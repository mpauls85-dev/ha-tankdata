"""Observed consumer operation, with unknown distinct from off."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .configuration import is_consumer
from .sensor import ConsumerSensor


async def async_setup_entry(hass, entry, async_add_entities):
    if is_consumer(entry) and entry.data["config"]["mode"] != "counter":
        tank = hass.config_entries.async_get_entry(entry.data["tank_entry_id"])
        async_add_entities(
            [ConsumerRunning(tank, entry.data["source_id"], entry.title)]
        )


class ConsumerRunning(BinarySensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Betrieb"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, tank, sid, title):
        reference = ConsumerSensor(tank, sid, title, "consumed", "L")
        self.runtime = tank.runtime_data
        self.sid = sid
        self._attr_unique_id = f"{tank.entry_id}_{sid}_running"
        self._attr_device_info = reference.device_info

    @property
    def available(self):
        return self.runtime.available

    @property
    def is_on(self):
        return self.runtime.source_running(self.sid)

    async def async_added_to_hass(self):
        self.runtime.listeners.add(self.async_write_ha_state)
        self.async_on_remove(
            lambda: self.runtime.listeners.discard(self.async_write_ha_state)
        )
