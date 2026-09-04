"""Small, dependency-free Fastly REST clients."""

from __future__ import annotations

import base64
import http.client
import json
import re
import ssl
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from http import HTTPStatus
from pathlib import Path
from secrets import token_hex
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlsplit

from fastly_cli.accounts import AccountConfig
from fastly_cli.request import (
    JSON_NOT_SET,
    MultipartValue,
    RequestOptions,
    has_header,
    header_value,
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class FastlyError(RuntimeError):
    """Base error for client failures."""


class FastlyMutationError(FastlyError):
    """Raised when a mutating method is not explicitly enabled."""


class FastlyTransportError(FastlyError):
    """Raised when an HTTP request cannot reach its endpoint."""


class FastlyHTTPError(FastlyError):
    """Raised for a non-successful Fastly response."""

    def __init__(self, account: str, status: int, data: Any) -> None:
        self.account = account
        self.status = status
        self.data = data
        super().__init__(f"{account}: HTTP {status}")


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """Decoded response returned by the REST API."""

    account: str
    status: int
    headers: dict[str, str]
    data: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "status": self.status,
            "headers": self.headers,
            "data": self.data,
        }


@dataclass(frozen=True, slots=True)
class _HttpRequest:
    """Resolved values required by the concrete HTTP transport."""

    account: AccountConfig
    method: str
    path: str
    payload: bytes | None
    headers: Mapping[str, str]
    host: str
    scheme: str
    port: int | None


def _binary_data(raw: bytes) -> dict[str, str]:
    return {"base64": base64.b64encode(raw).decode("ascii")}


