"""Generated Fastly operation metadata used for CLI discovery."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Any


@dataclass(frozen=True, slots=True)
class Operation:
    """One operation from the pinned Fastly client catalog."""

    operation: str
    group: str
    method: str
    path: str
    parameters: tuple[str, ...]
    required: tuple[str, ...]
    base_url: str
    summary: str
    path_params_allow_reserved: tuple[str, ...]
    content_types: tuple[str, ...]
    accepts: tuple[str, ...]
    parameter_locations: tuple[tuple[str, str], ...]
    parameter_names: tuple[tuple[str, str], ...]

    @property
    def parameter_routes(self) -> dict[str, tuple[str, str]]:
        """Return each logical parameter's location and wire name."""
        wire_names = dict(self.parameter_names)
        return {
            name: (location, wire_names[name])
            for name, location in self.parameter_locations
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "group": self.group,
            "method": self.method,
            "path": self.path,
            "parameters": list(self.parameters),
            "required": list(self.required),
            "base_url": self.base_url,
            "summary": self.summary,
            "path_params_allow_reserved": list(self.path_params_allow_reserved),
            "content_types": list(self.content_types),
            "accepts": list(self.accepts),
            "parameter_locations": dict(self.parameter_locations),
            "parameter_names": dict(self.parameter_names),
        }


def _strings(item: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = item.get(key, [])
    if not isinstance(values, list):
        raise TypeError(f"catalog field {key!r} must be a string list")
    strings = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"catalog field {key!r} must be a string list")
        strings.append(value)
    return tuple(strings)


def _mapping_strings(
    item: Mapping[str, object], key: str
) -> tuple[tuple[str, str], ...]:
    value = item.get(key, {})
    if not isinstance(value, Mapping):
        raise TypeError(f"catalog field {key!r} must be a string map")
    entries: list[tuple[str, str]] = []
    for name, mapped_name in value.items():
        if not isinstance(name, str) or not isinstance(mapped_name, str):
            raise TypeError(f"catalog field {key!r} must be a string map")
        entries.append((name, mapped_name))
    return tuple(entries)


def _locations(item: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    locations = _mapping_strings(item, "parameter_locations")
    allowed = {"path", "query", "header", "form", "body"}
    for _, location in locations:
        if location not in allowed:
            raise ValueError("catalog field 'parameter_locations' must be a string map")
    return locations


def _operation(item: Mapping[str, object]) -> Operation:
    fields = ("operation", "group", "method", "path", "base_url", "summary")
    values: dict[str, str] = {}
    for field in fields:
        value = item.get(field)
        if not isinstance(value, str):
            raise TypeError("catalog operation has invalid string fields")
        values[field] = value
    return Operation(
        operation=values["operation"],
        group=values["group"],
        method=values["method"],
        path=values["path"],
        parameters=_strings(item, "parameters"),
        required=_strings(item, "required"),
        base_url=values["base_url"],
        summary=values["summary"],
        path_params_allow_reserved=_strings(item, "path_params_allow_reserved"),
        content_types=_strings(item, "content_types"),
        accepts=_strings(item, "accepts"),
        parameter_locations=_locations(item),
        parameter_names=_mapping_strings(item, "parameter_names"),
    )


def _load_operations() -> tuple[Operation, ...]:
    document = json.loads(
        files("fastly_cli").joinpath("api_catalog.json").read_text(encoding="utf-8")
    )
    return tuple(_operation(item) for item in document["operations"])


OPERATIONS = _load_operations()


def find_operations(
    query: str | None = None, method: str | None = None
) -> tuple[Operation, ...]:
    """Return catalog operations filtered by free text and HTTP method."""
    normalized_query = query.lower() if query else None
    normalized_method = method.upper() if method else None
    return tuple(
        operation
        for operation in OPERATIONS
        if (normalized_method is None or operation.method == normalized_method)
        and (
            normalized_query is None
            or normalized_query in operation.operation.lower()
            or normalized_query in operation.group.lower()
            or normalized_query in operation.path.lower()
            or normalized_query in operation.summary.lower()
        )
    )


def get_operation(name: str) -> Operation:
    """Return one operation by case-insensitive operation name."""
    normalized_name = name.lower()
    for operation in OPERATIONS:
        if operation.operation.lower() == normalized_name:
            return operation
    raise KeyError(name)
