from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import (
    DwdPrecipitationForecastConfigEntry,
    DwdPrecipitationForecastCoordinator,
)
from .dwdradar import NotInAreaError


@dataclass(kw_only=True)
class DwdPrecipitationForecastEntityDescription(SensorEntityDescription):
    """Describes Example sensor entity."""

    name: str | None


SENSORS: tuple[DwdPrecipitationForecastEntityDescription, ...] = (
    DwdPrecipitationForecastEntityDescription(
        key="main",
        name=None,
        native_unit_of_measurement="mm/h",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    DwdPrecipitationForecastEntityDescription(
        key="next",
        name="Next Precipitation",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    DwdPrecipitationForecastEntityDescription(
        key="15min",
        name="Precipitation in next 15min",
    ),
    DwdPrecipitationForecastEntityDescription(
        key="30min",
        name="Precipitation in next 30min",
    ),
    DwdPrecipitationForecastEntityDescription(
        key="60min",
        name="Precipitation in next 60min",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DwdPrecipitationForecastConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entities from config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        DwdPrecipitationForecastEntity(coordinator, entry, description)
        for description in SENSORS
    )


class DwdPrecipitationForecastEntity(
    CoordinatorEntity[DwdPrecipitationForecastCoordinator], SensorEntity
):
    _attr_attribution = "Data provided by DWD"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DwdPrecipitationForecastCoordinator,
        entry: DwdPrecipitationForecastConfigEntry,
        entity_description: DwdPrecipitationForecastEntityDescription,
    ) -> None:
        super().__init__(coordinator)

        self.entry = entry
        self.entity_description = entity_description

        self._attr_name = entity_description.name
        self._attr_unique_id = (
            f"{entry.data.get('x')}-{entry.data.get('y')}--{entity_description.key}"
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data.get("x"), entry.data.get("y"))},
            name=f"DWD Precipitation Forecast {entry.title}",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        try:
            if self.entity_description.key == "next":
                next_precipitation = self.coordinator.api.get_next_precipitation(
                    self.entry.data.get("x"), self.entry.data.get("y")
                )
                return {
                    "end": next_precipitation["end"].isoformat()
                    if next_precipitation["end"] is not None
                    else None,
                    "length": int(next_precipitation["length"].total_seconds() / 60)
                    if next_precipitation["length"] is not None
                    else None,
                    "max": next_precipitation["max"],
                    "sum": next_precipitation["sum"],
                }
            else:
                next_precipitation = self.coordinator.api.get_next_precipitation(
                    self.entry.data.get("x"), self.entry.data.get("y")
                )
                return {
                    "forecast": {
                        k.isoformat(): v
                        for k, v in self.coordinator.api.get_precipitation_values(
                            self.entry.data.get("x"), self.entry.data.get("y")
                        ).items()
                    },
                    "next_start": max(next_precipitation["start"], datetime.now(UTC))
                    if next_precipitation["start"] is not None
                    else None,
                    "next_end": next_precipitation["end"].isoformat()
                    if next_precipitation["end"] is not None
                    else None,
                    "next_length": int(
                        next_precipitation["length"].total_seconds() / 60
                    )
                    if next_precipitation["length"] is not None
                    else None,
                }
        except NotInAreaError:
            return {}

    @property
    def native_value(self) -> int | None:
        try:
            if self.entity_description.key == "next":
                next_precipitation = self.coordinator.api.get_next_precipitation(
                    self.entry.data.get("x"), self.entry.data.get("y")
                )["start"]
                return (
                    max(next_precipitation, datetime.now(UTC))
                    if next_precipitation is not None
                    else None
                )
            elif self.entity_description.key == "15min":
                try:
                    return (
                        self.coordinator.api.get_next_precipitation(
                            self.entry.data.get("x"), self.entry.data.get("y")
                        )["start"]
                        - datetime.now(UTC)
                    ).total_seconds() <= 900
                except TypeError:
                    return False
            elif self.entity_description.key == "30min":
                try:
                    return (
                        self.coordinator.api.get_next_precipitation(
                            self.entry.data.get("x"), self.entry.data.get("y")
                        )["start"]
                        - datetime.now(UTC)
                    ).total_seconds() <= 1800
                except TypeError:
                    return False
            elif self.entity_description.key == "60min":
                try:
                    return (
                        self.coordinator.api.get_next_precipitation(
                            self.entry.data.get("x"), self.entry.data.get("y")
                        )["start"]
                        - datetime.now(UTC)
                    ).total_seconds() <= 3600
                except TypeError:
                    return False
            else:
                return self.coordinator.api.get_value(
                    self.entry.data.get("x"),
                    self.entry.data.get("y"),
                    datetime.now(UTC),
                )
        except NotInAreaError:
            return None
