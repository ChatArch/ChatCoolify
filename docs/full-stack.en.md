# API, database, and full stack

## API service

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
```

`Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Use Dockerfile deployment in Coolify, expose `8000`, set `/health`, and configure CPU and memory limits.

## Database

Add PostgreSQL, MySQL, or Redis within the same project/environment:

1. Create it through **New Resource → Database**.
2. Enable persistent storage.
3. Use the internal connection address from the API service.
4. Store passwords in Coolify environment variables.
5. Establish backups and test restore.

```text
DATABASE_URL=postgresql://app:<password>@postgres:5432/app
```

## Compose stack

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

Inject `DATABASE_PASSWORD` as a Coolify secret instead of committing it.

## Release sequence

```text
Read inventory -> generate plan -> human approval -> short-lived write access -> deploy access -> read-only acceptance
```
