"""Generated documentation must match the code it is generated from.

``wiki/Metrics.md`` is rendered by ``scripts/gen_metrics_doc.py`` from the
metrics registry, and the option tables in ``wiki/Configuration.md`` are
rendered by ``scripts/gen_config_doc.py`` from the Typer command tree. These
tests fail when either page drifts from the code, so CI forces a regeneration
whenever a metric, flag, env var or default changes.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from eero_exporter import metrics as m
from eero_exporter.cli import describe_options

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
METRICS_PAGE = REPO_ROOT / "wiki" / "Metrics.md"
CONFIG_PAGE = REPO_ROOT / "wiki" / "Configuration.md"

REGENERATE_HINT = "regenerate with: uv run python scripts/{script}"


def _load_script(name: str) -> ModuleType:
    """Import a ``scripts/*.py`` file as a module without a package."""
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen_metrics_doc() -> ModuleType:
    return _load_script("gen_metrics_doc.py")


@pytest.fixture(scope="module")
def gen_config_doc() -> ModuleType:
    return _load_script("gen_config_doc.py")


class TestMetricsPage:
    def test_committed_page_matches_generator_output(self, gen_metrics_doc: ModuleType) -> None:
        expected = gen_metrics_doc.render()
        actual = METRICS_PAGE.read_text(encoding="utf-8")
        assert actual == expected, REGENERATE_HINT.format(script="gen_metrics_doc.py")

    def test_every_registry_metric_is_documented(self) -> None:
        page = METRICS_PAGE.read_text(encoding="utf-8")
        missing = [p.name for p in m.describe_metrics() if f"| `{p.name}` |" not in page]
        assert not missing, f"metrics missing from wiki/Metrics.md: {missing}"

    def test_every_removed_metric_is_in_the_appendix(self) -> None:
        page = METRICS_PAGE.read_text(encoding="utf-8")
        appendix = page[page.index("## Removed in 4.0.0") :]
        missing = sorted(name for name in m.REMOVED_IN_4_0_0 if f"| `{name}` |" not in appendix)
        assert not missing, f"removed metrics missing from the appendix: {missing}"

    def test_every_status_value_is_documented(self) -> None:
        page = METRICS_PAGE.read_text(encoding="utf-8")
        missing = sorted(status for status in m.API_STATUS_VALUES if f"| `{status}` |" not in page)
        assert not missing

    def test_declared_metric_count_is_stated(self) -> None:
        page = METRICS_PAGE.read_text(encoding="utf-8")
        assert f"**{len(m.describe_metrics())} metrics**" in page

    def test_generator_metadata_covers_the_registry(self, gen_metrics_doc: ModuleType) -> None:
        # render() raises SystemExit when a family/tier/status/removed name is
        # unmapped; calling it directly makes the failure mode explicit.
        gen_metrics_doc.render()
        assert set(m.FAMILY_TIER.values()) <= set(gen_metrics_doc.TIER_TABLE)
        assert {p.family for p in m.describe_metrics()} <= set(gen_metrics_doc.FAMILY_TITLES)


class TestConfigurationPage:
    def test_committed_block_matches_generator_output(self, gen_config_doc: ModuleType) -> None:
        text = CONFIG_PAGE.read_text(encoding="utf-8")
        actual = gen_config_doc.extract_block(text)
        expected = gen_config_doc.render_block()
        assert actual == expected, REGENERATE_HINT.format(script="gen_config_doc.py")

    def test_every_option_and_env_var_is_documented(self) -> None:
        page = CONFIG_PAGE.read_text(encoding="utf-8")
        for option in describe_options():
            assert f"`{option.flag}`" in page, option
            assert f"`{option.env_var}`" in page, option

    def test_no_home_directory_leaks_into_the_page(self) -> None:
        page = CONFIG_PAGE.read_text(encoding="utf-8")
        assert str(Path.home()) not in page

    def test_legacy_speed_test_options_are_gone(self) -> None:
        page = CONFIG_PAGE.read_text(encoding="utf-8")
        assert "include_speed_test" not in page
        assert "speed_test_interval" not in page
