<p align="center">
  <img src="https://img.shields.io/badge/fastly--multiclient-Fastly%20REST%20CLI-blue?style=for-the-badge" alt="fastly-multiclient">
</p>

<h1 align="center">fastly-multiclient</h1>

<p align="center">
  <strong>Multi-account REST client and CLI for the Fastly API</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/fastly-multiclient/"><img src="https://img.shields.io/pypi/v/fastly-multiclient?style=flat-square&logo=pypi&logoColor=white" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/fastly-multiclient/"><img src="https://img.shields.io/pypi/pyversions/fastly-multiclient?style=flat-square&logo=python&logoColor=white" alt="Python Versions"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"></a>
  <a href="https://github.com/seifreed/fastly-cli/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/seifreed/fastly-cli/ci.yml?style=flat-square&logo=github&label=CI" alt="CI Status"></a>
</p>

<p align="center">
  <a href="https://github.com/seifreed/fastly-cli/stargazers"><img src="https://img.shields.io/github/stars/seifreed/fastly-cli?style=flat-square" alt="GitHub Stars"></a>
  <a href="https://github.com/seifreed/fastly-cli/issues"><img src="https://img.shields.io/github/issues/seifreed/fastly-cli?style=flat-square" alt="GitHub Issues"></a>
</p>

---

## Overview

**fastly-multiclient** is a Python 3.14 client and CLI for accessing any route
of the Fastly REST API with one or more accounts. It uses `Fastly-Key`, does
not depend on the generated official client, and supports both generic routes
and operations discovered from a typed catalog.

### Key Features

| Feature | Description |
| --- | --- |
| **Generic REST client** | Execute any HTTP method and Fastly route through one API |
| **Multi-account** | Configure multiple accounts and target one account or all of them |
| **Operation catalog** | Includes 636 operations from Fastly JS 16.1.0 with endpoint and parameter metadata |
| **Complete CLI** | Includes `request`, account management, `api list/describe/call`, and grouped commands |
| **Named arguments** | Each catalog operation exposes its parameters as CLI options |
| **Request bodies** | Supports JSON, binary files, forms, and multipart requests |
| **Exportable output** | Produces JSON by default or TOON output |
| **Explicit mutations** | Methods that modify data require `--allow-mutation` |
| **Cross-platform** | Works on Windows, Linux, and macOS on x64 and ARM |

### Supported Formats and Capabilities

```text
Responses        JSON, TOON
Request bodies   JSON, bytes, form-urlencoded, multipart
Discovery        JSON operation and parameter catalog
Quality          Tests, Black, Ruff, mypy, Bandit, and pip-audit in CI
Publishing       Wheel and sdist through PyPI Trusted Publishing
```

---

## Installation

### From PyPI (Recommended)

```bash
python -m pip install fastly-multiclient
```

### From Source

```bash
git clone https://github.com/seifreed/fastly-cli.git
cd fastly-cli
python3.14 -m venv venv

# Linux and macOS
source venv/bin/activate

# Windows PowerShell
# venv\Scripts\Activate.ps1

python -m pip install -e .
```

### Development Dependencies

The package has no runtime dependencies. Install the development tools from
the dependency group defined in `pyproject.toml`:

```bash
uv sync --group dev --python 3.14
```

---

## Quick Start

```bash
# Configure the current account token
export FASTLY="your-token"

# List services
fastly request GET /service

# Discover catalog operations
fastly api list service --method GET

# Run an operation with named arguments
fastly service get-service --service-id demo
```

On Windows PowerShell, configure the token with:

```powershell
$env:FASTLY = "your-token"
```

---

## Usage

### Credentials and Accounts

For a single account, use any of these environment variables:
`FASTLY`, `FASTLY_API_TOKEN`, or `FASTLY_API_KEY`.

For multiple accounts, create a TOML file:

```toml
[accounts.personal]
token = "personal-token"

[accounts.client]
token = "client-token"
base_url = "https://api.fastly.com"
timeout = 30
```

```bash
fastly --config fastly.toml --account personal request GET /service
fastly --config fastly.toml --all request GET /service
fastly --config fastly.toml accounts list
```

Real-time statistics operations are routed automatically to `rt.fastly.com`.
A custom account `base_url` takes precedence.

### Generic Requests

`request` accepts any Fastly method and route, including query parameters,
headers, JSON, and binary request bodies:

```bash
fastly request GET /service/{service_id} \
  --path-param service_id=demo \
  --query page=1 \
  --header X-Trace=demo

fastly request POST /service \
  --json '{"name":"demo"}' \
  --allow-mutation

fastly request POST /service \
  --form name=demo \
  --allow-mutation

fastly request POST /package \
  --body-file package.tar.gz \
  --allow-mutation

fastly request PUT /service/{service_id}/version/{version_id}/package \
  --path-param service_id=demo \
  --path-param version_id=1 \
  --multipart package=@package.tar.gz \
  --allow-mutation
```

