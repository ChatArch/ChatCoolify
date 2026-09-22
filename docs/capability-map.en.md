# Capability map

| Capability | Current status | Boundary |
| --- | --- | --- |
| Coolify health check | Implemented | Token-free read |
| Team, project, application, server, and deployment reads | Implemented | Team-scoped `read` token |
| Project creation | Implemented | `write` token plus explicit local gate |
| Public Git website creation | Implemented | Wraps official API payload only |
| Deployment trigger | Implemented | `deploy` token plus explicit local gate |
| Official MCP integration | Provided by Coolify | ChatCoolify does not reimplement an MCP server |
| Token creation, revocation, and permission management | Out of scope | Use the Coolify Web UI |
| Docker, VM, or hard tenant isolation | Out of scope | Provided by infrastructure |

## Responsibility layers

```text
Official Coolify REST / MCP
  -> permissions, teams, resource lifecycle
ChatCoolify
  -> Python types, CLI, read-only defaults, explicit write gate
AI / CI
  -> plans, constrained calls, human approval
People
  -> token grants, permission decisions, high-risk writes
```
