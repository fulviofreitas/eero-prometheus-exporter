"""Bulk edge-case coverage for collector.py's pure helper functions.

These are all stateless parsers/normalizers with no I/O -- exercised
directly, in isolation, without spinning up a collector or mocking a
client. Grouped by function; each group targets the specific branches the
coverage report identified as missed.
"""

from eero_exporter.collector import (
    _coerce_numeric,
    _coerce_power_saving_enabled,
    _extract_device_id_from_url,
    _extract_profile_id_from_url,
    _frequency_to_band,
    _get_connection_type,
    _get_source_eero_location,
    _get_wifi_generation,
    _normalize_device_type,
    _normalize_manufacturer,
    _parse_premium_enabled,
    _parse_signal_strength,
    _series_sum,
)

# ---------------------------------------------------------------------------
# _extract_profile_id_from_url / _extract_device_id_from_url
# ---------------------------------------------------------------------------


def test_extract_profile_id_from_url_empty_returns_empty_string() -> None:
    assert _extract_profile_id_from_url("") == ""
    assert _extract_profile_id_from_url(None) == ""


def test_extract_profile_id_from_url_falls_back_to_last_segment() -> None:
    """No '/profiles/<id>' pattern -- falls back to the last path segment."""
    assert _extract_profile_id_from_url("/2.2/networks/net-1/insights") == "insights"


def test_extract_device_id_from_url_empty_returns_empty_string() -> None:
    assert _extract_device_id_from_url("") == ""
    assert _extract_device_id_from_url(None) == ""


def test_extract_device_id_from_url_falls_back_to_last_segment() -> None:
    assert _extract_device_id_from_url("/2.2/networks/net-1/insights") == "insights"


# ---------------------------------------------------------------------------
# _parse_signal_strength
# ---------------------------------------------------------------------------


def test_parse_signal_strength_none_returns_none() -> None:
    assert _parse_signal_strength(None) is None
    assert _parse_signal_strength("") is None


def test_parse_signal_strength_unparseable_returns_none() -> None:
    assert _parse_signal_strength("not-a-number") is None


def test_parse_signal_strength_non_string_returns_none() -> None:
    """Passing a non-string (e.g. int) hits the AttributeError branch."""
    assert _parse_signal_strength(123) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _parse_premium_enabled
# ---------------------------------------------------------------------------


def test_parse_premium_enabled_active_status_string() -> None:
    assert _parse_premium_enabled("active", None) is True


def test_parse_premium_enabled_none_status_falls_through_to_details() -> None:
    assert _parse_premium_enabled(None, {"tier": "plus"}) is True


def test_parse_premium_enabled_inactive_and_empty_details_is_false() -> None:
    assert _parse_premium_enabled("none", {}) is False
    assert _parse_premium_enabled("false", None) is False
    assert _parse_premium_enabled("", None) is False


def test_parse_premium_enabled_details_without_tier_is_false() -> None:
    assert _parse_premium_enabled(None, {"other_field": "x"}) is False


def test_parse_premium_enabled_details_not_a_dict_is_false() -> None:
    assert _parse_premium_enabled(None, "not-a-dict") is False


# ---------------------------------------------------------------------------
# _coerce_numeric
# ---------------------------------------------------------------------------


def test_coerce_numeric_none_returns_none() -> None:
    assert _coerce_numeric(None) is None


def test_coerce_numeric_int_and_float() -> None:
    assert _coerce_numeric(5) == 5.0
    assert _coerce_numeric(5.5) == 5.5


def test_coerce_numeric_numeric_string() -> None:
    assert _coerce_numeric("42") == 42.0


def test_coerce_numeric_non_numeric_string_returns_none() -> None:
    assert _coerce_numeric("not-a-number") is None


def test_coerce_numeric_dict_with_known_key() -> None:
    assert _coerce_numeric({"seconds": 100}) == 100.0
    assert _coerce_numeric({"value": 7}) == 7.0
    assert _coerce_numeric({"current": 3}) == 3.0
    assert _coerce_numeric({"total": 9}) == 9.0
    assert _coerce_numeric({"count": 2}) == 2.0


