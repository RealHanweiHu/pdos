# Sprint 0 ECS 空应用与登录页 Smoke

本运行手册只用于 Sprint 0 人工出口。任何 ECS、RDS、OSS、Caddy 或 DNS 操作都必须先取得人的**明确授权**；自动测试不得使用生产凭据或生产数据库。

## 1. 人工前置条件

- RDS 已创建独立数据库 `pdos` 与普通账号 `pdos_app`，并在该库验证 `CREATE EXTENSION IF NOT EXISTS vector`。
- OSS 已创建私有桶 `pdos-files`；应用凭据没有建桶权限。
- ECS `8.140.197.68` 上 Docker/Compose 正常，`127.0.0.1:3002` 未占用；不对公网直接暴露 API 端口。
- `pdos.beepump.io` 的 DNS A 记录由人确认指向 ECS；Caddy 变更前先备份并执行配置校验。
- 服务器上的 `.env.production` 由 `.env.production.example` 复制后填写，权限设为仅部署账号可读；不得提交或复制回工作区。

## 2. 发布前检查

1. 记录待部署 commit 和当前线上 commit；设置唯一镜像标签，例如 `PDOS_IMAGE_TAG=<git-sha>`。
2. 确认 `DATABASE_URL` 使用 `pdos_app`、数据库名 `pdos`、`sslmode=verify-full` 与容器内 CA 路径。
3. 确认 `JWT_SECRET` 至少 32 字节且与开发值不同；确认 `APP_PORT=3002`。
4. 在本地隔离的 `pdos_test` 运行 `make verify-sprint-0`，全部门禁全绿后才上传代码。
5. 在 ECS 先把 `.env.production` 权限设为 `0600`，再运行 `make production-preflight`；失败时禁止执行 migration/build/up。该检查不打印配置值或 secrets。

## 3. ECS 启动顺序

在取得本次部署授权后，使用 `compose.production.yaml`：

```bash
docker compose --env-file .env.production -f compose.production.yaml build
docker compose --env-file .env.production -f compose.production.yaml up -d
docker compose --env-file .env.production -f compose.production.yaml ps
```

Compose 必须按 `migrate → api healthy → web healthy` 启动。`api` 仅在容器网络暴露 8000；宿主机只绑定 `127.0.0.1:3002`。

## 4. 公开前初始化、Caddy 与 smoke

若 `/api/session/status` 返回 `needs_setup: true`，此时不得先发布 DNS/Caddy。由人通过 **SSH 端口转发**访问宿主机回环端口，例如：

```bash
ssh -N -L 43002:127.0.0.1:3002 <deploy-user>@8.140.197.68
```

人在本机浏览器打开 `http://127.0.0.1:43002/login` 完成唯一一次 setup，确认状态变为 `needs_setup: false` 后关闭隧道。生产管理员密码只由人输入；不得出现在命令、任务消息或日志中。只有完成这一公开前初始化，才能开放域名入口。

Caddy 目标配置为：

```caddyfile
pdos.beepump.io {
    reverse_proxy 127.0.0.1:3002
}
```

先执行 Caddy 配置校验，再 reload。依次验证：

- 宿主机 `/login` 返回 200 且标题为 `登录 · PDOS`。
- 宿主机 `/api/session/status` 返回 `needs_setup` 布尔值。
- 公网 HTTPS `/login` 返回 200，证书有效，HTTP 自动跳转 HTTPS。
- 浏览器完成 login→me→首页；密码与 JWT 不出现在页面、响应体或日志。
- `docker compose logs api web` 无 traceback、hydration error 或连续 5xx。

setup 会创建生产管理员，是一次性业务写操作；必须由人确认账号信息并在私有隧道的浏览器中执行，Agent 不代填生产密码。

## 5. 成功判据与观察

- migration 完成且只有一个 Alembic head；API/web health 均为 healthy。
- 只有 `127.0.0.1:3002` 监听应用流量，8000 不映射到宿主机。
- 登录关键路径成功，错误密码返回稳定 401，事件与不可变审计仍同事务留痕。
- 部署后至少观察 30 分钟：5xx、容器重启、数据库连接错误与 Caddy 错误日志均无新增异常。

## 6. 回滚

触发条件：健康检查失败、持续 5xx、登录不可用、数据完整性异常或安全边界异常。

1. 保留数据库，不在事故处理中执行 Alembic downgrade。
2. 把 `PDOS_IMAGE_TAG` 恢复到部署前记录的镜像标签，重新执行 `docker compose ... up -d --no-build`。
3. 若新 Caddy 配置导致故障，恢复备份配置、校验后 reload。
4. 复查 `/healthz`、`/login`、`/api/session/status` 与日志；记录故障时间、commit、迁移 head 和处置结果。

若 migration 已引入不可向后兼容变化，应停止发布并走修复迁移，不得通过复用迁移号或手工改 schema 回退。
