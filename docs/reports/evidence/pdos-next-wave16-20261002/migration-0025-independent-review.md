# Wave16 · 0024 JSON 运算与 0025 独立只读审阅

本记录是 2026-10-03 的迁移实施审查，不是数据库验收。仅读取迁移源码、用标准库 AST 提取字面 SQL 并计算 SHA256；没有连接数据库、执行 SQL、应用迁移、运行测试或修改业务源码。真实 T2 提交的 `22P02: invalid input syntax for type integer: "history"`、事务回滚及停止运行器属于 Root 提供的实际观测，本审阅没有重新执行该请求。

## 结论与确定缺陷

0024 的 `require_quality_followup_atom()` 有两类确定的 JSON 提取优先级错误，共三个表达式。0025 当前精确替换覆盖全部三处，静态前后函数体摘要完全匹配。未在 `PROOF_SQL`、`CONFIRMATION_SQL`、`LINK_SQL` 或 Issue 其余表达式发现另一处同类有效数据路径错误。不能据此宣称 PL/pgSQL 或实际 T2/T1 已通过。

| 位置 | 原表达式与问题 | 必须保留语义的修复 |
| --- | --- | --- |
| [0024:174](../../../../pdos-next/server/migrations/versions/0024_quality_followup.py#L174) | `(NEW.issue_snapshot->'history' - (...-1))` 的外层括号没有把 JSON 提取与整数减号隔开；Root 已实测将 `history` 当整数操作数。 | `((NEW.issue_snapshot->'history') - (jsonb_array_length(NEW.issue_snapshot->'history')-1))`，仍要求只追加一条具名历史且前缀完整等于旧历史。 |
| [0024:202](../../../../pdos-next/server/migrations/versions/0024_quality_followup.py#L202) | `(NEW.issue_snapshot->'capa'-'actions')` 与 `prior` 同式也未先完成 JSON 提取，完成分支会遇到同类运算解析错误。 | `((NEW.issue_snapshot->'capa')-'actions')` 及 `((prior.issue_snapshot->'capa')-'actions')`，仍比较 CAPA 除 actions 外的全部字段。 |

已向 Root 在实施前指出第二处错误。原 applied `next_0024` 文件与失败日志应原样保留；通过新的 `next_0025 → next_0024` 单调修复，不覆写已应用的 0024。

## 全部四组 SQL 的审阅范围

| SQL 组 | 核对内容 | 结果与保留要求 |
| --- | --- | --- |
| `PROOF_SQL` | proof tier/UUID、具名当前 human、Product/revision/expiry、精确 Receipt/result、RequestKey 初始原子组、跨 Issue/Link proof 使用计数。 | 未发现 JSON 箭头与算术交叉。T2 根因与两个 T1 分级、一个消费恰对应一个目标、原 Receipt/Audit/Outbox helper 都必须保留。 |
| `CONFIRMATION_SQL` | INSERT unconsumed、只许 False→True、消费不可改删、双向延期目标配对。 | `(to_jsonb(NEW)-'consumed')` 左侧已经是 JSONB，没有箭头优先级问题。保留双向 deferred 原子约束；不改成仅看历史 consumed 布尔，也不加入破坏 SAVEPOINT 的 xmin/top-xid 判定。 |
| `ISSUE_SQL` | 当前 predecessor/CAS、旧历史、具名根因、本人逐 action 完成、九字段实际事实、host assessment、完整源读集、after/material snapshot/status/event。 | 三处修复之外，数组/JSON 字段删除表达式左侧直接为 JSONB，未发现同类歧义。`->'history'->-1` 是负整数索引，不是字段减法；已有数组长度递增约束，不能改掉最后历史核验。`jsonb_set` 的数组下标计算已在函数参数内独立分组。 |
| `LINK_SQL` | 当前 Issue/CAPA/action、固定 basis/output、ordered unique refs、私有受众收缩、当前专业/政策、proof/Receipt、unknown fulfillment。 | 未发现箭头与减法交叉。私有条件显式分组；AND/OR、比较和箭头链未发现可证的错误放行。Link 不推进 Issue，`action_fulfilled=null` 不变。 |

以下表达式无需因本次错误而修改：`issue_snapshot-ARRAY[...]`、`old_action-'completion'`、`NEW.source_basis-'shared_proof'-'completion_observations'`。其左值本来就是 JSONB；键删除左结合保持原逻辑。各 `(...->>'field')::integer/timestamptz` 已对提取加括号。`event_effect IS DISTINCT FROM (CASE ... END)` 的前次语法恢复已在当前 0024 源码中，0025 必须保留。

对于故意提交非数组、非法 UUID/时间/数字的持久 JSON，部分 `jsonb_array_elements`/类型转换可能直接抛异常；这属于 fail-closed 的 SQL 防护和宿主 typed 输入之间的边界，不是放行依据。没有运行 PostgreSQL，不能把静态审阅当作这些恶意输入或真实正向路径的执行证据。

## 0025 精确绑定核对

首次读取版本为 [0025](../../../../pdos-next/server/migrations/versions/0025_quality_followup_json_operators.py)，文件 SHA256：

`6d5baed1b6ef478d2eab18099d75c16af42ef1ce92311f0140ddb7a86d95ad64`

代码从实际 `pg_proc.prosrc` 和 `pg_get_functiondef` 取得 `require_quality_followup_atom()`；在替换前检查完整原函数体摘要，每个原字符串及定义锚点都必须恰一次，替换后再次检查完整摘要。执行原函数定义的 `CREATE OR REPLACE` 保留函数/trigger 关系；未改任何表、数据、RLS、权限、proof/confirmation/Link 函数、旧 merge/change guards 或操作矩阵。

标准库从 0024 `ISSUE_SQL` 的美元引号内提取函数体，得到：

| 摘要对象 | SHA256 | 核对 |
| --- | --- | --- |
| 0024 文件 | `a957c6dbc22647f2f5dbb39fc014bb4b7ef269b014d9497642110cc4664df252` | 原文件只读；未改 |
| 原 Issue 函数体 | `bad9809337d74467d6112e349d499bc9a765d3ecd462fbd59236f1180095a556` | 等于 0025 `BEFORE_SHA256` |
| 仅三处替换后的函数体 | `1440edf39592be9cebe21a6a36b29dfb35c5599980fd4996fe53461fe00aacbc` | 等于 0025 `AFTER_SHA256` |
| `PROOF_SQL` 字面量 | `73179fb0e400dd2522d823e5bd6f48b517001bcbb73819ee957f100588e495b3` | 未被 0025 替换 |
| `CONFIRMATION_SQL` 字面量 | `535e319365167a5c1b4194af86b2452acb2bd9a60cd57a0d717ee791e9e1cb70` | 未被 0025 替换 |
| `ISSUE_SQL` 字面量 | `db7021bc5ba54c4e2a5dc8cc04b80ac00fe08a288b3af64fe3bcfcd2582f3c3c` | 完整 CREATE 文本，区别于函数体摘要 |
| `LINK_SQL` 字面量 | `baca294dac1577f65c246fb4413a3989e35fa2e313af5167e0317b10d3de10c8` | 未被 0025 替换 |

这个结果证明源码修复范围，不证明实际库中的 `prosrc`；后者必须由 Root 的迁移步骤以同一 `BEFORE_SHA256` 当场核对。若实际函数不同，正确行为是停止，不追加宽松 replacement 或跳过摘要。

## 降级保留边界

0025 首次读取版本的降级会在存在根因/完成 Issue 行或 Link 行时拒绝恢复坏 guard，这个保留方向正确。该版本的 `EXISTS` 后没有表锁：在非静止环境，检查为空以后、恢复原函数以前可能有并发 followup 事务提交，形成已经保留新事实却降回有缺陷 guard 的竞态。

建议仅在新 0025 的 downgrade 加固这个保守检查，不改 0024：先复用 0024 降级的共同门锁（`confirmations/quality_issue_versions/capa_remediation_links/action_receipts`，`SHARE ROW EXCLUSIVE`），再在同事务检查新目标、对应三操作 Receipt/已消费 Confirmation 等保留事实。发现任何保留事实应拒绝降级，不删记录、不解除 trigger、不重新赋予旧 proof 使用权。原 `capa_verification_evidence` 如纳入更保守保留检查，也应阻断而不是清理。

Root 本次已停止 API/相关运行器且实际失败事务回滚的空业务往返可以按该已核实边界办理；本审查没有核实数据库静止状态。上述锁建议针对迁移以后可复用的降级安全性，不是追加一般审批要求。

**收尾复读**：Root 已在同一个新 0025 加入上述四表 `SHARE ROW EXCLUSIVE` 锁，并在锁后额外核对三操作的 Receipt/已消费 Confirmation，发现保留事实仍直接拒绝。收尾版本 SHA256 为 `321f54e31292e2f2c6b5321663432d781e3376f3aac41c051d0b308a246a7108`。这个定向 delta 解决本节所报降级竞态；原三个修复锚点、前后函数体摘要和原 0024 SHA 均保持。这里仅核对源码，没有执行降级或验证 PostgreSQL 锁行为。

## Root 必须补齐的执行证据

本记录只覆盖 SQL 表达式及 exact replacement 的静态一致性。Root 仍需独立保留：真实 head/rollback 核对、0025 up/down/up 与函数体摘要、真实 T2 根因提交、真实 T1 部分/全部完成，以及失败时版本/Current/proof/Receipt/Audit/Outbox 同事务回滚。两类坏表达式处在不同分支，只有迁移/schema 通过或根因一条正例不足以证明完成分支已可执行。

本轮写入范围仅此文档。没有改动 0024/0025、任何候选、运行代码、测试或唯一清单；未授生产资格，未声称人工 Exit。
