# 本地项目平台

`coolify platform` 为邀请制可信协作者提供前端项目登记、目录直传、预览、显式正式发布及回退。独立后端继续由 Coolify 原生 Application/Service 管理，可登记成项目服务关联。普通账号只获得平台会话；服务端持有原生 Team token，项目授权每次检查。

```bash
coolify platform --profile work login --url https://<platform-origin> --username <account>
coolify platform --profile work projects create my-site --visibility private
coolify platform --profile work upload PROJECT_ID ./dist
coolify platform --profile work preview PROJECT_ID RELEASE_ID
coolify platform --profile work status PROJECT_ID
coolify platform --profile work publish PROJECT_ID RELEASE_ID
coolify platform --profile work logs PROJECT_ID DEPLOYMENT_ID
coolify platform --profile work rollback PROJECT_ID PREVIOUS_PRODUCTION_RELEASE_ID
```

登录交互隐藏密码；自动化使用 `--password-env KEY` 指定环境变量名，密码不进入参数。endpoint 使用 ChatEnv 的 `coolify-platform` 具名配置，opaque session 使用 TokenStore；选 profile 不切换其他 active 配置。目录上传排除隐藏文件（包括 `.env`/`.git`），拒绝软链接、凭据文件、越界路径和 runtime 保留路径；最多 2,000 文件、8 MiB ZIP、32 MiB 解包内容。只支持已经构建完成并含 `index.html` 的前端产物，不能通过上传自定义 Dockerfile 执行任意宿主命令。

## 执行与来源

上传产物、统一 Dockerfile 和 runtime 形成服务器私有 bare Git commit。原生 Coolify private-deploy-key 应用按该 commit 构建镜像和运行容器；没有另外的 host 静态目录版本指针。preview 和 production 是两个原生应用。发布/回退必须选择不可变 release；上传不会提前改变 production。失败按原生构建/健康记录呈现，成功状态还核对运行中的 artifact digest。

资源返回稳定平台 ID 及经过筛选的 native Team/Project/Environment/Application/Deployment 引用、artifact/Dockerfile digest、实际构建 commit；原目录的原始 commit 与生成的构建 commit 分开。反复调用创建请求和部署请求可复用 `request_key`。派发结果不明时保留状态供核对，不盲目重复队列；日志会过滤凭据和过长构建输入行。

私有 Git source key 仅保留服务器及 Coolify 的密钥资源中，不放进镜像。host SSH forced-command 只允许 `git-upload-pack` 读取源根目录下已登记 bare repo，禁止 shell、写 Git、端口/agent 转发或读取根目录以外路径。需要按已安装 Coolify 的 URL 校验和自定义端口格式核实真实 clone。服务器不提供匿名 Git HTTP/daemon 入口。

## 权限和网页登录

owner 可授权 viewer/deployer；deployer 可预览、发布和回退，viewer 可阅读。账号 admin 负责邀请/停用用户，没有他人项目的隐式阅读、部署或 service-binding 修改权。所有 native 执行目标均从已授权项目映射推导。不要把原生 Team token 发给普通协作者。

每个前端镜像中的通用 runtime 在读取 HTML、JS、资源、导出和服务前检查策略，原始自动域名也受相同保护。public 只开放页面读取，不开放部署或管理；private 逐请求检查账号、reader 会话、中央父会话和当前项目授权，平台不可用时拒绝。

中央控制 cookie 与每个 app reader cookie 均为 host-only Secure/HttpOnly。app 先设置 120 秒 `__Host-` state/nonce cookie（Path=/、无 Domain、SameSite=Lax），回调 code 绑定 app、state 和中央会话，原子消费。唯一 callback auto-POST 同时核对精确中央 Origin 与 app 的 state cookie/form；其余写操作仍需同源 Origin 和 CSRF。当前协议面向同一站点的全 HTTPS 域名，未承诺跨站自定义域。中央退出传导撤销 reader，停用和项目撤权即时生效。ChatLogin 仍是嵌入身份库；这里的 issuer/reader 协议由平台宿主提供。

## Python 与独立服务

```python
from chatcoolify import PlatformClient

client = PlatformClient.from_profile("work")
project = client.create_project("another-site")
release = client.upload(project["id"], "./dist")
preview = client.deploy(project["id"], release["id"], environment="preview")
```

原有 `CoolifyClient` 和 Git/backend API 保留。`PlatformService`、`CoolifyBackend` 是可导入的宿主实现；CLI 是 SDK 薄适配。项目 owner 用 `services list PROJECT_ID --candidates` 取得该原生项目内的候选登记 ID，再以 `services register` 建立关联，不能选择任意 URL、宿主路径或外项目 UUID。第一项 transport adapter 为 ChatComment，签名绑定站点权限、method/path/body，后端独立验证；原始服务域名不绕过鉴权。

## 宿主运维

operator 通过 `coolify-platform-server` typed 配置提供持久目录、原生地址/Team token、受控 server、source URL/key UUID，以及公共/内部控制 origin；`coolify platform serve` 启动同一套服务。`bootstrap-owner` 只在服务器 CLI 首次执行，没有 HTTP 注册或 bootstrap 路由。控制面本身也应登记为原生 Coolify 应用，持久挂载身份/元数据/私有 source，不挂 Docker socket；普通前端没有 host 卷。

备份需同时覆盖 ChatLogin/平台 SQLite 一致快照、私有 bare Git、不可变 artifact 和服务器私有配置。Git commit 保持可达历史供发布和回退，不自动 prune；没有制定清理策略前保留所有登记 release。独立服务数据在自己的持久卷中，静态回退不覆盖数据库。升级/切换先验证新原生资源和数据，再退役旧入口。