def test_coerce_numeric_dict_unknown_shape_returns_none() -> None:
    result = _coerce_numeric({"totally_unknown_key": 1}, field_name="mystery")
    assert result is None


def test_coerce_numeric_other_type_returns_none() -> None:
    assert _coerce_numeric([1, 2, 3]) is None  # type: ignore[arg-type]
    assert _coerce_numeric(object()) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _coerce_power_saving_enabled
# ---------------------------------------------------------------------------


def test_coerce_power_saving_enabled_plain_bool() -> None:
    assert _coerce_power_saving_enabled(True) is True
    assert _coerce_power_saving_enabled(False) is False


def test_coerce_power_saving_enabled_flat_dict() -> None:
    assert _coerce_power_saving_enabled({"enabled": True}) is True
    assert _coerce_power_saving_enabled({"enabled": False}) is False


def test_coerce_power_saving_enabled_flat_dict_non_bool_enabled_returns_none() -> None:
    assert _coerce_power_saving_enabled({"enabled": "yes"}) is None


def test_coerce_power_saving_enabled_schedule_shape() -> None:
    assert _coerce_power_saving_enabled({"schedule": {"active": True}}) is True
    assert _coerce_power_saving_enabled({"schedule": {"active": False}}) is False


def test_coerce_power_saving_enabled_schedule_non_bool_active_returns_none() -> None:
    assert _coerce_power_saving_enabled({"schedule": {"active": "yes"}}) is None


def test_coerce_power_saving_enabled_unrecognised_shape_returns_none() -> None:
    assert _coerce_power_saving_enabled({"unrelated": 1}) is None
    assert _coerce_power_saving_enabled("not-a-dict-or-bool") is None
    assert _coerce_power_saving_enabled(None) is None


# ---------------------------------------------------------------------------
# _frequency_to_band
# ---------------------------------------------------------------------------


def test_frequency_to_band_none_or_zero() -> None:
    assert _frequency_to_band(None) == "unknown"
    assert _frequency_to_band(0) == "unknown"


def test_frequency_to_band_2_4ghz() -> None:
    assert _frequency_to_band(2412) == "2.4GHz"


def test_frequency_to_band_5ghz() -> None:
    assert _frequency_to_band(5180) == "5GHz"


def test_frequency_to_band_6ghz() -> None:
    assert _frequency_to_band(6115) == "6GHz"


def test_frequency_to_band_out_of_range_is_unknown() -> None:
    assert _frequency_to_band(999999) == "unknown"


# ---------------------------------------------------------------------------
# _normalize_manufacturer / _normalize_device_type
# ---------------------------------------------------------------------------


def test_normalize_manufacturer_none_or_empty() -> None:
    assert _normalize_manufacturer(None) == "unknown"
    assert _normalize_manufacturer("") == "unknown"


def test_normalize_manufacturer_truncates_and_strips() -> None:
    assert _normalize_manufacturer("  Apple  ") == "Apple"
    long_name = "x" * 80
    assert len(_normalize_manufacturer(long_name)) == 50


def test_normalize_manufacturer_whitespace_only_is_unknown() -> None:
    assert _normalize_manufacturer("   ") == "unknown"


def test_normalize_device_type_none_or_empty() -> None:
    assert _normalize_device_type(None) == "unknown"
    assert _normalize_device_type("") == "unknown"


def test_normalize_device_type_lowercases_and_truncates() -> None:
    assert _normalize_device_type("  Smart TV  ") == "smart tv"


def test_normalize_device_type_whitespace_only_is_unknown() -> None:
    assert _normalize_device_type("   ") == "unknown"


# ---------------------------------------------------------------------------
# _get_connection_type
# ---------------------------------------------------------------------------


def test_get_connection_type_explicit_wireless_bool() -> None:
    assert _get_connection_type({"wireless": True}) == "wireless"
    assert _get_connection_type({"wireless": False}) == "wired"


