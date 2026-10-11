# B4 读路径性能诊断（原候选，只读）

本审阅仅读取证据和源码、汇总既有样本；未改源码、测试、工具或迁移，未运行 PostgreSQL、测试或计时。以下是改动候选，不是优化通过记录。原 30 个实际业务 case 通过，但三个读取/输入 p95 超过 1 秒，仍须修复和重新冻结后证明。

证据：[`performance-attempt-1/b4-launch.json`](performance-attempt-1/b4-launch.json)（`test_exit=0`、`source_unchanged=true`）；根会话随后取得 [`b4-read-trace-fixed.json`](b4-read-trace-fixed.json)（原源码、单个 sample-1、`test_exit=0`、`source_unchanged=true`，288 条读路径 caller）。两者 `source_sha256` 完全一致。后者用于定位调用链，不替代 30 样本 p95。`b4-read-trace.json` 是错误 selector 的零收集结果，不是业务通过证据。

## 已观察结果及记录限制

p95 沿用现有汇总工具的 nearest-rank，不修改口径。

| HTTP 分组 | 样本 | p95 秒 | 每请求 SQL 次数 | 平均 HTTP / SQL 秒 | SQL / HTTP 均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| launch_read_before | 30 | 1.020689 | 60 | 0.926223 / 0.725377 | 78.3% |
| launch_read_running | 30 | 1.110761 | 51 | 0.895347 / 0.728533 | 81.4% |
| test.run.plan_inputs | 30 | 0.972411 | 58 | 0.822452 / 0.651077 | 79.2% |
| verification.schedule.promise_inputs | 30 | 1.095617 | 59 | 0.868743 / 0.719678 | 82.8% |
| test.run.start_inputs | 30 | 0.993579 | 60 | 0.877802 / 0.717924 | 81.8% |
| test.run.start_commit | 30 | 2.937841 | 195 | 2.661003 / 2.186609 | 82.2% |

原 SQL 记录只有 request × 首个表名的 `count`、`seconds`、`shape_count`。没有 SQL 文本、参数或实际对象 ID；shape 是 SQL 字符串的散列，与参数无关。单样本 trace 增加调用栈，仍没有参数或每条 SQL 的独立耗时。`seconds` 是 cursor 前后壁钟，包含传输/等待，不是 PostgreSQL EXPLAIN 的服务器执行时间。不能从“同 shape 两次”判断同一对象重复，也不能把聚合耗时归因到某个嵌套 RLS 函数。

trace 明确 `routine` 两次分别来自 `database.tenant_session` 的 `SET TRANSACTION READ ONLY` 和 `build_start._projection_current` 的 Current 联查。原 30 样本这个聚合桶的平均耗时为 before 90.410ms、running 82.512ms、promise inputs 83.961ms；证据没有拆开两条耗时，不能声称该值全是联查的服务器耗时。

## 建议的最小具体改动

### 1. 同一 RR 请求统一 BuildOperationalCurrent 读取入口

确切路径：`domain/test_resources/service.py:_lock_union`（原行 292）使用 `snapshot_scalar`，按 tenant/product/build 读取 BuildOperationalCurrent；之后 `domain/build_start/current.py:reservation_watermarks` 经 `domain/build_operational_facts/service.py:_pointer`（原行 336）用 `scoped_rows` 读取相同条件。两个请求证明的缓存命名空间和键不同，trace 证实两条路径都执行了 SQL。

候选：让 `_lock_union` 复用 canonical `_pointer`，或让两者使用相同的 canonical 指针读取证明。保留真实 Session/事务范围、tenant/product/build 条件、读写 lock 升级，以及后续 BuildOperationalFact 范围、可见性和摘要核对。不得把零查询的空集合改成跨请求缓存。

原 before 和三类 inputs 均为该表 2 次 / 1 shape；running 是 1 次，故此项只帮助前四组。原该表两次合计均值 before 22.833ms、plan 22.957ms、promise 44.914ms、start 23.619ms。减少 1 SQL 是静态预期；不能把合计均值直接当成节省量，也不能靠此项宣称 running 已达标。

### 2. RR 的 Build 当前投影复用已完整读取的不可变 Start

确切路径：`sample_handoff._start_context` 先通过 `(BuildStart, "by-build", product_id, build_id)` 读取 Start，并调用 `build_start._row` 完整验证范围和摘要。随后 `ReadContext.projection → execution_projection → _projection_current`（原行 1500）又在包含 assessment、两个批准指针和两个批准事实的联查中 outer join 同一 BuildStart。两次都执行完整 RLS；这是 trace 观察到的同一按 Build 选取路径。BuildStart 有 `(tenant_id, product_id, build_id)` 唯一约束，属于不可变事实。

候选：仅在真实 RR/只读分支，由 canonical `_start` 的本事务证明取得 Start，Current 联查保留 assessment 和两个 role 的指针/decision，移除对已经读取的 Start 的重复 join。保留 `_row` 的固定 Build/项目/双配置/摘要核对、`_read_evidence`、`_saved_capabilities` 和当前指针全部一致性校验。没有预读 Start 的调用者仍须实际执行 canonical RLS 读取；不得根据任意传入 DTO 或旧 Bound 推断 Start 存在。

