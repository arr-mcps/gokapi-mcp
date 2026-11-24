# AGENTS.md - gokapi-mcp

MCP server exposing Gokapi's REST API as 8 resource-scoped portmanteau
tools (36 operations). Uses FastMCP, `uv` for deps. Tested against Gokapi
2.2.4 (the version running in CT 121 on the new box).

## Tool design

Exactly 8 tools are registered, one per entry in `_GROUPS` in
`gokapi_mcp.py`: `gokapi_info`, `gokapi_files`, `gokapi_download`,
`gokapi_chunks`, `gokapi_requests`, `gokapi_auth`, `gokapi_users`,
`gokapi_logs`. Each tool takes an `operation` (a `Literal` of its functions'
names) plus an `arguments` dict and dispatches to a plain async endpoint
function. Do not register individual endpoint functions as tools. See the
arr-mcps masterlist `AGENTS.md` for the rationale (a 36-tool server blows
the MCP context budget).

`_register_group` marks a group `readOnlyHint=True` only when every operation
in it is a GET. Only `gokapi_info` is read-only; every other group is mixed
(downloads can bump the download counter, everything else mutates).

`dispatch` returns `ReturnVal = JSONObj | list[Any] | str | int | float | bool | None`
because binary downloads return base64 strings and presigned-URL downloads
return JSON. FastMCP validates the declared return type, so do not narrow it.

## Gokapi API specifics (verified against upstream source + live probing)

- Endpoint/method/parameter surface came from the live OpenAPI document at
  `http://10.10.10.25:53842/apidocumentation/openapi.json` (36 published
  endpoints), cross-checked against `internal/webserver/api/routing.go` in
  Forceu/Gokapi (master). Unpublished `/e2e/*` endpoints are intentionally
  excluded.
- Auth is the `apikey` request header (not `X-Api-Key`); the server sends it
  on every request.
- Parameters travel as HTTP **headers**, not query strings or JSON bodies.
  `_headers()` drops `None` values because header *presence* is semantically
  significant (e.g. sending `password` on `/files/modify` marks the password
  as set; omitting it leaves it unchanged; empty string clears it).
- Uploads are multipart form data: `/files/add` takes `file` (binary) plus
  form fields `allowedDownloads`/`expiryDays`/`password`; `/chunk/add` and
  `/uploadrequest/chunk/add` take `file` plus `uuid`/`filesize`/`offset`
  (uuid >= 10 chars, identical across a file's chunks).
- Downloads are binary (returned base64) unless `presign_url=true`, which
  returns a one-time 30-second URL as JSON instead of the bytes.
- Errors are `{"Result":"error","ErrorMessage":...,"ErrorCode":N}` with an
  HTTP status; `_error_message` surfaces `ErrorMessage`.
- Permissions are per-API-key: the deployment key lacks
  `PERM_MANAGE_FILE_REQUESTS` and `PERM_MANAGE_LOGS`, so the `requests` and
  `logs` groups return 401 Unauthorized with it. Tests mock those paths;
  do not "fix" them by broadening the tests.
- Large-file caveat: `MaxFilesize` on this server is 250000 MB and the live
  library holds a 198 GB share. Never exercise uploads or full downloads
  against the live service - cover them with mocked tests only, and stream
  (`presign_url=true` or the public download URL) rather than base64 when a
  real file must move. Base64 inflates payloads ~33% and the MCP return path
  is not a file-transfer channel.

`return` types of endpoint helpers are plain JSON pass-through dictionaries.
Do not place real API keys, passwords, or tokens in tool descriptions
or commit messages.

## Testing

- Offline suite: `make test` (or `uv run pytest`)
- Live integration (needs `GOKAPI_URL` + `GOKAPI_API_KEY`): `make test-integration`
- `tests/test_tools.py` has exact request-shape assertions for headers and
  multipart bodies, base64/presign download tests, `test_all_gokapi_grouped`,
  which asserts every endpoint function appears in exactly one `_GROUPS` entry.
- `tests/test_live.py` is read-only GETs only (version, config, list, get).
  Never add a write/upload/delete there.

## Release workflow

Use `make bump-*` (`uv version --bump patch|minor|major`), which updates
`pyproject.toml` and `uv.lock` together. Never hand-edit the version. Commit
message is just the version, tag `v<version>`, then push main and the tag.
This repo is not published to GitHub and is not pushed anywhere.
