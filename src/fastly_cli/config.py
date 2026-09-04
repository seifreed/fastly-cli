"""Account configuration loaded from TOML and environment variables."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path

from fastly_cli.accounts import DEFAULT_BASE_URL, AccountConfig, ConfigError

TOKEN_ENV_NAMES = ("FASTLY", "FASTLY_API_TOKEN", "FASTLY_API_KEY")


def _account_from_mapping(name: str, values: Mapping[str, object]) -> AccountConfig:
    token = values.get("token")
    base_url = values.get("base_url", DEFAULT_BASE_URL)
    timeout = values.get("timeout", 30.0)
    if not isinstance(token, str):
        raise ConfigError(f"account {name!r} must define a string token")
    if not isinstance(base_url, str):
        raise ConfigError(f"account {name!r} base_url must be a string")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise ConfigError(f"account {name!r} timeout must be numeric")
    return AccountConfig(name, token, base_url, float(timeout))


def _environment_account(env: Mapping[str, str]) -> AccountConfig | None:
    for variable in TOKEN_ENV_NAMES:
        token = env.get(variable)
        if token:
            return AccountConfig("default", token)
    return None


def load_config(
    path: str | Path | None = None, env: Mapping[str, str] | None = None
) -> dict[str, AccountConfig]:
    """Load accounts from TOML, falling back to the supported token variables."""
    environment = os.environ if env is None else env
    config_path = path or environment.get("FASTLY_CONFIG")
    accounts: dict[str, AccountConfig] = {}
    if config_path:
        with Path(config_path).expanduser().open("rb") as config_file:
            raw = tomllib.load(config_file)
        raw_accounts = raw.get("accounts", {})
        if not isinstance(raw_accounts, dict):
            raise ConfigError("[accounts] must be a TOML table")
        for name, values in raw_accounts.items():
            if not isinstance(name, str) or not isinstance(values, dict):
                raise ConfigError("each account must be a TOML table")
            accounts[name] = _account_from_mapping(name, values)
        if "token" in raw and "default" not in accounts:
            accounts["default"] = _account_from_mapping("default", raw)
    environment_account = _environment_account(environment)
    if environment_account is not None and not accounts:
        accounts["default"] = environment_account
    return accounts


def select_accounts(
    accounts: Mapping[str, AccountConfig],
    names: list[str] | None = None,
    all_accounts: bool = False,
) -> list[AccountConfig]:
    """Resolve one account, all accounts, or the sole configured account."""
    if all_accounts and names:
        raise ConfigError("--all cannot be combined with --account")
    if all_accounts:
        selected = list(accounts.values())
    elif names:
        missing = [name for name in names if name not in accounts]
        if missing:
            raise ConfigError(f"unknown account(s): {', '.join(missing)}")
        selected = [accounts[name] for name in names]
    elif "default" in accounts:
        selected = [accounts["default"]]
    elif len(accounts) == 1:
        selected = list(accounts.values())
    else:
        selected = []
    if not selected:
        raise ConfigError("no account selected; configure one or use --account/--all")
    return selected
