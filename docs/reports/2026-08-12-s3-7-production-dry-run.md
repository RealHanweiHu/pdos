# S3-7 生产试点 dry-run 证据

日期：2026-08-12
范围：CEHub `C4s`（`zGpNH0Xq`）与 `S18-01`（`aBnbEdQG`）→ PDOS `beepump` 租户
状态：dry-run 与独立抽查通过；后续 apply 与幂等重放亦已通过，见 `docs/reports/2026-08-12-s3-7-production-apply.md`

## 1. 候选制品与运行边界

- Git / OCI revision：`e1d0b2aaaff1ef9cf0b49e27f59464554aac80e3`
- Git bundle SHA-256：`fe728c33e94d1cd87bf211cfc55569b9ff0a211362800196311ba16afe668661`
- Linux/amd64 API 归档 SHA-256：`771620f4f819a9b82127b3675abda2d92b19ac69e58b7552c6fa6dd36c825816`
- API 与 Web 镜像 OCI revision 均等于上述 commit；API 以非 root `pdos` 用户运行，ECS release preflight 通过。
- 本轮只构建候选、读取源/目标库并写受限报告目录；未替换或重启线上容器，未运行 deploy 或 apply。

## 2. 目标库前置快照

- Alembic：`0020_cehub_migration_v1`
- 只读、Repeatable Read 事务：通过
- 迁移范围内已有对象：1 个现役管理员 User；Project / Workflow / Stage / Gate / Task / Gate History / File Reference / Project Member / Migration Run / Migration Mapping 均为 0。
- `C4s` 与 `S18-01` 目标 project code 均不存在；`cehub-v3` mapping 为 0。
- 报告：ECS 私有目录 `target-before.json`，mode `0600`，SHA-256 `059da38728c959a41204341168a0f10d8a789e85cca304dba3c8a4bdb846a814`。

## 3. 正式 dry-run

- 状态：`ready`
- 错误：0
- 目标写入：0
- 解析后项目 ID：`zGpNH0Xq`、`aBnbEdQG`
- Source fingerprint：`d37ac192c4c318b540f6beb74d3340ee8bbfd04f7776f4f0f1112b1760abe71d`
- 源计数：5 User、2 Project、53 Task、0 Gate Review、10 File Reference。
- 项目样本：
  - C4s：OBT / intake，21 Task，0 Gate Review，8 File Reference。
  - S18-01：NPD / concept，32 Task，0 Gate Review，2 File Reference。
- 报告：ECS 私有目录 `cehub-v1-dry-run.json`，mode `0600`，SHA-256 `30d7948b0a6cf9414c565bb83d15095365efce5a3545d97f1795be57610fecc5`。

## 4. 独立源数据抽查

未复用迁移报告聚合值，使用 CEHub 独立只读账号直接查询五张获批表：

- 两条项目主数据的 code、name、category、current stage、lifecycle 与 dry-run 样本一致。
- 每项目独立抽查 2 个 Task 的 phase、status、assignee、start/due date 与 completed 状态，共 4 条。
- 两项目 Gate Review 真实计数均为 0。
- 每项目抽查 1 个 OSS 引用的 filename、media type、size、phase/task、uploader 与 storage-key SHA-256；两条 visibility 均为 `internal`。
- 独立重新计算的 5 类计数与 dry-run `source_counts` 全部相等。
- 报告：ECS 私有目录 `source-owner-review.json`，mode `0600`，SHA-256 `49f5f36c5024d15644e5618ce5c1888b5669be31415f533525da60e6f662b4f0`。

## 5. 零写与线上健康复核

- dry-run 后以新的只读 Repeatable Read 事务重算 11 张目标表的全部租户行；每张表的 count 与内容 SHA-256 均与前置快照完全一致。
- Migration Run 与 Migration Mapping 仍为 0。
- 后置报告 `target-after-dry-run.json` mode `0600`，SHA-256 `7b4daf637195424bb45066f40e2eebf6fe0a83929d3717b832a9d1fc3c3ea2bd`。
- 线上 API / Dispatcher / Executor / Web 容器 ID 未变、restart count 均为 0、health 均为 healthy；公网 `/login` 返回 HTTP 200。

## 6. Data Owner 批准门禁

apply 已在项目负责人 / 数据 Owner 明确批准本报告后执行；批准同时绑定：

1. release revision `e1d0b2aaaff1ef9cf0b49e27f59464554aac80e3`；
2. source fingerprint `d37ac192c4c318b540f6beb74d3340ee8bbfd04f7776f4f0f1112b1760abe71d`；
3. 有序选择器 `C4s,S18-01`；
4. 目标租户 `e340c240-d8f0-429c-aac5-69ab9b42fac5`。

批准后已在任何目标写入前重新冻结源快照，fingerprint 保持一致；apply 成功后已原命令重放一次，五类 created 全为 0、业务表与 mapping 不增加，仅新增成功运行审计。完整结果见 `docs/reports/2026-08-12-s3-7-production-apply.md`。
