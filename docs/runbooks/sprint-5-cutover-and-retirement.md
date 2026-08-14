# Sprint 5 全量迁移、主入口切换与 CEHub 只读退役

> 本手册不授权生产操作。每次 ECS/RDS/CEHub 权限、Nginx/DNS 操作都必须先取得人的明确授权。执行时从经验证 Git bundle 的全新 release 目录运行；不得从本地脏工作树或线上旧镜像运行。

## 1. 发布窗口前准备

1. 冻结完整 release SHA，运行全量本地门禁并保存报告；生产目标 head 为 `0030_phase_three_agents`。
2. 在 ECS 复制上一版本 `.env.production` 到新 release 目录并保持 owner/mode `0600`。确认包含 `CEHUB_SOURCE_DATABASE_URL`、`CEHUB_SOURCE_SCHEMA`、`DATABASE_URL`、`PDOS_TENANT_ID`、`PDOS_MIGRATION_ACTOR_USER_ID`；连接串不得出现在终端输出、工单或报告。
3. 保持 `PDOS_DINGTALK_DELIVERY_ENABLED=false`。本次切换不执行真实钉钉外发，也不把 S5-1 延期例外改写为 PASS。
4. 记录部署前 API/Web image ID、完整 SHA、Alembic head、CEHub 写冻结/恢复负责人和低峰窗口。
5. 按 `docs/runbooks/sprint-0-ecs-smoke.md` 验证 bundle/release 目录并构建候选镜像，但未获部署授权前不要执行 `deploy`。

以下示例中的目录和镜像标签只能填写获批值：

```bash
export PDOS_CUTOVER_SHA='<approved-full-git-sha>'
export PDOS_CUTOVER_IMAGE="pdos-api:${PDOS_CUTOVER_SHA}"
export PDOS_CUTOVER_REPORT_DIR="/opt/pdos-migration-reports/${PDOS_CUTOVER_SHA}/cutover"
docker image inspect "$PDOS_CUTOVER_IMAGE" >/dev/null
install --directory --mode 0700 --owner 10001 --group 10001 "$PDOS_CUTOVER_REPORT_DIR"
```

## 2. 只读捕获全部项目清单

`capture` 读取完整 `projects` 表，包含 archived 历史项目，不写源库或目标库：

```bash
docker run --rm --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env.production \
  --mount type=bind,src="$PDOS_CUTOVER_REPORT_DIR",dst=/reports \
  "$PDOS_CUTOVER_IMAGE" python -m scripts.check_cehub_cutover_inventory \
  --report /reports/cehub-cutover-inventory-capture.json \
  capture
```

通过读取门禁：命令成功、`status=review_required`、`errors=[]`，project_count 与源库独立只读计数一致。报告只表示“待人审”，不表示可 apply。Data Owner 必须逐项确认 Project ID/number/name/category/archived，并签批 `inventory_fingerprint` 与**全部源 Project ID**。若出现非 NPD/OBT 类型，停止并按范围变更处理，禁止强映射。

已知未归档线索是 `zGpNH0Xq`/C4s、`aBnbEdQG`/S18-01、`WqWcl0wK`/D14-04、`xY8-PGbc`/D15-05；它们不是完整清单的替代品。

## 3. 写冻结后复核清单

旧 CEHub 的移动端 `availability.mode=read_only` 只是客户端能力声明，桌面端和服务端没有全局维护模式，不能用作生产写冻结。获批后必须在低峰窗口由 CEHub Owner 与 DBA 共同执行数据库会话级冻结：停止旧应用、清理旧连接、为真实应用角色设置数据库范围的 `default_transaction_read_only=on`，再启动同一旧镜像。短暂停机只用于连接池换代；启动后读取继续可用，业务写入必须返回 PostgreSQL `25006`。

### 3.1 冻结前身份与原值证据

旧 CEHub 的生产编排目录是 `/opt/ce-project-hub`，服务名是 `app`。先从**旧应用实际连接**读取数据库和角色身份；脚本只输出角色、数据库与只读设置，不输出 `DATABASE_URL`：

