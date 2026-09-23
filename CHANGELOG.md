# Changelog

## 0.1.1 - 2026-09-23

### Added

- Explicit automatic wildcard-domain contract for public Git applications when no custom `--domain` is supplied.
- Project and application detail retrieval, including project environments plus the allocated application domain and status.
- Optional `--health-check-path` support that enables Coolify health checks at application creation.
- A real source-to-public-HTTPS deployment case with public screenshots and verification guidance.

### Fixed

- Deployment history now accepts the official `{\"count\": ..., \"deployments\": [...]}` response envelope.
- API failures redact the configured token, discard raw HTTP exception chains, and reject credential-bearing base URLs.

## 0.1.0 - 2026-09-22

### Added

- Official Coolify REST API Python client with health, inventory, project, public Git website, and deployment operations.
- Read-only-by-default local safety gate for AI and CI automation.
- ChatEnv provider for Coolify URL and team-scoped API token configuration.
- `chatcoolify` CLI with version and command-tree output.
- Bilingual MkDocs documentation for invitation-only access, official REST/MCP integration, website hosting, full-stack services, and safety boundaries.
- Tag-driven PyPI Trusted Publisher and GitHub Pages workflow definitions.

## 0.0.1 - 2026-09-22

- Reserved the PyPI project name with a minimal placeholder package.
