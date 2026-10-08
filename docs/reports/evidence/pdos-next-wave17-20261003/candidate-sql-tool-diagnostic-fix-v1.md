# Candidate SQL tool diagnostic repair v1

状态：仅工具源码及离线检查冻结，未执行数据库、HTTP 或工具 `main()`。真实 SQL fixtures 与实际 HTTP positive 仍分别由主线执行和登记。

- 唯一工具源码：`pdos-next/tools/wave17_candidate_sql_checks.py`。
- 最终 SHA256：`52f34a0e7af5126cc4b4f322a8edb636dff211c5510d1dd093bb6426868c7c31`。
- 原只读审阅版本 `d6f712f38f897cbaa77ce6f23d24fbc641d63792a01c71f02c7be461acf4fb94` 为历史，后续 Root 独立修复 RequestKey 谓词。本次完整保留 exact tenant / actor / saved prepared-command idempotency_key 选择，不退回按 Receipt 的全部 aliases `.one()`。

本次窄修：

1. savepoint 已回滚后，`run()` 先记录真实 SQLSTATE、primary message、constraint、预期条件及 PASS/FAIL，再执行原预期状态和消息断言。意外拒绝不再因先断言而丢失真实诊断。
2. 已保存 FAIL case 不纳入末尾 `passed` 计数。
3. `save-at-expiry` 前增加 exact tenant/product/writer Grant 的只读选择。要求当前 `can_write is True` 且 Grant 终点严格晚于 proof expiry，防止先命中 named-human/write-Grant 守卫。前置不成立即写入明确 FAIL，再停止该归因检查；不改原 Grant、proof、TTL、SQL 或任何被保留行。

全部原 fixture 字段构造、真实 False→True SQL transition、缺 Receipt/Audit/Outbox、消费钟、三 NULL、角色写入、retained-row 预期、savepoint 及总事务回滚保持。工具只验证数据库约束，不证明 actual Host consumption marker 或当前专业资格。

离线检查：

- Ruff format/check exit 0。
- AST/compile exit 0，未导入/调用工具入口。
- 从实际工具 AST 提取 `run()`，以显式无数据库替身检查合法、正确拒绝、错状态、错原因、意外合法拒绝 5 项：诊断先记录、PASS/FAIL 正确、每次 rollback 保留。此为工具逻辑检查，不是实际 PG/savepoint/role 验证。
- 静态断言 Root 三个 RequestKey 谓词保留、只读 Grant 前置位于 expiry 负例之前。
- 实际检查输出：[`candidate-sql-tool-diagnostic-static-v1.log`](candidate-sql-tool-diagnostic-static-v1.log)。

待主线：运行真实 saved HTTP group 对应的 SQL 工具，读取实际拒绝约束/全部回滚摘要，并与 actual HTTP 正例分开报告。