Mutating methods require `--allow-mutation`; read-only requests do not need
that flag. Responses are printed as JSON by default:

```bash
fastly --format toon request GET /service --output service.toon
```

### Available Commands

| Command | Description |
| --- | --- |
| `fastly request METHOD PATH` | Execute a generic request against any route |
| `fastly accounts list` | List configured accounts |
| `fastly api list [QUERY]` | Search catalog operations by name, group, or path |
| `fastly api describe OPERATION` | Show an operation's method, path, and parameters |
| `fastly api call OPERATION` | Execute a catalog operation |
| `fastly <group> <endpoint>` | Execute an operation through a grouped command |

### Request Options

| Option | Description |
| --- | --- |
| `--query KEY=VALUE` | Add a query parameter |
| `--path-param KEY=VALUE` | Replace a path parameter |
| `--header KEY=VALUE` | Add an HTTP header |
| `--json JSON` | Send a JSON request body |
| `--body-file FILE` | Send a file as the request body |
| `--form KEY=VALUE` | Send form data |
| `--multipart KEY=@FILE` | Send a multipart part from a file |
| `--allow-mutation` | Authorize methods that modify data |
| `--format FORMAT` | Select `json` or `toon` |
| `-o, --output FILE` | Write output to a file |

### Catalog and Grouped Commands

The catalog can be queried without credentials:

```bash
fastly api list service --method GET
fastly api describe getService
```

`api describe` shows the location (`path`, `query`, `header`, `form`, or
`body`), wire name, and MIME type for every parameter. `api call` generates a
named argument for each parameter, converting `_` to `-`:

```bash
fastly --config fastly.toml api call getService --service-id demo
fastly --config fastly.toml api call getService --param service_id=demo
fastly --config fastly.toml service get-service --service-id demo
```

Body parameters receive JSON through their named argument, for example
`--customer-address '{"name":"demo"}'`. Full request bodies can also use
`--json`, `--body-file`, or `--multipart`. When a parameter conflicts with a
CLI option, use the `--api-` prefix, such as `--api-format` or `--api-query`.
Headers passed through `--header` take precedence over automatic catalog
values.

Each group shows only its endpoints, and each endpoint shows its arguments:

```bash
fastly --help
fastly service --help
fastly service get-service --help
```

The catalog helps discover available operations, while `request` can be used
immediately for routes that are not yet included in the catalog.

---

## Python Library

### Single Account

```python
from fastly_cli import AccountConfig, FastlyClient

client = FastlyClient(AccountConfig(name="default", token="your-token"))
response = client.request("GET", "/service")
print(response.as_dict())
```

### Multiple Accounts

```python
from fastly_cli import (
    FastlyMultiClient,
    RequestOptions,
    load_config,
    select_accounts,
    to_toon,
)

accounts = select_accounts(load_config("fastly.toml"), all_accounts=True)
responses = FastlyMultiClient(accounts).request(
    "GET", "/service", RequestOptions(params={"page": 1})
)
toon = to_toon(responses[0].as_dict())
```

The `request` method is intentionally generic: it covers current and future
Fastly routes without regenerating classes or publishing a version per
endpoint. Transport options are grouped in `RequestOptions`:
`params`, `path_params`, `headers`, `json_body`, `body`, `form`, `multipart`,
and `allow_mutation`.

---

## CI and Releases

GitHub Actions runs the full suite on `ubuntu-latest`, `windows-latest`, and
`macos-latest` with Python 3.14. It also runs Black, Ruff, mypy, Bandit, and
pip-audit. Pushes and pull requests run CI automatically.

Tags matching `v*` build the wheel and sdist and publish them through PyPI
Trusted Publishing. Configure `seifreed/fastly-cli` as a Trusted Publisher in
[PyPI](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
with workflow `publish.yml` and environment `pypi`, then create and push a
version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

---

## Requirements

- Python 3.14 or newer
- No runtime dependencies
- See [pyproject.toml](pyproject.toml) for development dependencies

---

## Contributing

1. Fork the repository
2. Create a branch (`git checkout -b feature/new-feature`)
3. Run the tests and quality checks
4. Commit and push your changes
5. Open a Pull Request

Before submitting changes, all checks must pass without errors or warnings:

```bash
pytest
black --check .
ruff check .
mypy .
bandit -r .
pip-audit .
```

---

## License

This project is distributed under the MIT license declared in
[pyproject.toml](pyproject.toml).

---

<p align="center">
  <sub>Built for practical multi-account Fastly API automation</sub>
</p>