```bash
CEHUB_CUTOVER_DIR=/opt/ce-project-hub
cd "$CEHUB_CUTOVER_DIR"
docker compose -f docker-compose.prod.yml ps app
docker compose -f docker-compose.prod.yml exec -T app node <<'NODE'
const { Client } = require("pg");
const client = new Client({ connectionString: process.env.DATABASE_URL });
(async () => {
  await client.connect();
  const result = await client.query(`
    SELECT current_user AS role_name,
           current_database() AS database_name,
           current_setting('default_transaction_read_only') AS default_read_only,
           current_setting('transaction_read_only') AS transaction_read_only
  `);
  console.log(JSON.stringify(result.rows[0]));
  await client.end();
})().catch(async (error) => {
  console.error("CEHUB_IDENTITY_FAILED", error.code || "", error.message);
  await client.end().catch(() => {});
  process.exit(1);
});
NODE
```

DBA 把输出的实际角色/数据库代入下面的只读查询，保存数据库范围与角色范围的原始设置；不得猜测角色名，也不得把连接串或密码写进报告：

```sql
SELECT r.rolname, d.datname, s.setconfig
FROM pg_db_role_setting AS s
JOIN pg_roles AS r ON r.oid = s.setrole
JOIN pg_database AS d ON d.oid = s.setdatabase
WHERE r.rolname = '<actual-cehub-app-role>'
  AND d.datname = '<actual-cehub-database>';

SELECT rolname, rolconfig
FROM pg_roles
WHERE rolname = '<actual-cehub-app-role>';
```

### 3.2 冻结、连接池换代与正反向验证

以下动作必须包含在新的明确生产授权中。先停应用，DBA 再清理该角色在该数据库中的旧连接并设置数据库范围默认只读；不要修改独立的 `pdos_cehub_readonly` 迁移账号：

```bash
cd "$CEHUB_CUTOVER_DIR"
docker compose -f docker-compose.prod.yml stop app
```

```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename = '<actual-cehub-app-role>'
  AND datname = '<actual-cehub-database>'
  AND pid <> pg_backend_pid();

ALTER ROLE "<actual-cehub-app-role>" IN DATABASE "<actual-cehub-database>"
  SET default_transaction_read_only = on;
```

旧 CEHub 的 activity-log tailer 每 5 秒写一次 heartbeat；数据库只读后若仍启用会形成持续 `25006` 日志。连接池换代前必须把旧私有环境中的 `ACTIVITY_LOG_TAILER_ENABLED` 原值保存到 `0600` 备份，并设置为 `false`。这只暂停旧系统的写型自动化，不改变读取 API；恢复写权限时也必须按原值恢复该设置。不得用 `AUTOMATION_EVENT_MODE=inline` 代替，否则用户请求会重新触发内联写尝试。

设置成功后启动原应用，不构建或部署任何镜像：

```bash
cd "$CEHUB_CUTOVER_DIR"
docker compose -f docker-compose.prod.yml up -d --no-deps app
```

必须从旧应用的新连接完成三项验证：默认事务和当前事务均为只读；项目计数可读；对永久表的零行 `UPDATE` 被 SQLSTATE `25006` 拒绝。探针即使冻结失效也因 `WHERE false` 不会改变任何行，但“命令成功”仍视为冻结失败并立即停止切换：

```bash
docker compose -f docker-compose.prod.yml exec -T app node <<'NODE'
const { Client } = require("pg");
const client = new Client({ connectionString: process.env.DATABASE_URL });
(async () => {
  await client.connect();
  const settings = await client.query(`
    SELECT current_user AS role_name,
           current_database() AS database_name,
           current_setting('default_transaction_read_only') AS default_read_only,
           current_setting('transaction_read_only') AS transaction_read_only
  `);
  if (settings.rows[0].default_read_only !== "on" ||
      settings.rows[0].transaction_read_only !== "on") {
    throw new Error("CEHub application connection is not read-only");
  }
  const readable = await client.query("SELECT count(*)::int AS project_count FROM public.projects");
  console.log("CEHUB_READ_OK", readable.rows[0].project_count);
  try {
    await client.query("UPDATE public.projects SET id = id WHERE false");
    throw new Error("CEHub write probe unexpectedly succeeded");
  } catch (error) {
    if (error.code !== "25006") throw error;
    console.log("CEHUB_WRITE_REJECTED", error.code);
  }
  await client.end();
})().catch(async (error) => {
  console.error("CEHUB_FREEZE_VERIFY_FAILED", error.code || "", error.message);
  await client.end().catch(() => {});
  process.exit(1);
});
NODE

curl --fail --silent --show-error --max-time 5 \
  http://127.0.0.1:3001/api/setup/status >/dev/null
```

