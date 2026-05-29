import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def aquarea_status() -> dict:
    return json.loads((FIXTURES / "aquarea_status.json").read_text())
