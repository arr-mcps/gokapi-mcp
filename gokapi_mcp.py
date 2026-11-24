"""MCP tools for the Gokapi REST API.

Full coverage of the published API (36 endpoints, Gokapi 2.2.4), exposed as
8 resource-scoped *portmanteau* tools instead of one tool per endpoint. Each
tool takes an `operation` enum plus an `arguments` dict; see AGENTS.md for
the rationale (a 36-tool server blows the MCP context budget on session
start). `_GROUPS` near the bottom buckets every endpoint function by resource
and `_register_group` wraps each bucket in one dispatching MCP tool; the
functions themselves are not tools anymore.

Gokapi passes API parameters as HTTP headers (not query strings or JSON
bodies) and authenticates with the `apikey` header. Request bodies stay
multipart form data for uploads, matching the upstream API documentation at
`http(s)://<gokapi>/apidocumentation/`.
"""

import base64
import inspect
import json
import os
import sys
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations

JSONObj = dict[str, Any]
JSONVal = JSONObj | list[Any]
ReturnVal = JSONVal | str | int | float | bool | None
READONLY = ToolAnnotations(readOnlyHint=True)

mcp = FastMCP("gokapi-mcp")
_client: httpx.AsyncClient | None = None


def build_client(
    base_url: str,
    api_key: str | None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.AsyncClient:
    headers = {"apikey": api_key} if api_key else {}
    return httpx.AsyncClient(
        base_url=f"{base_url.rstrip('/')}/api", headers=headers, transport=transport
    )


def _path(value: Any) -> str:
    return quote(str(value), safe="")


def _headers(**values: Any) -> dict[str, str]:
    """Build Gokapi API headers, dropping parameters that were not supplied.

    Presence matters for several Gokapi parameters (e.g. `password` on
    /files/modify clears the password only when the header is sent), so
    `None` means "do not send" and is never serialised.
    """
    out: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


def _decode_response(response: httpx.Response) -> ReturnVal:
    """Parse a successful response as JSON, a JSON scalar, or raw text."""
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return response.json()
    text = response.text
    try:
        return json.loads(text)
    except ValueError:
        return text


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        if isinstance(body, dict):
            return str(body.get("ErrorMessage", body))
        return str(body)
    except ValueError:
        return response.text


async def _req(
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
) -> ReturnVal:
    assert _client is not None, "client not configured"
    response = await _client.request(method, path, headers=headers)
    if response.status_code >= 400:
        raise ToolError(f"Gokapi API {response.status_code}: {_error_message(response)}")
    return _decode_response(response)


async def _req_b64(method: str, path: str, headers: dict[str, str] | None = None) -> str:
    """Fetch a binary endpoint (file/zip download) as base64."""
    assert _client is not None, "client not configured"
    response = await _client.request(method, path, headers=headers)
    if response.status_code >= 400:
        raise ToolError(f"Gokapi API {response.status_code}: {_error_message(response)}")
    return base64.b64encode(response.content).decode("ascii")


async def _upload_file(
    path: str,
    file_b64: str,
    filename: str,
    fields: dict[str, Any] | None = None,
) -> ReturnVal:
    """Upload to a multipart endpoint. `file` is the binary field; `fields`
    are the remaining form fields (only non-None values are sent)."""
    assert _client is not None, "client not configured"
    data = base64.b64decode(file_b64)
    form = {k: str(v) for k, v in (fields or {}).items() if v is not None}
    response = await _client.post(
        path, files={"file": (filename, data)}, data=form or None
    )
    if response.status_code >= 400:
        raise ToolError(f"Gokapi API {response.status_code}: {_error_message(response)}")
    return _decode_response(response)


# info  ------------------------------------------------------------------------

async def gokapi_info_version() -> ReturnVal:
    """Get Gokapi version (GET /api/info/version)."""
    return await _req("GET", "/info/version")


async def gokapi_info_config() -> ReturnVal:
    """Get upload parameters: max file/chunk sizes, E2E flag (GET /api/info/config)."""
    return await _req("GET", "/info/config")


# files  -----------------------------------------------------------------------

async def gokapi_files_list(show_file_requests: bool | None = None) -> ReturnVal:
    """List all files (GET /api/files/list). Set show_file_requests to include
    files uploaded through file requests."""
    return await _req(
        "GET", "/files/list", headers=_headers(showFileRequests=show_file_requests)
    )


async def gokapi_files_get(id: str) -> ReturnVal:
    """Get file metadata by ID (GET /api/files/list/{id})."""
    return await _req("GET", f"/files/list/{_path(id)}")


async def gokapi_files_add(
    file_b64: str,
    filename: str,
    allowed_downloads: int | None = None,
    expiry_days: int | None = None,
    password: str | None = None,
) -> ReturnVal:
    """Upload a file without chunking (POST /api/files/add, multipart). The
    file is a base64 string. allowed_downloads defaults to 1 (0 = unlimited),
    expiry_days defaults to 14 (0 = unlimited)."""
    return await _upload_file(
        "/files/add",
        file_b64,
        filename,
        {
            "allowedDownloads": allowed_downloads,
            "expiryDays": expiry_days,
            "password": password,
        },
    )


async def gokapi_files_delete(id: str, delay: int | None = None) -> ReturnVal:
    """Delete a file (DELETE /api/files/delete). delay waits N seconds before
    deleting so the file can still be restored."""
    return await _req("DELETE", "/files/delete", headers=_headers(id=id, delay=delay))


async def gokapi_files_restore(id: str) -> ReturnVal:
    """Restore a file pending deletion (POST /api/files/restore)."""
    return await _req("POST", "/files/restore", headers=_headers(id=id))


async def gokapi_files_duplicate(
    id: str,
    allowed_downloads: int | None = None,
    expiry_days: int | None = None,
    password: str | None = None,
    original_password: bool | None = None,
    filename: str | None = None,
) -> ReturnVal:
    """Duplicate a file (POST /api/files/duplicate). Returns the new file
    object. Set original_password=true to keep the source password."""
    return await _req(
        "POST",
        "/files/duplicate",
        headers=_headers(
            id=id,
            allowedDownloads=allowed_downloads,
            expiryDays=expiry_days,
            password=password,
            originalPassword=original_password,
            filename=filename,
        ),
    )


async def gokapi_files_modify(
    id: str,
    allowed_downloads: int | None = None,
    expiry_timestamp: int | None = None,
    password: str | None = None,
    original_password: bool | None = None,
) -> ReturnVal:
    """Change parameters of an uploaded file (PUT /api/files/modify).
    allowed_downloads 0 = unlimited; expiry_timestamp 0 (unix) = no expiry;
    omit password to leave it unchanged, pass empty string to remove it."""
    return await _req(
        "PUT",
        "/files/modify",
        headers=_headers(
            id=id,
            allowedDownloads=allowed_downloads,
            expiryTimestamp=expiry_timestamp,
            password=password,
            originalPassword=original_password,
        ),
    )


async def gokapi_files_replace(
    id: str, id_new_content: str, delete_new_file: bool | None = None
) -> ReturnVal:
    """Replace a file's content with another uploaded file (PUT /api/files/replace).
    Set delete_new_file=true to delete the source file afterwards."""
    return await _req(
        "PUT",
        "/files/replace",
        headers=_headers(id=id, idNewContent=id_new_content, deleteNewFile=delete_new_file),
    )


async def gokapi_files_change_owner(id: str, new_owner: int) -> ReturnVal:
    """Change a file's owner (PUT /api/files/changeOwner, admin only).
    new_owner is the target user ID."""
    return await _req(
        "PUT", "/files/changeOwner", headers=_headers(id=id, newOwner=new_owner)
    )


# download  --------------------------------------------------------------------

async def gokapi_download_file(
    id: str, increase_counter: bool | None = None, presign_url: bool | None = None
) -> ReturnVal:
    """Download a file (GET /api/files/download/{id}). Returns base64-encoded
    bytes. Set presign_url=true to get a one-time 30s download URL (returned
    as JSON) instead of the file content."""
    headers = _headers(increaseCounter=increase_counter, presignUrl=presign_url)
    if presign_url:
        return await _req("GET", f"/files/download/{_path(id)}", headers=headers)
    return await _req_b64("GET", f"/files/download/{_path(id)}", headers=headers)


async def gokapi_download_zip(
    ids: str,
    filename: str | None = None,
    increase_counter: bool | None = None,
    presign_url: bool | None = None,
    is_file_request_id: bool | None = None,
) -> ReturnVal:
    """Download files as a ZIP (GET /api/files/downloadzip). ids is a comma-
    separated list of file IDs. Returns base64-encoded bytes unless
    presign_url=true (one-time 30s URL as JSON). Set is_file_request_id=true
    to pass a file request ID and zip all its files."""
    headers = _headers(
        ids=ids,
        filename=filename,
        increaseCounter=increase_counter,
        presignUrl=presign_url,
        isFileRequestId=is_file_request_id,
    )
    if presign_url:
        return await _req("GET", "/files/downloadzip", headers=headers)
    return await _req_b64("GET", "/files/downloadzip", headers=headers)


# chunks  ----------------------------------------------------------------------

async def gokapi_chunk_add(
    file_b64: str, uuid: str, filesize: int, offset: int
) -> ReturnVal:
    """Upload one chunk (POST /api/chunk/add, multipart). uuid (>=10 chars)
    must be identical for all chunks of one file; offset is the chunk's byte
    offset. The file chunk is a base64 string."""
    assert _client is not None, "client not configured"
    data = base64.b64decode(file_b64)
    response = await _client.post(
        "/chunk/add",
        files={"file": ("chunk.bin", data)},
        data={"uuid": uuid, "filesize": str(filesize), "offset": str(offset)},
    )
    if response.status_code >= 400:
        raise ToolError(f"Gokapi API {response.status_code}: {_error_message(response)}")
    return _decode_response(response)


async def gokapi_chunk_complete(
    uuid: str,
    filename: str,
    filesize: int,
    contenttype: str | None = None,
    allowed_downloads: int | None = None,
    expiry_days: int | None = None,
    password: str | None = None,
    nonblocking: bool | None = None,
) -> ReturnVal:
    """Finalise uploaded chunks into a file (POST /api/chunk/complete).
    allowed_downloads defaults to 1 (0 = unlimited), expiry_days defaults to
    14 (0 = unlimited). nonblocking=true returns before processing finishes."""
    return await _req(
        "POST",
        "/chunk/complete",
        headers=_headers(
            uuid=uuid,
            filename=filename,
            filesize=filesize,
            contenttype=contenttype,
            allowedDownloads=allowed_downloads,
            expiryDays=expiry_days,
            password=password,
            nonblocking=nonblocking,
        ),
    )


async def gokapi_urequest_chunk_add(
    file_b64: str, file_request_id: str, uuid: str, filesize: int, offset: int
) -> ReturnVal:
    """Upload one chunk for a file request (POST /api/uploadrequest/chunk/add,
    multipart). The file chunk is a base64 string."""
    assert _client is not None, "client not configured"
    data = base64.b64decode(file_b64)
    response = await _client.post(
        "/uploadrequest/chunk/add",
        headers=_headers(fileRequestId=file_request_id),
        files={"file": ("chunk.bin", data)},
        data={"uuid": uuid, "filesize": str(filesize), "offset": str(offset)},
    )
    if response.status_code >= 400:
        raise ToolError(f"Gokapi API {response.status_code}: {_error_message(response)}")
    return _decode_response(response)


async def gokapi_urequest_chunk_complete(
    uuid: str,
    file_request_id: str,
    filename: str,
    filesize: int,
    contenttype: str | None = None,
    nonblocking: bool | None = None,
) -> ReturnVal:
    """Finalise uploaded chunks for a file request
    (POST /api/uploadrequest/chunk/complete)."""
    return await _req(
        "POST",
        "/uploadrequest/chunk/complete",
        headers=_headers(
            uuid=uuid,
            fileRequestId=file_request_id,
            filename=filename,
            filesize=filesize,
            contenttype=contenttype,
            nonblocking=nonblocking,
        ),
    )


async def gokapi_urequest_chunk_reserve(id: str) -> ReturnVal:
    """Reserve a UUID for a new file-request upload
    (POST /api/uploadrequest/chunk/reserve)."""
    return await _req("POST", "/uploadrequest/chunk/reserve", headers=_headers(id=id))


async def gokapi_urequest_chunk_unreserve(id: str, uuid: str) -> ReturnVal:
    """Free a reserved UUID after a cancelled upload
    (POST /api/uploadrequest/chunk/unreserve)."""
    return await _req(
        "POST", "/uploadrequest/chunk/unreserve", headers=_headers(id=id, uuid=uuid)
    )


# upload requests  --------------------------------------------------------------

async def gokapi_urequest_list() -> ReturnVal:
    """List all file requests (GET /api/uploadrequest/list)."""
    return await _req("GET", "/uploadrequest/list")


async def gokapi_urequest_get(id: str) -> ReturnVal:
    """Get a file request by ID (GET /api/uploadrequest/list/{id})."""
    return await _req("GET", f"/uploadrequest/list/{_path(id)}")


async def gokapi_urequest_save(
    id: str | None = None,
    name: str | None = None,
    notes: str | None = None,
    expiry: int | None = None,
    maxfiles: int | None = None,
    maxsize: int | None = None,
) -> ReturnVal:
    """Create or update a file request (POST /api/uploadrequest/save). Omit
    id to create a new request. expiry is a UTC unix timestamp (0 = none);
    maxfiles 0 = unlimited count; maxsize is MB per file (0 = unlimited)."""
    return await _req(
        "POST",
        "/uploadrequest/save",
        headers=_headers(
            id=id,
            name=name,
            notes=notes,
            expiry=expiry,
            maxfiles=maxfiles,
            maxsize=maxsize,
        ),
    )


async def gokapi_urequest_delete(id: str) -> ReturnVal:
    """Delete an upload request and all its files (DELETE /api/uploadrequest/delete)."""
    return await _req("DELETE", "/uploadrequest/delete", headers=_headers(id=id))


# auth (API keys)  ---------------------------------------------------------------

async def gokapi_auth_create(
    friendly_name: str | None = None, basic_permissions: bool | None = None
) -> ReturnVal:
    """Create a new API key (POST /api/auth/create). Returns the new key -
    store it immediately, it cannot be retrieved again."""
    return await _req(
        "POST",
        "/auth/create",
        headers=_headers(friendlyName=friendly_name, basicPermissions=basic_permissions),
    )


async def gokapi_auth_delete(target_key: str) -> ReturnVal:
    """Delete an API key (DELETE /api/auth/delete). target_key is the key's
    public ID or the key itself."""
    return await _req("DELETE", "/auth/delete", headers=_headers(targetKey=target_key))


async def gokapi_auth_friendlyname(target_key: str, friendly_name: str) -> ReturnVal:
    """Rename an API key (PUT /api/auth/friendlyname)."""
    return await _req(
        "PUT",
        "/auth/friendlyname",
        headers=_headers(targetKey=target_key, friendlyName=friendly_name),
    )


async def gokapi_auth_modify(
    target_key: str, permission: str, permission_modifier: str
) -> ReturnVal:
    """Grant/revoke one API-key permission (PUT /api/auth/modify). permission
    is one of PERM_VIEW, PERM_UPLOAD, PERM_DELETE, PERM_API_MOD, PERM_EDIT,
    PERM_REPLACE, PERM_MANAGE_USERS, PERM_MANAGE_LOGS,
    PERM_MANAGE_FILE_REQUESTS, PERM_DOWNLOAD; permission_modifier is GRANT or
    REVOKE."""
    return await _req(
        "PUT",
        "/auth/modify",
        headers=_headers(
            targetKey=target_key,
            permission=permission,
            permissionModifier=permission_modifier,
        ),
    )


# users  -------------------------------------------------------------------------

async def gokapi_user_create(username: str) -> ReturnVal:
    """Create a new user (POST /api/user/create). Returns the new user
    including its generated password."""
    return await _req("POST", "/user/create", headers=_headers(username=username))


async def gokapi_user_changerank(userid: int, new_rank: str) -> ReturnVal:
    """Change a user's rank (PUT /api/user/changeRank). new_rank is admin or
    user."""
    return await _req(
        "PUT", "/user/changeRank", headers=_headers(userid=userid, newRank=new_rank)
    )


async def gokapi_user_delete(userid: int, delete_files: bool | None = None) -> ReturnVal:
    """Delete a user (DELETE /api/user/delete). Set delete_files=true to also
    delete all their uploads."""
    return await _req(
        "DELETE", "/user/delete", headers=_headers(userid=userid, deleteFiles=delete_files)
    )


async def gokapi_user_modify(
    userid: int, userpermission: str, permission_modifier: str
) -> ReturnVal:
    """Grant/revoke one user permission (PUT /api/user/modify).
    userpermission is one of PERM_REPLACE, PERM_LIST, PERM_EDIT,
    PERM_REPLACE_OTHER, PERM_DELETE, PERM_LOGS, PERM_API, PERM_USERS,
    PERM_GUEST_UPLOAD; permission_modifier is GRANT or REVOKE."""
    return await _req(
        "PUT",
        "/user/modify",
        headers=_headers(
            userid=userid,
            userpermission=userpermission,
            permissionModifier=permission_modifier,
        ),
    )


async def gokapi_user_resetpassword(
    userid: int, generate_new_password: bool | None = None
) -> ReturnVal:
    """Reset a user's password (PUT /api/user/resetPassword). Returns the new
    password."""
    return await _req(
        "PUT",
        "/user/resetPassword",
        headers=_headers(userid=userid, generateNewPassword=generate_new_password),
    )


# logs  --------------------------------------------------------------------------

async def gokapi_logs_get(timestamp: int | None = None) -> ReturnVal:
    """Get server logs (GET /api/logs/get). timestamp optionally filters to
    entries newer than a unix epoch."""
    return await _req("GET", "/logs/get", headers=_headers(timestamp=timestamp))


async def gokapi_logs_delete(timestamp: int | None = None) -> ReturnVal:
    """Delete log entries (DELETE /api/logs/delete, admin only). timestamp is
    the cutoff unix epoch - older entries are deleted; omit to delete all."""
    return await _req("DELETE", "/logs/delete", headers=_headers(timestamp=timestamp))


async def gokapi_logs_resettraffic() -> ReturnVal:
    """Reset the traffic statistic (DELETE /api/logs/resetTraffic, admin only)."""
    return await _req("DELETE", "/logs/resetTraffic")


async def gokapi_logs_systemstatus() -> ReturnVal:
    """Get server status information (GET /api/logs/systemStatus)."""
    return await _req("GET", "/logs/systemStatus")


# Resource groups for portmanteau registration. Every tool function name
# must appear in exactly one group - see test_all_gokapi_grouped.
_GROUPS: dict[str, tuple[str, ...]] = {
    "gokapi_info": (
        "gokapi_info_config",
        "gokapi_info_version",
    ),
    "gokapi_files": (
        "gokapi_files_add",
        "gokapi_files_change_owner",
        "gokapi_files_delete",
        "gokapi_files_duplicate",
        "gokapi_files_get",
        "gokapi_files_list",
        "gokapi_files_modify",
        "gokapi_files_replace",
        "gokapi_files_restore",
    ),
    "gokapi_download": (
        "gokapi_download_file",
        "gokapi_download_zip",
    ),
    "gokapi_chunks": (
        "gokapi_chunk_add",
        "gokapi_chunk_complete",
        "gokapi_urequest_chunk_add",
        "gokapi_urequest_chunk_complete",
        "gokapi_urequest_chunk_reserve",
        "gokapi_urequest_chunk_unreserve",
    ),
    "gokapi_requests": (
        "gokapi_urequest_delete",
        "gokapi_urequest_get",
        "gokapi_urequest_list",
        "gokapi_urequest_save",
    ),
    "gokapi_auth": (
        "gokapi_auth_create",
        "gokapi_auth_delete",
        "gokapi_auth_friendlyname",
        "gokapi_auth_modify",
    ),
    "gokapi_users": (
        "gokapi_user_changerank",
        "gokapi_user_create",
        "gokapi_user_delete",
        "gokapi_user_modify",
        "gokapi_user_resetpassword",
    ),
    "gokapi_logs": (
        "gokapi_logs_delete",
        "gokapi_logs_get",
        "gokapi_logs_resettraffic",
        "gokapi_logs_systemstatus",
    ),
}


def _op_line(name: str, fn: Any) -> str:
    """One line of a group tool's description: signature + one-line doc."""
    sig = ", ".join(
        p.name if p.default is inspect.Parameter.empty else f"{p.name}={p.default!r}"
        for p in inspect.signature(fn).parameters.values()
    )
    return f"- {name}({sig}) - {' '.join((fn.__doc__ or '').split())}"


def _register_group(
    group: str, names: tuple[str, ...], ns: dict[str, Any], readonly_names: set[str]
) -> None:
    """Register one dispatching tool that fans out to every function named
    in `names`. The functions themselves are untouched - they're just
    looked up by name instead of each becoming its own tool."""
    fns = {n: ns[n] for n in names}

    async def dispatch(
        operation: str, arguments: JSONObj | None = None
    ) -> ReturnVal:
        fn = fns.get(operation)
        if fn is None:
            raise ToolError(
                f"Unknown operation {operation!r} for {group}. Valid: {', '.join(fns)}"
            )
        return await fn(**(arguments or {}))

    dispatch.__annotations__["operation"] = Literal[names]
    ann = READONLY if set(names) <= readonly_names else None
    mcp.add_tool(
        Tool.from_function(
            dispatch,
            name=group,
            description=(
                f"{group.replace('_', ' ')} operations on Gokapi. Pass `operation` and an "
                f"`arguments` dict matching that operation's parameters.\n\n"
                + "\n".join(_op_line(n, f) for n, f in fns.items())
            ),
            annotations=ann,
        )
    )


def _register_tools() -> None:
    ns = globals()
    readonly_names: set[str] = {
        "gokapi_info_config",
        "gokapi_info_version",
    }
    for group, names in _GROUPS.items():
        _register_group(group, names, ns, readonly_names)


_register_tools()


def main() -> None:
    global _client
    url = os.environ.get("GOKAPI_URL")
    if not url:
        print(
            "GOKAPI_URL environment variable is required (e.g. http://10.10.10.25:53842)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    _client = build_client(url, os.environ.get("GOKAPI_API_KEY"))
    mcp.run()


if __name__ == "__main__":
    main()
