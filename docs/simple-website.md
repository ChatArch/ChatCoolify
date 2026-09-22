# 托管简单网站

## 准备仓库

```text
simple-site/
└── index.html
```

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>我的网站</title>
  </head>
  <body>
    <h1>Hello from Coolify</h1>
  </body>
</html>
```

将它推送至公开 HTTPS Git 仓库：

```text
https://github.com/example/simple-site
```

## Web UI 路径

1. 创建 Project 与 `production` Environment。
2. 选择 **New Resource → Public Git repository**。
3. 填写仓库与分支。
4. Build pack 选择 **Static**。
5. 根目录文件使用 `/`；Vite 等构建产物通常使用 `dist`。
6. 先部署临时入口，再设置 `https://site.example.com`。
7. 检查首页、静态资源、HTTPS 和 SPA 刷新路由。

## AI 计划与执行

先生成计划：

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

确认 Project、Server、Environment、Repository 和 Domain 后再创建：

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

## 验收

```bash
curl --fail https://site.example.com/
```

确认：

- 页面与静态资源返回成功；
- TLS 与跳转正确；
- Git 更新触发的部署符合预期；
- CPU、内存、存储和构建资源有限制；
- Deployment History 中存在可用回滚版本。
