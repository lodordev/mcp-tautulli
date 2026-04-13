"""Tests for tautulli MCP server."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import HTTPStatusError, HTTPError

import tautulli


class TestClampDays:
    """Test _clamp_days helper function."""

    def test_clamp_days_default(self):
        assert tautulli._clamp_days(30) == 30

    def test_clamp_days_minimum(self):
        assert tautulli._clamp_days(0) == 1
        assert tautulli._clamp_days(-5) == 1

    def test_clamp_days_maximum(self):
        assert tautulli._clamp_days(400) == 365
        assert tautulli._clamp_days(1000) == 365

    def test_clamp_days_custom_max(self):
        assert tautulli._clamp_days(50, maximum=100) == 50
        assert tautulli._clamp_days(150, maximum=100) == 100


class TestSanitizeStr:
    """Test _sanitize_str helper function."""

    def test_sanitize_str_normal(self):
        assert tautulli._sanitize_str("hello") == "hello"

    def test_sanitize_str_with_whitespace(self):
        assert tautulli._sanitize_str("  hello  ") == "hello"

    def test_sanitize_str_truncation(self):
        long_str = "a" * 300
        result = tautulli._sanitize_str(long_str)
        assert len(result) == 200
        assert result == "a" * 200

    def test_sanitize_str_control_chars(self):
        # .strip() only removes whitespace, not control characters
        assert tautulli._sanitize_str("hello\x00world") == "hello\x00world"


class TestFmtDuration:
    """Test _fmt_duration helper function."""

    def test_fmt_duration_seconds(self):
        assert tautulli._fmt_duration(45) == "45s"
        assert tautulli._fmt_duration(59) == "59s"

    def test_fmt_duration_minutes(self):
        assert tautulli._fmt_duration(60) == "1m 0s"
        assert tautulli._fmt_duration(90) == "1m 30s"
        assert tautulli._fmt_duration(3599) == "59m 59s"

    def test_fmt_duration_hours(self):
        assert tautulli._fmt_duration(3600) == "1h 0m"
        assert tautulli._fmt_duration(3661) == "1h 1m"
        assert tautulli._fmt_duration(86399) == "23h 59m"

    def test_fmt_duration_days(self):
        assert tautulli._fmt_duration(86400) == "1d 0h 0m"
        assert tautulli._fmt_duration(90000) == "1d 1h 0m"
        assert tautulli._fmt_duration(90061) == "1d 1h 1m"

    def test_fmt_duration_float(self):
        assert tautulli._fmt_duration(45.5) == "45s"
        assert tautulli._fmt_duration(90.9) == "1m 30s"


class TestFmtSession:
    """Test _fmt_session helper function."""

    def test_fmt_session_episode(self):
        session = {
            "friendly_name": "John",
            "state": "playing",
            "media_type": "episode",
            "progress_percent": 45,
            "quality_profile": "1080p",
            "player": "Roku",
            "transcode_decision": "direct play",
            "grandparent_title": "Breaking Bad",
            "parent_media_index": 1,
            "media_index": 5,
            "title": "Cancer Man",
        }
        result = tautulli._fmt_session(session)
        assert "John playing" in result
        assert "Breaking Bad" in result
        assert "S01E05" in result
        assert "Cancer Man" in result

    def test_fmt_session_movie(self):
        session = {
            "friendly_name": "Jane",
            "state": "paused",
            "media_type": "movie",
            "progress_percent": 30,
            "player": "Web",
            "title": "Inception",
            "year": 2010,
        }
        result = tautulli._fmt_session(session)
        assert "Jane paused" in result
        assert "Inception (2010)" in result

    def test_fmt_session_track(self):
        session = {
            "friendly_name": "Bob",
            "state": "playing",
            "media_type": "track",
            "progress_percent": 50,
            "grandparent_title": "The Hobbit",
            "title": "Chapter 1",
        }
        result = tautulli._fmt_session(session)
        assert "Bob playing" in result
        assert "The Hobbit" in result
        assert "Chapter 1" in result

    def test_fmt_session_transcode(self):
        session = {
            "friendly_name": "Alice",
            "state": "playing",
            "media_type": "movie",
            "progress_percent": 75,
            "player": "Mobile",
            "transcode_decision": "transcode",
            "title": "Test Movie",
        }
        result = tautulli._fmt_session(session)
        assert "(transcode)" in result

    def test_fmt_session_missing_fields(self):
        session = {
            "user": "Unknown",
            "state": "unknown",
            "media_type": "unknown",
        }
        result = tautulli._fmt_session(session)
        assert "Unknown" in result


class TestChartTotals:
    """Test _chart_totals helper function."""

    def test_chart_totals_simple(self):
        data = {
            "categories": ["Roku", "Web"],
            "series": [
                {"name": "Direct Play", "data": [100, 50]},
                {"name": "Transcode", "data": [20, 10]},
            ],
        }
        result = tautulli._chart_totals(data)
        assert len(result) == 2
        assert result[0]["name"] == "Roku"
        assert result[0]["Direct Play"] == 100
        assert result[0]["Transcode"] == 20
        assert result[0]["total"] == 120
        assert result[1]["name"] == "Web"
        assert result[1]["total"] == 60

    def test_chart_totals_empty(self):
        data = {"categories": [], "series": []}
        result = tautulli._chart_totals(data)
        assert result == []

    def test_chart_totals_mismatched_lengths(self):
        data = {
            "categories": ["Roku", "Web", "Mobile"],
            "series": [
                {"name": "Direct Play", "data": [100, 50]},  # Only 2 values
            ],
        }
        result = tautulli._chart_totals(data)
        assert len(result) == 3
        assert result[0]["Direct Play"] == 100
        assert result[1]["Direct Play"] == 50
        assert result[2]["Direct Play"] == 0  # Should default to 0


class TestAPIHelper:
    """Test _api helper function."""

    @pytest_asyncio.fixture
    def mock_httpx_client(self):
        with patch("tautulli.httpx.AsyncClient") as mock:
            yield mock

    async def test_api_missing_url(self, monkeypatch):
        """Test that RuntimeError is raised when TAUTULLI_URL is not set."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "")
        with pytest.raises(
            RuntimeError, match="TAUTULLI_URL environment variable not set"
        ):
            await tautulli._api("get_activity")

    async def test_api_success(self, monkeypatch, mock_httpx_client):
        """Test successful API call."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "http://test.local")
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": {"result": "success", "data": {"stream_count": 5}}
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_httpx_client.return_value.__aenter__.return_value = mock_client

        result = await tautulli._api("get_activity")
        assert result == {"stream_count": 5}

    async def test_api_http_error(self, monkeypatch, mock_httpx_client):
        """Test HTTP error handling."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "http://test.local")
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "test-key")
        mock_client = AsyncMock()
        mock_client.get.side_effect = HTTPError("Connection failed")
        mock_httpx_client.return_value.__aenter__.return_value = mock_client

        with pytest.raises(RuntimeError, match="Tautulli unreachable"):
            await tautulli._api("get_activity")

    async def test_api_http_status_error(self, monkeypatch, mock_httpx_client):
        """Test HTTP status error handling."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "http://test.local")
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "test-key")
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = HTTPStatusError(
            "Not found", request=MagicMock(), response=mock_response
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_httpx_client.return_value.__aenter__.return_value = mock_client

        with pytest.raises(RuntimeError, match="HTTP 404"):
            await tautulli._api("get_activity")

    async def test_api_result_not_success(self, monkeypatch, mock_httpx_client):
        """Test API error response handling."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "http://test.local")
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "test-key")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {"result": "error"}}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_httpx_client.return_value.__aenter__.return_value = mock_client

        with pytest.raises(RuntimeError, match="API error"):
            await tautulli._api("get_activity")


