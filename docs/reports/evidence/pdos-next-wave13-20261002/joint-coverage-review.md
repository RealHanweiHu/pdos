# Wave13 联合覆盖去重审查（进行中）

读取快照：`2026-10-03T02:28:55.909758+00:00`。仅读取选集、源码 AST、候选摘要和已落盘日志；本审查未运行数据库、pytest collection 或公共测试。**本报告不表示联合检查完成。** 日志后续继续写入，由主线最终结果替代本快照。

## 选集完整性

[joint-shards.json](joint-shards.json) 为 **57 组、167 个唯一 selector、64 个实际测试文件**；与 [integrated-test-selection.json](integrated-test-selection.json) 中目录展开后的 64 个文件完全一致。没有重复 selector、整文件与函数节点重叠、缺文件或额外文件。8 个拆分模块共 111 个顶层 `test_` 函数，均恰好落入一个分片；参数化函数保持整体，不能把函数数等同参数展开后的 pytest 用例数。

| 拆分模块 | 函数 | 分片 |
| --- | ---: | ---: |
| `tests/build_start/test_transactions.py` | 17 | 4 |
| `tests/build_operational_facts/test_transactions.py` | 13 | 4 |
| `tests/sample_handoff/test_transactions.py` | 7 | 4 |
| `tests/verification_handoff/test_transactions.py` | 12 | 4 |
| `tests/test_resources/test_transactions.py` | 9 | 4 |
| `tests/verification_launch/test_transactions.py` | 11 | 4 |
| `tests/test_build_execution.py` | 26 | 4 |
| `tests/test_verification_execution.py` | 16 | 4 |

这是 AST / selector 层的完整性检查，未冒充 pytest 收集后的精确参数 nodeid 列表。选集 SHA256：`bfdb3e1eec01340b236785d1023769a53983d365897cb78eb9de37cd1b058eb0`；整合选集 SHA256：`4ea9884346e4d6a424dd1893db5ca54525503c3b4f2c4c9031f71bfeb5714d24`。

## 原失败与替换关系

必须保留原失败日志，再使用对应的新结果覆盖相同用例身份；不能将重试次数或重复通过计入覆盖数。

| 原组 / 失败节点 | 失败原因及修复边界 | 正确替换 |
| --- | --- | --- |
| `pure`：`tests/professional_authority/test_assessment.py::test_missing_qualification_is_null_and_operation_and_purpose_are_exact` | `test.run.start` 已注册，旧断言仍要求未配置；保留缺资格、精确用途和未配置操作拒绝。 | 与下一行一起由完整 [joint-pure-post-start-repair.log](joint-pure-post-start-repair.log) **960 passed** 替换原 pure 960 个用例。 |
| `pure`：`tests/verification_handoff/test_pure.py::test_history_is_guarded_but_does_not_repeat_current_actions_or_next_owners` | 旧 fake 缺新 RunIdentity 查询；补当前作用域 scalar、已 Run 阻断且历史不重复动作。 | 原 [joint-pure.log](joint-pure.log) **958 passed / 2 failed** 保留；只计新的 960，不能算 958+960，也不加局部 68。 |
| `test_resources-0`：`tests/test_resources/test_transactions.py::test_destructive_actual_start_consumes_once_and_new_use_remains_blocked` | 已真实保存 consumed 并完成同 key 200 后，JSON 错取 `receipt_id`；只改实际 Receipt JSON 为 `id`，SQL/FK 名不变。 | 主线 [recheck-destructive-replay.log](recheck-destructive-replay.log) 的完整单例结果替换该失败；原分片其余 2 passed 保留，不重新累加整个模块。 |
| `verification_launch-2`：`tests/verification_launch/test_transactions.py::test_same_key_and_cross_key_same_intent_replay_do_not_duplicate_truth` | 主线已定位同一 Receipt JSON 字段错误；函数有 `test.run.plan` / `verification.schedule.promise` / `test.run.start` 三个参数。原分组尚无终态时不能先报告完整失败/通过总数。 | [recheck-launch-replay.log](recheck-launch-replay.log) 按 **参数 nodeid** 覆盖旧失败；若重跑整函数 3 passed，必须替换这三个旧参数记录，不能将整函数 3 加到原分组已通过参数上。 |
| `test_build_execution-3`：`tests/test_build_execution.py::test_unknown_preparation_does_not_enable_start_or_quality_execution[test.run.start]` | 新专用 schema 拒绝旧 Build 载荷，实际 422/INVALID_PAYLOAD；旧预期 403。其余非法操作、计划不变守卫保留。 | 仅对应参数单例复验替换 1 failed；原分片 14 passed 保留，不把 5 参数整函数再累加。 |
| `test_verification_execution-2`：`tests/test_verification_execution.py::test_preparation_does_not_grant_professional_or_physical_authority` | 旧 front 六项未包含本波 plan/promise/start；结果导入/复核/处置仍未接入。专业权限 403、伪 qualified 422、runs 空及计划不变均保留。 | 仅该函数复验替换 1 failed；原分片 4 passed 保留。 |

