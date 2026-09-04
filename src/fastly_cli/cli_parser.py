"""Argument parsing for the Fastly command-line interface."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastly_cli.catalog import Operation, find_operations
from fastly_cli.request import JSON_NOT_SET

Parameter = tuple[str, str]


def _command_name(value: str) -> str:
    value = value.removesuffix("Api")
    return re.sub(r"(?<!^)(?=[A-Z])", "-", value).replace("_", "-").lower()


def _catalog_groups() -> tuple[tuple[str, tuple[Operation, ...]], ...]:
    grouped: dict[str, list[Operation]] = {}
    for operation in find_operations():
        grouped.setdefault(_command_name(operation.group), []).append(operation)
    return tuple(
        (
            name,
            tuple(sorted(operations, key=lambda item: _command_name(item.operation))),
        )
        for name, operations in sorted(grouped.items())
    )


_CATALOG_GROUPS = _catalog_groups()


@dataclass(slots=True)
class RequestInputs:
    """Command-line values grouped by the HTTP channel they target."""

    path_params: list[Parameter] = field(default_factory=list)
    query_params: list[Parameter] = field(default_factory=list)
    headers: list[Parameter] = field(default_factory=list)
    form: list[Parameter] = field(default_factory=list)
    multipart: list[tuple[str, str | Path]] | None = None
    json_body: Any = JSON_NOT_SET
    body: bytes | None = None

    def has_body(self) -> bool:
        return (
            self.json_body is not JSON_NOT_SET
            or self.body is not None
            or bool(self.form)
            or self.multipart is not None
        )


def _pair(value: str, label: str) -> tuple[str, str]:
    key, separator, item = value.partition("=")
    if not separator or not key:
        raise argparse.ArgumentTypeError(f"{label} must use KEY=VALUE")
    return key, item


def _multipart_pair(value: str) -> tuple[str, str | Path]:
    key, item = _pair(value, "multipart")
    return key, Path(item[1:]) if item.startswith("@") else item


def _body(value: str) -> Any:
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
    return json.loads(value)


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("json", "toon"), default=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=argparse.SUPPRESS)


def _add_request_options(parser: argparse.ArgumentParser, target: bool) -> None:
    if target:
        parser.add_argument("method")
        parser.add_argument("path")
    _add_output_options(parser)
    parser.add_argument(
        "--query", action="append", type=lambda value: _pair(value, "query")
    )
    parser.add_argument(
        "--path-param", action="append", type=lambda value: _pair(value, "path-param")
    )
    parser.add_argument(
        "--header", action="append", type=lambda value: _pair(value, "header")
    )
    parser.add_argument(
        "--form", action="append", type=lambda value: _pair(value, "form")
    )
    parser.add_argument("--multipart", action="append", type=_multipart_pair)
    parser.add_argument("--json", dest="json_body", type=_body, default=JSON_NOT_SET)
    parser.add_argument("--body-file", type=Path)
    parser.add_argument("--allow-mutation", action="store_true")


def _operation_parameter_flag(name: str) -> str:
    flag = name.replace("_", "-")
    return f"--api-{flag}" if flag in {"format", "query"} else f"--{flag}"


def _add_operation_parameters(
    parser: argparse.ArgumentParser, operation: Operation | None = None
) -> None:
    names = (
        operation.parameters
        if operation is not None
        else sorted({name for item in find_operations() for name in item.parameters})
    )
    for name in names:
        parser.add_argument(
            _operation_parameter_flag(name),
            dest=f"_operation_{name}",
        )


def _add_catalog_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    for group_name, operations in _CATALOG_GROUPS:
        group = commands.add_parser(
            group_name,
            help=f"{group_name.replace('-', ' ').capitalize()} API endpoints.",
        )
        operation_commands = group.add_subparsers(
            dest="catalog_operation_command", required=True
        )
        for operation in operations:
            endpoint = operation_commands.add_parser(
                _command_name(operation.operation), help=operation.summary
            )
            endpoint.set_defaults(catalog_operation=operation.operation)
            _add_request_options(endpoint, target=False)
            _add_operation_parameters(endpoint, operation)
            endpoint.add_argument(
                "--param", action="append", type=lambda value: _pair(value, "param")
            )


def build_parser() -> argparse.ArgumentParser:
    """Build the complete CLI parser from the API catalog."""
    parser = argparse.ArgumentParser(prog="fastly")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--account", action="append", dest="accounts")
    parser.add_argument("--all", action="store_true", dest="all_accounts")
    parser.add_argument("--format", choices=("json", "toon"), default="json")
    parser.add_argument("--output", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    accounts = commands.add_parser("accounts")
    accounts_list = accounts.add_subparsers(
        dest="accounts_command", required=True
    ).add_parser("list")
    _add_output_options(accounts_list)
    api = commands.add_parser("api")
    api_commands = api.add_subparsers(dest="api_command", required=True)
    api_list = api_commands.add_parser("list")
    api_list.add_argument("query", nargs="?")
    api_list.add_argument("--method")
    _add_output_options(api_list)
    api_describe = api_commands.add_parser("describe")
    api_describe.add_argument("operation")
    _add_output_options(api_describe)
    api_call = api_commands.add_parser("call")
    api_call.add_argument("operation")
    _add_request_options(api_call, target=False)
    _add_operation_parameters(api_call)
    api_call.add_argument(
        "--param", action="append", type=lambda value: _pair(value, "param")
    )
    request = commands.add_parser("request")
    _add_request_options(request, target=True)
    _add_catalog_commands(commands)
    return parser


_parser = build_parser
