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
chatcoolify --version
chatcoolify --tree
```

支持 Python `>=3.10`。

## 最快开始

```bash
chatcoolify --base-url https://<coolify-url> health
```

需要受保护 API 时，先在 Coolify 创建 Team-scoped 最小权限 Token，再通过 ChatEnv 配置：

```bash
chatenv init -t coolify -I
chatenv set COOLIFY_BASE_URL=https://<coolify-url>
chatenv set COOLIFY_API_TOKEN='<team-scoped-token>'
chatcoolify overview
```

## 网站计划示例

```bash
chatcoolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/simple-site \
  --domain https://site.example.com
```

该命令只输出官方 API payload。真正创建资源需要同时具备 `write` Token 和显式写门：

```bash
chatcoolify --allow-write website-create ...
```

## 安全边界

- 不把 Token 写入参数、仓库、日志或提示词。
- 不向普通 AI 或 CI 提供 `root` Token。
- Team 角色不是虚拟机隔离；不可信代码不应共享生产 Docker 守护进程。
- 完整操作流程见 [文档](https://arch.gh.wzhecnu.cn/ChatCoolify/)。

## 开发

```bash
python -m pip install -e '.[dev,docs]'
python -m pytest -q
python -m mkdocs build --strict
python -m build
python -m twine check dist/*
```

## 许可证

MIT。
