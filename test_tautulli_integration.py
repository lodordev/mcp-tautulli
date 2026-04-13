"""Integration tests for tautulli MCP server against a live Tautulli instance.

These tests are skipped unless both TAUTULLI_URL and TAUTULLI_API_KEY are set.

Run manually:
    uv run pytest test_tautulli_integration.py -v
"""

import os

import pytest

import tautulli

pytestmark = pytest.mark.skipif(
    not os.getenv("TAUTULLI_URL") or not os.getenv("TAUTULLI_API_KEY"),
    reason="TAUTULLI_URL and TAUTULLI_API_KEY must be set for integration tests",
)


class TestIntegrationTools:
    """Live integration tests — verify real API responses return non-empty strings with expected shape."""

    async def test_status_live(self):
        result = await tautulli.tautulli_status()
        assert isinstance(result, str)
        assert "Tautulli URL:" in result
        assert "Reachable: yes" in result

    async def test_activity_live(self):
        result = await tautulli.tautulli_activity()
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_history_live(self):
        result = await tautulli.tautulli_history(length=5)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_server_info_live(self):
        result = await tautulli.tautulli_server_info()
        assert isinstance(result, str)
        assert "Plex Server:" in result

    async def test_library_stats_live(self):
        result = await tautulli.tautulli_library_stats()
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_user_stats_live(self):
        result = await tautulli.tautulli_user_stats()
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_most_watched_live(self):
        result = await tautulli.tautulli_most_watched(days=30)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_transcode_stats_live(self):
        result = await tautulli.tautulli_transcode_stats(days=30)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_platform_stats_live(self):
        result = await tautulli.tautulli_platform_stats(days=30)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_stream_resolution_live(self):
        result = await tautulli.tautulli_stream_resolution(days=30)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_plays_by_date_live(self):
        result = await tautulli.tautulli_plays_by_date(days=14)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_plays_by_day_of_week_live(self):
        result = await tautulli.tautulli_plays_by_day_of_week(days=30)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_plays_by_hour_live(self):
        result = await tautulli.tautulli_plays_by_hour(days=30)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_search_live(self):
        result = await tautulli.tautulli_search(query="the")
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_recently_added_live(self):
        result = await tautulli.tautulli_recently_added(count=5)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_stream_data_invalid_live(self):
        result = await tautulli.tautulli_stream_data()
        assert "Either row_id or session_key must be provided" in result
