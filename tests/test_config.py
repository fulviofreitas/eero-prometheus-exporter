"""Tests for `ExporterConfig`, env-var derivation, and the CLI option catalogue.

Covers: CLI > env > YAML > default precedence (§4.3), env-var parsing
(including boolean truthy/falsy strings), list parsing for
`data_usage_periods`, the Typer-tree envvar walk (D15), `--session-file`
plumbing (see test_cli.py for the per-command variant), and
`describe_options()`.
"""

from pathlib import Path

import click
import pytest
import typer
import yaml

from eero_exporter.cli import app, describe_options
from eero_exporter.config import (
    DEFAULT_PORT,
    ExporterConfig,
    envvar_name,
    parse_data_usage_periods,
)

# ---------------------------------------------------------------------------
# envvar_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("--session-file", "EERO_EXPORTER_SESSION_FILE"),
        ("--get-retries", "EERO_EXPORTER_GET_RETRIES"),
        ("--include-devices", "EERO_EXPORTER_INCLUDE_DEVICES"),
        ("--log-level", "EERO_EXPORTER_LOG_LEVEL"),
    ],
)
def test_envvar_name_derivation(flag: str, expected: str) -> None:
    assert envvar_name(flag) == expected


# ---------------------------------------------------------------------------
# parse_data_usage_periods
# ---------------------------------------------------------------------------


def test_parse_data_usage_periods_from_csv_string() -> None:
    assert parse_data_usage_periods("day,week,month") == ["day", "week", "month"]


def test_parse_data_usage_periods_strips_whitespace() -> None:
    assert parse_data_usage_periods("day, week , month") == ["day", "week", "month"]


def test_parse_data_usage_periods_from_list_passthrough() -> None:
    assert parse_data_usage_periods(["day", "week"]) == ["day", "week"]


def test_parse_data_usage_periods_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="Invalid data_usage_periods"):
        parse_data_usage_periods("day,fortnight")


def test_parse_data_usage_periods_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_data_usage_periods("")


# ---------------------------------------------------------------------------
# ExporterConfig defaults / to_dict round-trip
# ---------------------------------------------------------------------------


def test_default_config_has_expected_new_fields() -> None:
    config = ExporterConfig()
    assert config.get_retries == 1
    assert config.send_legacy_cookie is True
    assert config.accept_language == "en-US"
    assert config.auth_failure_exit is False
    assert config.expose_public_ip is False
    assert config.data_usage_periods == ["day", "week", "month"]
    assert config.eeros_from_envelope is False
    assert config.include_extended is True
    assert config.include_rf is True
    assert config.include_per_profile is False
    assert config.include_per_device is False
    assert config.include_per_eero is False
    assert config.include_unverified is False


def test_to_dict_yaml_round_trip_includes_tier_flags(tmp_path: Path) -> None:
    config = ExporterConfig(include_per_device=True, data_usage_periods=["day"])
    path = tmp_path / "config.yml"
    config.save(path)

    loaded = ExporterConfig.from_file(path)

    assert loaded.include_per_device is True
    assert loaded.data_usage_periods == ["day"]
    assert loaded.include_extended is True  # unchanged default preserved


