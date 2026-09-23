# ChatCoolify

ChatCoolify is a safety-focused Python client and AI automation boundary for the official Coolify REST API.

<div class="grid cards" markdown>

-   :material-account-plus-outline: **Invitation-only collaboration**

    ---

    Keep public registration disabled and invite known external collaborators into the correct team.

    [Registration and invitations](registration.md)

-   :material-robot-outline: **Constrained AI access**

    ---

    Use the official MCP server for infrastructure reads and team-scoped REST tokens for Python automation.

    [AI integration](ai-integration.md)

-   :material-shield-lock-outline: **Two write gates**

    ---

    ChatCoolify is read-only by default. Creation and deployment require explicit local write permission.

    [Python client](python-client.md)

-   :material-web: **Website hosting paths**

    ---

    Follow complete examples for public Git sites, APIs, databases, and Docker Compose stacks.

    [Examples](simple-website.md)

-   :material-check-decagram-outline: **Verified release evidence**

    ---

    Inspect a real Release 4 from Git push through automatic tenant-domain allocation to a stable HTTPS URL.

    [Verified demo](self-service-demo.md)

</div>

## Good fit

- Teams that host websites, APIs, databases, or Compose services through Coolify.
- AI-assisted operations where people inspect a plan before approving risky changes.
- CI jobs that need least-privilege deployment of an existing application.

## Out of scope

- Replacing the Coolify server, Git provider, Docker, or Kubernetes.
- Bypassing Coolify team boundaries, token permissions, IP allowlists, or sensitive-value redaction.
- Treating a shared Docker host as a hard-isolated multi-tenant platform.

## Three paths

| Goal | Preferred surface | Minimum permission |
| --- | --- | --- |
| Let AI inspect infrastructure | Official MCP | `read` |
| Redeploy an existing app from CI | Official REST / ChatCoolify | `deploy` |
| Create a project or website | ChatCoolify | Short-lived `write` plus `--allow-write` |

!!! warning
    A `root` token is instance-level authority. Do not give it to ordinary AI clients, CI jobs, or external members.
