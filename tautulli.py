"""Tautulli MCP Server — Plex monitoring via MCP tools.

Single-file FastMCP server providing read-only access to Tautulli's API.
Designed for Claude Code integration via stdio transport.

Tools:
  tautulli_activity        — Who's watching right now
  tautulli_history         — Recent playback history
  tautulli_user_stats      — Per-user watch statistics
  tautulli_library_stats   — Library-level statistics
  tautulli_most_watched    — Top content by plays (configurable time range)
  tautulli_server_info     — Plex server identity and status
  tautulli_status          — Server configuration and reachability
  tautulli_transcode_stats — Direct play vs transcode breakdown by platform
  tautulli_platform_stats  — Top platforms/devices by plays and watch time
  tautulli_stream_resolution — Source vs delivered resolution analysis
  tautulli_plays_by_date   — Daily play counts over time by stream type

Environment variables:
  TAUTULLI_URL        — Tautulli base URL (required)
  TAUTULLI_API_KEY    — Tautulli API key (required)
  TAUTULLI_TLS_VERIFY — Verify TLS certificates (default: true)
"""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

# ── Configuration ────────────────────────────────────────────────────────

TAUTULLI_URL = os.environ.get("TAUTULLI_URL", "")
TAUTULLI_API_KEY = os.environ.get("TAUTULLI_API_KEY", "")
# Default true: set to "false" if using self-signed certs (e.g. Tailscale serve).
TLS_VERIFY = os.environ.get("TAUTULLI_TLS_VERIFY", "true").lower() in ("true", "1", "yes")

# ── Input validation ────────────────────────────────────────────────────

_VALID_MEDIA_TYPES = {"movie", "episode", "track", "live"}
_VALID_CATEGORIES = {"tv", "movies", "music", "users"}
_VALID_STAT_TYPES = {"plays", "duration"}
_MAX_STRING_LEN = 200
_MAX_DAYS = 365


def _clamp_days(days: int, default: int = 30, maximum: int = _MAX_DAYS) -> int:
    """Clamp days parameter to a safe range."""
    return min(max(1, days), maximum)


def _sanitize_str(value: str) -> str:
    """Truncate and strip control characters from user input."""
    return value[:_MAX_STRING_LEN].strip()

TIMEOUT = httpx.Timeout(15.0, connect=10.0)

mcp = FastMCP("tautulli")


# ── API helper ───────────────────────────────────────────────────────────


async def _api(cmd: str, **params) -> dict:
    """Call a Tautulli API command and return the response data.

    Raises RuntimeError on failure so FastMCP returns a proper error to the client.
    """
    if not TAUTULLI_URL:
        raise RuntimeError("TAUTULLI_URL environment variable not set")
    url = f"{TAUTULLI_URL.rstrip('/')}/api/v2"
    query = {"apikey": TAUTULLI_API_KEY, "cmd": cmd, **params}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=TLS_VERIFY) as client:
            resp = await client.get(url, params=query)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError:
        raise RuntimeError(f"Tautulli returned HTTP {resp.status_code} for {cmd}")
    except httpx.HTTPError:
        raise RuntimeError(f"Tautulli unreachable for {cmd}")

    response = body.get("response", {})
    if response.get("result") != "success":
        raise RuntimeError(f"Tautulli API error for {cmd}")

    return response.get("data", {})


# ── Formatting helpers ───────────────────────────────────────────────────


