# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-22

### Added
- `tautulli_recently_added` — recently added content to Plex
- `tautulli_search` — search Plex content by title
- `tautulli_plays_by_day_of_week` — weekly viewing pattern analysis
- `tautulli_plays_by_hour` — hourly viewing distribution
- CI linting with ruff (check + format) on push and PRs
- Troubleshooting section in README
- Example output section in README
- MCP Registry metadata in README
- CHANGELOG.md

### Fixed
- Removed unused `last_seen` variable in `tautulli_user_stats`

## [1.0.0] - 2026-03-20

### Added
- Initial release with 11 read-only tools
- FastMCP 2.14+ / httpx async architecture
- Environment variable configuration (TAUTULLI_URL, TAUTULLI_API_KEY, TAUTULLI_TLS_VERIFY)
- PyPI package (`mcp-tautulli`) and GitHub Actions publish workflow
- Dockerfile for containerized deployment
- Glama inspection support (glama.json)

[1.1.0]: https://github.com/lodordev/mcp-tautulli/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/lodordev/mcp-tautulli/releases/tag/v1.0.0
