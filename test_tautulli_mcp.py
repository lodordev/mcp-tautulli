"""Tests for tautulli MCP server using FastMCP Client.

This follows FastMCP's recommended testing approach:
- Uses FastMCP Client to test the actual MCP protocol behavior
- Tests tools through client.call_tool() instead of direct function calls
- Uses inline-snapshot for assertions on complex data structures
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.client.types import TextContent  # type: ignore

import tautulli


def _get_text_content(result) -> str:
    """Extract text from tool result, assuming it's TextContent."""
    assert result.content is not None
    assert len(result.content) > 0
    content = result.content[0]
    assert isinstance(content, TextContent), (
        f"Expected TextContent, got {type(content)}"
    )
    return content.text


@pytest.fixture
async def mcp_client():
    """Create a FastMCP Client fixture for testing."""
    # Set up environment variables for the client
    original_url = os.environ.get("TAUTULLI_URL")
    original_key = os.environ.get("TAUTULLI_API_KEY")

    os.environ["TAUTULLI_URL"] = "http://test.local"
    os.environ["TAUTULLI_API_KEY"] = "test-key"

    async with Client(tautulli.mcp) as client:
        yield client

    # Restore original environment variables
    if original_url is None:
        os.environ.pop("TAUTULLI_URL", None)
    else:
        os.environ["TAUTULLI_URL"] = original_url
    if original_key is None:
        os.environ.pop("TAUTULLI_API_KEY", None)
    else:
        os.environ["TAUTULLI_API_KEY"] = original_key


class TestListTools:
    """Test the list_tools endpoint."""

    async def test_list_tools(self, mcp_client: Client):
        """Test that all expected tools are listed."""
        tools = await mcp_client.list_tools()

        tool_names = [tool.name for tool in tools]
        expected_tools = [
            "tautulli_activity",
            "tautulli_history",
            "tautulli_recently_added",
            "tautulli_search",
            "tautulli_user_stats",
            "tautulli_library_stats",
            "tautulli_most_watched",
            "tautulli_server_info",
            "tautulli_status",
            "tautulli_transcode_stats",
            "tautulli_platform_stats",
            "tautulli_stream_resolution",
            "tautulli_plays_by_date",
            "tautulli_plays_by_day_of_week",
            "tautulli_plays_by_hour",
        ]

        for tool in expected_tools:
            assert tool in tool_names, f"Tool {tool} not found in listed tools"


class TestTautulliActivity:
    """Test tautulli_activity tool through MCP Client."""

    async def test_activity_no_streams(self, mcp_client: Client):
        """Test activity with no active streams."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"stream_count": 0, "sessions": []}

            result = await mcp_client.call_tool("tautulli_activity", arguments={})

            assert "No active streams on Plex" in _get_text_content(result)

    async def test_activity_with_streams(self, mcp_client: Client):
        """Test activity with active streams."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "stream_count": 2,
                "sessions": [
                    {
                        "friendly_name": "John",
                        "state": "playing",
                        "media_type": "movie",
                        "progress_percent": 50,
                        "title": "Test Movie",
                        "year": 2020,
                    }
                ],
                "total_bandwidth": 5000,
                "wan_bandwidth": 2000,
                "lan_bandwidth": 3000,
            }

            result = await mcp_client.call_tool("tautulli_activity", arguments={})

            text = _get_text_content(result)
            assert "2 active stream(s)" in text
            assert "John" in text
            assert "5.0 Mbps" in text


class TestTautulliHistory:
    """Test tautulli_history tool through MCP Client."""

    async def test_history_invalid_media_type(self, mcp_client: Client):
        """Test history with invalid media_type."""
        result = await mcp_client.call_tool(
            "tautulli_history", arguments={"media_type": "invalid"}
        )

        assert "Invalid media_type" in _get_text_content(result)

    async def test_history_no_results(self, mcp_client: Client):
        """Test history with no results."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": [], "recordsTotal": 0}

            result = await mcp_client.call_tool("tautulli_history", arguments={})

            assert "No playback history found" in _get_text_content(result)


class TestTautulliSearch:
    """Test tautulli_search tool through MCP Client."""

    async def test_search_empty_query(self, mcp_client: Client):
        """Test search with empty query."""
        result = await mcp_client.call_tool("tautulli_search", arguments={"query": ""})

        assert "Search query cannot be empty" in _get_text_content(result)

    async def test_search_with_results(self, mcp_client: Client):
        """Test search with results."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "results_list": {
                    "movie": [
                        {"title": "Test Movie", "year": 2020, "library_name": "Movies"}
                    ]
                }
            }

            result = await mcp_client.call_tool(
                "tautulli_search", arguments={"query": "test"}
            )

            text = _get_text_content(result)
            assert "Movies:" in text
            assert "Test Movie (2020)" in text


