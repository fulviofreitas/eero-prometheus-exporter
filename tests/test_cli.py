"""Tests for the `validate` and `status` CLI commands.

Regression coverage for the "unknown" network status bug: both commands used
to read `status` directly off the `/networks` list response, which does not
reliably carry a usable status field. They now always re-fetch the
per-network detail (`get_network`), mirroring `collector.py`, with a
defensive fallback chain: detail -> list-item status -> "unknown".

Mocking is done strictly at the EeroClient boundary (`eero_exporter.cli.EeroClient`),
per the repo's testing conventions.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from eero_exporter.cli import app
from eero_exporter.eero_adapter import EeroAPIError, EeroAuthError

runner = CliRunner()


def _make_mock_client(
    networks: list[dict[str, Any]],
    network_details: dict[str, dict[str, Any]] | None = None,
    detail_side_effect: BaseException | None = None,
) -> MagicMock:
    """Build a mock EeroClient instance behaving as an async context manager.

    Args:
        networks: Return value for `get_networks()`.
        network_details: Mapping of network_id -> detail dict, returned by
            `get_network(network_id)`.
        detail_side_effect: If set, `get_network()` raises this instead of
            returning a value.
    """
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get_networks = AsyncMock(return_value=networks)

    if detail_side_effect is not None:
        mock_client.get_network = AsyncMock(side_effect=detail_side_effect)
    else:
        details = network_details or {}

        async def _get_network(network_id: str) -> dict[str, Any]:
            return details.get(network_id, {})

        mock_client.get_network = AsyncMock(side_effect=_get_network)

    return mock_client


@pytest.fixture
def session_file(tmp_path: Path) -> Path:
    """A session file path that exists (commands gate on file existence)."""
    path = tmp_path / "session.json"
    path.write_text("{}")
    return path


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


class TestValidateCommand:
    """Tests for `eero-exporter validate`."""

    def test_happy_path_uses_detail_status(self, session_file: Path) -> None:
        """Status comes from get_network(), not the list item."""
        networks = [{"id": "123", "name": "iFulvio@House", "url": "https://x/2.2/networks/123"}]
        mock_client = _make_mock_client(networks, network_details={"123": {"status": "connected"}})

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "iFulvio@House: connected" in result.output
        assert "unknown" not in result.output
        mock_client.get_network.assert_awaited_once_with("123")

    def test_nested_status_dict_is_unwrapped(self, session_file: Path) -> None:
        """A detail response with status as {"status": "..."} is unwrapped."""
        networks = [{"id": "123", "name": "Net A", "url": "https://x/2.2/networks/123"}]
        mock_client = _make_mock_client(
            networks, network_details={"123": {"status": {"status": "offline"}}}
        )

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "Net A: offline" in result.output

    def test_status_absent_everywhere_defaults_to_unknown(self, session_file: Path) -> None:
        """No status on the list item nor the detail response -> "unknown"."""
        networks = [{"id": "123", "name": "Net A", "url": "https://x/2.2/networks/123"}]
        mock_client = _make_mock_client(networks, network_details={"123": {}})

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "Net A: unknown" in result.output

    def test_detail_call_failure_falls_back_to_list_item_status(self, session_file: Path) -> None:
        """If get_network() raises, fall back to the list item's own status."""
        networks = [
            {
                "id": "123",
                "name": "Net A",
                "url": "https://x/2.2/networks/123",
                "status": "connected",
            }
        ]
        mock_client = _make_mock_client(networks, detail_side_effect=EeroAPIError("boom"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "Net A: connected" in result.output

    def test_detail_call_failure_and_no_list_status_defaults_to_unknown(
        self, session_file: Path
    ) -> None:
        """If both the detail call fails and the list item lacks status -> "unknown"."""
        networks = [{"id": "123", "name": "Net A", "url": "https://x/2.2/networks/123"}]
        mock_client = _make_mock_client(networks, detail_side_effect=EeroAPIError("boom"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "Net A: unknown" in result.output

    def test_auth_failure_exits_nonzero(self, session_file: Path) -> None:
        """Regression guard: an expired session still exits 1 with no traceback."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_networks = AsyncMock(side_effect=EeroAuthError("expired"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 1
        assert "expired" in result.output.lower() or "invalid" in result.output.lower()

    def test_missing_session_file_exits_two(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(app, ["validate", "--session-file", str(missing)])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Tests for `eero-exporter status`."""

    def test_happy_path_uses_detail_status(self, session_file: Path) -> None:
        networks = [{"id": "123", "name": "iFulvio@House", "url": "https://x/2.2/networks/123"}]
        mock_client = _make_mock_client(networks, network_details={"123": {"status": "connected"}})

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "connected" in result.output
        assert "unknown" not in result.output
        mock_client.get_network.assert_awaited_once_with("123")

    def test_multi_network_status_independence(self, session_file: Path) -> None:
        """Each network's status is resolved independently, no cross-contamination."""
        networks = [
            {"id": "1", "name": "Net A", "url": "https://x/2.2/networks/1"},
            {"id": "2", "name": "Net B", "url": "https://x/2.2/networks/2"},
            {"id": "3", "name": "Net C", "url": "https://x/2.2/networks/3"},
        ]
        mock_client = _make_mock_client(
            networks,
            network_details={
                "1": {"status": "connected"},
                "2": {"status": {"status": "offline"}},
                "3": {},
            },
        )

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "Net A" in result.output and "connected" in result.output
        assert "Net B" in result.output and "offline" in result.output
        assert "Net C" in result.output and "unknown" in result.output
        assert mock_client.get_network.await_count == 3

    def test_detail_call_failure_falls_back_to_list_item_status(self, session_file: Path) -> None:
        networks = [
            {
                "id": "123",
                "name": "Net A",
                "url": "https://x/2.2/networks/123",
                "status": "connected",
            }
        ]
        mock_client = _make_mock_client(networks, detail_side_effect=EeroAPIError("boom"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "connected" in result.output

    def test_auth_failure_exits_nonzero(self, session_file: Path) -> None:
        """Regression guard: an expired session still exits 1 with no traceback."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_networks = AsyncMock(side_effect=EeroAuthError("expired"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "--session-file", str(session_file)])

        assert result.exit_code == 1
        assert "expired" in result.output.lower()

    def test_not_authenticated_exits_one(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(app, ["status", "--session-file", str(missing)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# --session-file plumbing: `cookie_file` must reach the adapter ctor (§4.3.7)
# ---------------------------------------------------------------------------


class TestSessionFilePlumbing:
    """Every command that talks to `EeroClient` must pass `cookie_file`."""

    def test_validate_passes_cookie_file(self, session_file: Path) -> None:
        mock_client = _make_mock_client([], network_details={})
        with patch("eero_exporter.cli.EeroClient", return_value=mock_client) as mock_ctor:
            runner.invoke(app, ["validate", "--session-file", str(session_file)])
        mock_ctor.assert_called_once_with(cookie_file=str(session_file))

    def test_status_passes_cookie_file(self, session_file: Path) -> None:
        mock_client = _make_mock_client([], network_details={})
        with patch("eero_exporter.cli.EeroClient", return_value=mock_client) as mock_ctor:
            runner.invoke(app, ["status", "--session-file", str(session_file)])
        mock_ctor.assert_called_once_with(cookie_file=str(session_file))

    def test_login_passes_cookie_file(self, tmp_path: Path) -> None:
        session_path = tmp_path / "session.json"
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.login = AsyncMock(side_effect=EeroAuthError("rejected"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client) as mock_ctor:
            result = runner.invoke(
                app, ["login", "user@example.com", "--session-file", str(session_path)]
            )

        mock_ctor.assert_called_once_with(cookie_file=str(session_path))
        assert result.exit_code == 1

    def test_test_command_passes_cookie_file(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.EeroCollector") as mock_collector_cls:
            mock_collector = MagicMock()
            mock_collector.collect = AsyncMock(return_value=True)
            mock_collector_cls.return_value = mock_collector

            runner.invoke(app, ["test", "--session-file", str(session_file)])

        _, kwargs = mock_collector_cls.call_args
        assert kwargs["session_file"] == str(session_file)


# ---------------------------------------------------------------------------
# EeroAPIError catch-all (§4.3.8) -- exit 1, one-line message, no traceback
# ---------------------------------------------------------------------------


class TestApiErrorCatchAll:
    def test_login_rejected_identifier_is_auth_error(self, tmp_path: Path) -> None:
        """8.0.1 re-wraps a rejected identifier as EeroAuthError (§1.2a)."""
        session_path = tmp_path / "session.json"
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.login = AsyncMock(side_effect=EeroAuthError("rejected identifier"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(
                app, ["login", "not-an-email", "--session-file", str(session_path)]
            )

        assert result.exit_code == 1
        assert "rejected identifier" in result.output
        assert "Traceback" not in result.output

    def test_status_generic_api_error_exits_one_no_traceback(self, session_file: Path) -> None:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get_networks = AsyncMock(
            side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
        )

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(app, ["status", "--session-file", str(session_file)])

        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "500" in result.output


# ---------------------------------------------------------------------------
# session-info
# ---------------------------------------------------------------------------


class TestSessionInfoCommand:
    def test_missing_file_exits_one_with_hint(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(app, ["session-info", "--session-file", str(missing)])
        assert result.exit_code == 1
        assert "login" in result.output.lower()

    def test_schema_2_record_reports_version_and_never_prints_token(self, tmp_path: Path) -> None:
        planted_token = "s=SUPER-SECRET-TOKEN-VALUE"  # nosec B105 - test fixture only
        path = tmp_path / "session.json"
        path.write_text(f'{{"session_id": "{planted_token}", "schema_version": 2}}')
        path.chmod(0o600)

        result = runner.invoke(app, ["session-info", "--session-file", str(path)])

        assert result.exit_code == 0
        assert "Schema version: 2" in result.output
        assert "Token present: True" in result.output
        assert planted_token not in result.output

    def test_schema_1_legacy_record_reports_legacy(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        path.write_text('{"session_id": "legacy-token-value"}')
        path.chmod(0o600)

        result = runner.invoke(app, ["session-info", "--session-file", str(path)])

        assert result.exit_code == 0
        assert "1 (legacy)" in result.output
        assert "legacy-token-value" not in result.output

    def test_unreadable_json_reports_error_and_exits_one(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        path.write_text("not valid json{{{")

        result = runner.invoke(app, ["session-info", "--session-file", str(path)])

        assert result.exit_code == 1

    def test_no_token_reports_false(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        path.write_text('{"schema_version": 2, "session_id": null}')

        result = runner.invoke(app, ["session-info", "--session-file", str(path)])

        assert result.exit_code == 0
        assert "Token present: False" in result.output


# ---------------------------------------------------------------------------
# serve: precedence fix + auth_failure_exit
# ---------------------------------------------------------------------------


class TestServeCommand:
    def test_yaml_value_survives_when_cli_flag_absent(
        self, tmp_path: Path, session_file: Path
    ) -> None:
        """Regression guard for the CLI-always-wins-over-YAML bug (§4.3.2)."""
        from eero_exporter.config import ExporterConfig

        config_path = tmp_path / "config.yml"
        ExporterConfig(port=9191).save(config_path)

        captured: dict[str, object] = {}

        def _fake_run_server(config: object) -> None:
            captured["port"] = config.port  # type: ignore[attr-defined]

        with patch("eero_exporter.cli.run_server", side_effect=_fake_run_server):
            result = runner.invoke(
                app,
                [
                    "serve",
                    "--config-file",
                    str(config_path),
                    "--session-file",
                    str(session_file),
                ],
            )

        assert result.exit_code == 0
        assert captured["port"] == 9191

    def test_cli_flag_overrides_yaml_value(self, tmp_path: Path, session_file: Path) -> None:
        from eero_exporter.config import ExporterConfig

        config_path = tmp_path / "config.yml"
        ExporterConfig(port=9191).save(config_path)

        captured: dict[str, object] = {}

        def _fake_run_server(config: object) -> None:
            captured["port"] = config.port  # type: ignore[attr-defined]

        with patch("eero_exporter.cli.run_server", side_effect=_fake_run_server):
            result = runner.invoke(
                app,
                [
                    "serve",
                    "--config-file",
                    str(config_path),
                    "--session-file",
                    str(session_file),
                    "--port",
                    "8181",
                ],
            )

        assert result.exit_code == 0
        assert captured["port"] == 8181

    def test_auth_failure_exit_flag_is_wired_to_run_server(self, session_file: Path) -> None:
        captured: dict[str, object] = {}

        def _fake_run_server(config: object) -> None:
            captured["auth_failure_exit"] = config.auth_failure_exit  # type: ignore[attr-defined]

        with patch("eero_exporter.cli.run_server", side_effect=_fake_run_server):
            result = runner.invoke(
                app,
                [
                    "serve",
                    "--session-file",
                    str(session_file),
                    "--auth-failure-exit",
                ],
            )

        assert result.exit_code == 0
        assert captured["auth_failure_exit"] is True

    def test_serve_exits_with_server_systemexit_code(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.run_server", side_effect=SystemExit(2)):
            result = runner.invoke(app, ["serve", "--session-file", str(session_file)])
        assert result.exit_code == 2
