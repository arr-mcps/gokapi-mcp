# gokapi-mcp

An MCP server exposing [Gokapi](https://github.com/Forceu/Gokapi)'s REST API
as tools for managing file shares, chunked uploads, file requests, API keys,
users, and server logs.

## Requirements

- Gokapi with its REST API reachable (tested against 2.2.4)
- Python 3.11+ and `uv` for source development

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `GOKAPI_URL` | Yes | Gokapi base URL, for example `http://10.10.10.25:53842`. The server appends `/api`. |
| `GOKAPI_API_KEY` | Yes | API key generated in the Gokapi web UI under "API". Sent as the `apikey` header. |

Register it with Claude Code:

```bash
uv tool install gokapi_mcp-*.whl
claude mcp add gokapi \
  --env GOKAPI_URL=http://10.10.10.25:53842 \
  --env GOKAPI_API_KEY=<key> \
  -- gokapi-mcp
```

For a source checkout:

```bash
uv sync
claude mcp add gokapi \
  --env GOKAPI_URL=http://10.10.10.25:53842 \
  --env GOKAPI_API_KEY=<key> \
  -- uv run --directory /path/to/gokapi-mcp gokapi-mcp
```

## Tools

**8 resource-scoped tools** cover all 36 published Gokapi REST operations via
an `operation` parameter. Call a tool with `operation` set to one of its listed
operations and an `arguments` dict matching that operation's parameters. Each
tool's own description (visible to your MCP client) lists every operation, its
signature, and a one-line doc, so no discovery round-trip is needed. This keeps
the whole API available while costing a fraction of the context budget of
registering 36 endpoints as separate tools.

| Tool | Operations | Covers |
| --- | --- | --- |
| `gokapi_files` | 9 | File listing, metadata, upload, duplicate, modify, delete, restore, replace, change owner |
| `gokapi_chunks` | 6 | Chunked uploads and file-request chunk reserve/complete/unreserve |
| `gokapi_users` | 5 | User create, rank change, delete, permission modify, password reset |
| `gokapi_requests` | 4 | File-request list, get, save, delete |
| `gokapi_auth` | 4 | API-key create, delete, rename, permission grant/revoke |
| `gokapi_logs` | 4 | Server logs, log deletion, traffic reset, system status |
| `gokapi_info` | 2 | Version and upload-parameter config |
| `gokapi_download` | 2 | Single-file and ZIP download (base64 or presigned URL) |

Only `gokapi_info` is marked `readOnlyHint=True`; every other group contains
write operations and carries no hint.

Example:

```text
gokapi_info(operation="gokapi_info_version", arguments={})
gokapi_files(operation="gokapi_files_list", arguments={})
gokapi_files(operation="gokapi_files_get", arguments={"id": "8w4NyybwoHP4ofK"})
```

Notes on special operations:

- Gokapi takes API parameters as HTTP headers; unset optional arguments are
  not sent at all (header presence is significant - e.g. omitting `password`
  on modify leaves it unchanged, an empty string clears it).
- File/chunk uploads take a `file_b64` argument containing a base64-encoded file.
- Binary downloads return base64-encoded strings; pass `presign_url=true` to
  get a one-time 30-second download URL as JSON instead.
- Large files: do not pull multi-GB shares through the MCP return path -
  use the presigned URL or the share's public download URL. See AGENTS.md.

## Development

```bash
make sync
make test
make test-integration   # requires GOKAPI_URL and GOKAPI_API_KEY (read-only GETs)
make build
```

The offline tests use `httpx.MockTransport`; integration tests are skipped by
default.
