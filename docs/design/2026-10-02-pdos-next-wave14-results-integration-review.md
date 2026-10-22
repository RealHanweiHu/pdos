# 第十四波结果返回：实施前合同衔接审查

**状态：实施前合同审查，未开始第十四波施工或验收，未授予专业资格、生产启用或人工 Exit。** 本文记录对[结果合同草稿](2026-10-02-pdos-next-wave14-results-contract-draft.md)、[完整目标架构](2026-10-02-pdos-complete-target-architecture-v1.md)及现有验证核/开测接线的定向只读结论。未修改草稿、`pdos-next` 候选或唯一清单，未运行数据库、公共测试、浏览器或迁移。第十三波可用性及同候选验证结果由主线收口；历史合成证明不等于真实工厂材料或专业资格。

草稿的业务主线与现有验证核一致。建议下一波最小完整交付为：真实 `running` Run → 原报告候选 → T1 部分追加 → T1 最终结果及真实结束 → 固定规则判定 → T2 具名专业复核 → T2 该 Run 处置。实施前必须冻结原值核验、同一持久版本链、历史执行证明三处接缝。

## 1. 可直接复用的核与当前接缝

| 资产 | 可复用内容 | 当前限制 |
|---|---|---|
| [验证 DTO](../../pdos-next/server/pdos_next/schemas/verification/contracts.py) | `Measurement` 保留原字符串；`ResultsSubmit` 的部分/最终范围、真实结束及未完责任；`ComputedResult`、独立 `ProfessionalConclusion`、`RunReview/RunDisposition`、UTC/IANA 时钟 | HTTP wrapper 仍须加入固定 Request/Run CAS、来源读集、capture/basis 绑定、共同 T1/T2 凭证。客户端不能提交资格或计算结论 |
| [验证规则](../../pdos-next/server/pdos_next/domain/verification/rules.py) | `compute_results`、`pairs/check_coverage/accepted_coverage/coverage_gaps/document_gaps` | 只解释固定实际 pair。缺元数据、非数值、单位/工况/方法/设备不一致保留 `indeterminate`；不复制算法或隐式换算 |
| [验证处理器](../../pdos-next/server/pdos_next/domain/verification/handlers.py) | `_run_action` 的部分追加/最终结束/复核/处置与 `_request_complete` 的精确请求分母 | 通过同一命令事务的真实端口接入，不再确认/预约。原核每 pair 一条测量，纠正/重复试验需另冻合同 |
| [验证端口](../../pdos-next/server/pdos_next/domain/verification/ports.py) | `EvidencePort.verify_measurement`、`SampleAvailabilityPort.recheck_running`、`CommandPort.runs/record` 的责任边界 | 真核值与结果阶段的历史执行适配仍未接通；端口不能返回乐观 stub |
| [前段适配器](../../pdos-next/server/pdos_next/domain/verification_front/adapters.py)及[开测适配器](../../pdos-next/server/pdos_next/domain/verification_launch/adapters.py) | 当前服务器 Authority 到核、固定 Build、同事务 Mutation 保存方式 | `BoundEvidence.verify_measurement` 明确拒绝；`LaunchCommands.confirm` 仅允许三个开测动作，不是结果 T1/T2 的通用授权器 |

数字判定与执行状态分别保存。部分先失败只说明固定范围的数值结果；局部 Run 最终 pass、reviewed 或 disposed 均不等于请求整体覆盖、工程/制造放行或可外发。自由处置文字不能暗改 `run.result=invalid`，也不能恢复执行或样件使用许可。

## 2. 原值核验 port：先固定 DTO，再并行实现

建议新 `domain/measurement_evidence/` 仅负责确定性提取/核验，不拥有 Run 状态、资源、批准或业务回执：

```python
extract_observations(report_binding, parsed_source, mapping) -> ObservationCandidates
verify_measurement(source_bundle, measurement, fixed_run) -> VerifiedObservation
```

这些是待冻结的合同名，不是已存在导出。最小 `VerifiedObservation` 须保存：

- 原始 `raw_value` 字符串或明确 null、值种类；每个单位/工况/方法/设备/环境/观测时钟字段的原位置、原标签或缺项，不能从 Run 理想值回填。
- 固定原件与 Artifact 的 id/revision/hash、解析器版本、原件安全 epoch、精确定位及映射依据、来源性质、完整核验 basis 摘要。
- 服务器绑定 tenant/product/project/Run、固定 sample/item pair、样件/实际配置版本；完整当前来源读集和受众边界。

首版优先有界原生 UTF-8 JSONL。拒绝重复 JSON key、多个候选、非法时区、越 Run pair、错误 locator/raw/metadata；逐字段核值不能退化成“Artifact 存在且 hash 正确”。`mapping` 仅选择原位置及固定 Run 已有 pair，不接收客户端可信 hash、数值、资格或当前状态。已有 JSONL 行中真实缺失的字段可以保留缺项；**最终覆盖所缺的 pair 必须有明确来源的缺值观测或可信人工观测事实，不能按 Run 名单凭空生成 null 测量来凑齐范围。**