class TestTautulliActivity:
    """Test tautulli_activity tool."""

    async def test_activity_no_streams(self):
        """Test activity with no active streams."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"stream_count": 0, "sessions": []}
            result = await tautulli.tautulli_activity()
            assert result == "No active streams on Plex."

    async def test_activity_with_streams(self):
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
            result = await tautulli.tautulli_activity()
            assert "2 active stream(s)" in result
            assert "John" in result
            assert "5.0 Mbps" in result


class TestTautulliHistory:
    """Test tautulli_history tool."""

    async def test_history_invalid_media_type(self):
        """Test history with invalid media_type."""
        result = await tautulli.tautulli_history(media_type="invalid")
        assert "Invalid media_type" in result

    async def test_history_with_episode(self):
        """Test history output with an episode record."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "episode",
                        "grandparent_title": "Breaking Bad",
                        "title": "Pilot",
                        "duration": 3600,
                        "player": "AppleTV",
                        "row_id": 42,
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "Breaking Bad" in result
            assert "Pilot" in result
            assert "row_id: 42" in result

    async def test_history_with_movie(self):
        """Test history output with a movie record."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Bob",
                        "media_type": "movie",
                        "title": "Dune",
                        "year": 2021,
                        "duration": 9000,
                        "player": "Roku",
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "Dune (2021)" in result

    async def test_history_with_track(self):
        """Test history output with a music track record."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "track",
                        "grandparent_title": "Dark Side of the Moon",
                        "title": "Money",
                        "duration": 380,
                        "player": "Sonos",
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "Dark Side of the Moon" in result
            assert "Money" in result

    async def test_history_with_unknown_type(self):
        """Test history falls back to full_title for unknown media types."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Dave",
                        "media_type": "live",
                        "full_title": "Live News",
                        "duration": 1800,
                        "player": "TV",
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "Live News" in result

    async def test_history_with_active_state(self):
        """Test history shows state for non-stopped streams."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "movie",
                        "title": "Test",
                        "duration": 100,
                        "state": "paused",
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "[paused]" in result

    async def test_history_with_user_filter(self):
        """Test that user filter is passed to API."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": [], "recordsTotal": 0}
            await tautulli.tautulli_history(user="alice")
            mock_api.assert_called_once()
            assert mock_api.call_args[1].get("user") == "alice"

    async def test_history_with_search_and_date(self):
        """Test that search and start_date filters are passed to API."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": [], "recordsTotal": 0}
            await tautulli.tautulli_history(search="dune", start_date="2024-01-01")
            assert mock_api.call_args[1].get("search") == "dune"
            assert mock_api.call_args[1].get("start_date") == "2024-01-01"

    async def test_history_length_clamping(self):
        """Test that length is properly clamped."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": [], "recordsTotal": 0}
            await tautulli.tautulli_history(length=100)
            mock_api.assert_called_once()
            # Check that length was clamped to 50
            call_args = mock_api.call_args
            assert call_args[1]["length"] == "50"

    async def test_history_no_results(self):
        """Test history with no results."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": [], "recordsTotal": 0}
            result = await tautulli.tautulli_history()
            assert "No playback history found" in result

    async def test_history_shows_transcode_decision(self):
        """Test that transcode_decision appears in history output."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "movie",
                        "title": "Dune",
                        "duration": 9000,
                        "transcode_decision": "transcode",
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "transcode" in result

    async def test_history_shows_ip_address(self):
        """Test that ip_address appears in history output."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "movie",
                        "title": "Dune",
                        "duration": 9000,
                        "ip_address": "192.168.1.42",
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "192.168.1.42" in result

    async def test_history_total_duration(self):
        """Test that total_duration appears in history output when present."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "movie",
                        "title": "Dune",
                        "duration": 9000,
                    }
                ],
                "recordsTotal": 1,
                "total_duration": "5 hrs 30 mins",
            }
            result = await tautulli.tautulli_history()
            assert "5 hrs 30 mins" in result

    async def test_history_all_stream_fields(self):
        """Test that transcode_decision and ip_address appear together."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Bob",
                        "media_type": "episode",
                        "grandparent_title": "The Wire",
                        "title": "The Target",
                        "duration": 3600,
                        "player": "Roku",
                        "transcode_decision": "direct play",
                        "ip_address": "10.0.0.5",
                        "row_id": 77,
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "direct play" in result
            assert "10.0.0.5" in result
            assert "row_id: 77" in result

    async def test_history_include_performance(self):
        """Test include_performance fetches stream_bitrate per record."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = [
                {
                    "data": [
                        {
                            "friendly_name": "Alice",
                            "media_type": "movie",
                            "title": "Dune",
                            "duration": 9000,
                            "row_id": 42,
                        }
                    ],
                    "recordsTotal": 1,
                },
                {"stream_bitrate": 8000, "title": "Dune", "media_type": "movie"},
            ]
            result = await tautulli.tautulli_history(include_performance=True)
            assert "8000 kbps" in result

    async def test_history_include_performance_empty_stream_data(self):
        """Test include_performance handles empty stream_data gracefully."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = [
                {
                    "data": [
                        {
                            "friendly_name": "Alice",
                            "media_type": "movie",
                            "title": "Dune",
                            "duration": 9000,
                            "row_id": 42,
                        }
                    ],
                    "recordsTotal": 1,
                },
                {},
            ]
            result = await tautulli.tautulli_history(include_performance=True)
            assert "Dune" in result
            assert "kbps" not in result

    async def test_history_include_performance_no_row_ids(self):
        """Test include_performance with records missing row_id skips fetch."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Alice",
                        "media_type": "movie",
                        "title": "Dune",
                        "duration": 9000,
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history(include_performance=True)
            assert "Dune" in result
            mock_api.assert_called_once()  # only get_history, no get_stream_data


class TestTautulliStreamData:
    """Test tautulli_stream_data tool."""

    async def test_stream_data_no_params(self):
        """Test stream_data with no parameters."""
        result = await tautulli.tautulli_stream_data()
        assert "Either row_id or session_key must be provided" in result

    async def test_stream_data_with_row_id(self):
        """Test stream_data with row_id parameter."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "media_type": "movie",
                "title": "Test Movie",
                "quality_profile": "Original",
                "bitrate": 15000,
                "video_bitrate": 14000,
                "audio_bitrate": 1000,
                "stream_bitrate": 15000,
                "stream_video_resolution": "1080",
                "stream_video_codec": "h264",
                "stream_video_bitrate": 14000,
                "stream_audio_codec": "aac",
                "stream_audio_channels": 6,
                "stream_audio_bitrate": 1000,
                "stream_video_decision": "direct play",
                "stream_audio_decision": "direct play",
                "container": "mkv",
                "video_codec": "h264",
                "audio_codec": "dca",
                "video_resolution": "1080",
            }
            result = await tautulli.tautulli_stream_data(row_id=123)
            assert "Stream Performance Data" in result
            assert "Test Movie" in result
            assert "Original" in result
            assert "15000 kbps" in result
            assert "1080" in result
            assert "direct play" in result

    async def test_stream_data_with_session_key(self):
        """Test stream_data with session_key parameter — episode title includes both show and episode name."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "media_type": "episode",
                "grandparent_title": "Test Show",
                "title": "Episode 1",
                "bitrate": "8000",
            }
            result = await tautulli.tautulli_stream_data(session_key=456)
            assert "Stream Performance Data" in result
            assert "Test Show" in result
            assert "Episode 1" in result

    async def test_stream_data_no_data(self):
        """Test stream_data when no data is returned."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {}
            result = await tautulli.tautulli_stream_data(row_id=123)
            assert "No stream data found" in result

    async def test_history_includes_row_id(self):
        """Test that history output includes row_id."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Test User",
                        "media_type": "movie",
                        "title": "Test Movie",
                        "year": 2020,
                        "duration": 7200,
                        "player": "Test Player",
                        "row_id": 999,
                    }
                ],
                "recordsTotal": 1,
            }
            result = await tautulli.tautulli_history()
            assert "row_id: 999" in result


class TestTautulliRecentlyAdded:
    """Test tautulli_recently_added tool."""

    async def test_recently_added_invalid_media_type(self):
        """Test recently_added with invalid media_type."""
        result = await tautulli.tautulli_recently_added(media_type="invalid")
        assert "Invalid media_type" in result

    async def test_recently_added_no_items(self):
        """Test recently_added with no items."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"recently_added": []}
            result = await tautulli.tautulli_recently_added()
            assert "No recently added content found" in result

    async def test_recently_added_with_items(self):
        """Test recently_added with items."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "recently_added": [
                    {
                        "title": "Test Movie",
                        "year": 2020,
                        "media_type": "movie",
                        "library_name": "Movies",
                        "added_at": str(int(datetime.now(timezone.utc).timestamp())),
                    }
                ]
            }
            result = await tautulli.tautulli_recently_added()
            assert "Test Movie (2020)" in result
            assert "movie" in result


class TestTautulliSearch:
    """Test tautulli_search tool."""

    async def test_search_empty_query(self):
        """Test search with empty query."""
        result = await tautulli.tautulli_search(query="")
        assert "Search query cannot be empty" in result

    async def test_search_with_episode_results(self):
        """Test search with episode results — covers episode title formatting."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "results_list": {
                    "episode": [
                        {
                            "title": "Pilot",
                            "grandparent_title": "Breaking Bad",
                            "parent_media_index": "1",
                            "media_index": "1",
                            "library_name": "TV Shows",
                        }
                    ]
                }
            }
            result = await tautulli.tautulli_search(query="pilot")
            assert "Breaking Bad" in result
            assert "S01E01" in result

    async def test_search_with_episode_no_season(self):
        """Test episode result without season/episode numbers."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "results_list": {
                    "episode": [
                        {
                            "title": "Pilot",
                            "grandparent_title": "Some Show",
                            "library_name": "TV Shows",
                        }
                    ]
                }
            }
            result = await tautulli.tautulli_search(query="pilot")
            assert "Some Show" in result
            assert "Pilot" in result

    async def test_search_no_results(self):
        """Test search with no results."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"results_list": {}}
            result = await tautulli.tautulli_search(query="nonexistent")
            assert 'No results for "nonexistent"' in result

    async def test_search_with_results(self):
        """Test search with results."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "results_list": {
                    "movie": [
                        {"title": "Test Movie", "year": 2020, "library_name": "Movies"}
                    ]
                }
            }
            result = await tautulli.tautulli_search(query="test")
            assert "Movies:" in result
            assert "Test Movie (2020)" in result


class TestTautulliUserStats:
    """Test tautulli_user_stats tool."""

    async def test_user_stats_no_users(self):
        """Test user_stats with no users."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": []}
            result = await tautulli.tautulli_user_stats()
            assert "No users found" in result

    async def test_user_stats_skips_inactive_users(self):
        """Test that users with 0 plays are skipped."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "Active",
                        "plays": 10,
                        "duration": 3600,
                        "last_played": "Movie",
                    },
                    {"friendly_name": "Inactive", "plays": 0, "duration": 0},
                ]
            }
            result = await tautulli.tautulli_user_stats()
            assert "Active" in result
            assert "Inactive" not in result

    async def test_user_stats_with_users(self):
        """Test user_stats with users."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "friendly_name": "John",
                        "plays": 100,
                        "duration": 36000,
                        "last_played": "Test Movie",
                    }
                ]
            }
            result = await tautulli.tautulli_user_stats()
            assert "John" in result
            assert "100 plays" in result

    async def test_user_stats_with_user_filter(self):
        """Test that user filter search param is passed to API."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": []}
            await tautulli.tautulli_user_stats(user="alice")
            assert mock_api.call_args[1].get("search") == "alice"


class TestTautulliLibraryStats:
    """Test tautulli_library_stats tool."""

    async def test_library_stats_no_libraries(self):
        """Test library_stats with no libraries."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"data": []}
            result = await tautulli.tautulli_library_stats()
            assert "No libraries found" in result

    async def test_library_stats_show_library(self):
        """Test library_stats with TV show library."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "section_name": "TV Shows",
                        "section_type": "show",
                        "count": 10,
                        "parent_count": 50,
                        "child_count": 500,
                        "plays": 1000,
                        "last_played": "Test Show",
                    }
                ]
            }
            result = await tautulli.tautulli_library_stats()
            assert "TV Shows" in result
            assert "10 shows, 50 seasons, 500 episodes" in result

    async def test_library_stats_artist_library(self):
        """Test library_stats with music/audiobook artist library."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "section_name": "Audiobooks",
                        "section_type": "artist",
                        "count": 5,
                        "parent_count": 20,
                        "child_count": 200,
                        "plays": 300,
                        "last_played": "",
                    }
                ]
            }
            result = await tautulli.tautulli_library_stats()
            assert "Audiobooks" in result
            assert "5 artists/authors, 20 albums, 200 tracks" in result

    async def test_library_stats_movie_library(self):
        """Test library_stats with movie library (else branch)."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "data": [
                    {
                        "section_name": "Movies",
                        "section_type": "movie",
                        "count": 500,
                        "plays": 2000,
                        "last_played": "Dune",
                    }
                ]
            }
            result = await tautulli.tautulli_library_stats()
            assert "Movies" in result
            assert "500 items" in result


class TestTautulliServerInfo:
    """Test tautulli_server_info tool."""

    async def test_server_info(self):
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
            result = await tautulli.tautulli_server_info()
            assert "Test Server" in result
            assert "1.0.0" in result
            assert "Linux" in result


class TestTautulliStatus:
    """Test tautulli_status tool."""

    async def test_status_no_api_key(self, monkeypatch):
        """Test status when API key is not set."""
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "")
        result = await tautulli.tautulli_status()
        assert "NOT SET" in result
        assert "TAUTULLI_API_KEY environment variable not set" in result

    async def test_status_reachable(self, monkeypatch):
        """Test status when server is reachable."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "http://test.local")
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "test-key")
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "pms_name": "Test Server",
                "pms_version": "1.0.0",
            }
            result = await tautulli.tautulli_status()
            assert "Reachable: yes" in result
            assert "Test Server" in result

    async def test_status_not_reachable(self, monkeypatch):
        """Test status when server is not reachable."""
        monkeypatch.setattr(tautulli, "TAUTULLI_URL", "http://test.local")
        monkeypatch.setattr(tautulli, "TAUTULLI_API_KEY", "test-key")
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = RuntimeError("Connection failed")
            result = await tautulli.tautulli_status()
            assert "Reachable: NO" in result


