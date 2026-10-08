# Wave16 迁移提案独立定向审阅

日期：2026-10-03。审阅对象为 C 最终冻结的 [public-migration-proposal.py.txt](public-migration-proposal.py.txt)，SHA-256 `56ca4b9a848d322b038195111af3fab66ec817853f2dab22ee924bca45582f57`，577行。配套 [C 说明](public-migration-proposal-review.md) SHA-256 `c6a105346dacc96c26123a9d29421c712fc07496adb676fd714a0088037bb49b`。

**结论：未发现需先修改的实质静态迁移缺陷。** 实际 PL/pgSQL 编译、DDL 往返、SAVEPOINT、合法组提交及反例均未由本审阅运行；这些结果不能由 Python AST 或已通过的独立包检查代替。提案仍未应用、revision 未分配。本次仅新增本报告，未修改 Root/C/A/B 候选、迁移或冻结文件，未连接 DB/HTTP、调用 pytest、应用公共补丁或读取私有配置。

## 实际消费与同 UOW 配对

提案第25–129行建立的双向关系可接受，条件是迁移前置检查、留存不可变和触发器正常启用：

- 升级先锁 confirmations 并拒绝所有既存 consumed=true 的三操作证明，不把历史布尔值误认作新消费。
- Confirmation 的 BEFORE guard 只允许新行 consumed=false、其它字段完全不变的 false→true；既已消费不可 UPDATE/DELETE，不能把其它 operation 改进三操作范围。
- 消费 UPDATE 的延期事件在本事务末要求一个且仅一个同 tenant/product/actor/operation 目标；QIV/Link 的延期事件反向核实际已消费 proof UUID/分级/Product水位/期限/具名 human，并跨两表统计该 proof 的唯一使用。
- 已消费目标不可变留存；历史 proof 再用于新目标会形成第二个使用而拒绝。因而目标不能仅凭一个历史 consumed=true 行独立提交。

这里没有 xmin、顶层 xid 或同事务号比较。合法消费和目标均处于 SAVEPOINT 内时，约束事件跟随子事务回滚；RELEASE 后仍在外层提交时统一验证，设计上不会因子事务产生不同 xid 而错误拒绝。Python 私有 marker 另绑定真实 Session/get_transaction/get_nested_transaction 和实际 false→true history，解决人的 token/material/provenance，SQL 没有冒充这部分。

本提案按现有「一个共同 command/UOW」核初次 RequestKey 恰一条。提交后的同/跨 key Receipt 重放不插入目标、不会触发新目标的初始计数检查。此审阅没有将同一 UOW 内连续执行多个 command/alias 视为已验证接口。

## QIV、Link 与既有守卫

| 边界 | 独立对照结论 |
|---|---|
| 旧 merge/change 原子门栓 | 原 `require_quality_change_atom()` 及其旧 trigger 不替换、不删除。离线还原 `_extended_receipt_sql`，去掉新增三 CASE 后逐字等于原 helper；原目标/source successors、完整 failures/maps、固定图 capture、Receipt/Audit/Outbox 判断均保留。原 atom SQL SHA 为 `6210659a580b8913296f1d2966158784b8973f5b72eb7cb8c10afd5f474d58ff`。 |
| QIV 前版/Current | 新延期 guard 要求原 actioning 版、连续 revision、完整 scope/owner/visibility/purpose、当前指针、完整旧来源/专业/政策读集继承，与 host `append_issue` 的同 Session CAS 对应。仍只有既有 IssueVersion/Current，不建立第二套当前真值。 |
| T2 根因 | 只追加原先为空的 NamedConclusion；原 CAPA/失败/假设/历史保持；writer、text、sources 与语义输入相等。新增 conclusion/history 的提交钟在 review 中归 null，实际旧钟不改。实际 T2 UUID 存 `source_basis.shared_proof`，kernel Invocation.decision_id 由 host 实际消费绑定；没有要求不存在的 conclusion.decision_id 字段。 |
| T1 部分/全完成 | 原 actions 的身份、executor、text、顺序及未选 completion 不改；已完成不覆盖，提交 action 唯一且都属于原 CAPA。逐项保存实际九字段 observation、收到钟、独立 CompletionAssessment 和事件 Source；本人/非未来 instant/微秒由宿主严核，SQL 与当次 review 逐项对应。部分完成仍 actioning，全完成仅 awaiting_verification；不产生 effectiveness/close。 |
| QIV 实质投影 | 提案仅将新增 history.at、新增 root_cause.at 归 null，再与 Confirmation.before/after、read_basis、completion_assessments/observations 相等；与 A `_preview_issue` 及 host review 对照一致。旧真实时钟、实际完成 EventTime、authority/policy/source_basis/完整读集均未删去。 |
| Link | 真实 current Issue/CAPA/action、固定 basis、原 executor、最窄 audience、refs 顺序/唯一性、1..20输出、authority/policy/readset 和当次 Confirmation.snapshot 相符；`action_fulfilled=null`。目标为独立 append-only Link，不推进 Issue Current，不把 planned output 或普通对象存在当实施/复验通过。与 B `_review/apply` 的字段形状一致。 |
| 回执原子组 | 新 helper 先复用原精确 subject/version/actor=requester/run null/visibility 及唯一 Audit/Outbox，再核 result.id/revision/status 与初次 RequestKey。三事件与公共注册一致：issue.root_cause_decided、capa.actions_completed、capa.followup_linked。 |

