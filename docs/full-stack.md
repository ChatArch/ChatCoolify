# 前后端与数据库

## API 服务

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
```

`Dockerfile`：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

在 Coolify 选择 Dockerfile 构建，暴露 `8000`，将健康检查设为 `/health`，并配置 CPU 与内存上限。

## 数据库

在同一 Project/Environment 添加 PostgreSQL、MySQL 或 Redis：

1. 使用 **New Resource → Database** 创建受管理数据库。
2. 启用持久化卷。
3. 为后端使用内部连接地址。
4. 把数据库密码保存在 Coolify Environment Variables。
5. 建立备份与恢复演练。

```text
DATABASE_URL=postgresql://app:<password>@postgres:5432/app
```

## Compose 栈

```yaml
services:
  api:
    build: ./api
    environment:
      DATABASE_URL: postgresql://app:${DATABASE_PASSWORD}@db:5432/app
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD}
      POSTGRES_DB: app
    volumes:
      - database-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      timeout: 3s
      retries: 20

volumes:
  database-data:
```

将 `DATABASE_PASSWORD` 作为 Coolify Secret 注入，不提交到仓库。

## 发布顺序

```text
只读清点 -> 生成变更计划 -> 人工确认 -> 短期写权限创建 -> deploy 权限发布 -> 只读验收
```