def test_get_connection_type_fallback_to_connection_type_field() -> None:
    assert _get_connection_type({"connection_type": "Wired"}) == "wired"
    assert _get_connection_type({"connection_type": "Wireless"}) == "wireless"


def test_get_connection_type_unrecognised_connection_type_field() -> None:
    assert _get_connection_type({"connection_type": "bluetooth"}) == "unknown"


def test_get_connection_type_no_fields_present() -> None:
    assert _get_connection_type({}) == "unknown"


# ---------------------------------------------------------------------------
# _get_source_eero_location
# ---------------------------------------------------------------------------


def test_get_source_eero_location_present() -> None:
    assert _get_source_eero_location({"source": {"location": "Living Room"}}) == "Living Room"


def test_get_source_eero_location_truncates_to_50_chars() -> None:
    long_location = "x" * 100
    result = _get_source_eero_location({"source": {"location": long_location}})
    assert len(result) == 50


def test_get_source_eero_location_missing_returns_unknown() -> None:
    assert _get_source_eero_location({}) == "unknown"
    assert _get_source_eero_location({"source": {}}) == "unknown"
    assert _get_source_eero_location({"source": "not-a-dict"}) == "unknown"


# ---------------------------------------------------------------------------
# _get_wifi_generation
# ---------------------------------------------------------------------------


def test_get_wifi_generation_no_connectivity_returns_none() -> None:
    assert _get_wifi_generation({}) is None


def test_get_wifi_generation_explicit_field() -> None:
    assert _get_wifi_generation({"connectivity": {"wifi_generation": 6}}) == 6


def test_get_wifi_generation_no_frequency_returns_none() -> None:
    assert _get_wifi_generation({"connectivity": {}}) is None


def test_get_wifi_generation_6ghz_band_infers_wifi6() -> None:
    assert _get_wifi_generation({"connectivity": {"frequency": 6115}}) == 6


def test_get_wifi_generation_infers_from_mode_he() -> None:
    assert (
        _get_wifi_generation({"connectivity": {"frequency": 5180, "rx_rate_info": {"mode": "HE"}}})
        == 6
    )


def test_get_wifi_generation_infers_from_mode_ax() -> None:
    assert (
        _get_wifi_generation(
            {"connectivity": {"frequency": 5180, "rx_rate_info": {"mode": "ax_something"}}}
        )
        == 6
    )


def test_get_wifi_generation_infers_from_mode_vht() -> None:
    assert (
        _get_wifi_generation(
            {"connectivity": {"frequency": 5180, "rx_rate_info": {"mode": "VHT80"}}}
        )
        == 5
    )


def test_get_wifi_generation_infers_from_mode_ac() -> None:
    assert (
        _get_wifi_generation(
            {"connectivity": {"frequency": 5180, "rx_rate_info": {"mode": "ac_mode"}}}
        )
        == 5
    )


def test_get_wifi_generation_infers_from_mode_ht() -> None:
    assert (
        _get_wifi_generation(
            {"connectivity": {"frequency": 2412, "rx_rate_info": {"mode": "HT20"}}}
        )
        == 4
    )


def test_get_wifi_generation_infers_from_mode_n() -> None:
    assert (
        _get_wifi_generation({"connectivity": {"frequency": 2412, "rx_rate_info": {"mode": "n"}}})
        == 4
    )


def test_get_wifi_generation_unrecognised_mode_returns_none() -> None:
    assert (
        _get_wifi_generation({"connectivity": {"frequency": 2412, "rx_rate_info": {"mode": "b"}}})
        is None
    )


def test_get_wifi_generation_no_rx_rate_info_returns_none() -> None:
    assert _get_wifi_generation({"connectivity": {"frequency": 2412}}) is None


# ---------------------------------------------------------------------------
# _series_sum: non-list "values"
# ---------------------------------------------------------------------------


def test_series_sum_non_list_values_returns_none() -> None:
    assert _series_sum({"values": "not-a-list"}) is None
