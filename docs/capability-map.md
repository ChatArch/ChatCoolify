# 能力地图

| 能力 | 当前状态 | 边界 |
| --- | --- | --- |
| Coolify 健康检查 | 已实现 | 无 Token 读取 |
| Team、项目、应用、服务器、部署读取 | 已实现 | Team-scoped `read` Token |
| 创建项目 | 已实现 | `write` Token 与显式写门 |
| 创建公开 Git 网站 | 已实现 | 省略域名时请求 Coolify 自动分配泛域名池地址 |
| 触发部署 | 已实现 | `deploy` Token 与显式写门 |
| 官方 MCP 接入 | 官方已有 | ChatCoolify 不重写 MCP Server |
| Token 创建、撤销与权限管理 | 不由本包执行 | 使用 Coolify Web UI |
| Docker、VM 或租户硬隔离 | 不由本包提供 | 由底层基础设施负责 |

## 责任分层

```text
Coolify 官方 REST / MCP
  -> 权限、Team、资源生命周期
ChatCoolify
  -> Python 类型、CLI、只读默认、显式写门
AI / CI
  -> 生成计划、调用受限接口、等待人工确认
人
  -> 决定是否授予权限、创建 Token、批准高风险写入
```