两项旧合同修复的原文件与哈希保存在 [before-repair.json](legacy-contract-test-before-repair/before-repair.json) 及该目录源文件副本。仅 Ruff、格式检查和 compile 已通过，未由本审查执行 PG。

| 文件 | 原 SHA256 | 修复 SHA256 |
| --- | --- | --- |
| `test_build_execution.py` | `18a37454f21ed34382fa303c4e0b8ef151cb93d00280bdf25952a24257d27568` | `b162c98aca3b70b895907b55618fe9405757e94f2acb238734f88d003a7c3852` |
| `test_verification_execution.py` | `a606054844f14f5675ab5369af9488328315f0eba71427d1fab6c4317ea0c248` | `4412a86010b33279b6c1be2bb7bf2b1e30d61418c86829816b2426c58aa8eff3` |

## 候选与真实时钟

[receipt-field-test-repair.json](receipt-field-test-repair.json) 记录两项 Receipt 测试修复；[test-only-clock-repair.json](test-only-clock-repair.json) 记录默认真实窗口调整；[long-storage-fixture-repair.json](long-storage-fixture-repair.json) 记录仅长存储故障用例的显式 indirect profile。默认 fixture 的窗口起点为捕获时刻 +5 分钟、终点 +12 分钟、事实期限 +20 分钟；长存储 profile 保留 +5 分钟起点，终点 +45 分钟、事实期限 +60 分钟，并在签核前保存其显式合成上游范围。它们不能混称同一原始测试候选。旧运行进程加载原 bytecode，其旧结果不能证明最终 fixture 版本；完整六故障 storage 用例必须使用最终 profile 重新完成。生产时钟、资格、确认 TTL 与领域守卫未因这些 fixture 修复放宽。

纯组替换与前述 PG 单例替换可以说明“同一后端生产候选 + 明确测试修复范围”，不能宣称所有文件从第一次执行至今哈希不变。[post-start-display-repair.json](post-start-display-repair.json) 另含界面/工具改动，其前端检查由主线独立补齐，PG 结果不证明前端完成。

读取时 [candidate.json](candidate.json) 共 571 个条目，SHA256=`8bcded6426b82b8be8663aa9878be40ee7e53bf981b0d4a779efc13b39cbd28e`。这只是该 manifest 的范围，不代表旧工作区全树冻结。本次两项旧合同测试当前摘要已与该候选一致。

## 日志终态快照

当前 **54/57 组** 有完整终态 summary。原 57 组中已结束日志的原始累计为 **1561 passed / 5 failed**，含原 pure 的 958/2，尚未将新 pure 或 PG 复验重复相加。仅将完整 pure960 替换后，已知通过数增加 2、原失败减少 2；这仍是未完成快照，**不可作为最终联合总数**。缺终态分组：`verification_launch-2`, `tests-test_launch_storage`, `lifecycle-isolated`。

