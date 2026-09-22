"""Unit tests for _coerce_numeric helper in collector.py.

Tests cover:
- Numeric passthrough (int, float)
- String coercion
- Dict shapes with common keys (seconds, value, current, total, count)
- Unknown dict shapes returning None with deduplicated DEBUG logging
- None and unsupported types returning None

Also covers `_parse_network_status` in eero_adapter.py: normalizing the
network `status` field, which may be a plain string, a nested dict, or
genuinely absent.
"""

import logging

import pytest

from eero_exporter.collector import _COERCE_UNKNOWN_SHAPES_SEEN, _coerce_numeric
from eero_exporter.eero_adapter import _parse_network_status

# ========================== _coerce_numeric Tests ==========================


class TestCoerceNumeric:
    """Tests for _coerce_numeric() defensive coercion helper."""

    def setup_method(self) -> None:
        """Clear the dedup set before each test for isolation."""
        _COERCE_UNKNOWN_SHAPES_SEEN.clear()

    # --- Numeric passthrough ---

    def test_int_returns_float(self) -> None:
        """Integer input is cast to float."""
        assert _coerce_numeric(123) == 123.0

    def test_float_passthrough(self) -> None:
        """Float input is returned as-is (as float)."""
        assert _coerce_numeric(45.6) == 45.6

    def test_zero_int(self) -> None:
        """Zero integer is returned as 0.0."""
        assert _coerce_numeric(0) == 0.0

    def test_negative_number(self) -> None:
        """Negative numbers are coerced correctly."""
        assert _coerce_numeric(-10) == -10.0

    # --- String coercion ---

    def test_numeric_string_returns_float(self) -> None:
        """String containing a number is parsed to float."""
        assert _coerce_numeric("123") == 123.0

    def test_float_string(self) -> None:
        """String containing a float is parsed correctly."""
        assert _coerce_numeric("45.6") == 45.6

    def test_non_numeric_string_returns_none(self) -> None:
        """Non-numeric string returns None."""
        assert _coerce_numeric("not_a_number") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert _coerce_numeric("") is None

    # --- Dict shapes ---

    def test_dict_with_seconds_key(self) -> None:
        """Dict with 'seconds' key is coerced to float."""
        assert _coerce_numeric({"seconds": 999}) == 999.0

    def test_dict_with_value_key(self) -> None:
        """Dict with 'value' key is coerced to float."""
        assert _coerce_numeric({"value": 5}) == 5.0

    def test_dict_with_current_key(self) -> None:
        """Dict with 'current' key is coerced, extra keys ignored."""
        assert _coerce_numeric({"current": 7, "last_reboot": "2024-01-01T00:00:00Z"}) == 7.0

    def test_dict_with_total_key(self) -> None:
        """Dict with 'total' key is coerced to float."""
        assert _coerce_numeric({"total": 42}) == 42.0

    def test_dict_with_count_key(self) -> None:
        """Dict with 'count' key is coerced to float."""
        assert _coerce_numeric({"count": 3}) == 3.0

    def test_dict_key_priority_seconds_over_value(self) -> None:
        """'seconds' takes priority over 'value' when both present."""
        assert _coerce_numeric({"seconds": 10, "value": 99}) == 10.0

    def test_dict_with_unknown_keys_returns_none(self) -> None:
        """Dict with no known keys returns None."""
        assert _coerce_numeric({"unknown": "junk"}) is None

    def test_dict_nested_numeric_value(self) -> None:
        """Dict value that is itself numeric is recursively coerced."""
        assert _coerce_numeric({"seconds": "500"}) == 500.0

    # --- None and unsupported types ---

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        assert _coerce_numeric(None) is None

    def test_list_returns_none(self) -> None:
        """List input returns None."""
        assert _coerce_numeric([1, 2, 3]) is None

    def test_bool_returns_float(self) -> None:
        """Bool is a subclass of int, so True->1.0 and False->0.0."""
        assert _coerce_numeric(True) == 1.0
        assert _coerce_numeric(False) == 0.0

    # --- DEBUG log deduplication ---

    def test_unknown_shape_logs_debug_once(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unknown dict shape triggers a DEBUG log exactly once per field+keys combo."""
        with caplog.at_level(logging.DEBUG, logger="eero_exporter.collector"):
            _coerce_numeric({"unknown": "junk"}, field_name="uptime")
            _coerce_numeric({"unknown": "junk"}, field_name="uptime")
            _coerce_numeric({"unknown": "junk"}, field_name="uptime")

        debug_records = [
            r for r in caplog.records if r.levelno == logging.DEBUG and "uptime" in r.message
        ]
        assert (
            len(debug_records) == 1
        ), f"Expected exactly 1 DEBUG log for same field+keys, got {len(debug_records)}"

    def test_unknown_shape_logs_separately_per_field(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Different field names each get their own deduplicated DEBUG log entry."""
        with caplog.at_level(logging.DEBUG, logger="eero_exporter.collector"):
            _coerce_numeric({"unknown": "junk"}, field_name="uptime")
            _coerce_numeric({"unknown": "junk"}, field_name="temperature")

        debug_records = [
            r for r in caplog.records if r.levelno == logging.DEBUG and "unknown" in r.message
        ]
        assert len(debug_records) == 2

    def test_unknown_shape_logs_separately_per_key_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Different key sets on same field each get one DEBUG log entry."""
        with caplog.at_level(logging.DEBUG, logger="eero_exporter.collector"):
            _coerce_numeric({"foo": 1}, field_name="uptime")
            _coerce_numeric({"bar": 2}, field_name="uptime")
            _coerce_numeric({"foo": 1}, field_name="uptime")  # duplicate — should NOT log again

        debug_records = [
            r for r in caplog.records if r.levelno == logging.DEBUG and "uptime" in r.message
        ]
        assert len(debug_records) == 2

    def test_known_key_after_unknown_dict_cleared(self) -> None:
        """Known-key dict coerces correctly regardless of dedup state."""
        _COERCE_UNKNOWN_SHAPES_SEEN.add(("uptime", ("seconds",)))  # pre-populate
        # Should still coerce correctly — dedup set only gates logging, not logic
        assert _coerce_numeric({"seconds": 100}, field_name="uptime") == 100.0


# ======================= _parse_network_status Tests =======================


class TestParseNetworkStatus:
    """Tests for _parse_network_status() defensive status normalization."""

    @pytest.mark.parametrize(
        ("raw_status", "expected"),
        [
            ("connected", "connected"),
            ("online", "online"),
            ("offline", "offline"),
            ({"status": "connected"}, "connected"),
            ({"status": "offline"}, "offline"),
            ({"other_key": "irrelevant"}, "unknown"),
            ({}, "unknown"),
            (None, "unknown"),
            (123, "123"),
            (True, "True"),
        ],
    )
    def test_parse_network_status(self, raw_status: object, expected: str) -> None:
        assert _parse_network_status(raw_status) == expected