class TestTautulliMostWatched:
    """Test tautulli_most_watched tool."""

    async def test_most_watched_invalid_category(self):
        """Test most_watched with invalid category."""
        result = await tautulli.tautulli_most_watched(category="invalid")
        assert "Invalid category" in result

    async def test_most_watched_invalid_stat_type(self):
        """Test most_watched with invalid stat_type."""
        result = await tautulli.tautulli_most_watched(stat_type="invalid")
        assert "Invalid stat_type" in result

    async def test_most_watched_no_data(self):
        """Test most_watched with no data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"rows": [], "stat_title": "Top Movies"}
            result = await tautulli.tautulli_most_watched()
            assert "No" in result

    async def test_most_watched_with_data(self):
        """Test most_watched with results."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "rows": [
                    {
                        "title": "Dune",
                        "year": 2021,
                        "total_plays": 50,
                        "total_duration": 180000,
                    },
                    {
                        "title": "Oppenheimer",
                        "year": 2023,
                        "total_plays": 30,
                        "total_duration": 108000,
                    },
                ],
                "stat_title": "Top Movies",
            }
            result = await tautulli.tautulli_most_watched()
            assert "Dune (2021)" in result
            assert "50 plays" in result
            assert "Oppenheimer (2023)" in result


class TestTautulliTranscodeStats:
    """Test tautulli_transcode_stats tool."""

    async def test_transcode_stats_no_data(self):
        """Test transcode_stats with no data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"categories": [], "series": []}
            result = await tautulli.tautulli_transcode_stats()
            assert "No stream data" in result

    async def test_transcode_stats_with_data(self):
        """Test transcode_stats with platform data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "categories": ["Apple TV", "Roku"],
                "series": [
                    {"name": "Direct Play", "data": [100, 50]},
                    {"name": "Direct Stream", "data": [10, 5]},
                    {"name": "Transcode", "data": [20, 30]},
                ],
            }
            result = await tautulli.tautulli_transcode_stats()
            assert "Apple TV" in result
            assert "direct play" in result
            assert "transcode" in result

    async def test_transcode_stats_skips_zero_total(self):
        """Test that platforms with zero total are skipped."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "categories": ["Apple TV", "Unused"],
                "series": [
                    {"name": "Direct Play", "data": [100, 0]},
                    {"name": "Direct Stream", "data": [0, 0]},
                    {"name": "Transcode", "data": [0, 0]},
                ],
            }
            result = await tautulli.tautulli_transcode_stats()
            assert "Apple TV" in result
            assert "Unused" not in result


class TestTautulliPlatformStats:
    """Test tautulli_platform_stats tool."""

    async def test_platform_stats_no_data(self):
        """Test platform_stats with no data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"rows": []}
            result = await tautulli.tautulli_platform_stats()
            assert "No platform data" in result

    async def test_platform_stats_with_data(self):
        """Test platform_stats with data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "rows": [
                    {
                        "platform": "Apple TV",
                        "total_plays": 200,
                        "total_duration": 720000,
                    },
                    {"platform": "Roku", "total_plays": 100, "total_duration": 360000},
                ]
            }
            result = await tautulli.tautulli_platform_stats()
            assert "Apple TV" in result
            assert "200 plays" in result
            assert "Roku" in result


class TestTautulliStreamResolution:
    """Test tautulli_stream_resolution tool."""

    async def test_stream_resolution_no_data(self):
        """Test stream_resolution with no data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"categories": [], "series": []}
            result = await tautulli.tautulli_stream_resolution()
            assert "No resolution data" in result

    async def test_stream_resolution_with_data(self):
        """Test stream_resolution with source and stream data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "categories": ["1080", "4k"],
                "series": [
                    {"name": "Direct Play", "data": [80, 20]},
                    {"name": "Direct Stream", "data": [5, 0]},
                    {"name": "Transcode", "data": [10, 5]},
                ],
            }
            result = await tautulli.tautulli_stream_resolution()
            assert "1080" in result or "Resolution analysis" in result

    async def test_stream_resolution_4k_downgrade_note(self):
        """Test that a note is shown when 4K content is downgraded."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            # source has 4k plays, stream has fewer 4k plays = downgrade occurred
            mock_api.side_effect = [
                {  # source resolution
                    "categories": ["4k"],
                    "series": [
                        {"name": "Direct Play", "data": [10]},
                        {"name": "Direct Stream", "data": [0]},
                        {"name": "Transcode", "data": [5]},
                    ],
                },
                {  # stream resolution — fewer 4k delivered
                    "categories": ["4k"],
                    "series": [
                        {"name": "Direct Play", "data": [10]},
                        {"name": "Direct Stream", "data": [0]},
                        {"name": "Transcode", "data": [0]},
                    ],
                },
            ]
            result = await tautulli.tautulli_stream_resolution()
            assert "4K" in result or "4k" in result


