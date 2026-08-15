# Sprint 5 CEHub 全量生产 apply、独立抽查与幂等重放证据

日期：2026-08-14（America/Los_Angeles；生产执行为 UTC 2026-08-15）

结论：**固定 release 与获批源快照的全量 apply、独立目标抽查和同参数幂等重放全部通过。** 主入口声明、DNS/Nginx 变更与钉钉外发均未执行；生产继续保持 `PDOS_DINGTALK_DELIVERY_ENABLED=false`。

## 1. 人工授权与固定输入

人明确授权在 ECS `8.140.197.68` 使用以下不可变输入执行生产 apply、目标只读抽查及成功后的同参数幂等重放，并明确排除主入口声明、DNS/Nginx 变更与钉钉外发：

- release / Git / OCI revision：`82de9d215c5b0101aaba8cbff2d1adf6d751ceef`；
- inventory fingerprint：`a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`；
- source fingerprint：`d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`；
- 有序项目：`WqWcl0wK,aBnbEdQG,xY8-PGbc,zGpNH0Xq`；
- tenant：`e340c240-d8f0-429c-aac5-69ab9b42fac5`；
- actor：`4bdba865-c5b1-4ca1-aa85-be467e1fad42`。

## 2. apply 立即前硬门禁

- 远端 HEAD 与 API/Web OCI revision 均精确等于最终 release；release worktree 干净，`.env.production` 为 `root:root 0600`。
- API image `sha256:9c4a1dc084b886cbd2c38b5cb94e48e6dd90bc7544de72217ea7e57d1f06fe95`，Web image `sha256:d0a0301a914e707e3f6a94bac7fd97b182af487b43333a8028ffeb41b7d70ba2`；运行用户分别为 `pdos` / `nextjs`。
- Alembic 为 `0030_phase_three_agents (head)`，五个 PDOS 容器全部 healthy，部署状态只读 readiness 为 2 Project 且 `no state was changed`。
- CEHub 仍为角色 `ce_hub` / 数据库 `cehub`，默认事务与当前事务均为只读，Project 数为 4；`ACTIVITY_LOG_TAILER_ENABLED=false`、`AUTOMATION_SCAN_INTERVAL_MIN=35790`。
- 不覆盖历史报告，重新生成的 inventory verify 与 dry-run 分别保持原 SHA-256 `30bd71ed7253b8865d3bf3d34a1dbc4bc270043c20c7a4d221ef5aa49204c66f`、`e61a55eed12222562a27136b64be053a2714f5c28432f013a180dfe8ace2029b`。
- verify 为 `status=ready`、`errors=[]`、4 active / 0 archived；fresh dry-run 为 `status=ready`、`errors=[]`、`target_writes=0`，fingerprint、项目顺序以及 source / created / skipped 五类计数均与批准值逐字一致。

apply 立即前快照 SHA-256 为 `c8dfbd1a201df6ebf62fa897a8e096fcad446bba2b5597acb818ef6be34b6553`。它与更早批准基线的唯一逐表差异为 `cehub_core.users`；只读审计证明该差异精确来自 Owner 在部署验收中完成的本地密码登录：actor 为批准 actor，`last_signed_in_at/updated_at` 与对应 `USER_SIGNED_IN` / `user.sign_in` 追加审计一致。其余十表哈希、全部 mapping 和 dry-run 预测不变，因此不是源或迁移漂移。

## 3. 首次生产 apply

执行窗口：`2026-08-15T02:07:49Z`～`2026-08-15T02:07:52Z`。

- 状态：`completed`；`errors=[]`；fingerprint、tenant 与有序项目全部匹配。
- source：6 User / 4 Project / 117 Task / 0 Gate Review / 14 File Reference。
- created：1 / 2 / 64 / 0 / 4。
- skipped：5 / 2 / 53 / 0 / 10。
- `target_writes=177`，与 1 个 Migration Run、71 个新业务/映射对象及两个 NPD Project 的 Workflow/Stage/Gate/Member 展开一致。
- apply 报告为 UID/GID `10001:10001`、mode `0600`，SHA-256 `2cb4da99f1697969577816a565add0630d045563cc4e43b47188e1286ce245e4`。

## 4. apply 后独立目标抽查

在新的 `REPEATABLE READ` + `SET TRANSACTION READ ONLY` 事务中，不复用迁移器聚合结果，得到：

- 11 表总量：7 User、4 Workflow、25 Stage、4 Project、8 Project Member、25 Gate、117 Task、0 Gate History、14 External File Reference、3 Migration Run、141 Migration Mapping。
- mapping 分布：6 User / 4 Project / 117 Task / 0 Gate Review / 14 File Reference；141 个 target 全部存在，非法 source hash 为 0。
- 6 个迁移用户全部 `is_active=false` 且 `password_hash IS NULL`。
- C4s 为 intake、4 Stage / 4 Gate / 21 Task / 8 File；D14-04、D15-05、S18-01 均为 concept、各 7 Stage / 7 Gate / 32 Task / 2 File；四项目均 active 且各有 2 个成员。
- 每项目独立抽查一条 Task 和一条 File Reference；状态、日期、媒体类型、大小、密级、Stage/Task 引用均有完整目标值。

