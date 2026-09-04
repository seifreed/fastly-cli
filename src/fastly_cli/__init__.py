"""Fastly multi-account client library."""

from fastly_cli.accounts import AccountConfig, ConfigError
from fastly_cli.catalog import Operation, find_operations, get_operation
from fastly_cli.client import ApiResponse, FastlyClient, FastlyMultiClient
from fastly_cli.config import load_config, select_accounts
from fastly_cli.request import RequestOptions
from fastly_cli.toon import to_toon

__all__ = [
    "AccountConfig",
    "ApiResponse",
    "ConfigError",
    "FastlyClient",
    "FastlyMultiClient",
    "Operation",
    "RequestOptions",
    "find_operations",
    "get_operation",
    "load_config",
    "select_accounts",
    "to_toon",
]

__version__ = "0.1.0"
