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
6. Deploy to a temporary URL before setting `https://site.example.com`.
7. Check the homepage, static assets, TLS, and SPA refresh routes.

## AI plan and execution

Create a plan first:

```bash
chatcoolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site \
  --build-pack static \
  --publish-directory / \
  --domain https://site.example.com
```

Create only after confirming the project, server, environment, repository, and domain:

```bash
chatcoolify --allow-write website-create \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site \
  --build-pack static \
  --publish-directory / \
  --domain https://site.example.com \
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
