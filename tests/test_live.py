"""Opt-in smoke tests for a live Gokapi instance.

Read-only GETs only: version, config, file listing and single-file metadata.
Never creates, modifies, deletes or uploads anything on the live service.
"""

import os

import pytest
from fastmcp import Client

import gokapi_mcp

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("GOKAPI_URL"),
        reason="requires GOKAPI_URL (and GOKAPI_API_KEY)",
    ),
]


@pytest.fixture(autouse=True)
def configure_client():
    gokapi_mcp._client = gokapi_mcp.build_client(
        os.environ["GOKAPI_URL"], os.environ.get("GOKAPI_API_KEY")
    )
    yield


async def call(group, operation, **arguments):
    async with Client(gokapi_mcp.mcp) as client:
        return await client.call_tool(
            group, {"operation": operation, "arguments": arguments}
        )


async def test_version_and_config():
    version = await call("gokapi_info", "gokapi_info_version")
    assert version.data is not None
    assert "Version" in version.data
    config = await call("gokapi_info", "gokapi_info_config")
    assert config.data is not None
    assert "MaxFilesize" in config.data


async def test_list_and_get_single_file():
    listing = await call("gokapi_files", "gokapi_files_list")
    assert listing.data is not None
    assert isinstance(listing.data, list)
    if listing.data:
        first_id = listing.data[0]["Id"]
        single = await call("gokapi_files", "gokapi_files_get", id=first_id)
        assert single.data is not None
        assert single.data["Id"] == first_id