def _fmt_duration(seconds: int | float) -> str:
    """Format seconds into human-readable duration."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours < 24:
        return f"{hours}h {mins}m"
    days = hours // 24
    hours = hours % 24
    return f"{days}d {hours}h {mins}m"


def _fmt_session(s: dict) -> str:
    """Format a single streaming session into a readable line."""
    user = s.get("friendly_name") or s.get("user", "Unknown")
    state = s.get("state", "unknown")
    media_type = s.get("media_type", "")
    progress = s.get("progress_percent", "?")
    quality = s.get("quality_profile", "")
    player = s.get("player", "")
    transcode = s.get("transcode_decision", "direct play")

    # Build title based on media type
    if media_type == "episode":
        show = s.get("grandparent_title", "")
        ep_num = f"S{int(s.get('parent_media_index', 0)):02d}E{int(s.get('media_index', 0)):02d}"
        ep_title = s.get("title", "")
        title = f"{show} {ep_num} — {ep_title}" if ep_title else f"{show} {ep_num}"
    elif media_type == "movie":
        title = s.get("title", "Unknown")
        year = s.get("year", "")
        if year:
            title = f"{title} ({year})"
    elif media_type == "track":
        book = s.get("grandparent_title", "")
        chapter = s.get("title", "")
        title = f"{book} — {chapter}" if book else chapter
    else:
        title = s.get("full_title") or s.get("title", "Unknown")

    parts = [f"{user} {state} \"{title}\""]
    parts.append(f"{progress}%")
    if player:
        parts.append(f"on {player}")
    if transcode and transcode != "direct play":
        parts.append(f"({transcode})")
    elif quality:
        parts.append(f"({quality})")

    return " — ".join([parts[0], ", ".join(parts[1:])])


# ── Tools ────────────────────────────────────────────────────────────────


@mcp.tool()
async def tautulli_activity() -> str:
    """Get current Plex streaming activity — who's watching what, playback state, progress, and quality.

    Use this before restarting Plex or rebooting servers to check for active streams.
    """
    data = await _api("get_activity")
    stream_count = int(data.get("stream_count", 0))
    sessions = data.get("sessions", [])

    if not sessions:
        return "No active streams on Plex."

    lines = [f"{stream_count} active stream(s):\n"]
    for s in sessions:
        lines.append(f"  • {_fmt_session(s)}")

    # Bandwidth summary
    total_bw = data.get("total_bandwidth", 0)
    wan_bw = data.get("wan_bandwidth", 0)
    lan_bw = data.get("lan_bandwidth", 0)
    if total_bw:
        lines.append(f"\nBandwidth: {int(total_bw) / 1000:.1f} Mbps total (LAN: {int(lan_bw) / 1000:.1f}, WAN: {int(wan_bw) / 1000:.1f})")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_history(
    length: int = 10,
    user: str = "",
    media_type: str = "",
    search: str = "",
    start_date: str = "",
) -> str:
    """Get recent Plex playback history.

    Args:
        length: Number of records to return (default 10, max 50).
        user: Filter by username.
        media_type: Filter by type: "movie", "episode", "track" (audiobook).
        search: Text search in titles.
        start_date: Only show history from this date (YYYY-MM-DD).
    """
    length = min(max(1, length), 50)
    params: dict = {"length": str(length)}
    if user:
        params["user"] = _sanitize_str(user)
    if media_type:
        if media_type not in _VALID_MEDIA_TYPES:
            return f"Invalid media_type: must be one of {', '.join(sorted(_VALID_MEDIA_TYPES))}"
        params["media_type"] = media_type
    if search:
        params["search"] = _sanitize_str(search)
    if start_date:
        params["start_date"] = _sanitize_str(start_date)

    data = await _api("get_history", **params)
    records = data.get("data", [])
    total = data.get("recordsTotal", 0)

    if not records:
        return "No playback history found matching filters."

    lines = [f"Playback history ({len(records)} of {total} records):\n"]
    for r in records:
        user_name = r.get("friendly_name") or r.get("user", "?")
        media = r.get("media_type", "")
        duration = _fmt_duration(r.get("duration", 0))
        player = r.get("player", "")

        if media == "episode":
            show = r.get("grandparent_title", "")
            ep = r.get("title", "")
            title = f"{show} — {ep}" if show else ep
        elif media == "movie":
            title = r.get("title", "Unknown")
            year = r.get("year", "")
            if year:
                title = f"{title} ({year})"
        elif media == "track":
            book = r.get("grandparent_title", "")
            chapter = r.get("title", "")
            title = f"{book} — {chapter}" if book else chapter
        else:
            title = r.get("full_title") or r.get("title", "Unknown")

        state = r.get("state", "")
        state_str = f" [{state}]" if state and state != "stopped" else ""
        player_str = f" on {player}" if player else ""
        lines.append(f"  • {user_name}: \"{title}\" ({duration}{player_str}){state_str}")

    total_dur = data.get("total_duration", "")
    if total_dur:
        lines.append(f"\nTotal watch time: {total_dur}")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_user_stats(user: str = "", days: int = 30) -> str:
    """Get per-user watch statistics — total plays, watch time, last seen.

    Args:
        user: Filter to a specific username. If empty, shows all active users.
        days: Time range in days for stats (default 30).
    """
    days = _clamp_days(days)
    params: dict = {"length": "25", "order_column": "plays", "order_dir": "desc"}
    if user:
        params["search"] = _sanitize_str(user)

    data = await _api("get_users_table", **params)
    users = data.get("data", [])

    if not users:
        return "No users found."

    lines = ["User statistics:\n"]
    for u in users:
        name = u.get("friendly_name") or u.get("username", "?")
        plays = u.get("plays", 0)
        duration = _fmt_duration(u.get("duration", 0))
        last_played = u.get("last_played", "")
        last_seen = u.get("last_seen")

        if plays == 0:
            continue  # Skip inactive users

        parts = [f"  • {name}: {plays} plays, {duration} watched"]
        if last_played:
            parts.append(f"last: \"{last_played}\"")

        lines.append(" — ".join(parts))

    return "\n".join(lines)


@mcp.tool()
async def tautulli_library_stats() -> str:
    """Get library-level statistics — item counts, total plays, and last played content per library."""
    data = await _api("get_libraries_table")
    libraries = data.get("data", [])

    if not libraries:
        return "No libraries found."

    lines = ["Library statistics:\n"]
    for lib in libraries:
        name = lib.get("section_name", "?")
        section_type = lib.get("section_type", "")
        count = lib.get("count", 0)
        plays = lib.get("plays", 0)
        last = lib.get("last_played", "")

        # Build count string based on type
        if section_type == "show":
            seasons = lib.get("parent_count", 0)
            episodes = lib.get("child_count", 0)
            count_str = f"{count} shows, {seasons} seasons, {episodes} episodes"
        elif section_type == "artist":
            albums = lib.get("parent_count", 0)
            tracks = lib.get("child_count", 0)
            count_str = f"{count} artists/authors, {albums} albums, {tracks} tracks"
        else:
            count_str = f"{count} items"

        last_str = f" — last: \"{last}\"" if last else ""
        lines.append(f"  • {name} ({section_type}): {count_str}, {plays} plays{last_str}")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_most_watched(
    days: int = 7,
    stat_type: str = "plays",
    category: str = "tv",
) -> str:
    """Get most watched content over a time period.

    Args:
        days: Time range in days (default 7).
        stat_type: Sort by "plays" (total plays) or "duration" (total watch time).
        category: Content category — "tv", "movies", "music", or "users" (top users).
    """
    days = _clamp_days(days)
    if category.lower() not in _VALID_CATEGORIES:
        return f"Invalid category: must be one of {', '.join(sorted(_VALID_CATEGORIES))}"
    if stat_type not in _VALID_STAT_TYPES:
        return f"Invalid stat_type: must be one of {', '.join(sorted(_VALID_STAT_TYPES))}"
    stat_map = {
        "tv": "top_tv",
        "movies": "top_movies",
        "music": "top_music",
        "users": "top_users",
    }
    stat_id = stat_map.get(category.lower(), "top_tv")
    stats_type = "total_plays" if stat_type == "plays" else "total_duration"

    data = await _api("get_home_stats", time_range=str(days), stat_id=stat_id, stats_type=stats_type)
    rows = data.get("rows", [])
    title = data.get("stat_title", f"Top {category}")

    if not rows:
        return f"No {category} data for the last {days} days."

    lines = [f"{title} (last {days} days):\n"]
    for i, r in enumerate(rows[:10], 1):
        name = r.get("title") or r.get("friendly_name", "?")
        year = r.get("year", "")
        plays = r.get("total_plays", 0)
        duration = _fmt_duration(r.get("total_duration", 0))

        name_str = f"{name} ({year})" if year else name
        lines.append(f"  {i}. {name_str} — {plays} plays, {duration}")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_server_info() -> str:
    """Get Plex server identity — name, version, platform, and connection details."""
    data = await _api("get_server_info")

    name = data.get("pms_name", "Unknown")
    version = data.get("pms_version", "?")
    platform = data.get("pms_platform", "?")
    ip = data.get("pms_ip", "?")
    port = data.get("pms_port", "?")
    ssl = "yes" if data.get("pms_ssl") else "no"
    plexpass = "yes" if data.get("pms_plexpass") else "no"

    return (
        f"Plex Server: {name}\n"
        f"  Version: {version}\n"
        f"  Platform: {platform}\n"
        f"  Address: {ip}:{port} (SSL: {ssl})\n"
        f"  PlexPass: {plexpass}"
    )


@mcp.tool()
async def tautulli_status() -> str:
    """Check Tautulli server configuration and reachability."""
    lines = [
        f"Tautulli URL: {TAUTULLI_URL}",
        f"API Key: {'configured' if TAUTULLI_API_KEY else 'NOT SET'}",
        f"TLS Verify: {TLS_VERIFY}",
    ]

    if not TAUTULLI_API_KEY:
        lines.append("\nError: TAUTULLI_API_KEY environment variable not set.")
        return "\n".join(lines)

    try:
        data = await _api("get_server_info")
        name = data.get("pms_name", "Unknown")
        version = data.get("pms_version", "?")
        lines.append(f"\nReachable: yes — Plex server \"{name}\" v{version}")
    except Exception:
        lines.append("\nReachable: NO — connection failed")

    return "\n".join(lines)


# ── Chart helper ─────────────────────────────────────────────────────────


def _chart_totals(data: dict) -> list[dict]:
    """Convert Tautulli chart format {categories, series} into per-category totals.

    Returns list of dicts: [{"name": "Roku", "Direct Play": 81, "Transcode": 31, ...}, ...]
    """
    categories = data.get("categories", [])
    series = data.get("series", [])
    result = []
    for i, cat in enumerate(categories):
        row: dict = {"name": cat}
        total = 0
        for s in series:
            val = s["data"][i] if i < len(s["data"]) else 0
            row[s["name"]] = val
            total += val
        row["total"] = total
        result.append(row)
    return result


# ── Analytics tools ──────────────────────────────────────────────────────


@mcp.tool()
async def tautulli_transcode_stats(days: int = 30) -> str:
    """Get direct play vs transcode breakdown by platform — shows which devices cause the most transcoding load.

    Args:
        days: Time range in days (default 30).
    """
    days = _clamp_days(days)
    data = await _api("get_stream_type_by_top_10_platforms", time_range=str(days))
    rows = _chart_totals(data)

    if not rows:
        return f"No stream data for the last {days} days."

    # Compute overall totals
    all_dp = sum(r.get("Direct Play", 0) for r in rows)
    all_ds = sum(r.get("Direct Stream", 0) for r in rows)
    all_tc = sum(r.get("Transcode", 0) for r in rows)
    all_total = all_dp + all_ds + all_tc

    lines = [f"Stream type by platform (last {days} days, {all_total} total plays):\n"]

    for r in rows:
        dp = r.get("Direct Play", 0)
        ds = r.get("Direct Stream", 0)
        tc = r.get("Transcode", 0)
        total = r["total"]
        if total == 0:
            continue
        tc_pct = tc / total * 100

        parts = []
        if dp:
            parts.append(f"{dp} direct play")
        if ds:
            parts.append(f"{ds} direct stream")
        if tc:
            parts.append(f"{tc} transcode")

        lines.append(f"  • {r['name']}: {total} plays — {', '.join(parts)} ({tc_pct:.0f}% transcode)")

    if all_total:
        overall_tc_pct = all_tc / all_total * 100
        lines.append(f"\nOverall: {all_dp} direct play, {all_ds} direct stream, {all_tc} transcode ({overall_tc_pct:.0f}% transcode)")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_platform_stats(days: int = 30) -> str:
    """Get top platforms/devices by plays and total watch time.

    Args:
        days: Time range in days (default 30).
    """
    days = _clamp_days(days)
    data = await _api("get_home_stats", time_range=str(days), stat_id="top_platforms")
    rows = data.get("rows", [])

    if not rows:
        return f"No platform data for the last {days} days."

    lines = [f"Top platforms (last {days} days):\n"]
    for i, r in enumerate(rows[:10], 1):
        platform = r.get("platform", "Unknown")
        plays = r.get("total_plays", 0)
        duration = _fmt_duration(r.get("total_duration", 0))
        lines.append(f"  {i}. {platform} — {plays} plays, {duration} watched")

    total_plays = sum(r.get("total_plays", 0) for r in rows)
    total_dur = sum(r.get("total_duration", 0) for r in rows)
    lines.append(f"\nTotal: {total_plays} plays, {_fmt_duration(total_dur)} watched across {len(rows)} platforms")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_stream_resolution(days: int = 30) -> str:
    """Get source vs delivered resolution analysis — shows what quality your library serves and what clients actually receive.

    Args:
        days: Time range in days (default 30).
    """
    days = _clamp_days(days)
    source = await _api("get_plays_by_source_resolution", time_range=str(days))
    stream = await _api("get_plays_by_stream_resolution", time_range=str(days))

    source_rows = _chart_totals(source)
    stream_rows = _chart_totals(stream)

    if not source_rows:
        return f"No resolution data for the last {days} days."

    lines = [f"Resolution analysis (last {days} days):\n"]

    # Source resolution
    lines.append("Source (file quality):")
    for r in source_rows:
        if r["total"] == 0:
            continue
        dp = r.get("Direct Play", 0)
        tc = r.get("Transcode", 0)
        ds = r.get("Direct Stream", 0)
        lines.append(f"  • {r['name']}: {r['total']} plays (DP:{dp}, DS:{ds}, TC:{tc})")

    # Stream resolution
    lines.append("\nDelivered (what clients received):")
    for r in stream_rows:
        if r["total"] == 0:
            continue
        dp = r.get("Direct Play", 0)
        tc = r.get("Transcode", 0)
        ds = r.get("Direct Stream", 0)
        lines.append(f"  • {r['name']}: {r['total']} plays (DP:{dp}, DS:{ds}, TC:{tc})")

    # Quick insight: 4K source vs stream
    src_4k = next((r["total"] for r in source_rows if r["name"] == "4k"), 0)
    str_4k = next((r["total"] for r in stream_rows if r["name"] == "4k"), 0)
    if src_4k > 0 and str_4k < src_4k:
        downgraded = src_4k - str_4k
        lines.append(f"\nNote: {downgraded} of {src_4k} 4K source plays were transcoded to lower resolution.")

    return "\n".join(lines)


@mcp.tool()
async def tautulli_plays_by_date(days: int = 14) -> str:
    """Get daily play counts over time, broken down by stream type (direct play, direct stream, transcode).

    Args:
        days: Number of days to show (default 14, max 90).
    """
    days = _clamp_days(days, default=14, maximum=90)
    data = await _api("get_plays_by_stream_type", time_range=str(days))
    rows = _chart_totals(data)

    if not rows:
        return f"No play data for the last {days} days."

    # Filter out zero-activity days from the start
    first_active = 0
    for i, r in enumerate(rows):
        if r["total"] > 0:
            first_active = i
            break
    rows = rows[first_active:]

    if not rows:
        return f"No play activity in the last {days} days."

    lines = [f"Daily plays (last {len(rows)} active days):\n"]
    for r in rows:
        dp = r.get("Direct Play", 0)
        ds = r.get("Direct Stream", 0)
        tc = r.get("Transcode", 0)
        total = r["total"]
        bar = "█" * min(total, 50)  # Simple visual bar, capped
        lines.append(f"  {r['name']}: {total:3d} {bar}  (DP:{dp} DS:{ds} TC:{tc})")

    total_all = sum(r["total"] for r in rows)
    avg = total_all / len(rows) if rows else 0
    lines.append(f"\nTotal: {total_all} plays, avg {avg:.1f}/day")

    return "\n".join(lines)


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    missing = []
    if not TAUTULLI_URL:
        missing.append("TAUTULLI_URL")
    if not TAUTULLI_API_KEY:
        missing.append("TAUTULLI_API_KEY")
    if missing:
        print(f"Error: Required environment variable(s) not set: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    mcp.run()
