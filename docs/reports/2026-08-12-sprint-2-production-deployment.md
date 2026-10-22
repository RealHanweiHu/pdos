# Sprint 2 Production Deployment Report

## Status

**Deployed and human-smoke verified; Sprint exit remains pending.** Sprint 2 的代码、迁移、数据库运行时边界和四容器运行面已部署到 `pdos.beepump.net`。人于 2026-08-12 明确反馈“已验证”。由于生产库当前没有 Project，仍需先选定或建立 1–2 个真实双跑项目，并获得明确的 Sprint 2 出口确认，才能进入 Sprint 3。

- 报告日期：2026-08-12
- 生产域名：`https://pdos.beepump.net`
- 生产应用制品：`cf79b2918efbed0254b855dacb6340ea13781c94`
- GitHub PR：`https://github.com/RealHanweiHu/pdos/pull/2`

## Release gates

- PR #2 的 `Quality and migration gates` 为 SUCCESS。
- 本地最终门禁：server 216 tests、web 90 tests，Ruff/format/mypy/ESLint/TypeScript/Next.js production build/Python compile 全绿。
- `make sprint2-removal-drill` 通过：停用全部模型凭据后无 provider 调用、无新 Finding、Chat/Brief 明确降级。
- `make sprint2-redteam` 通过：注入诱导写业务表与跨租户读取对 `pdos_agent` 均为 0 穿透。
- 候选 API/Web 镜像均验证为 `linux/amd64` 且以非 root 用户运行，随后才允许切换 ECS 容器。

## Production migration

Alembic 以 `pdos_app` 从 `0003_events_audit` 单调升级到唯一 head `0014_finding_quality_controls`：

```text
0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009
     → 0010 → 0011 → 0012 → 0013 → 0014
```

迁移后抽查保留原生产数据：1 Tenant、1 User、11 Event、11 Audit；部署时 Project 数为 0。未执行 Alembic downgrade，也未手工改写 migration head。

## Agent database boundary

一次性生产角色由人通过不回显的交互步骤设置独立密码；DSN 仅写入 ECS 上权限为 `0600` 的 `.env.production`，没有进入聊天、命令输出、仓库或镜像。

当前版本的 `agent-runtime.sql` 在迁移后连续执行两次均成功，随后验证：

| Check | Expected | Result |
| --- | ---: | ---: |
| `pdos_worker` SELECT `cehub_event.events` | true | true |
| `pdos_worker` UPDATE business Project | false | false |
| `pdos_agent` SELECT business Project | false | false |
| `pdos_agent` INSERT business Risk | false | false |
| `pdos_agent` INSERT model invocation | true | true |
| 未绑定 run lease 的 Agent project projection | 0 rows | 0 rows |

运行时环境边界也已核对：dispatcher 只有 `PDOS_WORKER_DATABASE_URL`；executor 只有 `PDOS_AGENT_DATABASE_URL` 与模型凭据；两者均没有 `DATABASE_URL`。

## ECS runtime

以下服务均运行提交 `cf79b29`，健康检查为 healthy，观察窗口内 restart count 为 0：

- `pdos-api-1`：UID/GID `10001:10001`，仅容器网络暴露 8000。
- `pdos-dispatcher-1`：UID/GID `10001:10001`，持 worker DSN。
- `pdos-executor-1`：UID/GID `10001:10001`，持 Agent DSN。
- `pdos-web-1`：UID/GID `1001:1001`，仅绑定 `127.0.0.1:3002→3000`。

部署后的明确错误扫描未发现 traceback、fatal、panic、permission denied、connection refused 或 HTTP 5xx。Nginx、DNS 和证书配置未变更。

## Public and human smoke

- HTTP `/login`：301 到 HTTPS。
- HTTPS `/login`：200，TLS 校验成功。
- `/api/session/status`：`needs_setup=false`。
- `/projects`：200。
- `/ai-review`：200。
- 真实浏览器刷新首页后按新版鉴权逻辑跳转到 `/login`，控制台 0 warning / 0 error。
- 人于 2026-08-12 使用生产入口完成验证，并明确反馈“已验证”。

## Rollback readiness

- 部署前完整备份：`/opt/pdos-backups/20260812T090032Z-pre-sprint2`。
- 旧发布目录：`/opt/pdos-releases/8bc4fda0a0029793af5f6ba2a5bf4123e7ca6120`。
- 旧 API/Web 镜像标签和 image ID 已记录在备份的 `containers.txt`。
- 应用故障时恢复旧镜像并重新 `up -d --no-build`；数据库保持 `0014`，不在事故处理中 downgrade。

## Remaining Sprint 2 exit actions

- [x] 汇报 S2-1～S2-7、CI、安全、迁移、生产部署与人工 smoke 证据。
- [ ] 由人选择或建立 1–2 个真实 Project，填写 `docs/runbooks/sprint-2-pilot.md` 并开始双跑。
- [ ] 人明确确认 Sprint 2 验收后，将唯一执行指针移至 S3-1。

