"""Coverage for the adapter's private extraction helpers, the not-initialized
guard on every read method, and __aenter__ error mapping.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from eero.exceptions import EeroAuthenticationException  # type: ignore[import-untyped]

from eero_exporter.eero_adapter import (
    EeroAPIError,
    EeroAuthError,
    EeroClient,
    _extract_data,
    _extract_list,
    _extract_network_id,
    _parse_network_status,
)
from tests.test_adapter_delegation import DELEGATION_TABLE

# ---------------------------------------------------------------------------
# _extract_data
# ---------------------------------------------------------------------------


def test_extract_data_none_returns_empty_dict() -> None:
    assert _extract_data(None) == {}


def test_extract_data_non_dict_passthrough() -> None:
    assert _extract_data(["a", "b"]) == ["a", "b"]
    assert _extract_data("raw-string") == "raw-string"


def test_extract_data_dict_without_envelope_shape_passthrough() -> None:
    """A dict lacking both 'meta' and 'data' keys is returned unmodified."""
    assert _extract_data({"foo": "bar"}) == {"foo": "bar"}


def test_extract_data_envelope_extracts_data_key() -> None:
    assert _extract_data({"meta": {}, "data": {"foo": "bar"}}) == {"foo": "bar"}


# ---------------------------------------------------------------------------
# _extract_list
# ---------------------------------------------------------------------------


def test_extract_list_none_returns_empty_list() -> None:
    assert _extract_list(None) == []


def test_extract_list_raw_list_passthrough() -> None:
    assert _extract_list([{"id": "1"}]) == [{"id": "1"}]


def test_extract_list_data_is_list() -> None:
    assert _extract_list({"meta": {}, "data": [{"id": "1"}]}) == [{"id": "1"}]


def test_extract_list_uses_list_key_nested_data() -> None:
    """{"data": {"networks": {"data": [...]}}} -- nested 'data' under list_key."""
    raw = {"meta": {}, "data": {"networks": {"data": [{"id": "1"}]}}}
    assert _extract_list(raw, "networks") == [{"id": "1"}]


def test_extract_list_uses_list_key_direct_list() -> None:
    raw = {"meta": {}, "data": {"eeros": [{"id": "1"}]}}
    assert _extract_list(raw, "eeros") == [{"id": "1"}]


def test_extract_list_list_key_absent_falls_back_to_common_keys() -> None:
    """When list_key doesn't match, the common-key fallback loop is tried."""
    raw = {"meta": {}, "data": {"devices": [{"id": "1"}]}}
    assert _extract_list(raw, "not-a-real-key") == [{"id": "1"}]


def test_extract_list_common_key_nested_data() -> None:
    raw = {"meta": {}, "data": {"profiles": {"data": [{"id": "1"}]}}}
    assert _extract_list(raw, None) == [{"id": "1"}]


def test_extract_list_no_matching_key_returns_empty() -> None:
    raw = {"meta": {}, "data": {"unrelated": "value"}}
    assert _extract_list(raw) == []


def test_extract_list_data_not_dict_or_list_returns_empty() -> None:
    raw = {"meta": {}, "data": "a-string"}
    assert _extract_list(raw) == []


# ---------------------------------------------------------------------------
# _parse_network_status
# ---------------------------------------------------------------------------


def test_parse_network_status_dict_shape() -> None:
    assert _parse_network_status({"status": "connected"}) == "connected"


def test_parse_network_status_dict_missing_status_key() -> None:
    assert _parse_network_status({}) == "unknown"


def test_parse_network_status_none() -> None:
    assert _parse_network_status(None) == "unknown"


def test_parse_network_status_plain_string() -> None:
    assert _parse_network_status("connected") == "connected"


# ---------------------------------------------------------------------------
# _extract_network_id
# ---------------------------------------------------------------------------


def test_extract_network_id_direct_id() -> None:
    assert _extract_network_id({"id": "net-1"}) == "net-1"


def test_extract_network_id_from_url_fallback() -> None:
    assert _extract_network_id({"url": "/2.2/networks/net-99/"}) == "net-99"


def test_extract_network_id_missing_both_returns_none() -> None:
    assert _extract_network_id({}) is None


# ---------------------------------------------------------------------------
# Every read method raises EeroAPIError before touching the SDK when the
# adapter hasn't entered its async context manager (self._client is None).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method_name", "call_args", "call_kwargs"),
    [(entry[0], entry[1], entry[2]) for entry in DELEGATION_TABLE],
    ids=[entry[0] for entry in DELEGATION_TABLE],
)
async def test_uninitialized_client_guard(
    method_name: str, call_args: tuple[Any, ...], call_kwargs: dict[str, Any]
) -> None:
    """Every read method raises a clear error, never an AttributeError, before init."""
    adapter = EeroClient()
    with pytest.raises(EeroAPIError, match="Client not initialized"):
        await getattr(adapter, method_name)(*call_args, **call_kwargs)


# ---------------------------------------------------------------------------
# __aenter__ error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method_name", "call_args", "call_kwargs"),
    [
        ("login", ("user@example.test",), {}),
        ("verify", ("123456",), {}),
        ("get_speed_test", ("net-1",), {}),
        ("is_premium", ("net-1",), {}),
    ],
)
async def test_uninitialized_client_guard_special_cased_methods(
    method_name: str, call_args: tuple[Any, ...], call_kwargs: dict[str, Any]
) -> None:
    """login/verify/get_speed_test/is_premium also guard against an uninitialized client."""
    adapter = EeroClient()
    with pytest.raises(EeroAPIError, match="Client not initialized"):
        await getattr(adapter, method_name)(*call_args, **call_kwargs)


async def test_aenter_maps_upstream_exception_to_local(tmp_path: Path) -> None:
    """A failure during the SDK client's own __aenter__ is mapped through _reraise_as_local."""
    adapter = EeroClient(cookie_file=str(tmp_path / "session.json"))

    with patch("eero_exporter.eero_adapter.BaseEeroClient") as mock_base_cls:
        mock_base = AsyncMock()
        mock_base.__aenter__ = AsyncMock(
            side_effect=EeroAuthenticationException(
                "bad session", error_code="error.session.expired"
            )
        )
        mock_base_cls.return_value = mock_base

        with pytest.raises(EeroAuthError):
            await adapter.__aenter__()


# ---------------------------------------------------------------------------
# is_authenticated property
# ---------------------------------------------------------------------------


def test_is_authenticated_false_before_init() -> None:
    adapter = EeroClient()
    assert adapter.is_authenticated is False


def test_is_authenticated_reflects_client_state() -> None:
    adapter = EeroClient()
    facade = AsyncMock()
    facade.is_authenticated = True
    adapter._client = facade
    assert adapter.is_authenticated is True
