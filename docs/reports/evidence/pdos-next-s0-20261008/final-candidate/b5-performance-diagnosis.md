# B5 首轮性能诊断草稿

只读审查；未连接 PostgreSQL、运行测试或追加计时，未改源码。依据冻结候选的 `performance-attempt-1/b5-quality.json`、`quality-samples.json` 与实际调用代码。首轮受控 SIGINT，外层 `test_exit=2`；采样器捕获 `BaseException` 后写 `outcome=failed`，该字段在本次表示采样未完成，不能解释为业务动作失败。已有成功样本全为 HTTP 200；另一个 inputs 请求被中断，没有响应状态。CAPA candidate 两条路径尚未执行，不能推算性能。

| 实际路径 | 完整成功样本 | 单样本耗时范围 | SQL 次数（app + auth） | 既定门槛 |
| --- | ---: | ---: | ---: | ---: |
| quality_read | 10 | 4.138–5.052 秒 | 185 | p95 ≤1 秒 |
| quality_containment_inputs | 9 | 5.418–6.272 秒 | 433–449 | p95 ≤1 秒 |
| quality_containment_preview | 9 | 3.600–4.251 秒 | 181 | p95 ≤2 秒 |
| quality_containment_confirmation | 9 | 8.238–9.376 秒 | 379 | p95 ≤2 秒 |

以上是未完成首轮的样本范围，不是 30 次验收 p95。按外层 profiler 的成功请求计算，四路平均 HTTP/SQL 耗时分别为 4.529/3.979、5.924/5.267、3.934/3.376、8.873/7.452 秒；SQL 已占主要部分。该统计是客户端执行耗时和次数，未将 PostgreSQL 函数/RLS 内部语句展开计数，不能当作全部数据库语句数。采样实际读取 `quality-execution?run_id=…&build_id=…`，inputs 走品质入口，预览和首次提交走品类根公共命令；各次提交是不同遏制动作，不是回执重放。

## 可直接定位的放大及最小修复候选

1. **同一遏制请求反复准备完整证明，优先消除阶段间重做。** `command_handlers.py:81` 的受控 prepare hooks 尚未登记 quality execution。公共预览 `service.py:651` 先调用 `validate`，随后 `reviewed_view` 调用 `preview_view`；品质实现 `domain/quality_execution/service.py:491、802` 均执行 `_load`。首次公共提交又依次执行 validate、replay_subject、确认实质回读、apply；对应 `:491、747、802、727` 共四次 `_load`。每次 `_load` 已完整核对原值，又在 `:413` 调用 `_refresh`。建议把品质动作接到公共服务明确登记的单次 prepare/review/apply 路径，或先使用既有 `apply_validated` 协议并在本调用内分享同一 Bound；回执查找和确认材料比较读取这份准备结果。不能仅把操作塞进 LIVE_CONSUMPTION 集合而缺少该集合要求的受控消费证明。准备结果须绑定真实 Session/事务、Context、操作与语义摘要、读集、产品/Issue 水位及 mutation_epoch；preview 和 commit 是两个 HTTP 请求，仍分别准备。实际确认消费、过期、具名身份、幂等与 Issue CAS 保留，写入前完成末端刷新。

2. **只读 inputs 使用写路径，失去 RR 读取复用并持锁。** `domain/quality_execution/api.py:31` 的 GET 明确 `read_snapshot=True`，但 inputs 的 `:54` 没有；服务 `:812` 先 `_human(write=True)`，`_load` 又做人和专业写核对，`:817` 调用 `_new_write`，其 `:526–534` 对 Issue Current `FOR UPDATE`。成功 inputs 每请求平均读取 builds 42 次、build_starts 24 次、formal_requests 20 次；公共 preview 分别为 1、2、4 次。建议拆开“具备当前写资格”与“取得写锁”，inputs 用 RR 读取事务、无写入的当前版本比较及写能力核对；真实 preview/commit 继续取得需要的锁。必须同步审阅 downstream owner 的 `write` 参数和所有 `FOR UPDATE`，不能只在 API 加 `read_snapshot=True` 后继续调写路径。旧 inputs 的权限、当前资格与来源读集不放宽。

