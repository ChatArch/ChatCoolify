# Changelog

## 0.2.3 - 2026-10-27

### Added

- Owner-only site-management metadata and an authenticated same-origin handoff to the exact native project settings entry.
- Explicit allowlisted signed guest reads for registered project catalog projections; private resources and mutation routes remain authenticated.

### Fixed

- Require the expected current visibility before changing a project's visitor policy, and read back the saved mode rather than reporting stale settings as success.
- Retain the existing account, grant, session, CSRF and project-owner boundaries when showing management links or changing public/private access.
- Publish the verified site-access implementation as a normal package version instead of requiring a private local build.

## 0.2.2 - 2026-10-21

### Added

- Readable production and preview hostnames derived from project slugs, with owner-managed domain reservations through the Python SDK, HTTP API and `coolify platform domains` commands.
- Transactional project-wide hostname claims, infrastructure reservations and native application, Compose and service-domain conflict discovery.
- Staged domain changes activated only after native deployment and runtime/configuration verification; retained old addresses redirect reads to the verified canonical origin.
- Responsive owner dashboard to create sites, choose public/private visitor access, reserve readable domain prefixes and explicitly apply changes to currently published artifacts.
- Public-by-default frontend reads and anonymous ChatComment transport with signed HttpOnly guest sessions, Origin/CSRF validation and bounded per-session rate limits; authenticated owner management remains separate.
- Owner-only visitor-policy synchronization for registered comment services and explicit login on public sites.

### Fixed

- Preserve existing canonical URLs and successful deployment evidence during metadata migration and staged domain changes, including failed-deployment rollback.
- Apply domains by repackaging the verified published artifact into a new immutable runtime release when needed; never rewrite historical sources or accidentally publish an unpublished draft.

## 0.2.1 - 2026-10-21

### Added

- Importable project platform SDK and `coolify platform` commands for built frontend upload, separate preview/production, explicit publication, native logs and verified-release rollback.
- ChatLogin account provisioning, project owner/deployer/viewer grants, host-only application SSO and immediate parent-session, account and grant revocation checks.
- Private Git build inputs, native Coolify resource mapping and runtime artifact verification with persisted deployment evidence; retained source references support pinned shallow-clone rollback.
- Owner-managed independent-service bindings with request-bound signed ChatComment access and password reauthentication.
- ChatEnv endpoint profiles, TokenStore sessions, shared ChatStyle command trees and bilingual platform documentation.

### Fixed

- Preserve browser Origin on password and SSO callback forms while rejecting null and foreign origins.
- Keep never-verified superseded jobs ineligible for rollback; historical native status alone does not create verification evidence.

## 0.2.0 - 2026-09-23

### Changed

- Renamed the installed CLI from `chatcoolify` to `coolify`; the `chatcoolify` executable is no longer installed.
- Kept the PyPI distribution name `ChatCoolify`, Python import package `chatcoolify`, and ChatEnv provider identity unchanged.

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
