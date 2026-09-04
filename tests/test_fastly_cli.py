from __future__ import annotations

import json
import math
import sys
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, cast

import pytest

from fastly_cli import (
    AccountConfig,
    ConfigError,
    FastlyClient,
    FastlyMultiClient,
    RequestOptions,
    find_operations,
    get_operation,
    load_config,
    select_accounts,
)
from fastly_cli import (
    to_toon as public_to_toon,
)
from fastly_cli.catalog import OPERATIONS, _load_operations, _operation, _strings
from fastly_cli.cli import main
from fastly_cli.cli_commands import (
    accounts_for_operation as _accounts_for_operation,
)
from fastly_cli.cli_commands import (
    apply_operation_params as _apply_operation_params,
)
from fastly_cli.cli_commands import (
    render as _render,
)
from fastly_cli.cli_commands import (
    write as _write,
)
from fastly_cli.cli_parser import (
    RequestInputs,
    _body,
    _multipart_pair,
    _pair,
)
from fastly_cli.client import (
    FastlyHTTPError,
    FastlyMutationError,
    FastlyTransportError,
    _connection_for,
    _decode_body,
    _path_for,
    _request_body,
)
from fastly_cli.request import JSON_NOT_SET
from fastly_cli.toon import to_toon


def verify(condition: object) -> None:
    """Raise a test failure without relying on Python's optimizable assert."""
    if not condition:
        raise AssertionError("test condition failed")


def credential(label: str) -> str:
    return f"test-credential-{label}"


class ApiHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body: bytes = b'{"ok":true}'
    response_content_type = "application/json"
    requests: ClassVar[list[tuple[str, str, bytes, dict[str, str]]]] = []

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        self._respond()

    def do_PUT(self) -> None:
        self._respond()

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append(
            (
                self.command,
                self.path,
                body,
                {key: value for key, value in self.headers.items()},
            )
        )
        self.send_response(self.response_status)
        self.send_header("content-type", type(self).response_content_type)
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture()
def server() -> Generator[tuple[ThreadingHTTPServer, str]]:
    ApiHandler.requests = []
    ApiHandler.response_status = 200
    ApiHandler.response_body = b'{"ok":true}'
    ApiHandler.response_content_type = "application/json"
    instance = ThreadingHTTPServer(("127.0.0.1", 0), ApiHandler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance, f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    thread.join()


def test_config_env_and_selection() -> None:
    accounts = load_config(env={"FASTLY": credential("a")})
    verify(list(accounts) == ["default"])
    verify(select_accounts(accounts)[0].token == credential("a"))


def test_config_toml_and_multi_selection() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "config.toml"
        path.write_text(
            f'[accounts]\n[accounts.one]\ntoken="one"\n[accounts.two]\ntoken="{credential("b")}"\n',
            encoding="utf-8",
        )
        accounts = load_config(path, env={})
    verify(
        [item.name for item in select_accounts(accounts, all_accounts=True)]
        == [
            "one",
            "two",
        ]
    )
    verify(select_accounts(accounts, ["two"])[0].token == credential("b"))
    with pytest.raises(ValueError, match="cannot be combined"):
        select_accounts(accounts, ["two"], all_accounts=True)
    with pytest.raises(ValueError, match="unknown account"):
        select_accounts(accounts, ["missing"])
    with pytest.raises(ValueError, match="no account"):
        select_accounts({}, [])


def test_config_rejects_bad_values() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        AccountConfig("", "token")
    with pytest.raises(ValueError, match="empty token"):
        AccountConfig("x", "")
    with pytest.raises(ValueError, match="invalid base_url"):
        AccountConfig("x", "token", "ftp://example.test")
    for base_url in (
        "https://user:password@example.test",
        "https://:443",
        "https://example.test:0",
        "https://example.test?query=value",
        "https://example.test#fragment",
        "https://[::1",
        "https://example.test:invalid",
    ):
        with pytest.raises(ValueError, match="invalid base_url"):
            AccountConfig("x", "token", base_url)
    with pytest.raises(ValueError, match="positive"):
        AccountConfig("x", "token", timeout=0)
    for timeout in (math.nan, math.inf, -math.inf, 10**1000):
        with pytest.raises(ValueError, match="positive"):
            AccountConfig("x", "token", timeout=timeout)
    invalid_accounts = (
        (cast(Any, 1), "token", "https://example.test", 30.0),
        ("x", cast(Any, 1), "https://example.test", 30.0),
        ("x", "token", cast(Any, None), 30.0),
        ("x", "token", "https://example.test", True),
        ("x", "token", "https://example.test", cast(Any, "30")),
    )
    for values in invalid_accounts:
        with pytest.raises(ConfigError):
            AccountConfig(*values)


def test_config_file_errors_and_environment_fallbacks() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        invalid_accounts = root / "invalid-accounts.toml"
        invalid_accounts.write_text("accounts = []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a TOML table"):
            load_config(invalid_accounts, env={})
        invalid_entry = root / "invalid-entry.toml"
        invalid_entry.write_text('[accounts]\none="token"\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="each account"):
            load_config(invalid_entry, env={})
        missing_token = root / "missing-token.toml"
        missing_token.write_text("[accounts.bad]\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="string token"):
            load_config(missing_token, env={})
        bad_base = root / "bad-base.toml"
        bad_base.write_text('[accounts.bad]\ntoken="x"\nbase_url=1\n', encoding="utf-8")
        with pytest.raises(ConfigError, match="base_url must"):
            load_config(bad_base, env={})
        bad_timeout = root / "bad-timeout.toml"
        bad_timeout.write_text(
            '[accounts.bad]\ntoken="x"\ntimeout=true\n', encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="timeout must"):
            load_config(bad_timeout, env={})
        top_level = root / "top-level.toml"
        top_level.write_text(f'token="{credential("top")}"\n', encoding="utf-8")
        verify(load_config(top_level, env={})["default"].token == credential("top"))
        env_path = root / "env-path.toml"
        env_path.write_text('[accounts.named]\ntoken="named"\n', encoding="utf-8")
        verify(list(load_config(env={"FASTLY_CONFIG": str(env_path)})) == ["named"])
    verify(
        load_config(env={"FASTLY_API_TOKEN": credential("a")})["default"].token
        == credential("a")
    )
    verify(
        load_config(env={"FASTLY_API_KEY": credential("b")})["default"].token
        == credential("b")
    )
    singleton = {"only": AccountConfig("only", "token")}
    verify(select_accounts(singleton)[0].name == "only")


def test_operation_catalog() -> None:
    verify(len(OPERATIONS) == 636)
    verify(len(_load_operations()) == 636)
    verify(
        all(
            set(operation.parameters)
            == set(dict(operation.parameter_locations))
            == set(dict(operation.parameter_names))
            for operation in OPERATIONS
        )
    )
    verify(
        all(
            set(operation.required).issubset(operation.parameters)
            for operation in OPERATIONS
        )
    )
    service_operations = find_operations("service", "get")
    verify(service_operations)
    operation = get_operation("GETSERVICE")
    verify(operation.path == "/service/{service_id}")
    verify("service_id" in operation.required)
    verify(
        get_operation("listEvents").parameter_routes["page_size"]
        == ("query", "page[size]")
    )
    verify(operation.as_dict()["method"] == "GET")
    verify(
        get_operation("purgeSingleUrl").path_params_allow_reserved == ("cached_url",)
    )
    verify(
        get_operation("kvStoreUpsertItem").content_types
        == ("application/octet-stream",)
    )
    request = RequestInputs()
    _apply_operation_params(
        get_operation("bulkPurgeTag"),
        [
            ("service_id", "service"),
            ("surrogate_key", "tag"),
            ("fastly_soft_purge", "1"),
        ],
        request,
    )
    verify(request.path_params == [("service_id", "service")])
    verify(request.headers == [("surrogate-key", "tag"), ("fastly-soft-purge", "1")])
    _apply_operation_params(
        get_operation("listEvents"),
        [("page_size", "10")],
        request,
    )
    verify(request.query_params == [("page[size]", "10")])
    _apply_operation_params(
        get_operation("createApexRedirect"),
        [("service_id2", "form-service")],
        request,
    )
    verify(request.form == [("service_id", "form-service")])
    with pytest.raises(ConfigError, match="unknown parameter"):
        _apply_operation_params(
            get_operation("getService"),
            [("unknown", "value")],
            request,
        )
    with pytest.raises(ConfigError, match="body parameter"):
        _apply_operation_params(
            get_operation("bulkPurgeTag"),
            [("purge_response", "value")],
            request,
        )
    verify(find_operations(method="DELETE"))
    verify(find_operations())
    verify(find_operations(query="never-a-fastly-operation") == ())
    with pytest.raises(KeyError, match="missing"):
        get_operation("missing")
    with pytest.raises(TypeError, match="string list"):
        _strings({"parameters": "invalid"}, "parameters")
    with pytest.raises(TypeError, match="string list"):
        _strings({"parameters": [1]}, "parameters")
    with pytest.raises(TypeError, match="string map"):
        _operation(
            {
                "operation": "x",
                "group": "x",
                "method": "GET",
                "path": "/",
                "base_url": "https://example.test",
                "summary": "",
                "parameter_locations": [],
            }
        )
    with pytest.raises(TypeError, match="string map"):
        _operation(
            {
                "operation": "x",
                "group": "x",
                "method": "GET",
                "path": "/",
                "base_url": "https://example.test",
                "summary": "",
                "parameter_locations": {"id": 1},
            }
        )
    with pytest.raises(ValueError, match="parameter_locations"):
        _operation(
            {
                "operation": "x",
                "group": "x",
                "method": "GET",
                "path": "/",
                "base_url": "https://example.test",
                "summary": "",
                "parameter_locations": {"id": "cookie"},
            }
        )
    with pytest.raises(TypeError, match="string fields"):
        _operation({})


def test_client_get_and_post(server: tuple[ThreadingHTTPServer, str]) -> None:
    instance, base_url = server
    client = FastlyClient(AccountConfig("local", "token", base_url))
    response = client.request(
        "GET",
        "/service/{service_id}",
        RequestOptions(
            params=[("page", "1"), ("tag", "a")],
            path_params={"service_id": "id with space"},
            headers={"X-Test": "yes"},
        ),
    )
    verify(response.data == {"ok": True})
    verify(ApiHandler.requests[-1][1] == "/service/id%20with%20space?page=1&tag=a")
    with pytest.raises(FastlyMutationError):
        client.request("POST", "/service")
    posted = client.request(
        "POST",
        "/service",
        RequestOptions(json_body={"name": "demo"}, allow_mutation=True),
    )
    verify(posted.status == 200)
    verify(json.loads(ApiHandler.requests[-1][2]) == {"name": "demo"})
    client.request(
        "POST",
        "/service",
        RequestOptions(form={"name": "demo"}, allow_mutation=True),
    )
    verify(ApiHandler.requests[-1][2] == b"name=demo")
    client.request(
        "POST",
        "/service",
        RequestOptions(
            json_body={},
            headers={"accept": "text/plain", "content-type": "application/custom"},
            allow_mutation=True,
        ),
    )
    verify(ApiHandler.requests[-1][3]["accept"] == "text/plain")
    verify(ApiHandler.requests[-1][3]["content-type"] == "application/custom")
    verify("Accept" not in ApiHandler.requests[-1][3])
    verify("Content-Type" not in ApiHandler.requests[-1][3])
    with TemporaryDirectory() as directory:
        package = Path(directory) / "package.tar.gz"
        package.write_bytes(b"package\x00data")
        uploaded = client.request(
            "PUT",
            "/package",
            RequestOptions(multipart={"package": package}, allow_mutation=True),
        )
    verify(uploaded.data == {"ok": True})
    upload_body = ApiHandler.requests[-1][2]
    upload_headers = ApiHandler.requests[-1][3]
    boundary = upload_headers["Content-Type"].split("boundary=", 1)[1]
    verify(f"--{boundary}".encode() in upload_body)
    verify(b'name="package"; filename="package.tar.gz"' in upload_body)
    verify(b"package\x00data" in upload_body)
    verify(instance.server_port > 0)


def test_client_http_error_and_binary(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base_url = server
    ApiHandler.response_status = 404
    ApiHandler.response_body = b"not-json"
    client = FastlyClient(AccountConfig("local", "token", base_url))
    with pytest.raises(FastlyHTTPError) as error:
        client.request("GET", "/missing")
    verify(error.value.data == "not-json")
    ApiHandler.response_status = 200
    ApiHandler.response_body = b"\xff\x00"
    response = client.request("GET", "/binary")
    verify("base64" in response.data)
    ApiHandler.response_content_type = "application/octet-stream"
    ApiHandler.response_body = b"binary-as-text"
    response = client.request("GET", "/binary-text")
    verify(response.data == {"base64": "YmluYXJ5LWFzLXRleHQ="})


def test_client_helpers_and_transport_errors(
    server: tuple[ThreadingHTTPServer, str],
) -> None:
    _, base_url = server
    verify(_decode_body(b"", "") is None)
    verify(
        _decode_body(b"binary-as-text", "application/octet-stream")
        == {"base64": "YmluYXJ5LWFzLXRleHQ="}
    )
    verify(_decode_body(b"{broken", "application/json") == "{broken")
    verify(_request_body({"a": 1}, None, None)[1] == "application/json")
    verify(_request_body(None, None, None)[0] == b"null")
    verify(_request_body(JSON_NOT_SET, "text", None)[0] == b"text")
    verify(_request_body(JSON_NOT_SET, b"bytes", None)[0] == b"bytes")
    verify(
        _request_body(JSON_NOT_SET, None, {"name": "demo"})[1]
        == "application/x-www-form-urlencoded"
    )
    multipart_values: dict[str, bytes | str] = {"field": "value", "file": b"data"}
    multipart_body, multipart_type = _request_body(
        JSON_NOT_SET, None, None, multipart_values
    )
    verify(multipart_body is not None)
    multipart_body = cast(bytes, multipart_body)
    verify(
        multipart_type is not None and multipart_type.startswith("multipart/form-data;")
    )
    verify(b'name="field"' in multipart_body)
    verify(b'name="file"; filename="file"' in multipart_body)
    with pytest.raises(ValueError, match="mutually exclusive"):
        _request_body({}, b"body", None)
    with pytest.raises(ValueError, match="mutually exclusive"):
        _request_body({}, None, {"name": "demo"})
    with pytest.raises(ValueError, match="mutually exclusive"):
        _request_body(JSON_NOT_SET, b"body", None, {"name": "demo"})
    with pytest.raises(ValueError, match="field names"):
        _request_body(JSON_NOT_SET, None, None, {"bad\nname": "value"})
    with TemporaryDirectory() as directory:
        bad_name = Path(directory) / "bad\nname"
        with pytest.raises(ValueError, match="filenames"):
            _request_body(JSON_NOT_SET, None, None, {"file": bad_name})
    verify(_request_body(JSON_NOT_SET, None, None) == (None, None))
    verify(
        _path_for(f"{base_url}/api", "/v1?existing=yes", {"page": 1})[-1]
        == ("/api/v1?existing=yes&page=1")
    )
    verify(_path_for(f"{base_url}/api", "v1", None)[-1] == "/api/v1")
    verify(_path_for(f"{base_url}/api", "/", None)[-1] == "/api/")
    verify(_path_for(base_url, "", None)[-1] == "/")
    verify(
        _path_for(
            base_url,
            "/purge/{cached_url}",
            None,
            {"cached_url": "https://example.test/a?b=1"},
            ("cached_url",),
        )[-1]
        == "/purge/https://example.test/a?b=1"
    )
    with pytest.raises(ValueError, match="no parameter"):
        _path_for(base_url, "/v1", None, {"missing": "x"})
    with pytest.raises(ValueError, match="missing path"):
        _path_for(base_url, "/v1/{required}/{other}", None, {"required": "x"})
    with pytest.raises(ValueError, match="missing path"):
        _path_for(base_url, "/v1/{required}", None)
    with pytest.raises(ValueError, match="relative"):
        _path_for(base_url, "https://example.test", None)
    https_connection = _connection_for(
        AccountConfig("secure", "token"), "example.test", "https", 443
    )
    https_connection.close()
    with pytest.raises(FastlyTransportError):
        FastlyClient(AccountConfig("offline", "token", "http://127.0.0.1:1")).request(
            "GET", "/service"
        )
    verify(base_url.startswith("http://"))


def test_multi_client_and_toon(
    server: tuple[ThreadingHTTPServer, str],
) -> None:
    _, base_url = server
    with pytest.raises(ValueError, match="at least one account"):
        FastlyMultiClient([])
    accounts = [
        AccountConfig("one", "a", base_url),
        AccountConfig("two", "b", base_url),
    ]
    multi = FastlyMultiClient(accounts)
    verify([client.account.name for client in multi.clients] == ["one", "two"])
    responses = multi.request("GET", "/service")
    verify([response.account for response in responses] == ["one", "two"])
    generator_options = RequestOptions(
        params=(("page", value) for value in ("1",)),
        path_params={"cached_url": "https://example.test/a?b=1"},
        path_params_allow_reserved=(name for name in ("cached_url",)),
    )
    multi.request("GET", "/purge/{cached_url}", generator_options)
    verify(ApiHandler.requests[-2][1] == "/purge/https://example.test/a?b=1&page=1")
    verify(ApiHandler.requests[-1][1] == "/purge/https://example.test/a?b=1&page=1")
    verify(public_to_toon({"ok": True}) == "ok: true")
    verify(
        to_toon({"users": [{"id": 1, "name": "Ada"}, {"id": 2, "name": "Bob"}]})
        == ("users[2]{id,name}:\n  1,Ada\n  2,Bob")
    )
    verify(to_toon({"values": [1, "two", None]}) == "values[3]: 1,two,null")
    verify(to_toon({"items": [{}, {}]}) == "items[2]:\n  -\n  -")
    verify(to_toon({"items": [{"a": {"b": 1}}]}) == "items[1]:\n  - a:\n      b: 1")
    verify(
        to_toon({"items": [{"a": 1, "b": 2}, {"b": 3, "a": 4}]})
        == ("items[2]{a,b}:\n  1,2\n  4,3")
    )


def test_toon_scalar_and_array_edges() -> None:
    verify(to_toon(True) == "true")
    verify(to_toon(False) == "false")
    verify(to_toon(1.5) == "1.5")
    verify(to_toon(1e-6) == "0.000001")
    verify(to_toon(-0.0) == "0")
    verify(
        to_toon(
            {
                "empty": [],
                "": "",
                "truth": "true",
                "bad key": "a,b",
                "plus": "+1",
                "hash": "#tag",
                "control": "a\x01b",
            }
        )
        == (
            'empty: []\n"": ""\ntruth: "true"\n"bad key": "a,b"\n'
            'plus: "+1"\nhash: "#tag"\ncontrol: "a\\u0001b"'
        )
    )
    verify(to_toon([]) == "[]")
    verify(to_toon([1, {"a": 2}]) == "[2]:\n  - 1\n  - a: 2")
    verify(to_toon([{"a": 1}, {"b": 2}]) == "[2]:\n  - a: 1\n  - b: 2")
    verify(to_toon([{}, [2, 3], []]) == ("[3]:\n  -\n  - [2]: 2,3\n  - [0]:"))
    verify(to_toon([[{"a": 1}]]) == "[1]:\n  - [1]:\n    - a: 1")
    verify(to_toon([[2, 3], []]) == "[2]:\n  - [2]: 2,3\n  - [0]:")
    verify(to_toon([[1, [2], "x"]]) == "[1]:\n  - [3]:\n    - 1\n    - [1]: 2\n    - x")
    verify(
        to_toon([1, [1, {"a": 2}, [3], "x"]])
        == ("[2]:\n  - 1\n  - [4]:\n    - 1\n    - a: 2\n    - [1]: 3\n    - x")
    )
    verify(to_toon([{"a": 1, "b": {"c": 2}}]) == ("[1]:\n  - a: 1\n    b:\n      c: 2"))
    verify(
        to_toon(
            {"value": "123", "space": "hello world", "dash": "-item", "key-name": 1}
        )
        == 'value: "123"\nspace: hello world\ndash: "-item"\n"key-name": 1'
    )
    verify(
        to_toon([{"nums": [1, 2, 3], "name": "test"}])
        == ("[1]:\n  - nums[3]: 1,2,3\n    name: test")
    )
    with pytest.raises(ValueError, match="non-finite"):
        to_toon(float("inf"))
    with pytest.raises(TypeError, match="not a TOON"):
        to_toon(object())


def test_cli_local_request(
    capsys: pytest.CaptureFixture[str], server: tuple[ThreadingHTTPServer, str]
) -> None:
    _, base_url = server
    arguments = ["--account", "default", "request", "GET", "/service"]
    with TemporaryDirectory() as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            f'[accounts.default]\ntoken="token"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        verify(main(["--config", str(config), *arguments]) == 0)
    verify(json.loads(capsys.readouterr().out)["data"] == {"ok": True})


def test_cli_helpers_accounts_output_and_errors(
    capsys: pytest.CaptureFixture[str], server: tuple[ThreadingHTTPServer, str]
) -> None:
    _, base_url = server
    with pytest.raises(Exception, match="KEY=VALUE"):
        _pair("invalid", "query")
    verify(_pair("key=value=rest", "query") == ("key", "value=rest"))
    verify(_multipart_pair("field=value") == ("field", "value"))
    verify(_multipart_pair("file=@upload.bin") == ("file", Path("upload.bin")))
    verify(_body('{"name":"demo"}') == {"name": "demo"})
    with TemporaryDirectory() as directory:
        root = Path(directory)
        body_file = root / "body.json"
        body_file.write_text('{"name":"file"}', encoding="utf-8")
        verify(_body(f"@{body_file}") == {"name": "file"})
        output = root / "result.toon"
        _write({"ok": True}, "toon", output)
        verify(output.read_text(encoding="utf-8") == "ok: true")
        config = root / "config.toml"
        config.write_text(
            f'[accounts.one]\ntoken="one"\nbase_url="{base_url}"\n'
            f'[accounts.two]\ntoken="two"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        verify(main(["--config", str(config), "accounts", "list"]) == 0)
        verify(len(json.loads(capsys.readouterr().out)["accounts"]) == 2)
        verify(main(["--config", str(config), "--all", "accounts", "list"]) == 0)
        verify(len(json.loads(capsys.readouterr().out)["accounts"]) == 2)
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "--all",
                    "request",
                    "GET",
                    "/service",
                ]
            )
            == 0
        )
        verify(len(json.loads(capsys.readouterr().out)) == 2)
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "--account",
                    "one",
                    "request",
                    "GET",
                    "https://bad",
                ]
            )
            == 2
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "--account",
                    "one",
                    "request",
                    "POST",
                    "/service",
                ]
            )
            == 2
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "--account",
                    "one",
                    "request",
                    "POST",
                    "/service",
                    "--json",
                    "{}",
                    "--body-file",
                    str(body_file),
                ]
            )
            == 2
        )
    verify(_render({"ok": True}, "toon") == "ok: true")


