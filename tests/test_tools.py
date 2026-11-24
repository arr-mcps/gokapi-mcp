"""Offline contract tests for the Gokapi MCP tools."""

import base64
import inspect
import json

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

import gokapi_mcp


class Recorder:
    def __init__(self):
        self.method = None
        self.url = None
        self.headers = None
        self.json = None
        self.raw = None
        self.form = None
        self.response = httpx.Response(200, json={"Result": "OK"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.method = request.method
        self.url = request.url
        self.headers = request.headers
        self.raw = request.content
        try:
            self.json = json.loads(request.content) if request.content else None
        except ValueError:
            self.json = None
        return self.response


@pytest.fixture
def recorder():
    return Recorder()


@pytest_asyncio.fixture
async def server(recorder, monkeypatch):
    client = gokapi_mcp.build_client(
        "http://10.10.10.25:53842",
        "test-key",
        transport=httpx.MockTransport(recorder.handler),
    )
    monkeypatch.setattr(gokapi_mcp, "_client", client)
    yield gokapi_mcp.mcp
    await client.aclose()


_OP_GROUP = {
    op: group for group, ops in gokapi_mcp._GROUPS.items() for op in ops
}


async def call(server, op_name, **kwargs):
    """Call `op_name` (an operation name) through its portmanteau tool."""
    async with Client(server) as client:
        return await client.call_tool(
            _OP_GROUP[op_name], {"operation": op_name, "arguments": kwargs}
        )


@pytest.mark.parametrize(
    ("name", "kwargs", "method", "path"),
    [
        ("gokapi_info_version", {}, "GET", "/api/info/version"),
        ("gokapi_info_config", {}, "GET", "/api/info/config"),
        ("gokapi_files_list", {}, "GET", "/api/files/list"),
        ("gokapi_files_get", {"id": "abc123"}, "GET", "/api/files/list/abc123"),
        ("gokapi_files_delete", {"id": "abc123"}, "DELETE", "/api/files/delete"),
        ("gokapi_files_restore", {"id": "abc123"}, "POST", "/api/files/restore"),
        (
            "gokapi_files_change_owner",
            {"id": "abc123", "new_owner": 2},
            "PUT",
            "/api/files/changeOwner",
        ),
        ("gokapi_files_modify", {"id": "abc123"}, "PUT", "/api/files/modify"),
        ("gokapi_files_replace", {"id": "a", "id_new_content": "b"}, "PUT", "/api/files/replace"),
        ("gokapi_files_duplicate", {"id": "abc123"}, "POST", "/api/files/duplicate"),
        ("gokapi_download_file", {"id": "abc123"}, "GET", "/api/files/download/abc123"),
        ("gokapi_download_zip", {"ids": "a,b"}, "GET", "/api/files/downloadzip"),
        ("gokapi_chunk_complete", {"uuid": "x" * 10, "filename": "f", "filesize": 1}, "POST", "/api/chunk/complete"),
        ("gokapi_urequest_list", {}, "GET", "/api/uploadrequest/list"),
        ("gokapi_urequest_get", {"id": "abc"}, "GET", "/api/uploadrequest/list/abc"),
        ("gokapi_urequest_save", {}, "POST", "/api/uploadrequest/save"),
        ("gokapi_urequest_delete", {"id": "abc"}, "DELETE", "/api/uploadrequest/delete"),
        (
            "gokapi_urequest_chunk_reserve",
            {"id": "abc"},
            "POST",
            "/api/uploadrequest/chunk/reserve",
        ),
        (
            "gokapi_urequest_chunk_unreserve",
            {"id": "abc", "uuid": "x" * 10},
            "POST",
            "/api/uploadrequest/chunk/unreserve",
        ),
        (
            "gokapi_urequest_chunk_complete",
            {"uuid": "x" * 10, "file_request_id": "abc", "filename": "f", "filesize": 1},
            "POST",
            "/api/uploadrequest/chunk/complete",
        ),
        ("gokapi_auth_create", {}, "POST", "/api/auth/create"),
        ("gokapi_auth_delete", {"target_key": "k"}, "DELETE", "/api/auth/delete"),
        (
            "gokapi_auth_friendlyname",
            {"target_key": "k", "friendly_name": "n"},
            "PUT",
            "/api/auth/friendlyname",
        ),
        (
            "gokapi_auth_modify",
            {"target_key": "k", "permission": "PERM_VIEW", "permission_modifier": "GRANT"},
            "PUT",
            "/api/auth/modify",
        ),
        ("gokapi_user_create", {"username": "bob"}, "POST", "/api/user/create"),
        ("gokapi_user_changerank", {"userid": 2, "new_rank": "admin"}, "PUT", "/api/user/changeRank"),
        ("gokapi_user_delete", {"userid": 2}, "DELETE", "/api/user/delete"),
        (
            "gokapi_user_modify",
            {"userid": 2, "userpermission": "PERM_LIST", "permission_modifier": "GRANT"},
            "PUT",
            "/api/user/modify",
        ),
        ("gokapi_user_resetpassword", {"userid": 2}, "PUT", "/api/user/resetPassword"),
        ("gokapi_logs_get", {}, "GET", "/api/logs/get"),
        ("gokapi_logs_delete", {}, "DELETE", "/api/logs/delete"),
        ("gokapi_logs_resettraffic", {}, "DELETE", "/api/logs/resetTraffic"),
        ("gokapi_logs_systemstatus", {}, "GET", "/api/logs/systemStatus"),
    ],
)
async def test_endpoint_routes(server, recorder, name, kwargs, method, path):
    await call(server, name, **kwargs)
    assert recorder.method == method
    assert recorder.url.raw_path.split(b"?")[0].decode() == path


@pytest.mark.parametrize(
    ("name", "kwargs", "header", "value"),
    [
        ("gokapi_files_list", {"show_file_requests": True}, "showfilerequests", "true"),
        ("gokapi_files_delete", {"id": "abc", "delay": 30}, "delay", "30"),
        ("gokapi_files_modify", {"id": "a", "allowed_downloads": 0}, "alloweddownloads", "0"),
        (
            "gokapi_files_modify",
            {"id": "a", "expiry_timestamp": 0},
            "expirytimestamp",
            "0",
        ),
        (
            "gokapi_files_duplicate",
            {"id": "a", "original_password": True},
            "originalpassword",
            "true",
        ),
        (
            "gokapi_files_replace",
            {"id": "a", "id_new_content": "b", "delete_new_file": True},
            "deletenewfile",
            "true",
        ),
        ("gokapi_files_change_owner", {"id": "a", "new_owner": 5}, "newowner", "5"),
        (
            "gokapi_download_file",
            {"id": "a", "increase_counter": False},
            "increasecounter",
            "false",
        ),
        ("gokapi_download_zip", {"ids": "a,b"}, "ids", "a,b"),
        (
            "gokapi_chunk_complete",
            {"uuid": "u", "filename": "f", "filesize": 10, "expiry_days": 0},
            "expirydays",
            "0",
        ),
        ("gokapi_auth_create", {"basic_permissions": True}, "basicpermissions", "true"),
        (
            "gokapi_user_delete",
            {"userid": 3, "delete_files": True},
            "deletefiles",
            "true",
        ),
        (
            "gokapi_user_modify",
            {"userid": 3, "userpermission": "PERM_API", "permission_modifier": "REVOKE"},
            "permissionmodifier",
            "REVOKE",
        ),
        ("gokapi_logs_get", {"timestamp": 123}, "timestamp", "123"),
        (
            "gokapi_urequest_save",
            {"maxfiles": 5, "maxsize": 100},
            "maxfiles",
            "5",
        ),
    ],
)
async def test_request_headers(server, recorder, name, kwargs, header, value):
    await call(server, name, **kwargs)
    assert recorder.headers[header] == value


async def test_unset_params_are_not_sent(server, recorder):
    await call(server, "gokapi_files_modify", id="a")
    assert "alloweddownloads" not in recorder.headers
    assert "expirytimestamp" not in recorder.headers
    assert "password" not in recorder.headers
    assert "originalpassword" not in recorder.headers


async def test_api_key_header(server, recorder):
    await call(server, "gokapi_info_version")
    assert recorder.headers["apikey"] == "test-key"


async def test_no_api_key_header(recorder, monkeypatch):
    client = gokapi_mcp.build_client(
        "http://10.10.10.25:53842",
        None,
        transport=httpx.MockTransport(recorder.handler),
    )
    monkeypatch.setattr(gokapi_mcp, "_client", client)
    await call(gokapi_mcp.mcp, "gokapi_info_version")
    assert "apikey" not in recorder.headers
    await client.aclose()


async def test_binary_download_is_base64(server, recorder):
    recorder.response = httpx.Response(200, content=b"\x89PNG\r\n\x1a\n")
    result = await call(server, "gokapi_download_file", id="abc")
    assert result.data == base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")


async def test_presign_url_returns_json(server, recorder):
    recorder.response = httpx.Response(
        200, json={"Url": "https://gokapi.example/p/abc?token=x"}
    )
    result = await call(server, "gokapi_download_file", id="abc", presign_url=True)
    assert result.data == {"Url": "https://gokapi.example/p/abc?token=x"}


async def test_file_upload_multipart(server, recorder):
    await call(
        server,
        "gokapi_files_add",
        file_b64=base64.b64encode(b"file-bytes").decode("ascii"),
        filename="test.txt",
        expiry_days=5,
    )
    assert recorder.method == "POST"
    assert recorder.url.path == "/api/files/add"
    assert "multipart/form-data" in recorder.headers["content-type"]
    assert b"file-bytes" in (recorder.raw or b"")
    assert b"test.txt" in (recorder.raw or b"")
    assert b"expiryDays" in (recorder.raw or b"")


async def test_chunk_upload_multipart(server, recorder):
    await call(
        server,
        "gokapi_chunk_add",
        file_b64=base64.b64encode(b"chunk-bytes").decode("ascii"),
        uuid="u" * 10,
        filesize=100,
        offset=0,
    )
    assert recorder.method == "POST"
    assert recorder.url.path == "/api/chunk/add"
    assert b"chunk-bytes" in (recorder.raw or b"")
    assert b"uuid" in (recorder.raw or b"")


async def test_urequest_chunk_upload_sends_request_id_header(server, recorder):
    await call(
        server,
        "gokapi_urequest_chunk_add",
        file_b64=base64.b64encode(b"c").decode("ascii"),
        file_request_id="req1",
        uuid="u" * 10,
        filesize=10,
        offset=0,
    )
    assert recorder.headers["filerequestid"] == "req1"
    assert b"c" in (recorder.raw or b"")


async def test_list_returning_tool(server, recorder):
    recorder.response = httpx.Response(200, json=[{"Id": "a"}, {"Id": "b"}])
    result = await call(server, "gokapi_files_list")
    assert result.structured_content == {"result": [{"Id": "a"}, {"Id": "b"}]}
    assert result.data is not None


async def test_error_message(server, recorder):
    recorder.response = httpx.Response(
        401, json={"Result": "error", "ErrorMessage": "Unauthorized", "ErrorCode": 2}
    )
    with pytest.raises(ToolError, match="401.*Unauthorized"):
        await call(server, "gokapi_urequest_list")


async def test_non_json_error(server, recorder):
    recorder.response = httpx.Response(502, text="<html>Bad Gateway</html>")
    with pytest.raises(ToolError, match="502"):
        await call(server, "gokapi_info_version")


def test_main_requires_url(monkeypatch):
    monkeypatch.delenv("GOKAPI_URL", raising=False)
    with pytest.raises(SystemExit):
        gokapi_mcp.main()


# --- full-surface smoke coverage ---------------------------------------------
# Only a subset of the 36 operations has exact request-shape assertions above.
# This exercises every endpoint function's URL-templating/header-marshaling
# path with type-appropriate dummy arguments, so all grouped operations are
# covered. Upload endpoints use a tiny in-memory payload - no real files.

ALL_ENDPOINT_NAMES = sorted(
    name
    for name in dir(gokapi_mcp)
    if name.startswith("gokapi_")
    and inspect.iscoroutinefunction(getattr(gokapi_mcp, name))
)


def _sample_value(param: inspect.Parameter):
    if param.name == "file_b64":
        return base64.b64encode(b"x").decode("ascii")
    ann = str(param.annotation)
    if "dict" in ann:
        return {}
    if "bool" in ann:
        return True
    if "int" in ann:
        return 1
    return "x"


@pytest.mark.parametrize("name", ALL_ENDPOINT_NAMES)
async def test_every_endpoint_is_callable(server, recorder, name):
    fn = getattr(gokapi_mcp, name)
    kwargs = {
        p.name: _sample_value(p)
        for p in inspect.signature(fn).parameters.values()
        if p.default is inspect.Parameter.empty
    }
    await call(server, name, **kwargs)
    assert recorder.method in ("GET", "POST", "PUT", "DELETE", "PATCH")
    assert recorder.url.path.startswith("/")


# --- portmanteau grouping safety net ------------------------------------------

def test_all_gokapi_grouped():
    """Every endpoint function must land in exactly one portmanteau group."""
    grouped_names = [n for names in gokapi_mcp._GROUPS.values() for n in names]
    assert sorted(grouped_names) == sorted(ALL_ENDPOINT_NAMES)
    assert len(grouped_names) == len(set(grouped_names))


async def test_group_tools_are_the_only_registered_tools(server):
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == set(gokapi_mcp._GROUPS)


async def test_unknown_operation_rejected_by_schema(server):
    # The Literal[...] enum on `operation` means an invalid value never reaches
    # _register_group's dispatch body - pydantic rejects it first.
    with pytest.raises(ToolError, match="validation error"):
        async with Client(server) as client:
            await client.call_tool("gokapi_files", {"operation": "not_real"})
