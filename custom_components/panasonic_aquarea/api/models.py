"""Parsed Aquarea status models (HA-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class OperationMode(IntEnum):
    OFF = 0
    HEAT = 1
    COOL = 2
    AUTO = 3
    DHW = 4

    @classmethod
    def parse(cls, value: int) -> OperationMode:
        try:
            return cls(value)
        except ValueError:
            return cls.OFF


class ZoneMode(IntEnum):
    """Whether a zone's setpoint is an absolute room temp or a compensation offset."""

    ABSOLUTE = 0
    OFFSET = 1


@dataclass(frozen=True)
class Zone:
    zone_id: int
    name: str
    mode: ZoneMode
    on: bool
    current_temperature: int
    heat_setpoint: int
    cool_setpoint: int
    heat_min: int
    heat_max: int
    cool_min: int
    cool_max: int

    @classmethod
    def from_dict(cls, d: dict) -> Zone:
        heat_min = d["heatMin"]
        heat_max = d["heatMax"]
        # Offset-mode zones use a symmetric range around 0 (e.g. -5..5); absolute
        # zones use real temperatures (e.g. 10..30). Negative min is the tell.
        mode = ZoneMode.OFFSET if heat_min < 0 else ZoneMode.ABSOLUTE
        return cls(
            zone_id=d["zoneId"],
            name=d["zoneName"],
            mode=mode,
            on=bool(d["operationStatus"]),
            current_temperature=d["temperatureNow"],
            heat_setpoint=d["heatSet"],
            cool_setpoint=d["coolSet"],
            heat_min=heat_min,
            heat_max=heat_max,
            cool_min=d["coolMin"],
            cool_max=d["coolMax"],
        )


@dataclass(frozen=True)
class Tank:
    on: bool
    current_temperature: int
    target_temperature: int
    heat_min: int
    heat_max: int

    @classmethod
    def from_dict(cls, d: dict) -> Tank:
        return cls(
            on=bool(d["operationStatus"]),
            current_temperature=d["temperatureNow"],
            target_temperature=d["heatSet"],
            heat_min=d["heatMin"],
            heat_max=d["heatMax"],
        )


@dataclass(frozen=True)
class AquareaDevice:
    guid: str
    name: str
    service_type: str
    operation_mode: OperationMode
    outdoor_temperature: int
    water_pressure: float
    pump_duty: int
    defrost: bool
    fault: bool
    force_dhw: bool
    zones: tuple[Zone, ...]
    tank: Tank | None

    @classmethod
    def from_status(cls, guid: str, payload: dict) -> AquareaDevice:
        """Parse a /remote/v1/api/devices transfer response into a device model."""
        status = payload["status"]
        tank_raw = status.get("tankStatus")
        return cls(
            guid=guid,
            name=payload.get("a2wName", guid),
            service_type=status.get("serviceType", ""),
            operation_mode=OperationMode.parse(status.get("operationMode", 0)),
            outdoor_temperature=status.get("outdoorNow"),
            water_pressure=status.get("waterPressure"),
            pump_duty=status.get("pumpDuty", 0),
            defrost=bool(status.get("deiceStatus", 0)),
            fault=bool(status.get("specialStatus", 0)),
            force_dhw=bool(status.get("forceDHW", 0)),
            zones=tuple(Zone.from_dict(z) for z in status.get("zoneStatus", [])),
            tank=Tank.from_dict(tank_raw) if tank_raw else None,
        )
