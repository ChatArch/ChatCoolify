# CLI 树

ChatCoolify 的发布包与 Python import 保持原名；安装后的 CLI 是 `coolify`，不提供 `chatcoolify` 命令别名。CLI 树来自实际 Click 注册表：

```text
coolify
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── --base-url BASE-URL  # Coolify control-plane URL. Keep API tokens out of command arguments.
├── --allow-write  # Allow commands that create or deploy resources. Read-only is the default.
├── application <APPLICATION-UUID>  # Show one application, including its allocated domain and status.
├── applications  # List applications visible to the configured API token.
├── deploy <APPLICATION-UUID> [--force]  # Trigger a deployment. Requires the global --allow-write flag.
├── deployments <APPLICATION-UUID> [--skip SKIP] [--take TAKE]  # List deployment history for one application.
├── health  # Call the public health endpoint; no API token is needed.
├── overview  # Show a compact read-only inventory for the configured team.
├── platform [--profile PROFILE] [--home HOME]  # Register local frontends and deploy them through native Coolify.
│   ├── bootstrap-owner <USERNAME> [--password-env PASSWORD-ENV]  # Operator-only first account bootstrap; never exposed as an HTTP route.
│   ├── domains  # Read addresses or reserve a readable managed hostname for a project.
│   │   ├── apply <PROJECT> [--environment ENVIRONMENT] [--request-key REQUEST-KEY]  # Apply a reserved domain using the currently published website bytes.
│   │   ├── list <PROJECT>  # Show active and desired preview/production URLs and pending changes.
│   │   └── set <PROJECT> <HOSTNAME> [--environment ENVIRONMENT]  # Owner: reserve HOSTNAME; explicit preview/publish activates it after verification.
│   ├── grant <PROJECT> <USER-ID> [--role ROLE]  # Project owner: grant collaboration or revoke it immediately.
│   ├── health [--port PORT]  # Check a local control runtime; exits nonzero on unhealthy HTTP status.
│   ├── login [--url URL] [--username USERNAME] [--password-env PASSWORD-ENV]  # Sign in to an invited account and save a private session.
│   ├── logout  # Revoke this control session and all its app reader children.
│   ├── logs <PROJECT> <DEPLOYMENT>  # Read sanitized native deployment logs for an authorized project.
│   ├── preview <PROJECT> <RELEASE> [--request-key REQUEST-KEY]  # Build and run a selected release at its native preview application.
│   ├── projects  # List and register projects owned by or shared with this account.
│   │   ├── create <SLUG> [--name NAME] [--visibility VISIBILITY] [--request-key REQUEST-KEY]  # Create one native-backed project; repeat registration is idempotent.
│   │   ├── list
│   │   └── visibility <PROJECT> <VISIBILITY>  # Owner: choose public visitor access or explicitly private access.
│   ├── publish <PROJECT> <RELEASE> [--request-key REQUEST-KEY]  # Explicitly deploy a selected immutable release to production.
│   ├── releases <PROJECT>  # List immutable artifacts and their native build source commits.
│   ├── rollback <PROJECT> <RELEASE> [--request-key REQUEST-KEY]  # Redeploy a previously successful production release through Coolify.
│   ├── serve [--host HOST] [--port PORT]  # Operator: run the control plane using server-only typed configuration.
│   ├── services  # Project owner: associate independent native backend resources.
│   │   ├── list <PROJECT> [--candidates]
│   │   └── register <PROJECT> <BINDING-ID> [--registration-id REGISTRATION-ID] [--site-id SITE-ID] [--adapter ADAPTER]
│   ├── status <PROJECT>  # Reconcile project deployments with actual native Coolify status.
│   ├── upload <PROJECT> <DIRECTORY> [--preview]  # Upload a local frontend artifact; production stays unchanged.
│   ├── users  # Administrator account provisioning; no public signup.
│   │   ├── create <USERNAME> [--password-env PASSWORD-ENV] [--display-name DISPLAY-NAME] [--email EMAIL]  # Provision an invited ordinary account.
│   │   ├── disable <USER-ID> [--enable]  # Change enabled state; ChatLogin revokes affected sessions.
│   │   └── list
│   └── whoami  # Show current account metadata without session/CSRF secrets.
├── project <PROJECT-UUID>  # Show one project and its environments by UUID.
├── project-create <NAME> [--description DESCRIPTION]  # Create a project. Requires the global --allow-write flag.
├── projects  # List projects visible to the configured API token.
├── servers  # List servers visible to the configured API token.
├── team  # Show the current team bound to the configured API token.
├── website-create [--project-uuid PROJECT-UUID] [--server-uuid SERVER-UUID] [--environment-name ENVIRONMENT-NAME] [--environment-uuid ENVIRONMENT-UUID] [--repository-url REPOSITORY-URL] [--branch BRANCH] [--build-pack BUILD-PACK] [--name NAME] [--domain DOMAIN] [--publish-directory PUBLISH-DIRECTORY] [--port PORT] [--health-check-path HEALTH-CHECK-PATH] [--spa] [--deploy]  # Create a public Git website. Requires the global --allow-write flag.
└── website-plan [--project-uuid PROJECT-UUID] [--server-uuid SERVER-UUID] [--environment-name ENVIRONMENT-NAME] [--environment-uuid ENVIRONMENT-UUID] [--repository-url REPOSITORY-URL] [--branch BRANCH] [--build-pack BUILD-PACK] [--name NAME] [--domain DOMAIN] [--publish-directory PUBLISH-DIRECTORY] [--port PORT] [--health-check-path HEALTH-CHECK-PATH] [--spa]  # Render a website payload without making a Coolify write request.
```

## 当前能力

| 命令 | 远端副作用 | 需要 Token |
| --- | --- | --- |
| `health` | 无 | 否 |
| `team`、`projects`、`project`、`application`、`applications`、`servers`、`deployments`、`overview` | 无 | `read` |
| `website-plan` | 无 | 否 |
| `project-create`、`website-create` | 创建资源 | `write` + `--allow-write` |
| `deploy` | 触发部署 | `deploy` + `--allow-write` |

`--tree-brief` 输出相同的命令结构但省略说明。CLI 永远不会把 Token 写入输出。
