# mcp-tautulli

A single-file [MCP](https://modelcontextprotocol.io/) server for [Tautulli](https://tautulli.com/) — Plex monitoring via Claude Code (or any MCP client).

11 read-only tools. No mutations. All configuration via environment variables.

## Prerequisites

- Python 3.10+
- A running [Tautulli](https://tautulli.com/) instance with an API key
- [Claude Code](https://claude.ai/code) (or any MCP-compatible client)

## Installation

```bash
pip install fastmcp httpx
```

Or from the repo:

```bash
git clone https://github.com/lodordev/mcp-tautulli.git
cd mcp-tautulli
pip install -r requirements.txt
```

## Configuration

Three environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TAUTULLI_URL` | Yes | — | Tautulli base URL (e.g. `http://localhost:8181`) |
| `TAUTULLI_API_KEY` | Yes | — | Tautulli API key (Settings → Web Interface → API Key) |
| `TAUTULLI_TLS_VERIFY` | No | `true` | Set to `false` if using self-signed certs (e.g. Tailscale serve) |

## Claude Code Setup

Add to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "tautulli": {
      "command": "python",
      "args": ["/path/to/tautulli.py"],
      "env": {
        "TAUTULLI_URL": "http://your-tautulli-host:8181",
        "TAUTULLI_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

Or run standalone:

```bash
export TAUTULLI_URL="http://localhost:8181"
export TAUTULLI_API_KEY="your-api-key"
python tautulli.py
```

## Tools

| Tool | Description |
|------|-------------|
| `tautulli_activity` | Current Plex streaming activity — who's watching what, progress, quality |
| `tautulli_history` | Recent playback history with filters (user, media type, search, date) |
| `tautulli_user_stats` | Per-user watch statistics — plays, watch time, last seen |
| `tautulli_library_stats` | Library item counts, total plays, last played per library |
| `tautulli_most_watched` | Top content by plays or duration (TV, movies, music, users) |
| `tautulli_server_info` | Plex server identity — name, version, platform, connection |
| `tautulli_status` | Server config and reachability check |
| `tautulli_transcode_stats` | Direct play vs transcode breakdown by platform |
| `tautulli_platform_stats` | Top platforms/devices by plays and watch time |
| `tautulli_stream_resolution` | Source vs delivered resolution analysis |
| `tautulli_plays_by_date` | Daily play counts over time by stream type |

All tools are **read-only** — this server does not modify any Tautulli or Plex state.

## License

MIT