class TestTautulliStatus:
    """Test tautulli_status tool through MCP Client."""

    async def test_status_no_api_key(self, mcp_client: Client):
        """Test status when API key is not set."""
        # Patch the module-level variable
        with patch.object(tautulli, "TAUTULLI_API_KEY", ""):
            result = await mcp_client.call_tool("tautulli_status", arguments={})

            assert "NOT SET" in _get_text_content(result)

    async def test_status_reachable(self, mcp_client: Client):
        """Test status when server is reachable."""
        with (
            patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api,
            patch.object(tautulli, "TAUTULLI_URL", "http://test.local"),
            patch.object(tautulli, "TAUTULLI_API_KEY", "test-key"),
        ):
            mock_api.return_value = {
                "pms_name": "Test Server",
                "pms_version": "1.0.0",
            }

            result = await mcp_client.call_tool("tautulli_status", arguments={})

            text = _get_text_content(result)
            assert "Reachable: yes" in text
            assert "Test Server" in text


class TestTautulliServerInfo:
    """Test tautulli_server_info tool through MCP Client."""

    async def test_server_info(self, mcp_client: Client):
        """Test server_info."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "pms_name": "Test Server",
                "pms_version": "1.0.0",
                "pms_platform": "Linux",
                "pms_ip": "192.168.1.1",
                "pms_port": "32400",
                "pms_ssl": True,
                "pms_plexpass": False,
            }

            result = await mcp_client.call_tool("tautulli_server_info", arguments={})

            text = _get_text_content(result)
            assert "Test Server" in text
            assert "1.0.0" in text
            assert "Linux" in text


class TestTautulliMostWatched:
    """Test tautulli_most_watched tool through MCP Client."""

    async def test_most_watched_invalid_category(self, mcp_client: Client):
        """Test most_watched with invalid category."""
        result = await mcp_client.call_tool(
            "tautulli_most_watched", arguments={"category": "invalid"}
        )

        assert "Invalid category" in _get_text_content(result)

    async def test_most_watched_invalid_stat_type(self, mcp_client: Client):
        """Test most_watched with invalid stat_type."""
        result = await mcp_client.call_tool(
            "tautulli_most_watched", arguments={"stat_type": "invalid"}
        )

        assert "Invalid stat_type" in _get_text_content(result)


class TestTautulliRecentlyAdded:
    """Test tautulli_recently_added tool through MCP Client."""

    async def test_recently_added_invalid_media_type(self, mcp_client: Client):
        """Test recently_added with invalid media_type."""
        result = await mcp_client.call_tool(
            "tautulli_recently_added", arguments={"media_type": "invalid"}
        )

        assert "Invalid media_type" in _get_text_content(result)

    async def test_recently_added_with_items(self, mcp_client: Client):
        """Test recently_added with items."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "recently_added": [
                    {
                        "title": "Test Movie",
                        "year": 2020,
                        "media_type": "movie",
                        "library_name": "Movies",
                        "added_at": str(int(1234567890)),
                    }
                ]
            }

            result = await mcp_client.call_tool("tautulli_recently_added", arguments={})

            text = _get_text_content(result)
            assert "Test Movie (2020)" in text
            assert "movie" in text


class TestTautulliUserStats:
    """Test tautulli_user_stats tool through MCP Client."""

    async def test_user_stats_no_users(self, mcp_client: Client):
        """Test user_stats with no users."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": []}

            result = await mcp_client.call_tool("tautulli_user_stats", arguments={})

            assert "No users found" in _get_text_content(result)


class TestTautulliLibraryStats:
    """Test tautulli_library_stats tool through MCP Client."""

    async def test_library_stats_no_libraries(self, mcp_client: Client):
        """Test library_stats with no libraries."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": []}

            result = await mcp_client.call_tool("tautulli_library_stats", arguments={})

            assert "No libraries found" in _get_text_content(result)
