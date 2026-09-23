# CLI 树

ChatCoolify 的发布包与 Python import 保持原名；安装后的 CLI 是 `coolify`，不提供 `chatcoolify` 命令别名。CLI 树来自实际 Click 注册表：

```text
coolify
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

## 当前能力

| 命令 | 远端副作用 | 需要 Token |
| --- | --- | --- |
| `health` | 无 | 否 |
| `team`、`projects`、`project`、`application`、`applications`、`servers`、`deployments`、`overview` | 无 | `read` |
| `website-plan` | 无 | 否 |
| `project-create`、`website-create` | 创建资源 | `write` + `--allow-write` |
| `deploy` | 触发部署 | `deploy` + `--allow-write` |

`--tree-brief` 输出相同的命令结构但省略说明。CLI 永远不会把 Token 写入输出。
