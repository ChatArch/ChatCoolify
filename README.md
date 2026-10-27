<div align="center">

# ChatCoolify

AI-safe Python client and MkDocs guide for the official Coolify API.

[文档](https://arch.gh.wzhecnu.cn/ChatCoolify/) · [English](README.en.md) · [PyPI](https://pypi.org/project/ChatCoolify/) · [源码](https://github.com/ChatArch/ChatCoolify)

</div>

## 解决什么问题

ChatCoolify 不替代 Coolify，而是把官方 REST API 变成可测试的 Python 客户端和 CLI：

- 默认只读，适合 AI 清点服务器、项目、应用与部署状态；
- 写操作必须有 Coolify Token 权限并显式传递 `--allow-write`；
- 支持 ChatEnv 配置、公开 Git 网站计划与创建、部署触发；
- 文档覆盖邀请制协作、MCP、网站、API、数据库和运维边界。

## 安装

```bash
python -m pip install --upgrade ChatCoolify
coolify --version
coolify --tree
```

支持 Python `>=3.10`。发布包仍叫 `ChatCoolify`，Python import 仍是 `chatcoolify`；安装后的唯一 CLI 是 `coolify`，不提供 `chatcoolify` 命令别名。

## 最快开始

已有平台账号可通过 `coolify platform` 完成本地目录上传、原生预览、显式发布及回退；平台按项目授权，普通用户不持有原生 Team token。见[本地项目平台](docs/platform.md)。以下保留原生 Coolify 客户端用法，其写操作仍需 `--allow-write`。

```bash
coolify --base-url https://<coolify-url> health
```

需要受保护 API 时，先在 Coolify 创建 Team-scoped 最小权限 Token，再通过 ChatEnv 配置：

```bash
chatenv init -t coolify -I
chatenv set COOLIFY_BASE_URL=https://<coolify-url>
chatenv set COOLIFY_API_TOKEN='<team-scoped-token>'
coolify overview
```

## 网站计划示例

```bash
coolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site
```

省略 `--domain` 时，计划会请求 Coolify 从已配置的泛域名池自动分配唯一 tenant URL；需要自定义域名时才显式传入 `--domain`。查看完整的 [真实 Git 到 HTTPS 演示](https://arch.gh.wzhecnu.cn/ChatCoolify/self-service-demo/)。

以上为直接原生 API 的低层命令。面向普通协作者的 `coolify platform` 使用项目名分配可读的正式／预览子域名，owner 可在“我的网站”管理页或通过 `domains set` 自定义受管前缀，并用 `domains apply` 应用到已发布网站。新项目默认公开阅读，管理登录与访客留言分离；登录、项目列表、目录上传与明确发布流程见[本地项目平台](https://arch.gh.wzhecnu.cn/ChatCoolify/platform/)。

该命令只输出官方 API payload。真正创建资源需要同时具备 `write` Token 和显式写门：

```bash
coolify --allow-write website-create ...
```

## 安全边界

- 不把 Token 写入参数、仓库、日志或提示词。
- 不向普通 AI 或 CI 提供 `root` Token。
- Team 角色不是虚拟机隔离；不可信代码不应共享生产 Docker 守护进程。
- 完整操作流程见 [文档](https://arch.gh.wzhecnu.cn/ChatCoolify/)。

## 开发

```bash
python -m pip install -e '.[dev,docs,comments]'
python -m pytest -q
python -m mkdocs build --strict
python -m build
python -m twine check dist/*
```

## 许可证

MIT。


## 签名访客的公开只读投影

公开项目可以由受信任服务显式实现 `GET` / `HEAD /api/public/catalog`、`/api/public/state` 和 `/api/public/projects/{id}`（ID 为 1–80 个 ASCII 字母、数字、下划线或连字符）。平台仍按应用和站点绑定签名，访客上下文保持 `authenticated=False`，不因签名或客户端身份声明成为已登录所有者。普通私有 API 不在访客白名单中；此扩展不改变既有评论提交协议。

后端必须独立验证准确的方法、路径/查询、正文与站点 read 权限，并生成明确允许的公开字段。不要把原始项目材料、来源连接、人工私人记录或凭据直接当成公开响应。投影路径只读；私有读取、管理写入和 CSRF 仍执行各自的认证规则。项目可见性是项目级策略，切换前同时核对预览与生产范围，不以一层登录遮罩替代后端权限。

正式发布包包含上述签名只读投影能力；是否允许公开读取仍由项目的持久化访问策略决定。

### 原生项目访问管理

已认证的项目所有者可通过 `GET /__platform/manage` 进入原生控制台的准确项目设置。正式站与预览共用持久化的访问模式；公开切换需要明确确认，保存时验证预期的旧模式并再次读取结果。普通阅读账号不能管理访问权限。该能力不新增或改名 CLI 命令。
