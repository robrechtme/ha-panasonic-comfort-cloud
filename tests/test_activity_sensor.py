import pytest
from homeassistant.core import HomeAssistant

from tests.test_binary_sensor import _setup


@pytest.mark.parametrize(
    ("direction", "mode", "expected"),
    [
        (0, 1, "idle"),
        (1, 1, "heating"),
        (1, 2, "cooling"),
        (2, 1, "hot_water"),
        (9, 1, "unknown"),
    ],
)
async def test_activity(hass: HomeAssistant, aquarea_status, direction, mode, expected):
    aquarea_status["status"]["direction"] = direction
    aquarea_status["status"]["operationMode"] = mode
    await _setup(hass, aquarea_status)
    state = hass.states.get("sensor.warmtepomp_activity")
    assert state.state == expected
    assert state.attributes["device_class"] == "enum"
