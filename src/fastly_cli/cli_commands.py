"""Application operations used by the Fastly command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastly_cli.accounts import AccountConfig, ConfigError
from fastly_cli.catalog import Operation, find_operations, get_operation
from fastly_cli.cli_parser import (
    _CATALOG_GROUPS,
    Parameter,
    RequestInputs,
    _body,
)
from fastly_cli.client import FastlyMultiClient
from fastly_cli.config import load_config, select_accounts
from fastly_cli.request import JSON_NOT_SET, RequestOptions, has_header
from fastly_cli.toon import to_toon


def render(value: Any, output_format: str) -> str:
    if output_format == "toon":
        return to_toon(value)
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write(value: Any, output_format: str, output: Path | None) -> None:
    rendered = render(value, output_format)
    if output:
        output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(rendered)


def _is_default_base_url(base_url: str) -> bool:
    parsed = urlsplit(base_url)
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname is not None
        and parsed.hostname.lower() == "api.fastly.com"
        and parsed.port in {None, 443}
        and parsed.path in {"", "/"}
    )


def accounts_for_operation(
    accounts: list[AccountConfig], operation_base_url: str
) -> list[AccountConfig]:
    return [
        (
            account
            if not _is_default_base_url(account.base_url)
            else replace(account, base_url=operation_base_url)
        )
        for account in accounts
    ]


def apply_operation_params(
    operation: Operation,
    values: list[tuple[str, str]],
    request: RequestInputs,
) -> None:
    routes = operation.parameter_routes
    targets = {
        "path": request.path_params,
        "query": request.query_params,
        "header": request.headers,
        "form": request.form,
    }
    for name, value in values:
        route = routes.get(name)
        if route is None:
            raise ConfigError(f"unknown parameter for {operation.operation}: {name}")
        location, wire_name = route
        if location == "body":
            raise ConfigError(
                f"{name} is a body parameter; use --json, --body-file, or --multipart"
            )
        targets[location].append((wire_name, value))


def validate_required_parameters(
    operation: Operation, request: RequestInputs, values: list[Parameter]
) -> None:
    routes = operation.parameter_routes
    provided = {name for name, _ in values}
    for parameters in (
        request.path_params,
        request.query_params,
        request.headers,
        request.form,
    ):
        provided.update(name for name, _ in parameters)
    missing = [
        name
        for name in operation.required
        if routes[name][0] != "body"
        and name not in provided
        and routes[name][1] not in provided
    ]
    body_required = any(routes[name][0] == "body" for name in operation.required)
    if body_required and not request.has_body():
        missing.extend(name for name in operation.required if routes[name][0] == "body")
    if missing:
        raise ConfigError(
            f"missing required parameter(s) for {operation.operation}: "
            + ", ".join(dict.fromkeys(missing))
        )


def request_inputs(
    args: argparse.Namespace, operation: Operation | None
) -> RequestInputs:
    if args.body_file and args.json_body is not JSON_NOT_SET:
        raise ConfigError("--json and --body-file are mutually exclusive")
    request = RequestInputs(
        path_params=list(args.path_param or []),
        query_params=list(args.query or []),
        headers=list(args.header or []),
        form=list(args.form or []),
        multipart=args.multipart,
        json_body=args.json_body,
        body=args.body_file.read_bytes() if args.body_file else None,
    )
    values = list(getattr(args, "param", None) or [])
    if operation is not None:
        for name in operation.parameters:
            value = getattr(args, f"_operation_{name}", None)
            if value is None:
                continue
            if operation.parameter_routes[name][0] == "body":
                if request.has_body():
                    raise ConfigError(
                        "named body parameters cannot be combined with a body option"
                    )
                request.json_body = _body(value)
            else:
                values.append((name, value))
        apply_operation_params(operation, values, request)
        validate_required_parameters(operation, request, values)
    return request


def request_headers(
    operation: Operation | None, request: RequestInputs
) -> dict[str, str]:
    headers = dict(request.headers)
    if operation and operation.accepts and not has_header(headers, "accept"):
        headers["Accept"] = operation.accepts[0]
    if (
        operation
        and request.has_body()
        and operation.content_types
        and request.multipart is None
        and not has_header(headers, "content-type")
    ):
        headers["Content-Type"] = operation.content_types[0]
    return headers


def operation_or_error(name: str) -> Operation:
    try:
        return get_operation(name)
    except KeyError as error:
        raise ConfigError(f"unknown operation: {name}") from error


def run(args: argparse.Namespace) -> None:
    operation: Operation | None = None
    operation_base_url: str | None = None
    operation_reserved: tuple[str, ...] = ()
    if args.command == "api":
        if args.api_command == "list":
            operation_data: Any = {
                "operations": [
                    operation.as_dict()
                    for operation in find_operations(args.query, args.method)
                ]
            }
            write(operation_data, args.format, args.output)
            return
        if args.api_command == "describe":
            operation_data = operation_or_error(args.operation).as_dict()
            write(operation_data, args.format, args.output)
            return
        operation = operation_or_error(args.operation)
        method = operation.method
        path = operation.path
        operation_base_url = operation.base_url
        operation_reserved = operation.path_params_allow_reserved
    elif args.command == "accounts":
        accounts = load_config(args.config)
        list_all = args.all_accounts or not args.accounts
        account_data = {
            "accounts": [
                {"name": account.name, "base_url": account.base_url}
                for account in select_accounts(accounts, args.accounts, list_all)
            ]
        }
        write(account_data, args.format, args.output)
        return
    elif args.command in dict(_CATALOG_GROUPS):
        operation = operation_or_error(args.catalog_operation)
        method = operation.method
        path = operation.path
        operation_base_url = operation.base_url
        operation_reserved = operation.path_params_allow_reserved
    else:
        method = args.method
        path = args.path
    accounts = load_config(args.config)
    selected = select_accounts(accounts, args.accounts, args.all_accounts)
    if operation_base_url is not None:
        selected = accounts_for_operation(selected, operation_base_url)
    request = request_inputs(args, operation)
    result = FastlyMultiClient(selected).request(
        method,
        path,
        RequestOptions(
            params=request.query_params or None,
            path_params=dict(request.path_params),
            path_params_allow_reserved=operation_reserved,
            headers=request_headers(operation, request),
            json_body=request.json_body,
            body=request.body,
            form=request.form or None,
            multipart=request.multipart,
            allow_mutation=args.allow_mutation,
        ),
    )
    value: Any = (
        result[0].as_dict() if len(result) == 1 else [item.as_dict() for item in result]
    )
    write(value, args.format, args.output)