原件读取复用 [originals 门禁](../../pdos-next/server/pdos_next/originals.py)和[解析定位 DTO](../../pdos-next/server/pdos_next/evidence_processing/types.py)。ACL、扫描/访问隔离、安全 epoch、不可变原件与派生文本边界均须保留。PDF 模糊命中、未接 OCR、XLSX 浮点转写/公式缓存不能声称原读数已核实；首版可保存原件与缺项，不将其包装成肯定测量。

capture 只保存可恢复的具名私有候选。候选键绑定完整固定报告/映射/Run 基准，提取结果与来源安全 basis 不变；准备或解析不推进 Run、不产生正式 Measurement、不授 scan clean。外部解析在命令事务外完成；候选保存及正式导入前分别重核固定来源，事务内不等待容器、LLM 或仪器网络。

## 3. 同一 Run / Formal 版本链，不能另建结果真值

现有 [Run 模型](../../pdos-next/server/pdos_next/domain/verification_launch/models.py)只允许 planned rev1 / running rev2 与 plan/start；[开测 `_snapshot`](../../pdos-next/server/pdos_next/domain/verification_launch/service.py)还拒绝测量、部分返回、结果及专业结论；[Formal `_snapshot`](../../pdos-next/server/pdos_next/domain/verification_front/service.py)只允许至 executing 并禁止结果时钟。仅新增结果表或放宽 CHECK 不足以接通业务，所有读取和原子触发器须与同一版本链一起扩展。

必须冻结如下持续不变量：

1. `VerificationRunIdentity` / `VerificationRunCurrent` 仍是唯一 Run 身份与 Current。Run 继续连续不可变版本：running 可多次部分追加 → results_pending → reviewed → disposed；没有 ResultsCurrent 第二指针。
2. 原 `request_version_id/request_revision`、`input_snapshot.plan_binding` 永远绑定起源 accepted Request；固定样件、实际配置、判据/方法、ExecutionPlan/hash 均继承，不改成后续请求版本。
3. 原 Start intent、正式 Reservation/occupancy/SampleRunUsage 证明须单独固定引用并保留。结果命令有自己的意图，不能用新结果 `intent_digest` 覆盖后再寻找原开测证明，也不得重新 stage/reserve。
4. 部分结果继续 running，并追加本批范围、缺项/下一责任人及返回钟；Formal 继续 executing。最终只有核 `_request_complete` 真实满足 offered/accepted/数量/模穴分母才 reported；否则仍保留未完成请求。处置同理。
5. review 通常只推进 Run，不推进 Formal。新 action fact 必须能精确记录 unchanged Request 的 before==after；不能为了回执伪增请求版本。全部新写 CAS 放在共同去重之后的 preview/apply，重放先当前鉴权与来源核对。
6. 原 `VerificationLaunchFact` 每 run/operation 唯一，适合 plan/start 而不适合多批 import。新结果 action fact 独立保留每批输入、Mutation 前后版本、固定 basis 和 Receipt；每个 Measurement immutable，unique `(tenant,run,sample,item)` 与独立测量身份均须保护。

主线应集中修改现有模型约束、共同读取/decoder、Formal/Run Current 与 deferred 原子检查、共同操作注册和真实 head 单调迁移。新结果服务不得复用开测 `_record` 的“禁止结果”保存逻辑或另起状态机。Run 显示与旧前段/交接读者也须能刷新结果新版本，历史内容保留真实 stale/未评估标记。

## 4. 历史执行证明：与当前再开测评估分开

[`test_resources.recheck_running`](../../pdos-next/server/pdos_next/domain/test_resources/service.py)目前仍调用完整 `_load/evaluate`，检查当前执行窗口、fact validity、当前执行者资格/样件 ready 及占用变化。它不能直接充当正常窗口结束后迟到报告的接收接口。

实施前须冻结只读 `inspect_retained_execution(...)` 合同，至少核对：原 Run/ExecutionPlan/真实 Start/intent、精确 ResourceReservation、全部已保存 occupancy 与 SampleRunUsage 集合、样件实际配置/破坏性/原归属、来源安全与当前消费者 ACL。成功不产生预约、消费、epoch 或资源释放；另一 Run 永远不能凭处置或时间经过复用破坏性样件。

需明确两类有效性，不能只将当前评估时间改成过去：

- **历史发生依据**：固定执行者、设备/校准和专业事实在真实发生区间的版本/有效期，以及原提交时完整证明；自然窗口结束或自然到期不等于原测量虚假，今天的新资源版本不能替换过去依据。
- **当前办理安全**：办理人当前本操作职责/资格、当前 ACL/原件安全、来源撤回与原签发者 epoch/issuer 的失效或 ABA。真实撤回、隔离或证明不可核对时阻断有效导入/复核或明确待核，不能从历史正例猜当前有效。