宿主实际追加的 `source_basis.shared_proof`、completion_observations 的 received_at 包装，以及 B `input_snapshot.shared_proof` 的位置都与提案一致；未发现「SQL 要求的字段不存在」「preview 的 server_on_save 被误当实际时钟」或实际 row/Receipt subject family 的错配。

## RLS、权限、生命周期与降级

新 Link 29列、Candidate 33列保留冻结 B 的 tenant/product/project/Issue/CAPA 精确 FK、唯一性、snapshot/状态 CHECK；两表 ENABLE+FORCE tenant RLS，PUBLIC/app/agent 先 REVOKE。app 仅 Link SELECT/INSERT，Candidate SELECT；UPDATE/DELETE 另有 retained_record 拒绝。两表均挂已有 lifecycle_reference_gate，公共 catalog 必须同时加入 COVERED_COLUMNS/GUARDED，不能将引用表声明 NON_CONSUMING。

Candidate 没有公开 writer，且数据库只允许 indeterminate、适用/独立/观察三项 null；本提案没有把候选模型登记升级成专业资格或有效性能力。ACL、private scope、真实 bytes/security/current issuer 和具名专业事实仍必须由实际 host/owner 守卫逐 phase 重核；tenant RLS 与 snapshot 中 qualified=true 不替代这些事实。

降级先锁 confirmations/QIV/新两表/Receipt，任一新表记录、新操作 QIV/Receipt 或已消费三操作 proof 留存即拒绝，不删除历史来通过往返。空库才撤新增 guard/function、先 Candidate 后 Link、恢复原 receipt helper 和原单列 CHECK；旧 merge/change 门栓不动。未消费预览保留不会被声称是已发生业务事实。revision 占位串在 upgrade/downgrade 首步拒绝误执行。

## 验证范围与具体待验

本次离线读取并解析 Python AST，不导入/执行迁移：最终 SHA 匹配、6份 CREATE FUNCTION 可按提案边界独立发送、原 receipt helper 精确仅扩三 CASE、旧 merge atom 不修改、两表29/33列范围明确。**没有 PostgreSQL body 编译结论。**

Root 应用后的最小受影响验证应包含合法三原子组和 partial→allComplete；同一 SAVEPOINT 的合法消费/目标，以及子事务回滚恢复 false/零新目标；无目标消费/目标无消费/历史 proof 二次使用；Outbox 末端故障的消费/Current/Version/Link 全回滚；Candidate app INSERT 拒绝；有留存拒降级。旧 merge/failure alias 与 change impact 必须保留受影响验证，不能由本次静态“原函数未变”冒充实际联合通过。已有事务候选可复用，未重复运行或修改。

Python digest/token、全部原报告 bytes、来源/issuer/security/专业/政策 ABA、独立 owner 真值不在 SQL 文本 hash 中重算；仍由已经审阅的真实消费 marker、A/B 各 phase `_load`/末端 refresh 负责。提案明确保留这一可信根边界，没有用 jsonb::text SHA 伪造 Python canonical digest。

## 基线摘要

| 文件 | SHA-256 |
|---|---|
| `migrations/versions/0023_quality_and_change_execution.py` | `54aa81a36d279ea049e76507360928f76bd37098655a3fa63b16673c171651a6` |
| `migrations/schema_0023.py` | `e2a660bf640ae5b5b907e3df1f8283e05149f1999b381a89d4bd441433e1c6d8` |
| B `capa_verification/models.py` | `321a721fd5b90d9857f8e29603ef057f6b7cc1cf62e29ba27b036c3296952ef4` |
| B `capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| A `quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| `quality_followup_host.py` | `6b67f2d9d20bfbd48d869aa2028ba92d84e85660e7a27d3e4fc8c049035470de` |

提案 SQL literal 摘要：PROOF `73179fb0e400dd2522d823e5bd6f48b517001bcbb73819ee957f100588e495b3`；CONFIRMATION `535e319365167a5c1b4194af86b2452acb2bd9a60cd57a0d717ee791e9e1cb70`；ISSUE `fdbe52285d18047388089f9ebe13e92f6f6cd6deff5764e75df687e0d90997e9`；LINK `baca294dac1577f65c246fb4413a3989e35fa2e313af5167e0317b10d3de10c8`。
