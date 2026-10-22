# 第十四波实施合同

**2026-10-08：本施工合同已被[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)整体取代，仅作只读历史对照。下方旧“当前/下一步/冻结”不再作为施工指令。** 范围根、一致性、期限与数量限制按 v1.1 和已批准的 [S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md)执行；[旧条款对照与 B0 基线](../reports/evidence/pdos-next-s0-20261008/baseline/baseline.md)保留取代依据。原证据、失败与当时范围不改写。

状态：2026-10-02 已进入施工；第十三波本地合成闭环已交付。冻结公共接缝，验收仍以唯一清单和本波证据为准。[草稿](2026-10-02-pdos-next-wave14-results-contract-draft.md)及[衔接审查](2026-10-02-pdos-next-wave14-results-integration-review.md)的范围、来源、T1/T2与人工出口边界保留。

## 复用与交付

沿用 FormalVerificationRequest/Current、VerificationRunIdentity/Version/Current、原 ExecutionPlan、Start、资源占用和 SampleRunUsage。结果核继续调用 VerificationHandler/compute_results；新增四个不可变对象 measurement_import_captures、test_measurements、test_result_projections、test_result_actions，无 ResultsCurrent。结果追加同一 Run 版本，专业复核可以保留 Request 前后同一版本；全请求完成仍须满足原核的数量、模穴和接收分母。

测量证据接口冻结为 measurement_evidence.schemas 的 ReportBinding/ObservationSelection/ObservationCandidates/VerifiedObservation；extract_observations(content, binding, selections) 与 verify_measurement(content, binding, measurement, run) 只核原值。首版源为有界 UTF-8 pdos-measurement-jsonl-v1，完整原件 hash/byte size、逐字段原 token/位置和固定样件/实际配置/模穴/pair 绑定；缺项保持未知，不从 Run 回填元数据。

原件在当前 ACL/扫描/安全门禁内读取，两阶段读取与保存中间执行纯提取；保存及正式导入重新核对。候选不等于 Measurement，不推进状态或授予扫描 clean。run_basis_sha256 固定实际开始与计划、scope、Build、样件/items/coverage，结果追加不能覆盖原始执行基底。

历史证明入口冻结 test_resources.inspect_retained_execution(s, ctx, product_id, run_row, at=None, write=False)：固定原 rev2 Start/intent/已接收版本，核原占用、消费与固定期间依据，以及当前来源、安全 epoch、issuer、撤回和身份。窗口或历史专业事实自然到期按原发生期间核对；当前办理人仍须有当前职责与资格。接口零 reserve/stage/epoch 写入，不能恢复已消耗样件或默认为可以继续执行。缺证明明确阻断。

## 公共入口

- GET /v1/products/{product_id}/verification-results?build_id=&run_id=：同一 Run/请求历史、候选、原测量、固定判定及独立专业决定，当前能力仅由服务器评估。
- POST /v1/products/{product_id}/verification-results/captures：CaptureInput，仅选择固定原报告与原行/pair，不接可信原值、hash或资格。
- POST /v1/products/{product_id}/verification-results/inputs：完整 Command，固定载荷、读集、权限、来源状态与阻断原因；公共 preview/commands 统一确认、CAS、回执与重放。
- test.results.import 为 T1；test.result.compute 为 canonical T0；test.run.review 为辅助 T2；test.disposition.decide 为 canonical T2。后两项分别具名确认，AI 无 T2 权限。计算不改变原测量、运行状态或发生时钟。

载荷以 verification_results/schemas.py 为冻结源；四持久模型以 verification_results/models.py 为冻结源。新增迁移须核对真实 head 后单调分配，不修改已应用迁移。

## 并行归属与验证

A 独占 measurement_evidence 及其测试；B 独占 verification_results 及其测试；C 独占 build-results 组件及辅助模块/测试。主线独占共享 snapshot/模型约束/历史证明、注册/事件/API/BFF/挂载、原件引用 catalog、迁移、公共验证及唯一清单。三路可依冻结 DTO 并行，公共检查集中执行。

最小闭环须真实本地来源导入部分结果、最终结果与 Actual End、确定性投影、具名复核、处置和刷新恢复；原占用消费保持，局部结果不冒充全请求完成。检查原值/位置/范围/元数据、迟到结果/撤回、T1/T2/CAS/重放与末端回滚、private/RLS/Agent 权限及原件引用保护。合成数据不授真实资格、生产启用或人工 Exit；分段、重复采样/纠正、仪器连接、Issue/CAPA接线和资源释放未因此完成。