这一区分是待冻结的规则，不是已实现的免检例外。共享 asset 变化导致严格旧 fingerprint 失效的 v1 限制应如实显示，不以 stub 或偷偷排除其他 owner 占用绕过。报告原件与候选可以保留，但缺历史证明应明确 `INTEGRATION_REQUIRED`。

## 5. T1 / T2 与原子边界

`test.results.import` 的 T1 只确认本批精确 pair、原值/缺项、部分未完责任或真实最终结束。服务器由 capture 生成 `ResultsSubmit`，同 UOW 保存 Measurement、核结果、新 Request/Run 版本和共同 Receipt/Audit/Outbox。接收/保存钟在实质预览显示提交时未知，避免评估 now 或临时 UUID 造成确认摘要漂移；完整来源、判据、occupancy/usage 证明及 basis 摘要仍绑定。

`test.result.compute` 为 canonical T0 固定规则计算，不改变 final/执行状态/专业时钟，不增加 T1 或 AI 资格。导入内自动计算与独立计算复用同一函数和固定输入，不产生两套算法真值。

`test.run.review` 与 `test.disposition.decide` 分别 T2。共同 named approval 必须绑定 Run 版本、全部 Measurement/判据/结果 projection basis、专业事实 epoch、确切文本及真实 event 来源；当前人须有对应品质资格，AI 不执行 T2。专业来源/资格失效影响当前可用性，不改历史具名内容。现 [共同等级注册](../../pdos-next/server/pdos_next/command_handlers.py)尚未注册这些动作，现有私有 confirmed 适配亦不覆盖结果；须新增明确接线，不能靠载荷的 approved_by 或字符串角色。

复核/处置不批准工程、制造、客户承认或外发，不清消费、不重新授权开测。自由文字不自动解释成 invalid/hold/pass；新增 typed 无效、复测或释放动作前须另冻规则。

## 6. 独占并行建议

| 包 | 建议独占文件 | 可立即并行的输出 |
|---|---|---|
| A 原报告核验 | 新 `server/pdos_next/domain/measurement_evidence/**`、`server/tests/measurement_evidence/**` | 先发冻结 locator / Observation / verifier DTO；实现 JSONL 逐字段原值、缺项及负例，不拥有 Run/批准/回执 |
| B 结果领域 | 新 `server/pdos_next/domain/verification_results/**`、`server/tests/verification_results/**` | capture、Measurement、固定 result projection、action fact 与现核同 UOW 接线；旧意图重放、CAS/回滚测试 |
| C 用户办理 | 新 `web/src/components/builds/build-results.tsx`、`web/src/lib/build-results-view.ts` 与局部辅助测试 | 原件/位置、样件标签/模穴/实际配置、固定方法、局部/整体分母、一次 T1 与分别 T2、精确未知回执恢复 |
| 主线公共接缝 | 既有 Run/Formal 模型/读取/原子触发器、retained proof、公共 PAYLOADS/等级/专业操作/events/API/BFF、生命周期 catalog 与迁移 | 冻结同一 append/历史证明/GET/实质预览合同后派工；统一数据库/联合检查及唯一清单 |

A/B/C 不同时修改共享模型；原 `verification/resource_readiness` 核继续冻结。若核确有规则缺口，先报告并指定唯一归属，不能把现核拒绝当成可绕过的适配障碍。资源端口不再执行 stage，因此结果接线不引入新的资源分配等待；性能复用限同一显式 phase 与完整安全 binding，不能跨 inputs/preview/execute 缓存资格或删来源核值。

## 7. 最小真实验收节点与未完成范围

- 两批原值追加、最终空批收尾、T2 复核与处置；每阶段旧 Request/Run、Start、占用/消费证明保持，局部 pass 但缺模穴/未接收请求不 reported。
- 错 locator/raw/单位/工况/方法/设备、重复 JSON key、越 pair、伪 null 补齐、重复测量身份；真实缺项保留未知，既有原测量不能换 UUID 覆写。
- 窗口结束后原消费归属的迟到返回；另一 Run 不得重用。source/原件安全、原专业签发者撤回/恢复 ABA、issuer 失效与 T2 basis 漂移均按当前守卫办理。
- 不同 key 同意图仅一套回执；CAS 双并发、末端 Outbox 失败回滚 Measurement/双 pointer/动作与凭证消费；结果路径零新 reservation/usage/epoch。
- 新旧 Run/Formal GET 可刷新、private 来源不可扩大、RLS/Agent 零直写及 AI T2 拒绝；由主线统一真实 head 往返与同候选选择集。

AT-09 分段/纠正、AT-23 失败 Issue/CAPA 闭环、真实仪器资格、自动资源释放、正式放行/外发及人工 Exit 均未完成，也不属于本审查新增授权。本文只给出下一波的可实施接缝与验收条件。
