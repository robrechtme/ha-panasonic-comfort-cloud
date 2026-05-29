from custom_components.panasonic_aquarea.api.models import AquareaDevice, OperationMode, ZoneMode


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
