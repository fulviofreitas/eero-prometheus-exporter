#!/usr/bin/env python3
"""Thin wrapper so ``python scripts/probe_api.py`` == ``eero-exporter probe``.

All logic lives in :mod:`eero_exporter.probe`; this file only forwards its
arguments to the ``probe`` subcommand of the installed CLI. Useful in a
scratch venv where the console script is not on ``PATH``.

Example:
    python scripts/probe_api.py --session-file /tmp/session.json --out ./probes
"""

from __future__ import annotations

import sys

from eero_exporter.cli import app


def main() -> None:
    """Invoke the ``probe`` subcommand with this process's arguments."""
    app(args=["probe", *sys.argv[1:]])


if __name__ == "__main__":
    main()
