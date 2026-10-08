# Wave14 检查选集与替代审计

读取快照：2026-10-03 04:14 UTC。只读已完成日志、选集/result JSON 与当前测试参数声明；仅新增本文，未启动数据库、pytest 或修改代码。运行中日志不计通过，本文不是 Wave14 完成声明。

**本快照有 417 个去重 PASSED 节点；另 12 个节点尚待最终结果。** 其中 1 个保留原 FAILED、正等待修复复验，另 11 个属于正在重跑的结果业务选择。最终预期并集为 429 个 pytest 节点，不能提前写为 429 通过。

## 选集与已完成节点

以完整 pytest nodeid（含参数值）为计数单位，从 `-rA` 的 PASSED/FAILED/ERROR 行取集合，不把一次函数、多次尝试或参数函数视作固定一项。

| 选择 | 已完成原日志 | 原节点结果 | 精确替代后的覆盖 |
|---|---|---|---|
| 专业权威 | `regression-professional.log` | 53 PASSED | 53，包含 transactions 27 与 assessment 26 |
| Build 开工 | `regression-build.log` | 59 PASSED、1 FAILED | 60；失败节点由 mock-recheck 的对应 PASSED 替代 |
| 样件交接 | `regression-handoff.log` | 61 PASSED | 61 |
| 原值/结果/资源/正式请求纯核 | `regression-pure.log` | 174 PASSED、1 FAILED | 原覆盖175；失败由 narrow-port 单例替代；另8个新结果纯核节点见下 |
| Run/开测共同入口 | 原 `regression-launch.log` 中断；完成的 `regression-launch-recheck.log` | 54 PASSED、1 FAILED | 55；失败由 clock-recheck 同参数节点替代 |
| 后加 TOCTOU/历史展示纯核 | `regression-mock-recheck.log` | 44 PASSED、1 FAILED | 仅8个 PASSED 在原回归集合之外；其余属于重复/替代 |
| retained Start 新 PG | `new-pg-10.log`～`new-pg-14.log` | 各1 PASSED | 5 |

原 [regression-selection.json](regression-selection.json) 五组按节点展开为404；修复替代后这404个节点均已有 PASSED。mock-recheck 的8个新增节点使当前回归集合为412，再加5个 retained PG，得到 **417**。按测试范围拆分为377个纯检查节点、40个 PG 节点。此数字是本轮限定选集的证据并集，跨保留的原候选/修复链，不是一次 pytest 全通过，也不是全仓库检查数字。

新增8项位于 `tests/verification_results/test_pure.py`：`test_original_store_callback_epoch_drift_is_rejected_before_proof_use` 的 issuer/authority/retained_issuer/ledger/source/reads/None 七参数，以及 `test_retained_proof_display_clock_and_elapsed_window_do_not_revoke_old_execution`。原 pure 日志有35项结果纯核，mock-recheck 为43项；不能只沿旧175总数漏掉新增覆盖。

## 同一节点的正确替代

| 节点 | 必须保留的失败/中断 | 当前完成替代证据 |
|---|---|---|
| `tests/build_start/test_rules.py::test_historical_reviewer_epoch_checked_in_own_readonly_context` | regression-build 的 FAILED | `regression-mock-recheck.log` 对应 PASSED；只替这1项 |
| `tests/test_resources/test_rules.py::test_scope_uses_narrow_sample_port_and_retains_full_binding` | regression-pure、regression-mock-recheck 均 FAILED（替身未支持新增参数） | `regression-narrow-port-recheck.log` 1 PASSED；不重复计原/中间两次 |
| `tests/test_launch_common.py::test_launch_cannot_smuggle_result_or_disposition_through_shared_reader[preliminary_result]` | regression-launch-recheck 的 FAILED（实际读守卫缺口） | `launch-result-clock-recheck.log` 7 PASSED 中仅此1项替代失败，其余6项重复；[migration 22 证据](clock-guard-migration-result.json) 的4个 SQL 约束探针另外列示，不当作4个 pytest 节点 |
| `tests/test_retained_execution.py::test_retained_proof_rejects_new_real_observation_of_configuration_deviation` | `new-pg-15.log` 1 FAILED / KeyError engineering_payload | [retained-fixture-repair.json](retained-fixture-repair.json) 只证明夹具修复与静态检查；`retained-deviation-recheck.log` 仍无终结结果，尚不能替为 PASSED |

旧 `retained-clock-initial.log` 使用先前函数名 `test_retained_start_survives_elapsed_window_and_natural_qualification_expiry` 且为 setup ERROR；当前 `new-pg-10.log` 的新明确函数名说明“真实保存 Start + 模拟迟到读取时点”，只计当前这1项。不能把旧名称再加一项，或把模拟读取称为真实自然资格到期验收。

