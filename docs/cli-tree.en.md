# CLI tree

The ChatCoolify tree comes from the registered Click command surface:

```text
chatcoolify
|- --help
|- --version
|- --tree
|- --tree-brief
|- --base-url
|- --allow-write
|- application  # Show one application, including its allocated domain and status.
|- applications  # List applications visible to the configured API token.
|- deploy  # Trigger a deployment. Requires the global --allow-write flag.
|- deployments  # List deployment history for one application.
|- health  # Call the public health endpoint; no API token is needed.
|- overview  # Show a compact read-only inventory for the configured team.
|- project  # Show one project and its environments by UUID.
|- project-create  # Create a project. Requires the global --allow-write flag.
|- projects  # List projects visible to the configured API token.
|- servers  # List servers visible to the configured API token.
|- team  # Show the current team bound to the configured API token.
|- website-create  # Create a public Git website. Requires the global --allow-write flag.
`- website-plan  # Render a website payload without making a Coolify write request.
```

## Current commands

| Command | Remote side effect | Required token |
| --- | --- | --- |
| `health` | None | No |
| `team`, `projects`, `project`, `application`, `applications`, `servers`, `deployments`, `overview` | None | `read` |
| `website-plan` | None | No |
| `project-create`, `website-create` | Creates resources | `write` plus `--allow-write` |
| `deploy` | Triggers a deployment | `deploy` plus `--allow-write` |

`--tree-brief` renders the same command topology without descriptions. The CLI never prints tokens.
