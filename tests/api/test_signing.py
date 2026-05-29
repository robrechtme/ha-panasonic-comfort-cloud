from custom_components.panasonic_aquarea.api.signing import cfc_key, app_timestamp


def test_app_timestamp_format():
    ts = app_timestamp(epoch_seconds=1717000000)  # fixed instant
    # "YYYY-MM-DD HH:MM:SS", 19 chars, space separator
    assert len(ts) == 19
    assert ts[4] == "-" and ts[7] == "-" and ts[10] == " " and ts[13] == ":"


def test_cfc_key_is_deterministic_and_inserts_cfc():
    # Known vector: timestamp interpreted as UTC, token "TKN"
    key = cfc_key("2024-05-29 12:00:00", "TKN")
    assert key[9:12] == "cfc"
    assert len(key) == 64 + 3  # sha256 hex (64) + inserted "cfc"
    # deterministic
    assert key == cfc_key("2024-05-29 12:00:00", "TKN")