def test_cli_operation_commands(capsys: pytest.CaptureFixture[str]) -> None:
    verify(main(["api", "list", "service", "--method", "GET"]) == 0)
    listed = json.loads(capsys.readouterr().out)
    verify(listed["operations"])
    verify(all(item["method"] == "GET" for item in listed["operations"]))
    verify(main(["api", "describe", "getService", "--format", "toon"]) == 0)
    verify("operation: getService" in capsys.readouterr().out)
    verify(main(["api", "describe", "missing"]) == 2)
    verify("unknown operation" in capsys.readouterr().err)
    verify(main(["api", "call", "missing"]) == 2)
    verify("unknown operation" in capsys.readouterr().err)


def test_grouped_catalog_command(
    capsys: pytest.CaptureFixture[str], server: tuple[ThreadingHTTPServer, str]
) -> None:
    _, base_url = server
    with TemporaryDirectory() as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            f'[accounts.default]\ntoken="token"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "service",
                    "get-service",
                    "--service-id",
                    "demo",
                ]
            )
            == 0
        )
        verify(ApiHandler.requests[-1][1] == "/service/demo")
        verify(json.loads(capsys.readouterr().out)["status"] == 200)


def test_cli_operation_call(
    capsys: pytest.CaptureFixture[str], server: tuple[ThreadingHTTPServer, str]
) -> None:
    _, base_url = server
    with TemporaryDirectory() as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            f'[accounts.default]\ntoken="token"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "getService",
                    "--service-id",
                    "id with space",
                    "--format",
                    "toon",
                ]
            )
            == 0
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "suggestDomains",
                    "--api-query",
                    "demo",
                ]
            )
            == 0
        )
        verify(
            ApiHandler.requests[-1][1]
            == "/domain-management/v1/tools/suggest?query=demo"
        )
        verify("status: 200" in capsys.readouterr().out)
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "purgeSingleUrl",
                    "--path-param",
                    "cached_url=https://example.test/a?b=1",
                    "--allow-mutation",
                ]
            )
            == 0
        )
        verify(ApiHandler.requests[-1][1] == "/purge/https://example.test/a?b=1")
        package = Path(directory) / "item.bin"
        package.write_bytes(b"kv-item")
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "kvStoreUpsertItem",
                    "--path-param",
                    "store_id=store",
                    "--path-param",
                    "key=item",
                    "--body-file",
                    str(package),
                    "--allow-mutation",
                ]
            )
            == 0
        )
        verify(ApiHandler.requests[-1][3]["Content-Type"] == "application/octet-stream")
        verify(ApiHandler.requests[-1][2] == b"kv-item")
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "kvStoreGetItem",
                    "--path-param",
                    "store_id=store",
                    "--path-param",
                    "key=item",
                ]
            )
            == 0
        )
        verify(ApiHandler.requests[-1][3]["Accept"] == "application/octet-stream")
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "getStatsLastSecond",
                    "--path-param",
                    "service_id=id",
                    "--path-param",
                    "timestamp_in_seconds=0",
                ]
            )
            == 0
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "getUsageMetrics",
                ]
            )
            == 2
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "createCustomerAddress",
                    "--customer-address",
                    "{}",
                ]
            )
            == 2
        )
        verify("mutation" in capsys.readouterr().err)
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "createCustomerAddress",
                    "--customer-address",
                    "{}",
                    "--json",
                    "{}",
                ]
            )
            == 2
        )
        verify("named body parameters" in capsys.readouterr().err)
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "api",
                    "call",
                    "createCustomerAddress",
                    "--allow-mutation",
                ]
            )
            == 2
        )
    verify(ApiHandler.requests[-1][1] == "/v1/channel/id/ts/0")


