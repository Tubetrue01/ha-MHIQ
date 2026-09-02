"""Support for SLAC Climate (AC) entities."""
import json
import logging
from typing import Any, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 工作模式映射：0: 自动, 1: 制冷, 2: 除湿, 3: 送风, 4: 制热
SLAC_TO_HA_HVAC = {
    0: HVACMode.AUTO,
    1: HVACMode.COOL,
    2: HVACMode.DRY,
    3: HVACMode.FAN_ONLY,
    4: HVACMode.HEAT,
}

HA_TO_SLAC_HVAC = {v: k for k, v in SLAC_TO_HA_HVAC.items()}

# 风速映射：0: 自动, 1: 低风, 3: 中风, 5: 高风
SLAC_TO_HA_FAN = {
    0: FAN_AUTO,
    1: FAN_LOW,
    3: FAN_MEDIUM,
    5: FAN_HIGH,
}

HA_TO_SLAC_FAN = {v: k for k, v in SLAC_TO_HA_FAN.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SLAC Climate entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    devices = coordinator.devices

    entities = []
    for dev in devices:
        entities.append(SlacClimateEntity(coordinator, dev))

    _LOGGER.info("Adding %d SLAC Climate entities", len(entities))
    async_add_entities(entities)


class SlacClimateEntity(CoordinatorEntity, ClimateEntity):
    """Representation of a SLAC Climate entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
    )
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
        HVACMode.AUTO,
    ]
    _attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0

    def __init__(self, coordinator, device_info: dict):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._device = device_info
        self._iot_id = device_info.get("iotId", "")
        self._internal_addr = device_info.get("internalAddress", 0)
        self._room_name = (
            device_info.get("roomName")
            or device_info.get("nickName")
            or f"AC_{self._internal_addr}"
        )

        # 区分 5 台内机的关键 ID
        self._attr_unique_id = f"slac_{self._iot_id}_{self._internal_addr}"
        self._attr_name = self._room_name

        # 设备分组挂载到统一的网关下
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._iot_id)},
            name="SLAC 中央空调网关",
            manufacturer="SLAC",
            model="VRF Gateway",
        )

    @property
    def _parsed_info(self) -> dict:
        """获取当前内机对应的 Info0 ~ Info4 属性结构"""
        if not self.coordinator.data or "properties" not in self.coordinator.data:
            return {}

        props = self.coordinator.data["properties"].get(self._iot_id, {})
        info_key = f"Info{self._internal_addr}"
        info_val = props.get(info_key, {})

        if isinstance(info_val, dict):
            return info_val
        return {}

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current hvac mode."""
        info = self._parsed_info
        if not info or info.get("PowerSwitch") == 0:
            return HVACMode.OFF

        work_mode = info.get("WorkMode", 1)
        return SLAC_TO_HA_HVAC.get(work_mode, HVACMode.COOL)

    @property
    def target_temperature(self) -> Optional[float]:
        """Return target temperature."""
        info = self._parsed_info
        return info.get("TargetTemperature")

    @property
    def current_temperature(self) -> Optional[float]:
        """Return current temperature."""
        info = self._parsed_info
        return info.get("CurrentTemperature")

    @property
    def fan_mode(self) -> Optional[str]:
        """Return fan mode."""
        info = self._parsed_info
        wind_speed = info.get("WindSpeed", 0)
        return SLAC_TO_HA_FAN.get(wind_speed, FAN_AUTO)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new hvac mode."""
        if hvac_mode == HVACMode.OFF:
            payload = {
                "InternalAddress": self._internal_addr,
                "PowerSwitch": 0
            }
        else:
            slac_mode = HA_TO_SLAC_HVAC.get(hvac_mode, 1)
            payload = {
                "InternalAddress": self._internal_addr,
                "PowerSwitch": 1,
                "WorkMode": slac_mode
            }

        _LOGGER.debug("Setting HVAC mode for %s: %s", self.name, payload)
        info_key = f"Info{self._internal_addr}"
        await self.coordinator.api.async_set_properties(
            self._iot_id, {info_key: json.dumps(payload)}
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return

        payload = {
            "InternalAddress": self._internal_addr,
            "TargetTemperature": float(temp)
        }

        _LOGGER.debug("Setting temperature for %s: %s", self.name, payload)
        info_key = f"Info{self._internal_addr}"
        await self.coordinator.api.async_set_properties(
            self._iot_id, {info_key: json.dumps(payload)}
        )
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new fan mode."""
        slac_fan = HA_TO_SLAC_FAN.get(fan_mode, 0)
        payload = {
            "InternalAddress": self._internal_addr,
            "WindSpeed": slac_fan
        }

        _LOGGER.debug("Setting fan mode for %s: %s", self.name, payload)
        info_key = f"Info{self._internal_addr}"
        await self.coordinator.api.async_set_properties(
            self._iot_id, {info_key: json.dumps(payload)}
        )
        await self.coordinator.async_request_refresh()