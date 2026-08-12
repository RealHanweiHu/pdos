# CEHub → PDOS 迁移工具 v1 运行手册

> 适用范围：Sprint 3 试点项目的离线迁移演练。v1 支持 NPD 与 OBT 两类项目，并只读取老 CEHub 的 `users`、`projects`、`project_tasks`、`project_gate_reviews`、`project_files`。工具不创建 RDS 账号、不复制文件正文、不触发历史业务事件或 Agent。

## 1. 人工前置门禁

以下动作必须由 DBA/运维在人确认后执行，编码 Agent 不代办：

1. 在 CEHub 数据库创建独立只读登录账号；仅授予上述五张表的 `SELECT`，设置 `default_transaction_read_only=on`。
2. 确认 PDOS 已升级到 Alembic `0020_cehub_migration_v1`，目标租户与迁移操作人均存在且为 active。
3. 确认本轮项目选择器。`--project-id` 可接受真实源 ID，或唯一 `projectNumber`；推荐试点配置已拍板为 `C4s`（源 ID `zGpNH0Xq`）与 `S18-01`（源 ID `aBnbEdQG`）。不要省略该参数以运行无边界全库迁移。
4. 在 ECS 的 `.env.production` 中以权限保持型编辑器写入迁移变量；文件必须仍由部署账号拥有且为 `0600`。连接串不得使用 shell `export`，避免进入 history，也不得写入仓库或报告：

   ```dotenv
   CEHUB_SOURCE_DATABASE_URL=postgresql://<readonly-user>:<secret>@<rds-host>:5432/<cehub-db>?sslmode=verify-full&sslrootcert=/app/certs/ApsaraDB-CA-Chain.pem
   CEHUB_SOURCE_SCHEMA=public
   DATABASE_URL=postgresql://<pdos-app>:<secret>@<rds-host>:5432/pdos?sslmode=verify-full&sslrootcert=/app/certs/ApsaraDB-CA-Chain.pem
   PDOS_TENANT_ID=<target-tenant-uuid>
   PDOS_MIGRATION_ACTOR_USER_ID=<active-operator-user-uuid>
   ```

生产 CLI 还会在连接前验证：目标必须是已批准 RDS 上的 `pdos`/`pdos_app` 且使用固定 CA，源与目标必须是同一 RDS 的不同数据库和不同登录角色，源连接同样必须 `verify-full` 使用固定 CA。命令行入口不会输出连接 URL；报告先以 `0600` 临时文件落盘并原子替换，拒绝符号链接，不存在先公开创建再 chmod 的窗口。
如 CEHub 连接串沿用 Prisma 模板并包含 `uselibpqcompat=true`，入口只移除这一 psycopg 不识别的兼容参数；`sslmode` 等真实 PostgreSQL 参数原样保留。

DBA 可在 CEHub 数据库中按以下模板创建账号（密码通过 RDS 安全渠道生成和交付，不把成品 SQL 写入仓库）：

```sql
CREATE ROLE pdos_cehub_readonly LOGIN NOINHERIT PASSWORD '<generated-secret>';
ALTER ROLE pdos_cehub_readonly SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE cehub TO pdos_cehub_readonly;
GRANT USAGE ON SCHEMA public TO pdos_cehub_readonly;
GRANT SELECT ON public.users, public.projects, public.project_tasks,
  public.project_gate_reviews, public.project_files TO pdos_cehub_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON public.users, public.projects, public.project_tasks,
  public.project_gate_reviews, public.project_files FROM pdos_cehub_readonly;
```

迁移器会在读取项目数据前再次验证：当前登录的默认事务必须为只读、五张源表均可 `SELECT` 且均无写权限。使用现役 CEHub 可写应用账号会 fail-close，即使代码随后执行了 `SET TRANSACTION READ ONLY` 也不会放行。

## 2. Dry-run（强制先执行）

正式 ECS 操作必须使用待审 commit 构建出的 API 候选镜像，不能借用当前线上旧镜像，也不能在宿主机直接运行 Python（连接串中的 CA 路径是容器内路径）。`build` 只产生本地镜像，不替换运行容器；确认镜像标签等于待审 git SHA 后，为 UID/GID 10001 的非 root 容器准备唯一可写报告目录：

```bash
./scripts/deploy-ecs.sh build
export PDOS_MIGRATION_IMAGE='pdos-api:<approved-git-sha>'
docker image inspect "$PDOS_MIGRATION_IMAGE" >/dev/null
export PDOS_MIGRATION_REPORT_DIR="/opt/pdos-migration-reports/${PDOS_MIGRATION_IMAGE#pdos-api:}"
install --directory --mode 0700 --owner 10001 --group 10001 "$PDOS_MIGRATION_REPORT_DIR"

docker run --rm --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env.production \
  --mount type=bind,src="$PDOS_MIGRATION_REPORT_DIR",dst=/reports \
  "$PDOS_MIGRATION_IMAGE" python -m scripts.migrate_cehub_v1 \
  --dry-run \
  --project-id C4s \
  --project-id S18-01 \
  --report /reports/cehub-v1-dry-run.json
```

