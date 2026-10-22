# S3-7 生产 migration 0020 与真实源预检记录

日期：2026-08-12
范围：升级 PDOS 生产 schema、确认 CEHub 试点数据形态，并建立正式迁移所需的独立只读账号与执行上下文；未执行正式 dry-run/apply，未部署新应用镜像。

## 已完成

- 经人授权，以提交 `189492e` 的候选迁移目录执行一次性 Alembic runtime。
- 生产 PDOS 从 `0014_finding_quality_controls` 单调升级至 `0020_cehub_migration_v1`。
- `alembic current` 返回 `0020_cehub_migration_v1 (head)`。
- 已确认 `cehub_audit.migration_runs`、`cehub_audit.migration_mappings`、`cehub_project.external_file_references`、`cehub_project.gate_history_records` 存在。
- `pdos-web-1`、`pdos-api-1`、`pdos-dispatcher-1`、`pdos-executor-1` 均保持 healthy，restart count 为 0；`https://pdos.beepump.net/login` 返回 HTTP 200。
- 运行中应用仍是原 `cf79b2918efbed0254b855dacb6340ea13781c94` 镜像；本次没有切换容器或重部署业务代码。
- 经人于 2026-08-12 授权创建 RDS 角色 `pdos_cehub_readonly`：`LOGIN + NOINHERIT`、连接上限 2，且无 CREATEROLE/CREATEDB/SUPERUSER/REPLICATION/BYPASSRLS；角色自身未加入任何其他角色。
- 新角色的 `default_transaction_read_only=on`，且对 `users`、`projects`、`project_tasks`、`project_gate_reviews`、`project_files` 五表均为 `SELECT=true`、`INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER=false`。验证使用新账号真实建连，不采信创建 SQL 本身。
- `/opt/pdos/.env.production` 已唯一写入 `CEHUB_SOURCE_DATABASE_URL`、`CEHUB_SOURCE_SCHEMA`、`PDOS_TENANT_ID`、`PDOS_MIGRATION_ACTOR_USER_ID`；文件仍为 `root:root 0600`，四个运行容器未重启且均保持 healthy。
- 目标上下文已用生产 PDOS 复核：active 租户为 `beepump`（`e340c240-d8f0-429c-aac5-69ab9b42fac5`），操作人为 active `admin` Owner（`4bdba865-c5b1-4ca1-aa85-be467e1fad42`）。写入前配置备份为 `/opt/pdos/.env.production.backup-before-cehub-readonly-20260812T163833Z`；密码和连接串未进入报告或命令输出。
- 最新提交 `5a82d0023cf1b5255d1ae9e2c7262c4c0d34b0e2` 已在本地构建为 API 候选镜像；OCI revision 等于完整 commit、运行用户为 `pdos`，镜像内含六类非 SELECT 权限校验，且 `scripts.migrate_cehub_v1 --help` 在只读容器中可启动。该本地 smoke 未连接数据库，也不构成上传或 production dry-run。

## 真实源只读预检

| 项目编号 | CEHub 源 ID | 类型 / 当前阶段 | 当前纳入 v1 的源记录形态 |
|---|---|---|---|
| C4s | `zGpNH0Xq` | OBT / intake | 21 Tasks、8 Files、0 Gate reviews |
| S18-01 | `aBnbEdQG` | NPD / concept | 32 Tasks、2 Files、0 Gate reviews |

预检揭示原本把项目编号当主键、把 C4s 当 NPD 的假设不成立。迁移器已改为接受源 ID 或唯一项目编号，报告/审计始终保存真实源 ID；同时按 CEHub 语义增加 OBT `intake → sample → pvt → mp` Workflow 和独立 Gate 策略。

## 已就绪但尚未执行的门禁

- `cehub_audit.migration_runs` / `migration_mappings` 尚未写入试点迁移记录；生产业务数据 apply 尚未开始。
- 现役 CEHub 应用登录账号具备写权限，不能作为 S3-7 正式验收凭据；正式运行只允许使用已验证的 `pdos_cehub_readonly`。
- 现役 CEHub URL 含 Prisma 专用 `uselibpqcompat` 参数，psycopg 原生连接会拒绝；迁移入口现仅剔除该参数，并保留 `sslmode` 等 PostgreSQL 参数，已有回归测试。
- 提交 `c39b2b4` 的只读候选已上传至 `/opt/pdos-migration-c39b2b4`（444 个受版本控制文件），未替换运行容器。以该候选对真实 CEHub 现役可写账号执行负向 smoke，连接参数规范化成功后在项目快照读取前得到 `blocked_write_capable_role`；目标 PDOS 数据库未参与该 smoke。
- 独立账号和私有执行环境已就绪；收到正式 production dry-run 确认后，严格执行 `dry-run → 数据 Owner 抽查 → apply 再授权 → apply → 幂等重放 → 抽样 SQL`。
