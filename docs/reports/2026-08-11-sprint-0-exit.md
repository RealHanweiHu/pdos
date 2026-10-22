# Sprint 0 Exit Report

## Status

**Passed and approved.** S0-0～S0-5、基础设施、生产部署、HTTPS、回滚准备、观察窗口和人工认证公网 smoke 均已验证；人于 2026-08-11 明确确认进入 Sprint 1。

- 报告日期：2026-08-11
- 生产域名：`https://pdos.beepump.net`
- 生产应用制品：`8bc4fda0a0029793af5f6ba2a5bf4123e7ca6120`

## Canonical scope completion

| Work item | Status | Evidence |
| --- | --- | --- |
| S0-0 UI baseline | Complete | UI v0.2、橙色 token、8px 圆角、双主题和三承重界面定义已冻结 |
| S0-1 scaffold | Complete | Next.js/FastAPI/Alembic、pgvector/MinIO、CI 和测试库 fail-close 全绿 |
| S0-2 migration 0001 | Complete | 10 schema namespace 与首批实体表、约束、索引及往返迁移测试通过 |
| S0-3 auth/tenant | Complete | 一次性 setup、密码登录、JWT 与 fail-close 租户解析正反例通过 |
| S0-4 RBAC | Complete | 7 角色矩阵、项目成员边界、外部角色最小可见面与跨租户拒绝测试通过 |
| S0-5 event/audit | Complete | migration 0003、10 类版本化事件、同事务 event+audit、幂等和不可变审计测试通过 |

唯一执行计划中的 S0-0～S0-5 checkbox 均为 `[x]`；当前唯一指针仍是 Sprint 0 Exit Gate。

## Quality gate

最终本地命令：

```bash
export TEST_DATABASE_URL='<isolated pdos_test DSN>'
export JWT_SECRET='<test-only value of at least 32 bytes>'
PDOS_POSTGRES_PORT=56432 make verify-sprint-0
```

结果：

- web：15 tests；lint、typecheck、production build 全绿。
- server：82 tests；ruff、format、mypy、compileall 全绿。
- `pdos_test` 隔离检查与 Alembic head migration 全绿。
- web/API/BFF runtime smoke 全绿。
- production container smoke：migrate→API healthy→web healthy；API/web 均以非 root 用户运行。
- 生产模板不含真实密钥；本地 `.env.production` 被忽略且权限为 `0600`。

## Production infrastructure

### RDS and OSS

- RDS 数据库/账号：`pdos` / `pdos_app`；生产迁移到 `0003_events_audit (head)`。
- 托管 pgvector 已验证，版本 `0.8.1.2`。
- OSS：北京区私有桶 `pdos-files`，公共访问阻断、AES256、最小权限 RAM policy；应用角色没有建桶权限。
- 生产 setup 已由人通过私有 SSH 隧道完成；数据库验证 tenant/user/Owner、`TENANT_BOOTSTRAPPED` event 和对应 audit 各一条，`needs_setup=false`；隧道随后关闭。

### ECS containers

- `pdos-api-1`：healthy，UID 10001，仅容器网络暴露 8000。
- `pdos-web-1`：healthy，UID 1001，仅绑定 `127.0.0.1:3002→3000`。
- `pdos-migrate-1`：exit 0。
- web 的生产网络别名冻结为 `pdos-web`，Nginx 不使用跨项目重复的通用别名 `web`。

## Public edge and security

- DNS：`pdos.beepump.net` 从 ECS 解析到 `8.140.197.68`。
- HTTP `/login`：301 到 HTTPS。
- HTTPS `/login`：200，标题 `登录 · PDOS`；`/api/session/status` 返回 `needs_setup=false`。
- 证书：Let’s Encrypt，CN `pdos.beepump.net`，有效期至 2026-11-09。
- `certbot renew --cert-name pdos.beepump.net --dry-run --no-random-sleep-on-renew` 成功；域名定向 deploy hook 已通过 `nginx -t` 与 reload 验证。
- 安全响应头：CSP、HSTS、X-Frame-Options DENY、nosniff、Referrer-Policy、Permissions-Policy 各一份；已隐藏 `X-Powered-By`。
- `/api/session/login` 与 `/api/session/setup` 在 Nginx 和应用层均有限流；公网错误凭据稳定返回 401。
- Nginx 同时接入原 ERP 网络与 `pdos_default`，反代唯一别名 `pdos-web:3000`。
- 观察中发现并修复 ERP/CRM 共享别名 `web` 的既有偶发误路由；ERP 上游改为唯一 DNS 名 `erp-management-dashboard-web-1:3000`。ERP、CRM、Hub 回归响应正常。

## Observation and rollback

最终 Nginx 配置从 `2026-08-11T12:55:58Z` 起连续观察至少 30 分钟：

- API alerts：0。
- web alerts：0。
- Nginx errors/5xx：0。
- API、web、Nginx restart count：0。
- PDOS 登录页和 ERP 主站每分钟探针持续返回预期状态。

回滚准备：

- ECS 备份目录：`/opt/pdos-backups/20260811-nginx-cutover`，包含原 ERP Compose、Nginx TLS 配置、证书 hook、PDOS Compose 与 `0600` 环境文件。
- PDOS 可把 `PDOS_IMAGE_TAG` 恢复到部署前标签并执行 `docker compose ... up -d --no-build`；不执行 Alembic downgrade。
- 边缘故障时恢复 Compose/TLS/hook 备份、先校验，再只强制重建 Nginx。
- 单文件 bind mount 原子替换会更换 inode，因此最终配置不能只 reload；该陷阱已记录在 ADR-001。

## Human-authenticated public smoke

- [x] 人使用生产账号在 `https://pdos.beepump.net/login` 完成成功 login→`/api/session/me`→首页。
- Nginx 访问日志核对到成功路径：`POST /api/session/login = 200`、随后 `GET /api/session/me = 200`。
- 登录后健康复核：API/web 均为 healthy、Nginx running，三者 restart count 均为 0；HTTPS 登录页返回 200，`needs_setup=false`，最近 10 分钟 PDOS 5xx 为 0。

## Exit decision

Sprint 0 验收证据完整，报告状态为 Passed，并已于 2026-08-11 获得人的明确出口确认。当前执行指针已移动到 S1-1。
