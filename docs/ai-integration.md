# 官方 API 与 MCP

Coolify 已提供官方 REST API 和官方 MCP Server。ChatCoolify 只为这两个官方接口增加 Python 类型、CLI 和本地安全门，不创建私有服务端协议。

## REST API

```text
https://<coolify-url>/api/v1
```

常见资源：

- Team、成员、项目和 Environment；
- Application、Database、Service；
- Server、Destination、Deployment；
- 部署日志、备份、通知和共享变量。

受保护请求使用 Team-scoped Bearer Token：

```http
Authorization: Bearer <team-scoped-token>
Accept: application/json
```

## MCP

```text
https://<coolify-url>/mcp
```

MCP 使用 Streamable HTTP。它受同一套实例 API 开关、Team、Token 权限、IP Allowlist 与敏感字段脱敏规则约束。

## 权限地图

| 权限 | 应用场景 |
| --- | --- |
| `read` | AI 清点、状态检查、日志摘要 |
| `deploy` | CI 或受控 AI 触发部署、停止、重启 |
| `write` | 创建或修改项目、应用与数据库 |
| `read:sensitive` | 只有确实需要支持的敏感读操作时才授予 |
| `root` | 实例级管理；禁止用于日常 AI 自动化 |

## 启用顺序

1. 管理员在 **Settings → Advanced** 打开实例 API Access。
2. 仅允许固定来源时设置 IP Allowlist。
3. 在目标 Team 打开 MCP。
4. 为每个 AI 或 CI 创建独立、最小权限、可过期的 Token。
5. 将 Token 放入受保护的 ChatEnv 或密钥管理器。
6. 先执行只读健康和资源清点，再开放 `deploy` 或短期 `write`。

!!! warning
    不要把 Token 放到 Prompt、命令行参数、仓库、文档、Issue、PR 或日志中。
