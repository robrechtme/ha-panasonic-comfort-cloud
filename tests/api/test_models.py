
from datetime import UTC

from custom_components.panasonic_aquarea.api.models import (
    AquareaDevice,
    OperationMode,
    ZoneMode,
    parse_energy_history,
)


def test_parses_top_level(aquarea_status):
    dev = AquareaDevice.from_status("B218954411", aquarea_status)
    assert dev.guid == "B218954411"
    assert dev.name == "Warmtepomp"
    assert dev.service_type == "STD_ADP-TAW1"
    assert dev.operation_mode is OperationMode.COOL
    assert dev.outdoor_temperature == 31
    assert dev.water_pressure == 1.32
    assert dev.pump_duty == 0
    assert dev.defrost is False
    assert dev.fault is False
    assert dev.force_dhw is False


def test_parses_zones_with_mode_detection(aquarea_status):
    dev = AquareaDevice.from_status("B218954411", aquarea_status)
    boven = dev.zones[0]
    beneden = dev.zones[1]
    assert beneden.name == "Beneden"
    assert beneden.mode is ZoneMode.ABSOLUTE
    assert beneden.on is True
    assert beneden.current_temperature == 24
    assert beneden.heat_setpoint == 20
    assert beneden.heat_min == 10 and beneden.heat_max == 30
    assert boven.name == "Boven"
    assert boven.mode is ZoneMode.OFFSET
    assert boven.on is False


def test_parses_tank(aquarea_status):
    dev = AquareaDevice.from_status("B218954411", aquarea_status)
    assert dev.tank is not None
    assert dev.tank.on is True
    assert dev.tank.current_temperature == 46
    assert dev.tank.target_temperature == 52
    assert dev.tank.heat_min == 40 and dev.tank.heat_max == 65


def test_parse_energy_history_keeps_hour_timestamps():
    tz = UTC
    payload = {
        "historyDataList": [
            {
                "dataTime": "20260529 09",
                "heatConsumption": 0,
                "coolConsumption": 0.05,
                "tankConsumption": 0,
            },
            {
                "dataTime": "20260529 10",
                "heatConsumption": 0.1,
                "coolConsumption": 0.07,
                "tankConsumption": 0.2,
            },
        ]
    }
    buckets = parse_energy_history(payload, tz)
    assert [b.start.hour for b in buckets] == [9, 10]
    assert buckets[0].total == 0.05
    assert buckets[1].heating == 0.1 and buckets[1].cooling == 0.07 and buckets[1].hot_water == 0.2
    assert buckets[1].total == 0.37
    assert buckets[0].start.tzinfo is tz


def test_parse_energy_history_empty_payload():
    assert parse_energy_history({}, UTC) == []