## 结果业务仍待的 11 个节点

[results-authority-recheck-selection.json](results-authority-recheck-selection.json) 重跑原结果10个函数，参数展开为11个节点；08 的 professional/resources 两参数分别算节点。当前00～03日志已创建但无终结结果，04～09尚未有完成日志；结果 JSON 未完成。对应关系如下：

| 分组后缀 | 函数 / 节点数 | 原证据状态 |
|---|---|---|
| 00 | partial/final→compute→review→disposition 同链，1 | 初 priority 及 new-pg/results-fixture-recheck 都未成功 |
| 01 | 最后 Outbox 故障全组回滚，1 | 同上 |
| 02 | 捕获稳定 key 与未知原值，1 | new-pg 与 results-fixture-recheck 为 setup ERROR |
| 03 | 已全部返回后的空 final 批次，1 | 同上 |
| 04 | 原报告撤回阻断确认/回执重放，1 | 同上 |
| 05 | 同 Run 并发导入 CAS，1 | 同上 |
| 06 | 当前 quality/精确 scope/Agent 边界，1 | 两旧组 SIGINT / no tests ran，不能算失败已复验或通过 |
| 07 | 结果表 immutable/RLS/Agent 零写，1 | 同上 |
| 08 | 原件读取期间 issuer 撤销，2 | 两旧组中断，两个参数都没有完成通过证据 |
| 09 | compute 旧意图重放期间运行时撤销，1 | 两旧组中断，无完成证据 |

`new-pg-00`～`05` 的实际 setup 错误为脱离 Session 后读取 ORM；`results-fixture-recheck-00`～`05` 为夹具在 Promise 前已越过原未来开始时刻。修复过程与中断原因见 [detached cancellation](fixture-detached-cancellation.json)、[window cancellation](fixture-window-cancellation.json)。这些原因解释重跑，但不是业务断言已通过。00/01 的早期 `results-chain/outbox-initial.log`、`*-fixture-recheck.log` 也只是同两个节点的失败/中断尝试，不能新增分母或抹掉历史失败。

完整 [new-pg-selection.json](new-pg-selection.json) 为16个函数/17节点（11结果+6 retained）。当前5 retained 通过、1 retained 失败待复验；11结果未获最终成功。因此“417通过 + 12待最终办理”与预期429节点相符，而不能将旧错误与新运行中节点写成零失败完成。

## 不可相加的包与候选范围

- `regression-mock-recheck` 的44个 PASSED 中36项与原回归覆盖重叠，仅8项新增；其中 Build 旧失败的 PASSED 是替代。其 FAILED 与 narrow-port PASSED 是同一节点，不另计。
- `launch-result-clock-recheck` 的7项都已在原 Run/launch 选择中；整组只更新节点状态，不新增7项。原值 verifier 的87项已包括在 regression-pure，不再加独立包历史87项。首版结果 pure35与续版43只计43的并集。
- priority/new-pg/results-fixture/results-authority 的同函数尝试不是不同业务用例；参数展开后方可去重。旧 SIGINT、setup ERROR、运行日志增长均不代表通过。
- 迁移往返/schema、4个数据库 CHECK 探针、构建、UI helper 与真实 HTTP/浏览器演练分别是检查证据，不能混入 pytest 节点总数。历史 Wave13 数字也不能叠加为 Wave14 同候选联合通过。
- [candidate-final-source.json](candidate-final-source.json) 与 [candidate-final-delta.json](candidate-final-delta.json) 是当时冻结范围；后续 Start 时钟守卫、单调22迁移、retained夹具修复及服务器资格重核对应其独立证据。最终报告须列出真实最终候选及受影响替代，不把早期 candidate hash 冒充覆盖后续全部修改。

## 主线最终还需读取

1. `results-authority-recheck-result.json`：应有00～09全部10组、所有 exit_code=0；逐日志 `results-authority-recheck-00.log`～`09.log` 应有完整 PASSED，08 必须两个参数都通过。当前无终结日志不能代读完成状态。
2. `retained-deviation-recheck-result.json` 与 `retained-deviation-recheck.log`：同一原失败 nodeid 必须实际 PASSED，才能将第6个 retained 算入。
3. 确认最终 source freeze/差异记录包含最后生产、模型/迁移与测试修复；核本轮真实 HTTP/浏览器链与 PG 出口在相应候选上完成。若两组出现新失败，应保留原日志、只以同节点修正版完成证据替代，不提前修改本文快照为全通过。

本报告冻结的是上述时点证据审计；后续主线结果需要另行汇总，不能由时间经过、日志文件出现或静态检查推定成功。
