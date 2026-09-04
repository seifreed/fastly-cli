"""Minimal TOON encoder for JSON-compatible API responses."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_NUMBER = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")
_STRUCTURAL = set("[]{}:")


def _number(value: float) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("TOON cannot encode non-finite numbers")
    if isinstance(value, float):
        if value == 0:
            return "0"
        text = str(value)
        if "e" in text.lower():
            return format(Decimal(text), "f")
        return text
    return str(value)


def _string(value: str) -> str:
    if _safe_unquoted(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    raise TypeError(f"not a TOON scalar: {type(value).__name__}")


def _key(value: str) -> str:
    return value if _KEY.fullmatch(value) else json.dumps(value, ensure_ascii=False)


def _safe_unquoted(value: str) -> bool:
    return bool(
        value
        and value == value.strip()
        and value not in {"true", "false", "null"}
        and not _NUMBER.fullmatch(value)
        and not value.startswith("-")
        and not value.startswith("#")
        and not any(character in value for character in _STRUCTURAL)
        and not any(ord(character) < 0x20 for character in value)
        and not any(character in value for character in '"\\')
        and "," not in value
    )


def _uniform_rows(value: Sequence[Any]) -> tuple[list[str], list[list[Any]]] | None:
    if (
        not value
        or not all(isinstance(item, Mapping) for item in value)
        or any(not item for item in value)
    ):
        return None
    first = list(value[0].keys())
    if any(set(item.keys()) != set(first) for item in value):
        return None
    rows = [[item[field] for field in first] for item in value]
    if any(
        any(isinstance(cell, (Mapping, list, tuple)) for cell in row) for row in rows
    ):
        return None
    return first, rows


def _encode_mapping(value: Mapping[Any, Any], depth: int) -> list[str]:
    indent = "  " * depth
    lines: list[str] = []
    for key, item in value.items():
        encoded_key = _key(str(key))
        if isinstance(item, (Mapping, list, tuple)):
            if isinstance(item, (list, tuple)):
                lines.extend(_encode_value(item, encoded_key, depth))
            else:
                lines.append(f"{indent}{encoded_key}:")
                lines.extend(_encode_value(item, encoded_key, depth + 1))
        else:
            lines.append(f"{indent}{encoded_key}: {_scalar(item)}")
    return lines


def _encode_sequence(value: Sequence[Any], prefix: str, depth: int) -> list[str]:
    indent = "  " * depth
    if not value:
        return [f"{indent}{prefix + ': ' if prefix else ''}[]"]
    rows = _uniform_rows(value)
    header = f"{indent}{prefix}[{len(value)}]"
    if rows is not None:
        fields, data_rows = rows
        lines = [f"{header}{{{','.join(_key(field) for field in fields)}}}:"]
        lines.extend(
            f"{'  ' * (depth + 1)}{','.join(_scalar(cell) for cell in row)}"
            for row in data_rows
        )
        return lines
    if value and all(isinstance(item, (list, tuple)) for item in value):
        return _encode_array_of_arrays(value, header, depth)
    if all(not isinstance(item, (Mapping, list, tuple)) for item in value):
        values = ",".join(_scalar(item) for item in value)
        return [f"{header}: {values}" if value else f"{header}:"]
    lines = [f"{header}:"]
    for item in value:
        item_indent = "  " * (depth + 1)
        if isinstance(item, Mapping):
            lines.extend(_encode_mapping_item(item, item_indent, depth + 1))
        elif isinstance(item, (list, tuple)):
            lines.extend(_encode_list_item(item, item_indent, depth + 1))
        else:
            lines.append(f"{item_indent}- {_scalar(item)}")
    return lines


def _encode_value(value: Any, prefix: str, depth: int) -> list[str]:
    if isinstance(value, Mapping):
        return _encode_mapping(value, depth)
    if isinstance(value, (list, tuple)):
        return _encode_sequence(value, prefix, depth)
    return [f"{'  ' * depth}{_scalar(value)}"]


def _encode_array_of_arrays(value: Sequence[Any], header: str, depth: int) -> list[str]:
    lines = [f"{header}:"]
    for item in value:
        item_indent = "  " * (depth + 1)
        if all(not isinstance(cell, (Mapping, list, tuple)) for cell in item):
            lines.append(
                f"{item_indent}- [{len(item)}]: {','.join(_scalar(cell) for cell in item)}"
                if item
                else f"{item_indent}- [0]:"
            )
        else:
            lines.extend(_encode_list_item(item, item_indent, depth + 1))
    return lines


def _encode_mapping_item(
    value: Mapping[Any, Any], indent: str, depth: int
) -> list[str]:
    items = list(value.items())
    if not items:
        return [f"{indent}-"]
    first_key, first_value = items[0]
    key = _key(str(first_key))
    if isinstance(first_value, (list, tuple)):
        encoded = _encode_value(first_value, key, depth)
        lines = [f"{indent}- {encoded[0][len(indent):]}", *encoded[1:]]
    elif not isinstance(first_value, Mapping):
        lines = [f"{indent}- {key}: {_scalar(first_value)}"]
    else:
        lines = [f"{indent}- {key}:"]
        lines.extend(_encode_value(first_value, key, depth + 2))
    for item_key, item_value in items[1:]:
        lines.extend(_encode_value({item_key: item_value}, "", depth + 1))
    return lines


def _encode_list_item(value: Sequence[Any], indent: str, depth: int) -> list[str]:
    header = f"{indent}- [{len(value)}]:"
    if value and all(not isinstance(item, (Mapping, list, tuple)) for item in value):
        return [
            f"{indent}- [{len(value)}]: {','.join(_scalar(item) for item in value)}"
        ]
    lines = [header]
    for item in value:
        item_indent = "  " * (depth + 1)
        if isinstance(item, Mapping):
            lines.extend(_encode_mapping_item(item, item_indent, depth + 1))
        elif isinstance(item, (list, tuple)):
            lines.extend(_encode_list_item(item, item_indent, depth + 1))
        else:
            lines.append(f"{item_indent}- {_scalar(item)}")
    return lines


def to_toon(value: Any) -> str:
    """Encode JSON-compatible data as TOON text with LF line endings."""
    return "\n".join(_encode_value(value, "", 0))