3. **固定原 Run 证明多次重新展开资源、专业和原件闭包。** `quality_result_bridge.py:163、246` 在一次字节核对的前后各调用 `inspect_retained_execution`；`:172–228` 每次读取完整测量集合、捕获报告并核对原值，报告缓存只在此次函数内部。末端 `recheck_fixed_failure_result:288–340` 又读取所有测量和完整 retained。retained 的 `:385、460` 前后两次调用原执行人专业 recheck，`:402` 重建资源 bundle；`_fixed_dependency:124–139` 先 `_one(Current)`、`_one(Fact)`，随后又 `resources._current`，`_one:51` 每次直接 SELECT/populate_existing，未走 held snapshot。成功 preview/commit 的 sample_run_usages 12/26 次、resource_facts 19/41 次、occupancies 13/28 次、resource_current 13/28 次；提交中这些四类耗时平均合计约 2.87 秒。优先把这些精确固定行查询接入已有 RR/真实 model gate 的 request proof，再在同一事务内分享原 Run 级的字节、规则与 retained 准备证明。后续每个 failure 仍独立验证精确测量、Run 版本与 event/Receipt 投影归属；不能省略不同 measurement/event 的选择检查。末端以真实当前指针/资源与消费水位、来源安全/ACL epoch、issuer/host runtime、实际本人 deadline 重核，并保留完整比较；遇当前水位变化须重新完整核对或明确失效，不能直接缓存 `current=True`、延长期限或删除 IO 后守卫。

4. **品质 GET 同时核对 Issue 和失败候选；历史列表成本随真实追加增长。** `list_quality:1235–1268` 读取最多 100 个 Issue 历史版本，当前行 `_view` 核对失败，随后同 Run `_failure_candidates:1331` 又按 failed measurement × event 调完整 bridge。可共享上述精确 Run 级准备证明，同时保持历史/current 分别呈现和每个 event 的归属。单次 `quality_issue_versions` SELECT 在十次 GET 中从 0.207 增至 1.114 秒，客户端总 SQL 一直 185；仅减少 Python 调用不能保证该读路径达 1 秒。该 SELECT 涉及逐步增加的真实遏制历史及其 RLS，尚无执行计划，不能归因于某个索引或宣布 RLS 是唯一原因。后续要独立检查该查询的真实返回量、排序/选择索引及已登记 audience 摘要读取；不能隐藏历史、放宽 RLS 或由应用补一个不可信摘要来过门槛。

5. **来源和专业复查可共享直接事实，不能按 SQL shape 合并主体。** `_view:887–925` 为各操作分别 assess，包括业务状态已不合法的操作；`quality_followup/service.py:734–825` 的读取又完整 bridge→refresh，并前后重复来源、政策与每个操作的专业比较，`quality_followup_views.py:461–514` 再次展开同 Issue/输出 owner。这是未执行 candidate 两路的静态风险，尚无该两路实测。`quality_execution/evidence.py:33–109` 已通过 snapshot_scalar 读原件安全及精确登记回执，但每次仍遍历完整 reads。可在真实 RR/held scope 内准备完整直接来源并按固定子读集投影，最后核对当前来源/runtime/deadline；具名人工 SourceRef 的完整行/quote/hash 验证保留。专业 `professional_authority/service.py:877` 已按 `(product, project, subject)` 缓存 Current，不同操作者、原 Start 签署人、执行人不可合并。现有 profile 没有参数/subject 标识，不能凭同表或同 shape 断言重复主体，也不能将操作资格与通用 can_write 合并。

## 修复后仍需根统一核对

先落实单次品质准备和 RR inputs，再判断 retained 精确查询/证明共享的收益；每次只验证受影响的真实成功与拒绝路径。重点保持 IO 后 runtime/issuer 或源安全撤销、另一 failure 撤销先前证明、资格/Grant 真实到期、Issue/产品水位变化、Session flush/Core DML/rollback 和嵌套 UOW 的失效。`request_proof.py:30–100` 已有 mutation_epoch、flush/直接 DML/rollback 清理；扩展必须复用这些实际边界，不能跨事务或使用全局/TTL 缓存。最后同一冻结候选重新取得 B5 六路各 30 个成功样本并检查 allowed/current/evaluated_current，随后归入 B8 的完整 32 路性能汇总。首轮证据保留，当前不标性能通过。