def _decode_body(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    if content_type.lower().split(";", 1)[0].strip() == "application/octet-stream":
        return _binary_data(raw)
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return _binary_data(raw)
    return text


def _pairs(
    value: Mapping[str, Any] | Iterable[tuple[str, Any]],
) -> list[tuple[str, Any]]:
    return list(value.items()) if isinstance(value, Mapping) else list(value)


def _request_body(
    json_body: Any,
    body: bytes | str | None,
    form: Mapping[str, Any] | Iterable[tuple[str, Any]] | None,
    multipart: (
        Mapping[str, MultipartValue] | Iterable[tuple[str, MultipartValue]] | None
    ) = None,
) -> tuple[bytes | None, str | None]:
    if (
        sum(
            (
                json_body is not JSON_NOT_SET,
                body is not None,
                form is not None,
                multipart is not None,
            )
        )
        > 1
    ):
        raise ValueError("request bodies are mutually exclusive")
    if json_body is not JSON_NOT_SET:
        return (
            json.dumps(json_body, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
    if body is None:
        if multipart is not None:
            return _multipart_body(multipart)
        if form is None:
            return None, None
        values = _pairs(form)
        return (
            urlencode(values, doseq=True).encode("utf-8"),
            "application/x-www-form-urlencoded",
        )
    return (body.encode("utf-8") if isinstance(body, str) else body), None


def _multipart_body(
    values: Mapping[str, MultipartValue] | Iterable[tuple[str, MultipartValue]],
) -> tuple[bytes, str]:
    boundary = f"----fastly-{token_hex(16)}"
    parts: list[bytes] = []
    items = _pairs(values)
    for name, value in items:
        if any(character in name for character in '"\r\n'):
            raise ValueError("multipart field names cannot contain quotes or newlines")
        filename: str | None = None
        if isinstance(value, Path):
            filename = value.name
            if any(character in filename for character in '"\r\n'):
                raise ValueError(
                    "multipart filenames cannot contain quotes or newlines"
                )
            payload = value.read_bytes()
        elif isinstance(value, bytes):
            payload = value
            filename = name
        else:
            payload = value.encode("utf-8")
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        parts.append(f"--{boundary}\r\n{disposition}\r\n".encode())
        if filename is not None:
            parts.append(b"Content-Type: application/octet-stream\r\n")
        parts.append(b"\r\n")
        parts.append(payload)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _replace_path_params(
    path: str,
    path_params: Mapping[str, Any] | None,
    path_params_allow_reserved: Iterable[str] | None = None,
) -> str:
    reserved = set(path_params_allow_reserved or ())
    if path_params:
        for name, value in path_params.items():
            placeholder = "{" + name + "}"
            if placeholder not in path:
                raise ValueError(f"path has no parameter {name!r}")
            safe = ":/?#[]@!$&'()*+,;=" if name in reserved else ""
            path = path.replace(placeholder, quote(str(value), safe=safe))
    missing = re.findall(r"\{([^{}]+)\}", path)
    if missing:
        raise ValueError(f"missing path parameter(s): {', '.join(missing)}")
    return path


def _path_for(
    base_url: str,
    path: str,
    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None,
    path_params: Mapping[str, Any] | None = None,
    path_params_allow_reserved: Iterable[str] | None = None,
) -> tuple[str, str, int | None, str]:
    base = urlsplit(base_url)
    resolved_path = _replace_path_params(path, path_params, path_params_allow_reserved)
    requested = urlsplit(resolved_path)
    if requested.scheme or requested.netloc or resolved_path.startswith("//"):
        raise ValueError("path must be relative to the configured base_url")
    request_path = requested.path or "/"
    base_path = base.path.rstrip("/")
    relative_path = request_path.lstrip("/")
    if relative_path:
        full_path = f"{base_path}/{relative_path}" if base_path else f"/{relative_path}"
    elif request_path == "/" and base_path:
        full_path = f"{base_path}/"
    else:
        full_path = base_path or "/"
    query = list(requested.query.split("&")) if requested.query else []
    if params:
        query.extend(urlencode(_pairs(params), doseq=True).split("&"))
    if query:
        full_path = f"{full_path}?{'&'.join(query)}"
    return base.hostname or "", base.scheme, base.port, full_path


def _connection_for(
    account: AccountConfig, host: str, scheme: str, port: int | None
) -> http.client.HTTPConnection:
    if scheme == "https":
        return http.client.HTTPSConnection(
            host,
            port=port,
            timeout=account.timeout,
            context=ssl.create_default_context(),
        )
    return http.client.HTTPConnection(host, port=port, timeout=account.timeout)


def _request_headers(
    account: AccountConfig,
    custom: Mapping[str, str] | None,
    body_type: str | None,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Fastly-Key": account.token,
        "User-Agent": "fastly-multiclient/0.1.0",
    }
    if custom:
        headers = {
            key: value for key, value in headers.items() if not has_header(custom, key)
        }
        headers.update(custom)
    if body_type and not has_header(headers, "content-type"):
        headers["Content-Type"] = body_type
    return headers


def _send_request(request: _HttpRequest) -> tuple[int, list[tuple[str, str]], bytes]:
    connection = _connection_for(
        request.account, request.host, request.scheme, request.port
    )
    try:
        connection.request(
            request.method,
            request.path,
            body=request.payload,
            headers=request.headers,
        )
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    except (OSError, URLError, TimeoutError) as error:
        raise FastlyTransportError(f"{request.account.name}: {error}") from error
    finally:
        connection.close()


def _reusable(value: Any) -> Any:
    if value is None or isinstance(value, Mapping):
        return value
    return _pairs(value)


def _reusable_options(options: RequestOptions | None) -> RequestOptions | None:
    if options is None:
        return None
    reserved = (
        tuple(options.path_params_allow_reserved)
        if options.path_params_allow_reserved is not None
        else None
    )
    return replace(
        options,
        params=_reusable(options.params),
        path_params_allow_reserved=reserved,
        form=_reusable(options.form),
        multipart=_reusable(options.multipart),
    )


class FastlyClient:
    """Client for every Fastly API route through one generic request method."""

    def __init__(self, account: AccountConfig) -> None:
        self.account = account

    def request(
        self,
        method: str,
        path: str,
        options: RequestOptions | None = None,
    ) -> ApiResponse:
        request = options or RequestOptions()
        normalized_method = method.upper()
        if normalized_method not in SAFE_METHODS and not request.allow_mutation:
            raise FastlyMutationError(
                f"{normalized_method} blocked; pass allow_mutation=True to enable it"
            )
        host, scheme, port, request_path = _path_for(
            self.account.base_url,
            path,
            request.params,
            request.path_params,
            request.path_params_allow_reserved,
        )
        payload, body_type = _request_body(
            request.json_body, request.body, request.form, request.multipart
        )
        request_headers = _request_headers(self.account, request.headers, body_type)
        status, raw_headers, raw = _send_request(
            _HttpRequest(
                self.account,
                normalized_method,
                request_path,
                payload,
                request_headers,
                host,
                scheme,
                port,
            )
        )
        response_headers = dict(raw_headers)
        data = _decode_body(raw, header_value(response_headers, "Content-Type"))
        if status < HTTPStatus.OK or status >= HTTPStatus.MULTIPLE_CHOICES:
            raise FastlyHTTPError(self.account.name, status, data)
        return ApiResponse(self.account.name, status, response_headers, data)


class FastlyMultiClient:
    """Apply one request to one or more accounts and retain account identity."""

    def __init__(self, accounts: Iterable[AccountConfig]) -> None:
        self.clients = [FastlyClient(account) for account in accounts]
        if not self.clients:
            raise ValueError("at least one account is required")

    def request(
        self, method: str, path: str, options: RequestOptions | None = None
    ) -> list[ApiResponse]:
        reusable_options = _reusable_options(options)
        return [
            client.request(method, path, reusable_options) for client in self.clients
        ]
