# ChatCoolify

ChatCoolify 是官方 Coolify REST API 的安全 Python 客户端与 AI 自动化边界层。

<div class="grid cards" markdown>

-   :material-account-plus-outline: **邀请制协作**

    ---

    保持 Coolify 公开注册关闭，由管理员向明确的外部协作者发出团队邀请。

    [注册与邀请](registration.md)

-   :material-robot-outline: **AI 受限接入**

    ---

    优先使用官方 MCP 做基础设施读取；Python 自动化使用 Team-scoped REST Token。

    [AI 接入](ai-integration.md)

-   :material-shield-lock-outline: **写操作双重确认**

    ---

    Token 权限之外，ChatCoolify 默认只读；创建和部署必须显式启用本地写门。

    [Python 客户端](python-client.md)

-   :material-web: **网站托管路径**

    ---

    从公开 Git 仓库、静态网站到 API、数据库与 Docker Compose 的完整示例。

    [使用示例](simple-website.md)

-   :material-check-decagram-outline: **真实上线证据**

    ---

    查看一个从 Git 推送、自动 tenant 域名到稳定 HTTPS URL 的实际 Release 4。

    [真实演示](self-service-demo.md)

</div>

## 适合什么

- 需要把网站、API、数据库或 Compose 服务交给 Coolify 管理的团队。
- 希望 AI 先读取项目、服务器和部署状态，再由人确认高风险变更的场景。
- 需要在 CI 中以最小权限触发已有应用部署的场景。

## 不负责什么

- 不替代 Coolify 服务端、Git Provider、Docker 或 Kubernetes。
- 不绕过 Coolify 的 Team、Token、IP Allowlist 或敏感字段脱敏规则。
- 不把共享 Docker 主机伪装成硬隔离多租户平台。

## 三条使用路径

| 目标 | 首选 | 最小权限 |
| --- | --- | --- |
| AI 了解当前基础设施 | 官方 MCP | `read` |
| CI 重新部署已存在应用 | 官方 REST / ChatCoolify | `deploy` |
| 自动化创建项目或网站 | ChatCoolify | 短期 `write` + `--allow-write` |

!!! warning
    `root` Token 是实例级高权限能力，不应提供给普通 AI、CI 或外部成员。