def test_cli_operation_base_url_routing(
    server: tuple[ThreadingHTTPServer, str],
) -> None:
    _, base_url = server
    accounts = [
        AccountConfig("default", "token"),
        AccountConfig("default-slash", "token", "https://api.fastly.com/"),
        AccountConfig("default-port", "token", "https://api.fastly.com:443"),
        AccountConfig("default-case", "token", "HTTPS://API.FASTLY.COM/"),
        AccountConfig("proxy", "token", base_url),
    ]
    selected = _accounts_for_operation(accounts, "https://rt.fastly.com")
    verify(selected[0].base_url == "https://rt.fastly.com")
    verify(selected[1].base_url == "https://rt.fastly.com")
    verify(selected[2].base_url == "https://rt.fastly.com")
    verify(selected[3].base_url == "https://rt.fastly.com")
    verify(selected[4].base_url == base_url)


def test_request_local_options_after_subcommand(
    capsys: pytest.CaptureFixture[str], server: tuple[ThreadingHTTPServer, str]
) -> None:
    _, base_url = server
    with TemporaryDirectory() as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            f'[accounts.default]\ntoken="token"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "request",
                    "GET",
                    "/service",
                    "--format",
                    "toon",
                ]
            )
            == 0
        )
    verify(capsys.readouterr().out.startswith("account: default\n"))