apply 后目标快照 SHA-256 为 `b29695657f642c09598cfcce6a4bb0aec67161c554121bfad12997329d4b4ff1`；独立抽查报告 `status=ready`、`errors=[]`，SHA-256 为 `c6247fa266d224bd4812b00a25e258ee66b3c471f798d0968fa8e64efb48eff7`。

## 5. 同参数幂等重放

执行窗口：`2026-08-15T02:20:18Z`～`2026-08-15T02:20:20Z`。

- 状态：`completed`；`errors=[]`；五类 `created_counts` 全部为 0。
- skipped 为 6 / 4 / 117 / 0 / 14，与 source counts 逐项相等。
- `target_writes=1`，仅新增第二条本次全量序列的成功 Migration Run 审计。
- replay 报告 mode `0600`，SHA-256 `13d548bf4f0c7fe70b102718337f45ca2af4ecf96afb12d4e2c45ec0f773ea32`。

重放后快照 SHA-256 为 `eaf2ef92b97ebebe760c5a161fe796c89a997b729acda9505b4f71de52dc6fb3`：仅 `migration_runs` 从 3 增为 4；User、Workflow、Stage、Project、Project Member、Gate、Task、Gate History、File Reference 与 Migration Mapping 十表的 count 和内容 SHA-256 均与 apply 后逐项相同。Mapping 保持 141 条，内容 SHA-256 保持 `5dd25cbe49ad6c938f3b87e574cbd7eeebb6cb848b97fa5f7ea5628c8c1f0187`。

## 6. 运行面复核

`2026-08-15T02:21:27Z` 最终复核：

- `deploy-ecs.sh status` 对 4 Project readiness 通过并明确 `no state was changed`；五个 PDOS 容器继续运行最终 release 且全部 healthy。
- apply 开始后的 PDOS fatal pattern 为 0，Project 500 为 0；`PDOS_DINGTALK_DELIVERY_ENABLED=false`。
- CEHub container ID 保持 `380b9284a8d1c126c0f9caff26d2a9e75178780b050d6744050bfd261f0403b5`、restart=0、running；tailer=false、scanner=35790，scheduled/tailer/read-only/25006 日志计数为 0。
- `https://pdos.beepump.net/`、`/login`、`/api/session/status` 均为 HTTP 200，TLS verify result 为 0。
- 没有部署新镜像、修改 migration、恢复 CEHub 写权限、变更 DNS/Nginx、宣布主入口或执行钉钉外发。

## 7. 不可变证据位置

生产私有目录：
`/opt/pdos-migration-reports/82de9d215c5b0101aaba8cbff2d1adf6d751ceef/cutover/`

上述八份 JSON 报告均为 UID/GID `10001:10001`、mode `0600`。只读快照脚本 SHA-256 为 `686ca87654c483b8056df4c5b5f5ff822cb243a50cdd88c7ba7d67a3b7d473fd`；实际执行的独立抽查脚本 SHA-256 为 `91f78635a686da930e0d80e0420633dba98b498781bce0c74c988b281004b2b4`。

报告与已执行脚本已下载到本地隔离目录 `/private/tmp/pdos-release-82de9d.iTEP40/artifacts/production-apply-20260815/`，本地 mode 均为 `0600`，SHA-256 与 ECS 逐项一致。

## 8. 非破坏性执行偏差

- 一次 SSH 在读取既有快照脚本时被远端关闭；重连后只读获取成功，未执行数据库动作。
- 首次 users 差异审计 SQL 的字符串字面量引号被远端 shell 吃掉，查询在只读事务中以语法错误退出；改为绑定参数后通过，没有写入。
- 独立抽查脚本首版在执行前发现缺少 JSON 非原生类型序列化；保留未执行首版，上传新文件名的 v2 并核对哈希后才运行。报告路径从未被覆盖。
- 首批本地 `scp` 仅完成前四份文件；其余文件分批只读下载，最终逐项哈希与权限复核通过，不影响 ECS 原始证据。

## 9. 后续 Gate 状态

1. [x] 业务 Owner 已明确宣布 `pdos.beepump.net` 为 PDOS 主入口；现有域名/TLS 正确，未制造 DNS/Nginx 变更。
2. [x] 声明后的正式只读窗口持续 1844 秒，四项目登录/查询、PDOS 健康日志与 CEHub 只读审计归档均通过；证据见 `docs/reports/2026-08-14-sprint-5-main-entry-observation.md`。
3. [x] Data Owner、发布 Owner、业务 Owner 已共同确认 Sprint 5 / Cutover Exit。
4. [x] S5-1 真实钉钉 password-free login / notification / approval / card smoke 作为已接受延期残余风险单独跟踪，canonical checkbox 保持未勾选，生产保持 `delivery=false`。