DBA 同时确认该角色没有遗留的已分配写事务；任何返回行都必须先调查并清零：

```sql
SELECT pid, state, xact_start, backend_xid
FROM pg_stat_activity
WHERE usename = '<actual-cehub-app-role>'
  AND datname = '<actual-cehub-database>'
  AND backend_xid IS NOT NULL;
```

冻结失败时保持旧应用停止，不得执行 inventory verify 或 dry-run。恢复写权限不是自动回退动作；只有 Data Owner 单独批准恢复后，才停止 `app`，按 3.1 保存的原值执行对应的 `ALTER ROLE ... IN DATABASE ... SET ...`，或仅在原来不存在该设置时执行：

```sql
ALTER ROLE "<actual-cehub-app-role>" IN DATABASE "<actual-cehub-database>"
  RESET default_transaction_read_only;
```

随后再次清理旧连接、启动 `app`，并从应用连接核对设置与 3.1 原值完全一致。不得用无条件 `RESET` 覆盖原本已有的组织级只读政策。

把 Data Owner 批准的所有源 ID 按批准顺序放进 shell 数组；不要从 JSON 用不受控的 `eval` 生成命令：

```bash
export PDOS_CUTOVER_APPROVED_INVENTORY_FINGERPRINT='<approved-inventory-fingerprint>'
PDOS_CUTOVER_PROJECT_IDS=(
  '<approved-source-id-1>'
  '<approved-source-id-2>'
)
PDOS_CUTOVER_PROJECT_ARGS=()
for project_id in "${PDOS_CUTOVER_PROJECT_IDS[@]}"; do
  PDOS_CUTOVER_PROJECT_ARGS+=(--expected-project-id "$project_id")
done

docker run --rm --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env.production \
  --env PDOS_CUTOVER_APPROVED_INVENTORY_FINGERPRINT \
  --mount type=bind,src="$PDOS_CUTOVER_REPORT_DIR",dst=/reports \
  "$PDOS_CUTOVER_IMAGE" python -m scripts.check_cehub_cutover_inventory \
  --report /reports/cehub-cutover-inventory-verify.json \
  verify "${PDOS_CUTOVER_PROJECT_ARGS[@]}"
```

只有 `status=ready`、`errors=[]`、fingerprint 与 ID 集合精确相等才继续。失败时保持窗口状态并让 Data Owner 决定重新盘点或终止；不得直接替换批准 fingerprint。

## 4. 最终全量 dry-run 与批准

把同一有序源 ID 数组转换为迁移器参数：

```bash
PDOS_MIGRATION_PROJECT_ARGS=()
for project_id in "${PDOS_CUTOVER_PROJECT_IDS[@]}"; do
  PDOS_MIGRATION_PROJECT_ARGS+=(--project-id "$project_id")
done

docker run --rm --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env.production \
  --mount type=bind,src="$PDOS_CUTOVER_REPORT_DIR",dst=/reports \
  "$PDOS_CUTOVER_IMAGE" python -m scripts.migrate_cehub_v1 \
  --dry-run \
  "${PDOS_MIGRATION_PROJECT_ARGS[@]}" \
  --report /reports/cehub-cutover-dry-run.json
```

要求 `status=ready`、`errors=[]`、`target_writes=0`，并由 Data Owner 按 `docs/runbooks/cehub-migration-v1.md` 抽查全部项目与五类计数。最终批准必须同时写明 release SHA、tenant UUID、actor UUID、有序项目 ID、inventory fingerprint、dry-run `source_fingerprint` 与窗口。

## 5. 部署、apply 与幂等重放

先取得这一次 release 部署授权，再使用唯一受控入口升级到获批 SHA；脚本会执行 migration 0030、重施 Agent 权限和健康检查：