| 分组 | 本次读取的日志终态 |
| --- | --- |
| [pure](joint-pure.log) | 2 failed, 958 passed in 12.89s |
| [build_start-0](joint-build_start-0.log) | 5 passed in 125.75s (0:02:05) |
| [build_start-1](joint-build_start-1.log) | 4 passed in 64.63s (0:01:04) |
| [build_start-2](joint-build_start-2.log) | 4 passed in 69.58s (0:01:09) |
| [build_start-3](joint-build_start-3.log) | 4 passed in 91.48s (0:01:31) |
| [build_operational_facts-0](joint-build_operational_facts-0.log) | 4 passed in 25.30s |
| [build_operational_facts-1](joint-build_operational_facts-1.log) | 6 passed in 34.68s |
| [build_operational_facts-2](joint-build_operational_facts-2.log) | 3 passed in 19.65s |
| [build_operational_facts-3](joint-build_operational_facts-3.log) | 3 passed in 22.49s |
| [sample_handoff-0](joint-sample_handoff-0.log) | 2 passed in 171.84s (0:02:51) |
| [sample_handoff-1](joint-sample_handoff-1.log) | 2 passed in 205.44s (0:03:25) |
| [sample_handoff-2](joint-sample_handoff-2.log) | 2 passed in 240.18s (0:04:00) |
| [sample_handoff-3](joint-sample_handoff-3.log) | 1 passed in 104.14s (0:01:44) |
| [verification_handoff-0](joint-verification_handoff-0.log) | 3 passed in 494.73s (0:08:14) |
| [verification_handoff-1](joint-verification_handoff-1.log) | 3 passed in 478.07s (0:07:58) |
| [verification_handoff-2](joint-verification_handoff-2.log) | 3 passed in 483.15s (0:08:03) |
| [verification_handoff-3](joint-verification_handoff-3.log) | 3 passed in 575.09s (0:09:35) |
| [test_resources-0](joint-test_resources-0.log) | 1 failed, 2 passed in 1152.50s (0:19:12) |
| [test_resources-1](joint-test_resources-1.log) | 2 passed in 503.77s (0:08:23) |
| [test_resources-2](joint-test_resources-2.log) | 2 passed in 858.23s (0:14:18) |
| [test_resources-3](joint-test_resources-3.log) | 2 passed in 925.80s (0:15:25) |
| [verification_launch-0](joint-verification_launch-0.log) | 3 passed in 1248.48s (0:20:48) |
| [verification_launch-1](joint-verification_launch-1.log) | 3 passed in 853.13s (0:14:13) |
| [verification_launch-2](joint-verification_launch-2.log) | 待结束（无终态 summary） |
| [verification_launch-3](joint-verification_launch-3.log) | 2 passed in 987.20s (0:16:27) |
| [test_build_execution-0](joint-test_build_execution-0.log) | 15 passed in 140.36s (0:02:20) |
| [test_build_execution-1](joint-test_build_execution-1.log) | 15 passed in 171.43s (0:02:51) |
| [test_build_execution-2](joint-test_build_execution-2.log) | 15 passed in 124.34s (0:02:04) |
| [test_build_execution-3](joint-test_build_execution-3.log) | 1 failed, 14 passed in 122.76s (0:02:02) |
| [test_verification_execution-0](joint-test_verification_execution-0.log) | 6 passed in 85.02s (0:01:25) |
| [test_verification_execution-1](joint-test_verification_execution-1.log) | 16 passed in 67.42s (0:01:07) |
| [test_verification_execution-2](joint-test_verification_execution-2.log) | 1 failed, 4 passed in 73.54s (0:01:13) |
| [test_verification_execution-3](joint-test_verification_execution-3.log) | 5 passed in 79.52s (0:01:19) |
| [tests-test_cost_execution](joint-tests-test_cost_execution.log) | 37 passed in 233.15s (0:03:53) |
| [products-test_definition_transactions](joint-products-test_definition_transactions.log) | 9 passed in 5.23s |
| [products-test_variants_transactions](joint-products-test_variants_transactions.log) | 16 passed in 24.64s |
| [professional_authority-test_transactions](joint-professional_authority-test_transactions.log) | 27 passed in 27.65s |
| [providers-test_persistent_budget_transactions](joint-providers-test_persistent_budget_transactions.log) | 24 passed in 10.20s |
| [tests-test_build_comparison](joint-tests-test_build_comparison.log) | 5 passed in 0.01s |
| [tests-test_build_demand](joint-tests-test_build_demand.log) | 25 passed in 96.70s (0:01:36) |
| [tests-test_build_readiness](joint-tests-test_build_readiness.log) | 41 passed in 0.07s |
| [tests-test_build_start_common](joint-tests-test_build_start_common.log) | 8 passed in 0.07s |
| [tests-test_builds](joint-tests-test_builds.log) | 26 passed in 76.62s (0:01:16) |
| [tests-test_checkpoint_recovery](joint-tests-test_checkpoint_recovery.log) | 12 passed in 7.35s |
| [tests-test_configurations](joint-tests-test_configurations.log) | 25 passed in 35.64s |
| [tests-test_durable_evidence](joint-tests-test_durable_evidence.log) | 18 passed in 9.42s |
| [tests-test_handoff_common](joint-tests-test_handoff_common.log) | 7 passed in 0.07s |
| [tests-test_launch_common](joint-tests-test_launch_common.log) | 7 passed in 0.15s |
| [tests-test_launch_storage](joint-tests-test_launch_storage.log) | 待结束（无终态 summary） |
| [tests-test_original_security](joint-tests-test_original_security.log) | 26 passed in 25.90s |
| [tests-test_project_first_plan](joint-tests-test_project_first_plan.log) | 19 passed in 17.08s |
| [test_resources-test_rules](joint-test_resources-test_rules.log) | 37 passed in 0.17s |
| [tests-test_supply_execution](joint-tests-test_supply_execution.log) | 29 passed in 193.63s (0:03:13) |
| [tests-test_trusted_source_work](joint-tests-test_trusted_source_work.log) | 34 passed in 14.72s |
| [verification_front-test_read_concurrency_transactions](joint-verification_front-test_read_concurrency_transactions.log) | 2 passed in 2.10s |
| [verification_front-test_transactions](joint-verification_front-test_transactions.log) | 11 passed in 242.40s (0:04:02) |
| [lifecycle-isolated](joint-lifecycle-isolated.log) | 待结束（日志未生成） |

单例/专项复验读取状态：

- [joint-pure-post-start-repair.log](joint-pure-post-start-repair.log)：960 passed in 13.32s，读取大小 1141 bytes。
- [recheck-launch-replay.log](recheck-launch-replay.log)：尚无完整终态，读取大小 1 bytes。
- [recheck-destructive-replay.log](recheck-destructive-replay.log)：尚无完整终态，读取大小 0 bytes。
- [recheck-legacy-contracts.log](recheck-legacy-contracts.log)：2 passed in 23.51s，读取大小 99 bytes。
- [recheck-storage-real-window.log](recheck-storage-real-window.log)：尚无完整终态，读取大小 0 bytes。


`lifecycle-isolated` 必须在并发组结束后单独完成；其 DDL / 约束操作的隔离边界不能由其它业务通过代替。只有进度点或空文件的分组不能当作通过。最终出口需完整原组终态、失败节点替换、最终候选稳定性与主线专项检查同时就绪，当前仍待主线收口。专项日志已读取到旧合同两节点 `2 passed`，可按上表逐节点替换原两失败；该复验没有在上文原始累计中再次加总。