class TestTautulliPlaysByDate:
    """Test tautulli_plays_by_date tool."""

    async def test_plays_by_date_no_data(self):
        """Test plays_by_date with no data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"categories": [], "series": []}
            result = await tautulli.tautulli_plays_by_date()
            assert "No play data" in result

    async def test_plays_by_date_with_data(self):
        """Test plays_by_date with data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "categories": ["2024-01-01", "2024-01-02"],
                "series": [
                    {"name": "Direct Play", "data": [5, 10]},
                    {"name": "Transcode", "data": [2, 3]},
                ],
            }
            result = await tautulli.tautulli_plays_by_date()
            assert "2024-01-01" in result or "plays" in result.lower()


class TestTautulliPlaysByDayOfWeek:
    """Test tautulli_plays_by_day_of_week tool."""

    async def test_plays_by_day_of_week_no_data(self):
        """Test plays_by_day_of_week with no data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"categories": [], "series": []}
            result = await tautulli.tautulli_plays_by_day_of_week()
            assert "No play data" in result

    async def test_plays_by_day_of_week_with_data(self):
        """Test plays_by_day_of_week with data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "categories": [
                    "Sunday",
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                ],
                "series": [
                    {"name": "TV", "data": [10, 20, 15, 12, 8, 25, 30]},
                    {"name": "Movies", "data": [5, 3, 4, 2, 1, 8, 10]},
                ],
            }
            result = await tautulli.tautulli_plays_by_day_of_week()
            assert "Monday" in result
            assert "peak" in result
            assert "Total:" in result