def test_cli_multipart_local_request(
    capsys: pytest.CaptureFixture[str], server: tuple[ThreadingHTTPServer, str]
) -> None:
    _, base_url = server
    with TemporaryDirectory() as directory:
        root = Path(directory)
        config = root / "config.toml"
        package = root / "package.tar.gz"
        package.write_bytes(b"cli-package")
        config.write_text(
            f'[accounts.default]\ntoken="token"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        verify(
            main(
                [
                    "--config",
                    str(config),
                    "request",
                    "PUT",
                    "/package",
                    "--multipart",
                    f"package=@{package}",
                    "--allow-mutation",
                ]
            )
            == 0
        )
    verify(json.loads(capsys.readouterr().out)["data"] == {"ok": True})
    verify(b"cli-package" in ApiHandler.requests[-1][2])


def test_module_entry_point(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base_url = server
    with TemporaryDirectory() as directory:
        config = Path(directory) / "config.toml"
        config.write_text(
            f'[accounts.default]\ntoken="token"\nbase_url="{base_url}"\n',
            encoding="utf-8",
        )
        original_argv = sys.argv
        sys.argv = ["fastly", "--config", str(config), "request", "GET", "/service"]
        try:
            with pytest.raises(SystemExit) as result:
                __import__("runpy").run_module(
                    "fastly_cli.__main__", run_name="__main__"
                )
            verify(result.value.code == 0)
        finally:
            sys.argv = original_argv
