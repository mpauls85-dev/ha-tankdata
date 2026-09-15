"""Read-only presentation of the committed ledger."""

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import (
    DeviceEntryType,
    DeviceInfo,
    async_get_device_id_by_identifier,
)

from .const import DOMAIN
from .model import replay


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            TankSensor(entry, key, name, unit)
            for key, name, unit in [
                ("stock", "Bestand", "L"),
                ("percent", "Füllstand", "%"),
                ("consumed", "Verbrauch", "L"),
            ]
        ]
    )
    for source_id, subentry in entry.subentries.items():
        async_add_entities(
            [
                ConsumerSensor(entry, source_id, subentry.title, "consumed", "L"),
            ],
            config_subentry_id=source_id,
        )
        if subentry.data["mode"] in {"running", "power"}:
            async_add_entities(
                [ConsumerSensor(entry, source_id, subentry.title, "runtime", "h")],
                config_subentry_id=source_id,
            )


class TankSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry, key, name, unit):
        self.runtime = entry.runtime_data
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        if key == "consumed":
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="TankData",
        )

    @property
    def available(self):
        return self.runtime.available

    @property
    def native_value(self):
        return replay(self.runtime.data)[self.key]

    @property
    def extra_state_attributes(self):
        return {
            "out_of_bounds": replay(self.runtime.data)["out_of_bounds"],
            "event_count": len(self.runtime.data["events"]),
            "incomplete_sources": sum(
                not self.runtime.source_valid(sid)
                for sid in self.runtime.entry.subentries
            ),
        }

    async def async_added_to_hass(self):
        self.runtime.listeners.add(self.async_write_ha_state)
        self.async_on_remove(
            lambda: self.runtime.listeners.discard(self.async_write_ha_state)
        )


class ConsumerSensor(TankSensor):
    def __init__(self, entry, source_id, title, key, unit):
        label = "Laufzeit" if key == "runtime" else "Verbrauch"
        super().__init__(entry, key, label, unit)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{source_id}")},
            name=title,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="TankData",
            via_device_id=async_get_device_id_by_identifier(
                self.runtime.hass,
                (DOMAIN, entry.entry_id),
                config_entry_id=entry.entry_id,
            ),
        )
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self.source_id = source_id
        self._attr_unique_id = f"{entry.entry_id}_{source_id}_{key}"

    @property
    def native_value(self):
        if self.key == "runtime":
            return (
                sum(
                    e.get("runtime_seconds", 0)
                    for e in self.runtime.data["events"]
                    if e.get("source_id") == self.source_id
                )
                / 3600
            )
        return sum(
            e["liters"]
            for e in self.runtime.data["events"]
            if e.get("source_id") == self.source_id
        )

    @property
    def extra_state_attributes(self):
        basis = self.runtime.data["sources"].get(self.source_id)
        return {
            "source_valid": self.runtime.source_valid(self.source_id),
            "last_source_report": basis["at"] if basis else None,
        }
