<div align="center">

# ChatCoolify

AI-safe Python client and MkDocs guide for the official Coolify API.

[Documentation](https://arch.gh.wzhecnu.cn/ChatCoolify/) · [中文](README.md) · [PyPI](https://pypi.org/project/ChatCoolify/) · [Source](https://github.com/ChatArch/ChatCoolify)

</div>

## What it solves

ChatCoolify does not replace Coolify. It turns the official REST API into a testable Python client and CLI:

- read-only by default for AI inventory of servers, projects, applications, and deployments;
- writes require both Coolify token permission and explicit `--allow-write`;
- ChatEnv configuration, public Git website planning/creation, and deployment triggers;
- documentation for invitation-only collaboration, MCP, websites, APIs, databases, and operating boundaries.

## Install

```bash
python -m pip install --upgrade ChatCoolify
coolify --version
coolify --tree
```

Python `>=3.10` is supported. The distribution remains `ChatCoolify` and the Python import remains `chatcoolify`; `coolify` is the only installed CLI, with no `chatcoolify` command alias.

## Quick start

```bash
coolify --base-url https://<coolify-url> health
```

For protected API calls, create a least-privilege team-scoped token in Coolify and configure ChatEnv:

```bash
chatenv init -t coolify -I
chatenv set COOLIFY_BASE_URL=https://<coolify-url>
chatenv set COOLIFY_API_TOKEN='<team-scoped-token>'
coolify overview
```

## Website plan example

```bash
coolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site
```

When `--domain` is omitted, the plan asks Coolify to allocate a unique tenant URL from the configured wildcard pool. Pass `--domain` only for a custom domain. See the full [verified Git-to-HTTPS demo](https://arch.gh.wzhecnu.cn/ChatCoolify/en/self-service-demo/).

The command only renders an official API payload. Creating a resource requires both a `write` token and an explicit local gate:

```bash
coolify --allow-write website-create ...
```

## Safety boundary

- Never place tokens in arguments, repositories, logs, or prompts.
- Do not give `root` tokens to normal AI or CI.
- Team roles are not VM isolation; untrusted code must not share a production Docker daemon.
- See the full [documentation](https://arch.gh.wzhecnu.cn/ChatCoolify/).

## Development

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
python -m mkdocs build --strict
python -m build
python -m twine check dist/*
```

## License

MIT.