```bash
export PDOS_DEPLOY_CONFIRM="deploy:${PDOS_CUTOVER_SHA}"
./scripts/deploy-ecs.sh deploy
unset PDOS_DEPLOY_CONFIRM
./scripts/deploy-ecs.sh status
```

部署通过后，取得全量 apply 的单独生产授权。确认口令由同一有序数组生成，人工核对后再注入容器：

```bash
export PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT='<approved-dry-run-source-fingerprint>'
PDOS_CUTOVER_PROJECT_CSV="$(IFS=,; echo "${PDOS_CUTOVER_PROJECT_IDS[*]}")"
export PDOS_MIGRATION_APPLY_CONFIRM="apply:<target-tenant-uuid>:${PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT}:${PDOS_CUTOVER_PROJECT_CSV}"

docker run --rm --read-only --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env-file .env.production \
  --env PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT \
  --env PDOS_MIGRATION_APPLY_CONFIRM \
  --mount type=bind,src="$PDOS_CUTOVER_REPORT_DIR",dst=/reports \
  "$PDOS_CUTOVER_IMAGE" python -m scripts.migrate_cehub_v1 \
  --apply \
  "${PDOS_MIGRATION_PROJECT_ARGS[@]}" \
  --report /reports/cehub-cutover-apply.json
```

成功后原命令重放一次，只把报告名改为 `cehub-cutover-replay.json`。重放必须 `created_counts` 全 0、`skipped_counts == source_counts`。若前两个试点已迁移且源 hash 未变，它们应为 skipped；任何 `SOURCE_CHANGED` 都必须停止转正并由 Data Owner 对账。

## 6. 主入口与只读归档验收

1. 执行迁移运行/mapping 计数及 Project/Task/Gate/File reference 抽查；旧用户必须保持 inactive，账号启用另走治理。
2. Owner/Admin 在 `https://pdos.beepump.net/login` 登录，验证 Portfolio、至少一个 NPD 与一个 OBT 项目、历史 Gate 和文件引用。
3. 若域名和 TLS 已正确指向当前 PDOS，不做 DNS/Nginx 变更；由业务 Owner 宣布该域名为主入口并记录时间。若现状不符，停止并另行申请 Nginx/DNS 授权。
4. 保持 CEHub 数据库默认只读/写服务冻结，保留审计查询入口；用审计账号验证读取可用，并验证业务写操作 fail-close。记录 CEHub 归档入口、保留期限与 Owner。
5. 运行 `./scripts/deploy-ecs.sh status`，观察至少 30 分钟；检查 5xx、容器重启、数据库错误、权限错误和迁移对账告警。

只有 Data Owner、发布 Owner 和业务 Owner 均签字，才能确认 Sprint 5 Exit 与切换退役完成。S5-1 延期项必须作为残余风险单独保留。

## 7. 停止与回滚

- inventory/dry-run 失败：零目标写，停止窗口。
- deploy 失败：按 `docs/runbooks/sprint-0-ecs-smoke.md` 使用前一完整 SHA 回滚应用；不执行 Alembic downgrade。
- apply 失败：事务应整体回滚，保存失败报告并排查；禁止手工补写。
- apply 成功但抽查失败：不宣布主入口，不删除迁移数据；用 migration run/mapping 对账并走修复迁移。
- 已转正后发生阻断故障：先取得回滚授权，再回滚应用；只有 Data Owner 明确批准时才恢复 CEHub 写权限。恢复前记录故障编号、原只读设置和责任人。

收尾时清除一次性变量，不删除审计报告：

```bash
unset PDOS_DEPLOY_CONFIRM PDOS_MIGRATION_APPLY_CONFIRM \
  PDOS_MIGRATION_APPROVED_SOURCE_FINGERPRINT \
  PDOS_CUTOVER_APPROVED_INVENTORY_FINGERPRINT \
  PDOS_CUTOVER_PROJECT_CSV PDOS_CUTOVER_IMAGE PDOS_CUTOVER_SHA
unset PDOS_CUTOVER_PROJECT_IDS PDOS_CUTOVER_PROJECT_ARGS PDOS_MIGRATION_PROJECT_ARGS
```