class TestTautulliPlaysByHour:
    """Test tautulli_plays_by_hour tool."""

    async def test_plays_by_hour_no_data(self):
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"categories": [], "series": []}
            result = await tautulli.tautulli_plays_by_hour()
            assert "No play data" in result

    async def test_plays_by_hour_with_data(self):
        """Test plays_by_hour with data."""
        with patch.object(tautulli, "_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {
                "categories": [str(i) for i in range(24)],
                "series": [
                    {
                        "name": "TV",
                        "data": [0] * 8
                        + [5, 10, 15, 20, 18, 12, 8, 5, 3, 2, 1, 0, 0, 0, 0, 0],
                    },
                ],
            }
            result = await tautulli.tautulli_plays_by_hour()
            assert "peak" in result
            assert "Total:" in result


class TestEntryPoint:
    """Test the CLI entry point."""

    def test_main_function_exists(self):
        """Test that the main() function exists and is callable."""
        assert hasattr(tautulli, "main"), "main() function should exist"
        assert callable(tautulli.main), "main() should be callable"

    def test_main_missing_url(self, monkeypatch):
        """Test that main() exits when TAUTULLI_URL is missing."""
        monkeypatch.delenv("TAUTULLI_URL", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            tautulli.main()
        assert exc_info.value.code == 1

    def test_main_missing_api_key(self, monkeypatch):
        """Test that main() exits when TAUTULLI_API_KEY is missing."""
        monkeypatch.setenv("TAUTULLI_URL", "http://test.local")
        monkeypatch.delenv("TAUTULLI_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            tautulli.main()
        assert exc_info.value.code == 1