def test_from_file_rejects_invalid_data_usage_periods_falls_back_to_defaults(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.yml"
    path.write_text(yaml.dump({"data_usage_periods": ["not-a-period"]}))

    # Malformed config falls back to defaults rather than raising (matches
    # existing from_file() behaviour for any bad value).
    loaded = ExporterConfig.from_file(path)
    assert loaded.data_usage_periods == ["day", "week", "month"]


# ---------------------------------------------------------------------------
# merge_overrides precedence: CLI > env > YAML > default
# ---------------------------------------------------------------------------


def test_merge_overrides_none_values_do_not_override_yaml() -> None:
    """A `None` sentinel (option not provided) leaves the YAML/default value alone."""
    base = ExporterConfig(port=9999, log_level="DEBUG")
    merged = base.merge_overrides(port=None, log_level=None)
    assert merged.port == 9999
    assert merged.log_level == "DEBUG"


def test_merge_overrides_non_none_values_win_over_yaml() -> None:
    base = ExporterConfig(port=9999)
    merged = base.merge_overrides(port=8080)
    assert merged.port == 8080


def test_merge_overrides_bool_field_false_is_still_applied() -> None:
    """False is a legitimate override, not a sentinel -- only None is skipped."""
    base = ExporterConfig(include_devices=True)
    merged = base.merge_overrides(include_devices=False)
    assert merged.include_devices is False


def test_merge_overrides_string_field() -> None:
    base = ExporterConfig(accept_language="en-US")
    merged = base.merge_overrides(accept_language="fr-FR")
    assert merged.accept_language == "fr-FR"


def test_merge_overrides_list_field_parses_csv_string() -> None:
    base = ExporterConfig()
    merged = base.merge_overrides(data_usage_periods="day,month")
    assert merged.data_usage_periods == ["day", "month"]


def test_merge_overrides_unknown_field_raises() -> None:
    base = ExporterConfig()
    with pytest.raises(TypeError):
        base.merge_overrides(not_a_real_field=True)


def test_precedence_four_levels_port(tmp_path: Path) -> None:
    """default < YAML < env < CLI, verified independently at each level."""
    # 1. default
    assert ExporterConfig().port == DEFAULT_PORT

    # 2. YAML overrides default
    path = tmp_path / "config.yml"
    ExporterConfig(port=7000).save(path)
    from_yaml = ExporterConfig.from_file(path)
    assert from_yaml.port == 7000

    # 3. "env"-resolved value overrides YAML (simulated: Typer/Click already
    # resolved env -> the value passed to merge_overrides)
    from_env = from_yaml.merge_overrides(port=7100)
    assert from_env.port == 7100

    # 4. CLI-resolved value overrides the env-resolved value
    from_cli = from_env.merge_overrides(port=7200)
    assert from_cli.port == 7200


# ---------------------------------------------------------------------------
# CLI env-var walk (D15)
# ---------------------------------------------------------------------------


def _iter_click_options() -> list[tuple[str, click.Option]]:
    click_app = typer.main.get_command(app)
    assert isinstance(click_app, click.Group)
    results = []
    for command_name, command in click_app.commands.items():
        for param in command.params:
            if isinstance(param, click.Option):
                results.append((command_name, param))
    return results


def test_every_option_of_every_command_has_an_envvar() -> None:
    for command_name, option in _iter_click_options():
        assert option.envvar, f"{command_name} option {option.opts} has no envvar"


def test_every_option_envvar_matches_the_derived_name() -> None:
    """The declared envvar must equal envvar_name(<primary long flag>).

    A `probe` command (owned by a sibling agent) is allowed to use its own
    `EERO_EXPORTER_PROBE_*` prefix when present.
    """
    for command_name, option in _iter_click_options():
        long_opt = next((o for o in option.opts if o.startswith("--")), option.opts[0])
        expected = envvar_name(long_opt)
        actual = option.envvar
        if command_name == "probe" and isinstance(actual, str):
            if actual.startswith("EERO_EXPORTER_PROBE_"):
                continue
        assert (
            actual == expected
        ), f"{command_name} {long_opt}: envvar {actual!r} != expected {expected!r}"


def test_every_option_shows_envvar_in_help() -> None:
    for _command_name, option in _iter_click_options():
        assert option.show_envvar is True


# ---------------------------------------------------------------------------
# boolean env-var string parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("false", False),
        ("False", False),
        ("0", False),
    ],
)
def test_boolean_flag_parses_common_truthy_falsy_env_strings(
    monkeypatch: pytest.MonkeyPatch, env_value: str, expected: bool
) -> None:
    from typer.testing import CliRunner

    from eero_exporter.config import envvar_name as _env

    monkeypatch.setenv(_env("--include-devices"), env_value)
    # Use `serve --help`'s underlying param resolution indirectly via a
    # minimal click Context to avoid needing a full session/server setup:
    click_app = typer.main.get_command(app)
    assert isinstance(click_app, click.Group)
    serve_cmd = click_app.commands["serve"]
    ctx = serve_cmd.make_context("serve", [], resilient_parsing=True)
    assert ctx.params["include_devices"] is expected

    # CliRunner import kept to ensure this module's fixture style matches
    # the rest of the suite (str usage below silences an unused-import
    # warning if the direct check above is ever removed).
    assert CliRunner is not None


# ---------------------------------------------------------------------------
# describe_options()
# ---------------------------------------------------------------------------


def test_describe_options_lists_every_typer_option() -> None:
    described = list(describe_options())
    expected_count = len(_iter_click_options())
    assert len(described) == expected_count


def test_describe_options_includes_session_file_for_every_relevant_command() -> None:
    described = list(describe_options())
    commands_with_session_file = {row.command for row in described if row.flag == "--session-file"}
    assert commands_with_session_file >= {
        "login",
        "logout",
        "validate",
        "status",
        "test",
        "serve",
        "session-info",
    }


def test_describe_options_env_var_matches_helper() -> None:
    for row in describe_options():
        assert row.env_var == envvar_name(row.flag) or row.env_var.startswith(
            "EERO_EXPORTER_PROBE_"
        )
