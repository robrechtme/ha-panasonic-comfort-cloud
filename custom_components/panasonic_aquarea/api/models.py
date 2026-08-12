"""Parsed Aquarea status models (HA-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


class UpdateOperationMode(IntEnum):
    """Values accepted by the operationMode write.

    These deliberately differ from the read-side `OperationMode`: the Aquarea
    write API uses its own numbering (HEAT=2/COOL=3/AUTO=8), verified against
    aioaquarea and live behaviour. Sending a read-side value here silently
    selects the wrong mode (e.g. read-COOL 2 == write-HEAT). DHW is excluded —
    it is not a settable whole-unit operation mode.
    """

    OFF = 0
    HEAT = 2
    COOL = 3
    AUTO = 8

    @classmethod
    def from_read(cls, mode: OperationMode) -> UpdateOperationMode:
        """Map a read-side OperationMode to the value the write API expects."""
        return _READ_TO_UPDATE.get(mode, cls.OFF)


_READ_TO_UPDATE = {
    OperationMode.OFF: UpdateOperationMode.OFF,
    OperationMode.HEAT: UpdateOperationMode.HEAT,
    OperationMode.COOL: UpdateOperationMode.COOL,
    OperationMode.AUTO: UpdateOperationMode.AUTO,
}


@dataclass(frozen=True)
class EnergyTotals:
    """Today's consumption (kWh) summed across hourly buckets."""

    heating: float
    cooling: float
    hot_water: float
    total: float

    @classmethod
    def from_consumption(cls, payload: dict) -> EnergyTotals:
        buckets = payload.get("historyDataList", []) if isinstance(payload, dict) else []
        heating = sum(b.get("heatConsumption") or 0 for b in buckets)
        cooling = sum(b.get("coolConsumption") or 0 for b in buckets)
        hot_water = sum(b.get("tankConsumption") or 0 for b in buckets)
        return cls(
            heating=round(heating, 3),
            cooling=round(cooling, 3),
            hot_water=round(hot_water, 3),
            total=round(heating + cooling + hot_water, 3),
        )


@dataclass(frozen=True)
class EnergyHourBucket:
    """One hour of consumption, as Panasonic itself buckets it (device-local hour)."""

    start: datetime
    heating: float
    cooling: float
    hot_water: float

    @property
    def total(self) -> float:
        return self.heating + self.cooling + self.hot_water

    @classmethod
    def from_dict(cls, d: dict, tzinfo: timezone) -> EnergyHourBucket:
        return cls(
            start=datetime.strptime(d["dataTime"], "%Y%m%d %H").replace(tzinfo=tzinfo),
            heating=d.get("heatConsumption") or 0,
            cooling=d.get("coolConsumption") or 0,
            hot_water=d.get("tankConsumption") or 0,
        )


def parse_energy_history(payload: dict, tzinfo: timezone) -> list[EnergyHourBucket]:
    """Parse the same consumption payload as `EnergyTotals`, keeping per-hour timestamps."""
    buckets = payload.get("historyDataList", []) if isinstance(payload, dict) else []
    return [EnergyHourBucket.from_dict(b, tzinfo) for b in buckets]