通过条件：

- `status` 为 `ready`、`errors` 为空、`target_writes` 恰好为 `0`；
- 记录 64 位 `source_fingerprint`；项目负责人和数据 Owner 的批准必须明确绑定这一快照，而不只是绑定项目编号；
- `selected_project_ids` 为解析后的真实源 ID `zGpNH0Xq`、`aBnbEdQG`，而不是项目编号；
- `source_counts` 与 CEHub 五张源表的限定项目计数一致；
- 每个 `samples` 项目的 code/name/current_stage，以及 Task/Gate review/File reference 计数，经人工抽查一致；
- 无 `UNSUPPORTED_PROJECT_CATEGORY`、`SOURCE_REFERENCE_MISSING`、`TARGET_CONFLICT` 或 `SOURCE_CHANGED`。

旧账号按 User 身份记录迁移，但统一 `is_active=false`、`password_hash=NULL`；Owner/Admin 降为目标 Admin，Member/Viewer 降为 Engineer，External 降为 Supplier。账号启用与角色提升必须另走人工治理。

## 3. Apply（需再次获得生产操作授权）

Dry-run 报告由项目负责人和数据 Owner 签字后，将报告内的完整 `source_fingerprint` 注入批准变量，并使用完全相同、顺序相同的项目选择器。确认口令同时绑定目标租户、获批快照与项目范围；缺一项或任一字符不同，CLI 都会在连接数据库前拒绝：

```bash
export PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT='<dry-run source_fingerprint>'
export PDOS_MIGRATION_TENANT_CONFIRM='<same target-tenant-uuid from .env.production>'
export PDOS_MIGRATION_APPLY_CONFIRM="apply:${PDOS_MIGRATION_TENANT_CONFIRM}:${PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT}:C4s,S18-01"
docker run --rm --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env.production \
  --env PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT \
  --env PDOS_MIGRATION_APPLY_CONFIRM \
  --mount type=bind,src="$PDOS_MIGRATION_REPORT_DIR",dst=/reports \
  "$PDOS_MIGRATION_IMAGE" python -m scripts.migrate_cehub_v1 \
  --apply \
  --project-id C4s \
  --project-id S18-01 \
  --report /reports/cehub-v1-apply.json
```

apply 会在任何目标写入前重新冻结源快照，并与获批 fingerprint 做常量时间比较；不一致时返回 `SOURCE_SNAPSHOT_NOT_APPROVED`。必须重新 dry-run、抽查和批准，禁止把环境变量改成新 fingerprint 以绕过复核。单次 apply 是一个目标库事务，并按租户加事务级 advisory lock。任一验证或写入失败都会整体回滚。成功后：

- `cehub_audit.migration_runs` 记录源快照指纹、项目范围和计数；
- `cehub_audit.migration_mappings` 记录每个 User/Project/Task/Gate review/File reference 的稳定 external key、目标 UUID 与源行 hash；
- 每个 Project 按源类型实例化独立版本化 Workflow：NPD 为七阶段/七个 Gate，OBT 为 `intake → sample → pvt → mp` 四阶段/四个 Gate；全部历史 Gate review 保存在 `gate_history_records`，最新一轮投影到 Gate 当前状态；
- 文件只进入 `external_file_references`，保留原 OSS object key/URL/元数据，不进入新文档抽取链，也不复制对象正文。

## 4. 幂等重放与抽样 SQL

以相同 `PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT` 和相同确认口令原命令再次 `--apply`，仅把报告文件名改为 `cehub-v1-replay.json`。通过条件：`created_counts` 五类全部为 `0`，`skipped_counts == source_counts`，业务表和 mapping 行数不增加；只新增一条成功运行审计记录。重放验证完成后执行 `unset PDOS_MIGRATION_APPLY_CONFIRM PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT PDOS_MIGRATION_TENANT_CONFIRM PDOS_MIGRATION_IMAGE PDOS_MIGRATION_REPORT_DIR`。

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
- `SOURCE_SNAPSHOT_NOT_APPROVED`：当前完整源快照与数据 Owner 批准的 dry-run fingerprint 不同；重新 dry-run 和人工抽查，不得直接批准新值。
- `TARGET_CONFLICT`：目标 code/username/email 已被其他实体占用。禁止改脚本静默合并；由数据 Owner 给出映射决策。
- `UNSUPPORTED_PROJECT_CATEGORY`：v1 仅支持 NPD/OBT；ECO/Derivative/IDR/JDM 不得强映射到这两类 Workflow。
- 失败 apply 无部分数据，无需回退。成功 apply 不提供自动删除命令；如演练必须撤销，由 DBA 根据该 run 的 mapping 清单，在备份与人批准后按 FK 逆序处理。
- 正式切换前老 CEHub 仍是双跑期事实源；Sprint 5 全员切换前不得将其改为只读归档。
