# Host a simple website

## Prepare a repository

```text
simple-site/
└── index.html
```

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>My website</title>
  </head>
  <body>
    <h1>Hello from Coolify</h1>
  </body>
</html>
```

Push it to a public HTTPS Git repository:

```text
https://github.com/example/simple-site
```

## Web UI path

1. Create a project and `production` environment.
2. Select **New Resource → Public Git repository**.
3. Enter the repository and branch.
4. Select **Static** as the build pack.
5. Use `/` for root files; Vite-style output is often `dist`.
6. When the platform's `cool` domain pool is configured, leave Domain empty and Coolify allocates a unique tenant address.
7. Add a custom domain such as `https://site.example.com` only after application validation.
8. Check the homepage, static assets, TLS, and SPA refresh routes.

## Automatic tenant domain

After one wildcard configuration, users do not need a per-project DNS or reverse-proxy edit. Omitting `--domain` asks ChatCoolify to request a Coolify-generated address; the plan should include:

```json
{"autogenerate_domain": true}
```

The allocated URL has this shape:

```text
https://APPLICATION_UUID.cool.wzhecnu.cn
```

## AI plan and execution

Create a plan first:

```bash
chatcoolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site \
  --build-pack static \
  --publish-directory /
```

Create only after confirming the project, server, environment, repository, and automatic-domain policy:

```bash
chatcoolify --allow-write website-create \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site \
  --build-pack static \
  --publish-directory / \
  --deploy
```

## Acceptance

```bash
curl --fail https://site.example.com/
```

Confirm that:

- pages and static assets succeed;
- TLS and redirects are correct;
- Git changes deploy as expected;
- CPU, memory, storage, and build resources are bounded;
- Deployment History has a usable rollback version.
