# S3-7 生产 migration 0020 与真实源预检记录

日期：2026-08-12
范围：只升级 PDOS 生产 schema，并对 CEHub 试点项目做只读形态确认；未执行项目数据 apply，未部署新应用镜像。

## 已完成

- 经人授权，以提交 `189492e` 的候选迁移目录执行一次性 Alembic runtime。
- 生产 PDOS 从 `0014_finding_quality_controls` 单调升级至 `0020_cehub_migration_v1`。
- `alembic current` 返回 `0020_cehub_migration_v1 (head)`。
- 已确认 `cehub_audit.migration_runs`、`cehub_audit.migration_mappings`、`cehub_project.external_file_references`、`cehub_project.gate_history_records` 存在。
- `pdos-web-1`、`pdos-api-1`、`pdos-dispatcher-1`、`pdos-executor-1` 均保持 healthy，restart count 为 0；`https://pdos.beepump.net/login` 返回 HTTP 200。
- 运行中应用仍是原 `cf79b2918efbed0254b855dacb6340ea13781c94` 镜像；本次没有切换容器或重部署业务代码。

## 真实源只读预检

| 项目编号 | CEHub 源 ID | 类型 / 当前阶段 | 当前纳入 v1 的源记录形态 |
|---|---|---|---|
| C4s | `zGpNH0Xq` | OBT / intake | 21 Tasks、8 Files、0 Gate reviews |
| S18-01 | `aBnbEdQG` | NPD / concept | 32 Tasks、2 Files、0 Gate reviews |

预检揭示原本把项目编号当主键、把 C4s 当 NPD 的假设不成立。迁移器已改为接受源 ID 或唯一项目编号，报告/审计始终保存真实源 ID；同时按 CEHub 语义增加 OBT `intake → sample → pvt → mp` Workflow 和独立 Gate 策略。

## 未执行与剩余门禁

- `cehub_audit.migration_runs` / `migration_mappings` 尚未写入试点迁移记录；生产业务数据 apply 尚未开始。
- 现役 CEHub 应用登录账号具备写权限，不能作为 S3-7 正式验收凭据。
- DBA 仍需创建或确认只对 `users`、`projects`、`project_tasks`、`project_gate_reviews`、`project_files` 授予 `SELECT`，且 `default_transaction_read_only=on` 的独立账号，并以 `CEHUB_SOURCE_DATABASE_URL` 注入私有执行环境。
- 获得该账号和生产 dry-run 授权后，严格执行 `dry-run → 数据 Owner 抽查 → apply 再授权 → apply → 幂等重放 → 抽样 SQL`。
