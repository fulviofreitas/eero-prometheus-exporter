#!/usr/bin/env python3
"""Render the option tables inside ``wiki/Configuration.md`` from the CLI tree.

The block between ``<!-- BEGIN GENERATED: options -->`` and
``<!-- END GENERATED: options -->`` is produced from
:func:`eero_exporter.cli.describe_options`, which walks the real Typer command
tree, so every flag, environment variable, YAML key, default and help string
comes from the code. The prose around the block is hand-written.
``tests/test_metrics_doc.py`` asserts the committed block equals this
script's output.

Usage::

    uv run python scripts/gen_config_doc.py            # rewrite the block in place
    uv run python scripts/gen_config_doc.py --stdout   # print the block only
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

from eero_exporter.cli import describe_options
from eero_exporter.config import DEFAULT_CONFIG_FILE, ExporterConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = REPO_ROOT / "wiki" / "Configuration.md"
BEGIN_MARKER = "<!-- BEGIN GENERATED: options -->"
END_MARKER = "<!-- END GENERATED: options -->"

#: Options whose YAML key is not derivable from the flag name.
_YAML_KEY_OVERRIDES: dict[tuple[str, str], str | None] = {
    ("serve", "--interval"): "collection_interval",
    # Not a config value: it names the config file itself.
    ("serve", "--config-file"): None,
}

#: Defaults that live outside ``ExporterConfig``.
_EXTRA_DEFAULTS: dict[tuple[str, str], Any] = {
    ("serve", "--config-file"): DEFAULT_CONFIG_FILE,
}

_COMMAND_ORDER = (
    "serve",
    "login",
    "logout",
    "validate",
    "status",
    "test",
    "session-info",
    "probe",
)


def _config_defaults() -> dict[str, Any]:
    cfg = ExporterConfig()
    return {f.name: getattr(cfg, f.name) for f in fields(cfg)}


def _home_relative(path: Path) -> str:
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return path.as_posix()


def _fmt_default(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    if isinstance(value, Path):
        return f"`{_home_relative(value)}`"
    if isinstance(value, list | tuple):
        return f"`{','.join(str(v) for v in value)}`"
    return f"`{value}`"


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def render_block() -> str:
    """Render the generated block, markers included."""
    config_defaults = _config_defaults()
    by_command: dict[str, list[Any]] = {}
    for option in describe_options():
        by_command.setdefault(option.command, []).append(option)

    unknown = set(by_command) - set(_COMMAND_ORDER)
    if unknown:
        raise SystemExit(f"_COMMAND_ORDER lacks commands: {sorted(unknown)}")

    out: list[str] = [BEGIN_MARKER, ""]
    for command in _COMMAND_ORDER:
        options = by_command.get(command)
        if not options:
            continue
        out.append(f"### `eero-exporter {command}`")
        out.append("")
        out.append("| Flag | Environment variable | YAML key | Default | Description |")
        out.append("|---|---|---|---|---|")
        for option in options:
            key = (command, option.flag)
            yaml_key = _YAML_KEY_OVERRIDES.get(key, option.yaml_key)
            default = option.default
            if default is None and key in _EXTRA_DEFAULTS:
                default = _EXTRA_DEFAULTS[key]
            elif default is None and yaml_key in config_defaults:
                default = config_defaults[yaml_key]
            yaml_cell = f"`{yaml_key}`" if yaml_key and command == "serve" else "-"
            out.append(
                f"| `{option.flag}` | `{option.env_var}` | {yaml_cell} | "
                f"{_fmt_default(default)} | {_escape(option.help)} |"
            )
        out.append("")
    out.append(END_MARKER)
    return "\n".join(out)


def replace_block(text: str, block: str) -> str:
    """Return ``text`` with the marker-delimited block replaced by ``block``."""
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER) + len(END_MARKER)
    return text[:start] + block + text[end:]


def extract_block(text: str) -> str:
    """Return the marker-delimited block currently in ``text``."""
    start = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER) + len(END_MARKER)
    return text[start:end]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true", help="print the block only")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args(argv)

    block = render_block()
    if args.stdout:
        sys.stdout.write(block + "\n")
        return 0
    text = args.target.read_text(encoding="utf-8")
    args.target.write_text(replace_block(text, block), encoding="utf-8")
    print(f"updated {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
