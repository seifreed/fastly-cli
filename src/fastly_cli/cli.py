"""Command-line entry point for the multi-account client."""

from __future__ import annotations

import json
import sys

from fastly_cli.accounts import ConfigError
from fastly_cli.cli_commands import run
from fastly_cli.cli_parser import build_parser
from fastly_cli.client import FastlyError


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (
        ConfigError,
        FastlyError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(f"fastly: {error}", file=sys.stderr)
        return 2
    return 0
