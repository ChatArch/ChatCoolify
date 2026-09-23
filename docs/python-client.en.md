# Python client

## Install

```bash
python -m pip install ChatCoolify
```

## Configure ChatEnv

The Python import remains `chatcoolify`; the CLI command is `coolify`, with no `chatcoolify` CLI alias.

```bash
chatenv init -t coolify -I
chatenv set COOLIFY_BASE_URL=https://<coolify-url>
chatenv set COOLIFY_API_TOKEN='<team-scoped-token>'
```

Keep sensitive tokens only in protected configuration or a secret manager.

## Read-only operations

```bash
coolify --base-url https://<coolify-url> health
coolify team
coolify overview
coolify projects
coolify project PROJECT_UUID
coolify applications
coolify application APPLICATION_UUID
coolify servers
```

Python usage:

```python
from chatcoolify import CoolifyClient

client = CoolifyClient.from_env()
print(client.health())
print(client.current_team())
print(client.list_projects())
print(client.get_project("PROJECT_UUID"))
print(client.get_application("APPLICATION_UUID"))
```

## Two write gates

ChatCoolify does not write merely because a token exists. Both conditions are required:

1. The Coolify token has `write` or `deploy` permission.
2. The caller explicitly sets `allow_write=True` or passes `--allow-write`.

```python
from chatcoolify import CoolifyClient

client = CoolifyClient.from_env(allow_write=True)
project = client.create_project("demo-site")
```

```bash
coolify --allow-write project-create demo-site
```

Use `website-plan` first, then create only after human approval:

```bash
coolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/site
```

Omitting `--domain` makes the payload explicitly include `autogenerate_domain: true`; Coolify allocates a unique address from the platform wildcard pool.
