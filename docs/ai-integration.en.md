# Official API and MCP

Coolify already provides an official REST API and MCP server. ChatCoolify adds Python types, a CLI, and local safety gates around those official interfaces; it does not create a private server protocol.

## REST API

```text
https://<coolify-url>/api/v1
```

Common resources include:

- Teams, members, projects, and environments;
- applications, databases, and services;
- servers, destinations, and deployments;
- deployment logs, backups, notifications, and shared variables.

Protected requests use a team-scoped Bearer token:

```http
Authorization: Bearer <team-scoped-token>
Accept: application/json
```

## MCP

```text
https://<coolify-url>/mcp
```

MCP uses Streamable HTTP. It remains subject to the same instance API switch, team boundaries, token permissions, IP allowlist, and sensitive-value redaction rules.

## Permission map

| Permission | Use case |
| --- | --- |
| `read` | AI inventory, status inspection, log summaries |
| `deploy` | CI or controlled AI lifecycle actions |
| `write` | Create or modify projects, applications, and databases |
| `read:sensitive` | Only when supported sensitive reads are truly required |
| `root` | Instance administration; not for normal AI automation |

## Enablement order

1. An administrator enables instance API Access under **Settings → Advanced**.
2. Configure an IP allowlist when callers use fixed source addresses.
3. Enable MCP for the intended team.
4. Create separate least-privilege, expiring tokens for each AI or CI integration.
5. Store tokens in protected ChatEnv or a secret manager.
6. Start with health and inventory reads before allowing `deploy` or short-lived `write` access.

!!! warning
    Do not place tokens in prompts, command arguments, repositories, docs, issues, pull requests, or logs.
