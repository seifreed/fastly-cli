"""Immutable request values shared by application and transport layers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

JSON_NOT_SET = object()
MultipartValue = bytes | str | Path


def header_value(headers: Mapping[str, str], name: str) -> str:
    """Return a header value without depending on its capitalization."""
    normalized_name = name.lower()
    return next(
        (value for key, value in headers.items() if key.lower() == normalized_name),
        "",
    )


def has_header(headers: Mapping[str, str], name: str) -> bool:
    """Return whether a header exists without depending on its capitalization."""
    normalized_name = name.lower()
    return any(key.lower() == normalized_name for key in headers)


@dataclass(frozen=True, slots=True)
class RequestOptions:
    """Optional transport and payload values for one API request."""

    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None
    path_params: Mapping[str, Any] | None = None
    path_params_allow_reserved: Iterable[str] | None = None
    headers: Mapping[str, str] | None = None
    json_body: Any = JSON_NOT_SET
    body: bytes | str | None = None
    form: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None
    multipart: (
        Mapping[str, MultipartValue] | Iterable[tuple[str, MultipartValue]] | None
    ) = None
    allow_mutation: bool = False
