"""Extra CLI coverage: login/logout/test happy+error paths, session-info
stat/JSON error branches, and remaining --session-file plumbing.

Mocking is done strictly at the EeroClient/EeroCollector boundary, per the
repo's testing conventions (see test_cli.py).
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from eero_exporter.cli import app
from eero_exporter.eero_adapter import EeroAPIError, EeroAuthError

runner = CliRunner()


@pytest.fixture
def session_file(tmp_path: Path) -> Path:
    path = tmp_path / "session.json"
    path.write_text("{}")
    return path


def _login_client(login_side_effect: Any = None, verify_side_effect: Any = None) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.login = AsyncMock(side_effect=login_side_effect, return_value=None)
    client.verify = AsyncMock(side_effect=verify_side_effect, return_value=None)
    return client


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


class TestLoginCommand:
    def test_happy_path_prompts_for_code_and_succeeds(self, tmp_path: Path) -> None:
        session_path = tmp_path / "session.json"
        mock_client = _login_client()

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(
                app,
                ["login", "user@example.com", "--session-file", str(session_path)],
                input="123456\n",
            )

        assert result.exit_code == 0
        assert "Login successful" in result.output
        mock_client.login.assert_awaited_once_with("user@example.com")
        mock_client.verify.assert_awaited_once_with("123456")

    def test_login_generic_api_error_exits_one(self, tmp_path: Path) -> None:
        session_path = tmp_path / "session.json"
        mock_client = _login_client(
            login_side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
        )

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(
                app, ["login", "user@example.com", "--session-file", str(session_path)]
            )

        assert result.exit_code == 1
        assert "Login failed" in result.output

    def test_verify_auth_error_exits_one(self, tmp_path: Path) -> None:
        session_path = tmp_path / "session.json"
        mock_client = _login_client(verify_side_effect=EeroAuthError("bad code"))

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(
                app,
                ["login", "user@example.com", "--session-file", str(session_path)],
                input="000000\n",
            )

        assert result.exit_code == 1
        assert "Verification failed" in result.output

    def test_verify_generic_api_error_exits_one(self, tmp_path: Path) -> None:
        session_path = tmp_path / "session.json"
        mock_client = _login_client(
            verify_side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
        )

        with patch("eero_exporter.cli.EeroClient", return_value=mock_client):
            result = runner.invoke(
                app,
                ["login", "user@example.com", "--session-file", str(session_path)],
                input="000000\n",
            )

        assert result.exit_code == 1
        assert "Verification failed" in result.output


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------


class TestLogoutCommand:
    def test_logout_removes_existing_session_file(self, session_file: Path) -> None:
        assert session_file.exists()
        result = runner.invoke(app, ["logout", "--session-file", str(session_file)])
        assert result.exit_code == 0
        assert "Session cleared" in result.output
        assert not session_file.exists()

    def test_logout_no_session_file_reports_none_found(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(app, ["logout", "--session-file", str(missing)])
        assert result.exit_code == 0
        assert "No session file found" in result.output


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


class TestTestCommand:
    def test_collection_success_prints_success(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.EeroCollector") as mock_collector_cls:
            mock_collector = MagicMock()
            mock_collector.collect = AsyncMock(return_value=True)
            mock_collector_cls.return_value = mock_collector

            result = runner.invoke(app, ["test", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "successful" in result.output.lower()

    def test_collection_returns_false_exits_one(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.EeroCollector") as mock_collector_cls:
            mock_collector = MagicMock()
            mock_collector.collect = AsyncMock(return_value=False)
            mock_collector_cls.return_value = mock_collector

            result = runner.invoke(app, ["test", "--session-file", str(session_file)])

        assert result.exit_code == 1
        assert "failed" in result.output.lower()

    def test_collection_raises_api_error_exits_one(self, session_file: Path) -> None:
        with patch("eero_exporter.cli.EeroCollector") as mock_collector_cls:
            mock_collector = MagicMock()
            mock_collector.collect = AsyncMock(
                side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
            )
            mock_collector_cls.return_value = mock_collector

            result = runner.invoke(app, ["test", "--session-file", str(session_file)])

        assert result.exit_code == 1
        assert "Metrics collection failed" in result.output

    def test_no_session_file_exits_one(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        result = runner.invoke(app, ["test", "--session-file", str(missing)])
        assert result.exit_code == 1
        assert "not authenticated" in result.output.lower()


# ---------------------------------------------------------------------------
# session-info: stat/OSError and non-dict-record branches
# ---------------------------------------------------------------------------


class TestSessionInfoErrorBranches:
    def test_stat_failure_exits_one(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "session.json"
        path.write_text("{}")

        original_stat = Path.stat

        def _raise_for_target(self: Path, *a: object, **k: object) -> object:
            if self == path:
                raise OSError("permission denied")
            return original_stat(self, *a, **k)

        monkeypatch.setattr(Path, "stat", _raise_for_target)

        result = runner.invoke(app, ["session-info", "--session-file", str(path)])

        assert result.exit_code == 1
        assert "Could not stat session file" in result.output

    def test_non_dict_json_record_exits_one(self, tmp_path: Path) -> None:
        path = tmp_path / "session.json"
        path.write_text("[1, 2, 3]")

        result = runner.invoke(app, ["session-info", "--session-file", str(path)])

        assert result.exit_code == 1
        assert "does not contain a JSON object" in result.output


# ---------------------------------------------------------------------------
# validate: happy-path per-network loop + generic API error branch
# ---------------------------------------------------------------------------


class TestValidateExtraBranches:
    def test_happy_path_lists_each_network(self, session_file: Path) -> None:
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get_networks = AsyncMock(
            return_value=[{"id": "net-1", "name": "Home", "url": "/2.2/networks/net-1"}]
        )
        client.get_network = AsyncMock(return_value={"status": "connected"})

        with patch("eero_exporter.cli.EeroClient", return_value=client):
            result = runner.invoke(app, ["validate", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "Home" in result.output
        assert "connected" in result.output

    def test_generic_api_error_quiet_suppresses_message(self, session_file: Path) -> None:
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get_networks = AsyncMock(
            side_effect=EeroAPIError("boom", status_code=500, error_code="error.internal")
        )

        with patch("eero_exporter.cli.EeroClient", return_value=client):
            result = runner.invoke(
                app, ["validate", "--session-file", str(session_file), "--quiet"]
            )

        assert result.exit_code == 1
        assert result.output.strip() == ""


# ---------------------------------------------------------------------------
# status: no-networks-found branch
# ---------------------------------------------------------------------------


class TestStatusExtraBranches:
    def test_no_networks_found(self, session_file: Path) -> None:
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get_networks = AsyncMock(return_value=[])

        with patch("eero_exporter.cli.EeroClient", return_value=client):
            result = runner.invoke(app, ["status", "--session-file", str(session_file)])

        assert result.exit_code == 0
        assert "No networks found" in result.output