此项覆盖 before、running 和全部 inputs。已预读的路径 SQL 次数可能保持不变，但联查少一次对 Start 的 RLS 求值。联查聚合桶较大是观察事实，具体节省量、RLS 内部代价及是否足以关闭超标是推断，需改后实测。

### 3. 专业历史核对复用同一 RR 中已授权的确切 Current 摘要

确切路径：`professional_authority.recheck_snapshot` 先 `_historical_facts`（原行 1061）读取冻结引用，再读取该 subject 的 ProfessionalCurrent（`scoped_rows` 原行 1158）。trace 中 before/inputs 的两条 facts 分别服务于样件 Readiness 的制造签名和 ActualMethod 的品质签名；running 的一条服务于制造签名。原 ProfessionalFact 聚合均值 before 37.084ms、promise 36.394ms、running 22.700ms。

候选：在严格真实 Session RR/只读且无脏专业事实的分支，先获取按 subject 精确缓存的 Current 集；仅对 `fact_id/revision/series` 与冻结引用完全一致的事实，用现有 `_summary_row` 和 `_check_current(..., summary_read=True)` 取得数据库维护的摘要。当前 ProfessionalCurrent RLS 同时包含 `professional_summary_audience` 和指向原 ProfessionalFact 的 `upstream_audience`，因此仍由完整现行 RLS 证明该确切事实可读。已换版、缺失、不匹配或没有可用摘要的历史引用，继续走原 `_historical_facts` 查询。混合集合只对未证明的引用走 fallback。

必须保留冻结 ref 的 hash/revision/epoch/series 比较、完整 Current 水位、issuer 对象/版本/epoch、当前注入时钟的有效窗、`retained` 语义和失效结果；不授予历史事实当前写入权。非 RR、写入、锁升级和更改专业事实的路径沿用原查询/失效纪律。预计当前合成 case 可少 running 1 条、before/inputs 2 条历史 facts 查询；这是当前指针匹配时的静态预期，不是所有历史的保证。实现后最小回归应覆盖已换版签名、issuer 变更、隐藏/撤回来源、受众收紧、授权到期和 RR/命令隔离。

## 可合批但不应误判为重复的读取

- `verification_formal_requests` 在 inputs 的 3/4 次分别来自当前请求、accepted 资源父版（start）、ActualMethod 的审阅父版、planned Method 的审阅父版。版本具有不同职责，不能删除核对。可以在 `_load` 已取得 actual-method 行和固定 documents 后，合批这些已知历史父版 ID，并让现有 `front._row` 继续逐一验证；必须保留当前版本与各固定历史版本的独立绑定。此项影响 inputs，不帮助当前 running GET（其 FormalRequest 集合已经 1 SQL）。
- `actual_configurations` 的两次分别是选中样件的单个实际配置和 `_actual_binding` 的整个 Build 实际配置集合；后者还通过 `build_actual_count` 验证不可读配置不能被遗漏。集合不能被单个配置替换。
- running 的 `operational_resource_occupancies` 两次分别是 BuildStart 的制造占用和 TestRun 的实际测试占用，两类 owner 不能合并为一种语义或省略。物理容量 summary 两次分别是 sample 与 resource 范围，也不是同一查询。
- running 的 Artifact 四条 SQL 中两条来自历史请求的 `_source_state`。可以把已加载请求/run 行的来源 ID 做同一 RR 的 `batch_read` 预取，随后原 `_read_evidence` 逐行执行 tenant/category/product、revision/status、visibility 和 Original 安全检查；trace 没有参数，不能断言四条里存在重复 ID。一次合批的收益需要实测。
- 读取能力的 `front._assess` 与 `_capability._load` 有部分重复计算，但 ProfessionalCurrent 早已按 subject 缓存。Readiness 的制造签名和当前品质调用者属于不同 subject；删除第二次同 shape SQL 会丢失专业核对。整体 Bound 不能跨 operation、请求或事务复用。

## 冻结与验证边界

优先实施前三项同事务复用，再评估是否需要 inputs 历史父版/GET 来源合批。原证据保留在 attempt-1；不能覆盖为新候选通过。三个小改动的已知 SQL 节省并不保证消除全部 p95 超标，尤其 running 差额 110.761ms。若改后仍超标，现有资料不足以判断规划、嵌套 RLS、数据规模或调度等待各占多少；应由根取得明确 SQL/服务器计划证据后再决定，不能为了门槛省略权限或事实证明。

每个复用仅限相同服务器身份、品类/型号、Session 和实际 RR/只读事务；写入仍保持完整 lock、失效、来源和专业校验。必要受影响回归由根统一执行，之后在新冻结候选记录真实 HTTP 的读/输入 p95 ≤1 秒和提交档位原门槛。单样本 trace、静态代码及旧候选功能通过均不构成优化后性能通过。
