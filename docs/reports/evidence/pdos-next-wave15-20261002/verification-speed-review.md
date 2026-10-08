# Wave14 → Wave15 验证耗时只读定位

状态：代码路径分析，未改生产或测试；未连接数据库、HTTP、运行 pytest/collection、构建或浏览器。下列次数来自调用关系，不是实测耗时或性能承诺。主线提供的“单进程、无锁等待、CPU 约 22%”只作为定位背景。

已确认存在有界的重复完整证明构建；未找到可据此声称的无限递归或证据树无界增长。优先考虑以下三项。

## 1. 夹具复用固定回读，Wave15 不先上传未使用的通过报告

- `tests/verification_launch/fixtures.py:130` 在 Accept 后用 `upstream.current(work)` 完整 GET；随后 `launch_work` 的 `:156` 再 GET 相同当前请求/实际方法/样件。这两个读取之间无业务写入。`tests/verification_handoff/fixtures.py:332` 的 GET 又未带已知 `build_id`，即使调用方只要一个请求，也读取全产品可读历史。可在后续夹具显式保存 Accept 后的一个 scoped view，由它取固定请求、方法及样件；发生写入后重新取，不能沿用 Accept 前的 view。现有 `actual_method`/`handoff` 已传 `_view`，这两处不应再重复优化。
- `tests/verification_results/fixtures.py:150` 总是上传、扫描并解析值为 `10.0000` 的报告；`tests/quality_execution/fixtures.py:55` 继承后立即另上传 `11.0000` 的失败报告，后续只捕获后者。后续可在测试专用报告构造入口明确选择通过/失败原值，Quality 只执行一次真实上传→扫描→解析；保留真实来源和完整安全链，不能直接插 Measurement 或替换已保存原件。
- 每个函数级 `results_work` 还完整重走 `launch.started`。资源窗在 `verification_launch/fixtures.py:164` 设为真实 now+5 分钟，`:435` 只等待尚未到达的剩余时间；若 Plan/Promise 已花过五分钟则不再额外等待。它确实设置了开测前的时间下限，但不能把全部十几分钟归因于 sleep。Wave15 一个连续正例可只建一次真实上游，逐步走 Issue/CAPA/Change；负例仍应保持独立事务/基线。**不能把当前 HTTP 多事务夹具直接改成共享可变 session fixture，也不能 mock 时钟或放宽生产 TTL。**

风险/验证：scoped GET 要保持私人过滤及 fixed revision；优化后检查报告字节、原件安全状态、Run 真实 Start 和两样件覆盖仍真实成立。保留原 Wave14 正例，不用精简夹具冒充其全链验收。

## 2. 单次 retained 核对内部重复重建同一 Build，可做带历史时钟的局部复用

调用放大有明确依据：首次结果 T1/T2 通常为 `inputs` 一次、common preview 的 validate/review 两次、execute 的 validate/replay_subject/confirmation review/apply 四次，共 **7 次** `verification_results.service._load`。每次 `:526` 的 `_load` 首尾都核对 retained（末尾 `_refresh_phase_proofs :662`），即至少 14 次完整 retained 证明构建；重放路径仍先 validate，但不应删此守卫。

`test_resources/retained.py:21` → `test_resources.service._load :747` → `_scope :335` 对每个样件调用 `inspect_sample`。当前两件 A/B 虽属于同一 Build，却都未传 `read_context`；每个 ready 样件经 `sample_handoff.service._start_context :289` 再执行 `build_start.service.execution_projection :1301`。投影重算当前双配置/批准、需求、供给、资源与占用、专业与完整来源，`:1061` 的 `build_operational_facts._load_bundle` 又构建/序列化完整需求并重新核对来源。一个结果动作因而至少可达到 **28 次同 Build 投影**（7×前后 retained 2×样件 2），还未计上游 Launch、捕获或最终 GET；这是静态路径次数，不是实测 SQL 次数。

后续可只在同一次 `_scope`/纯 GET 内，按 session+transaction+身份+产品+Build+固定 Start+**retained_at** 复用 Build 投影，逐样件的私人范围、readiness、实际方法与自身身份仍独立核对。现有 `sample_handoff.ReadContext` 可借鉴作用域/issuer epoch/期限护栏，但**不能直接传入 retained 分支**：其 `projection()` 调用未传 `retained_at`，会把原 Start 时刻换成当前时间；期限遍历也会把已结束的历史窗口视为失效。先把评估时钟纳入协议，且禁止跨原件 I/O 前后两次核对、跨 validate/preview/apply、跨事务复用。不要删第二次 retained、来源安全检查或当前专业重核。

风险/验证：需覆盖两样件同 Build 的复用次数，历史窗口结束但证明有效、Build 实际偏离、私人 current、来源/专业 issuer 撤销或 ABA、资源及样件 epoch 变化、原件读取回调期间撤销。当前候选不改，此项宜在后续单独增量验证。

## 3. Wave15 多失败按同一固定 Run 分组核验，避免每个失败再扫全 Run

`quality_execution.service._load :222` 为 Issue 中每条 FailureRef 分别调用结果桥；`quality_result_bridge.fixed_failure_result :117` 每次均读取该 Run **全部** MeasurementRecord，重算全部判据/Projection，循环核验全部测量的原报告，再前后各构建 retained。内部 `captured_reports` 只在这一次桥调用按 capture 去重。两个失败来自同一 Run/报告时，整个报告和全部原值至少重复两遍；有 k 条失败、m 条测量时，该部分呈 k×m 的重复扫描。后续 `_refresh` 又逐证明做一次完整 retained 重核，不能省掉跨字节读取后的最终守卫。

后续可以在一个品质核对 phase 内按 tenant/product/身份、固定 Run 版本、Projection basis、精确事件分别绑定，先一次核验完整 Run/报告，再为每个 measurement_id 生成独立 FixedQualityResult 和 FailureRef。保留每个事件→Receipt→固定 Run/Projection 的归属、每个失败 identity 与 delivery 映射，不把多个失败合并成一个 Inbox；末尾仍对完整 union read-set、全部 retained proof、opaque issuer/runtime stamp、当前政策与专业资格做重核。先在已有 two-failure merge 路径验证，不能跨命令持久缓存“已核验”。

风险/验证：同 Run 不同版本/不同事件不能误共享；Projection 事件与 import 事件须各自核绑定；某一测量缺字节证明、同报告第二行错误、原件读取时撤销、归并后历史失败需重核都必须继续拒绝。UNKNOWN/indeterminate 仍不能建确定失败单。

## 执行建议

当前 Wave14 联验维持冻结。下一步先做第 1 项测试构造/回读精简；若要解决主要运行核对耗时，优先实施第 2 项的单 phase 复用，再处理第 3 项多失败桥批量绑定。未有采样计时，不能给节省分钟数或断言唯一瓶颈。没有建议删批准、Receipt replay 前守卫、真实时钟、扫描、原字节核验或存储完整性约束。
