# Python 客户端

## 安装

```bash
python -m pip install ChatCoolify
```

## ChatEnv 配置

```bash
chatenv init -t coolify -I
chatenv set COOLIFY_BASE_URL=https://<coolify-url>
chatenv set COOLIFY_API_TOKEN='<team-scoped-token>'
```

敏感 Token 应只存在于受保护的配置文件或密钥管理器中。

## 只读操作

```bash
chatcoolify --base-url https://<coolify-url> health
chatcoolify team
chatcoolify overview
chatcoolify projects
chatcoolify applications
chatcoolify servers
```

Python 调用：

```python
from chatcoolify import CoolifyClient

client = CoolifyClient.from_env()
print(client.health())
print(client.current_team())
print(client.list_projects())
```

## 写操作的双门

ChatCoolify 不会因 Token 存在就自动写入。写操作必须同时满足：

1. Coolify Token 有对应 `write` 或 `deploy` 权限；
2. 调用方显式声明 `allow_write=True` 或 CLI 的 `--allow-write`。

```python
from chatcoolify import CoolifyClient

client = CoolifyClient.from_env(allow_write=True)
project = client.create_project("demo-site")
```

```bash
chatcoolify --allow-write project-create demo-site
```

先用 `website-plan` 输出资源计划，再由人确认后创建：

```bash
chatcoolify website-plan \
  --project-uuid PROJECT_UUID \
  --server-uuid SERVER_UUID \
  --environment-uuid ENVIRONMENT_UUID \
  --repository-url https://github.com/example/site \
  --domain https://site.example.com
```
