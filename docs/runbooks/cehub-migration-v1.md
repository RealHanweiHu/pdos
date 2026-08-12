# CEHub → PDOS 迁移工具 v1 运行手册

> 适用范围：Sprint 3 试点项目的离线迁移演练。v1 支持 NPD 与 OBT 两类项目，并只读取老 CEHub 的 `users`、`projects`、`project_tasks`、`project_gate_reviews`、`project_files`。工具不创建 RDS 账号、不复制文件正文、不触发历史业务事件或 Agent。

## 1. 人工前置门禁

以下动作必须由 DBA/运维在人确认后执行，编码 Agent 不代办：

1. 在 CEHub 数据库创建独立只读登录账号；仅授予上述五张表的 `SELECT`，设置 `default_transaction_read_only=on`。
2. 确认 PDOS 已升级到 Alembic `0020_cehub_migration_v1`，目标租户与迁移操作人均存在且为 active。
3. 确认本轮项目选择器。`--project-id` 可接受真实源 ID，或唯一 `projectNumber`；推荐试点配置已拍板为 `C4s`（源 ID `zGpNH0Xq`）与 `S18-01`（源 ID `aBnbEdQG`）。不要省略该参数以运行无边界全库迁移。
4. 在私有执行环境注入连接变量，不写入仓库、shell history 或报告：

   ```bash
   export CEHUB_SOURCE_DATABASE_URL='postgresql://<readonly-user>:<secret>@<rds-host>:5432/<cehub-db>?sslmode=verify-full'
   export CEHUB_SOURCE_SCHEMA='public'
   export DATABASE_URL='postgresql://<pdos-app>:<secret>@<rds-host>:5432/pdos?sslmode=verify-full'
   export PDOS_TENANT_ID='<target-tenant-uuid>'
   export PDOS_MIGRATION_ACTOR_USER_ID='<active-operator-user-uuid>'
   ```

源库与目标库名称必须不同。命令行入口不会输出连接 URL，报告文件权限固定为 `0600`。

## 2. Dry-run（强制先执行）

从仓库根目录运行：

```bash
cd server
uv run python -m scripts.migrate_cehub_v1 \
  --dry-run \
  --project-id C4s \
  --project-id S18-01 \
  --report ../output/migrations/cehub-v1-dry-run.json
```

通过条件：

- `status` 为 `ready`、`errors` 为空、`target_writes` 恰好为 `0`；
- `selected_project_ids` 为解析后的真实源 ID `zGpNH0Xq`、`aBnbEdQG`，而不是项目编号；
- `source_counts` 与 CEHub 五张源表的限定项目计数一致；
- 每个 `samples` 项目的 code/name/current_stage，以及 Task/Gate review/File reference 计数，经人工抽查一致；
- 无 `UNSUPPORTED_PROJECT_CATEGORY`、`SOURCE_REFERENCE_MISSING`、`TARGET_CONFLICT` 或 `SOURCE_CHANGED`。

旧账号按 User 身份记录迁移，但统一 `is_active=false`、`password_hash=NULL`；Owner/Admin 降为目标 Admin，Member/Viewer 降为 Engineer，External 降为 Supplier。账号启用与角色提升必须另走人工治理。

## 3. Apply（需再次获得生产操作授权）

Dry-run 报告由项目负责人和数据 Owner 签字后，使用完全相同的项目选择器执行：

```bash
cd server
uv run python -m scripts.migrate_cehub_v1 \
  --apply \
  --project-id C4s \
  --project-id S18-01 \
  --report ../output/migrations/cehub-v1-apply.json
```

单次 apply 是一个目标库事务，并按租户加事务级 advisory lock。任一验证或写入失败都会整体回滚。成功后：

- `cehub_audit.migration_runs` 记录源快照指纹、项目范围和计数；
- `cehub_audit.migration_mappings` 记录每个 User/Project/Task/Gate review/File reference 的稳定 external key、目标 UUID 与源行 hash；
- 每个 Project 按源类型实例化独立版本化 Workflow：NPD 为七阶段/七个 Gate，OBT 为 `intake → sample → pvt → mp` 四阶段/四个 Gate；全部历史 Gate review 保存在 `gate_history_records`，最新一轮投影到 Gate 当前状态；
- 文件只进入 `external_file_references`，保留原 OSS object key/URL/元数据，不进入新文档抽取链，也不复制对象正文。

## 4. 幂等重放与抽样 SQL

原命令再次 `--apply`。通过条件：`created_counts` 五类全部为 `0`，`skipped_counts == source_counts`，业务表和 mapping 行数不增加；只新增一条成功运行审计记录。

以下 SQL 仅示意，参数由 DBA 绑定，不直接拼接：

```sql
SELECT source_fingerprint, selected_project_ids, stats, created_at
FROM cehub_audit.migration_runs
WHERE tenant_id = :tenant_id
ORDER BY created_at DESC;

SELECT entity_type, count(*)
FROM cehub_audit.migration_mappings
WHERE tenant_id = :tenant_id AND source_system = 'cehub-v3'
GROUP BY entity_type ORDER BY entity_type;

SELECT p.code, p.name, s.code AS current_stage, p.status
FROM cehub_project.projects p
JOIN cehub_project.stages s ON s.tenant_id = p.tenant_id AND s.id = p.current_stage_id
WHERE p.tenant_id = :tenant_id AND p.code IN (:project_code_1, :project_code_2);
```

至少抽查：项目主数据、当前阶段、2 个 Task 状态/负责人/日期、全部 Gate review 轮次和 1 个 OSS 引用。报告不得包含连接串或密码。

## 5. 失败、漂移与回退

- `SOURCE_CHANGED`：源行在首次成功导入后发生变化。工具不会覆盖目标真值；先确认双跑 SoR，再由人决定新一轮对账方案。
- `TARGET_CONFLICT`：目标 code/username/email 已被其他实体占用。禁止改脚本静默合并；由数据 Owner 给出映射决策。
- `UNSUPPORTED_PROJECT_CATEGORY`：v1 仅支持 NPD/OBT；ECO/Derivative/IDR/JDM 不得强映射到这两类 Workflow。
- 失败 apply 无部分数据，无需回退。成功 apply 不提供自动删除命令；如演练必须撤销，由 DBA 根据该 run 的 mapping 清单，在备份与人批准后按 FK 逆序处理。
- 正式切换前老 CEHub 仍是双跑期事实源；Sprint 5 全员切换前不得将其改为只读归档。
