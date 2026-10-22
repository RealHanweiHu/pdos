# Wave17 CAPA 独立有效性与关闭合同草稿

**状态：只读续接草稿，供主线审阅；待主线冻结施工合同，未实施本波，未执行任何数据库、HTTP 或测试。** 用户按完整设计连续建设的既有授权保持有效，本方案不新增用户批准关卡；当前不改源码是因为 Wave16 的 backend480 候选冻结运行。本文不改变唯一清单、Wave16 候选或原人工 Exit。目录、DTO、旧纯测试和本草稿均不代表可信端口已接通或验收通过。

依据：[完整目标架构 §11～14、黄金路径 D、附录 66 操作与验收场景](2026-10-02-pdos-complete-target-architecture-v1.md)、[执行方案 §12～13、G3](2026-10-02-pdos-next-execution-plan.md)、[Wave16 冻结合同](2026-10-02-pdos-next-wave16-quality-followup-implementation-contract.md)及[独立续接审阅 §1～3](../reports/evidence/pdos-next-wave16-20261002/wave17-draft-independent-review.md)。源码判断仅针对下列当前模块，不从旧轨或历史模拟继承资格。

## 1. Wave16 之后实际还缺什么

已有根因 T2、本人完成 T1 和真实输出回链 T1，可以证明一项调查完成并创建了新的正式请求 Draft。新请求有真实 owner 保存回执，仍不证明样件接收、实际测试、方法适用、完整原报告、专业复核、观察期覆盖或有效性。

`domain/capa_verification/service.py::inspect_candidate` 已核固定 Issue/CAPA、回链、新 Run/sample/item/实际配置、原报告逐字段原值及确定投影，并禁止原失败 Run 作复验。它明确保留适用、独立性、观察事实接口缺项；`CandidateInspect` 的这些字段只能为 null、结果只能 indeterminate、有效性/关闭能力只能 false。`quality_execution/adapters.py::BoundPolicy.verification` 仍抛 `INTEGRATION_REQUIRED`。目前专业 operation matrix 也没有有效性与关闭操作。

新 Formal 候选只枚举具有直接 canonical 保存回执的精确 Current 版；由开测或结果动作推进、回执主体为 Run 的 Formal 配对桥仍未配置。不得借旧请求 Current、原失败请求的旧版或猜测 ID 补这个缺口。后续新 Run 自己的 `test_run` Receipt 可用，但 Formal 配对证明仍需严格 owner 适配。

实际复验推进后，新请求 Current 本身也会成为 paired Formal 版，Wave16 的直接回执枚举不够支撑最终候选。已保存的 Draft Link 保留其原始 planned 输出，不能把它的旧版 ref 当作新 Current，不能改写它的 snapshot 或 resolution_sha256。最短可交付路径是完成真实复验后，用下文严格 paired owner 证明选择精确 Current 输出，另存晚回链；更宽的合法后继跟踪必须另冻，不能靠忽略版本来实现。

当前主线保留的 Wave15/16 Issue 与原来源为 private，现有调查系列读取门禁只允许 series owner。该 owner 又属于旧核排除的参与者，不能承担本条独立有效性决定。为 peer 新增 ProductGrant 不改变 Issue 或原来源的 visibility，也不构成独立性证明；内部借用 owner Context 读取后让 peer 决定同样越过读取门禁。本条私有调查保留原历史，继续等待合法独立证据与读取权；本文不批准 ACL 扩展或旧系列受众变更。

## 2. 推荐最小可验证业务结果

推荐在来源与系列从最初即允许独立人合法读取的调查类 CAPA 上，形成“真实新请求 → 已接收的实际样件与适用方法 → 新 Run 实际执行及原报告 → 确定性判定与具名复核 → 有来源的观察事实 → 不可变候选 → 独立具名有效性决定 → 单独具名关闭”。当前私有调查可继续保存缺项候选，不能充当正向独立决定的验收场景。

第一条可执行正向用例须从真正 product 可读的原始来源和另一个合法、已发生的失败场景初建共享 Issue。它需要不同的真实 Run/样件、实际措施完成和观察事实，不能复制同一个 Failure 建第二条共享调查，也不能改旧 Issue 或原来源 visibility 来制造读取权。可复用来源允许且范围一致的固定 Definition/BOM/工程与制造配置版本；原失败身份、措施完成、复验和观察仍分别取本场景真实 owner 事实。

该正例还须满足：措施确属已验证调查类、根因已具名、措施全完成、全部原失败可精确映射、合法独立复核人当前能读取完整来源闭包，且现有 owner 能提供当前方法与实际执行证据。所有必要观察事实必须已实际发生。合成联验只采用宿主核对过的显式 local-synthetic profile，来源、时钟和 nature 明示；不能把它称为真实产品有效性或工厂资格。共享合法新失败场景和稳定 CAPA 语义锚都是施工合同冻结前的依赖，不能留给验收时临时绕过。

若 CAPA 措施要求正式工程改版、制造切换或培训/库存处置，当前 Change 的八 facet UNKNOWN 不能清零。这类措施依真正的 ChangeOrder/实施/实际生效 owner，缺口继续阻断。调查类闭环不授权工程发布、制造放行、客户承认、外发或 Change 关闭。

本波必须同时可用地保存“不适用、观察未齐、结果 indeterminate、确定 ineffective”路径。真实新分支或候选保存成功不能自动选择 effective；未知不得改成 ineffective，缺口也不能仅由按钮关闭而丢失原因。

## 3. 原样复用与必须新增的适配

| 当前模块 | 直接复用 | 尚缺事实/适配 |
|---|---|---|
| `domain/quality_issues/handlers.py::_verification`、`EffectivenessDecide`、`IssueClose` | 措施全完成、根因、观察期、禁止原 Run、nature、全部失败精确覆盖、独立参与者排除、effective/ineffective 分路、关闭重新比较 read_digest/政策 | 真实 `PolicyPort.verification`、共同 T2 持久 adapter 和专业操作矩阵；不复制规则 |
| `domain/capa_verification/{schemas,service,models}.py` | `FollowupBasis`、`FailurePairMapping`、固定 owner 读取、原值重核、回链及缺项、候选表声明 | 候选写入尚无公开动作；固定 null/indeterminate 的旧候选不能直接升为已核验事实 |
| `domain/verification_{execution,front,handoff,launch,results}` | 真正新请求、实际配置方法适用、接收、计划/承诺/开测、部分/最终结果、复核/处置与版本链 | 按 CAPA 要求对新方法/判据/样件配置作专门适用映射；不能从一般 method applicable 或 Run pass 推导 |
| `domain/measurement_evidence`、`domain/test_resources/retained.py` | 原报告 bytes、精确字段 token/定位、固定 Run 基底、原 Start/占用/消费历史证明 | 完整 CAPA 证据 owner 必须调用这些实际端口；不重新占用或消耗，不以 native 文本替代仪器报告 |
| `domain/professional_authority`、`quality_execution/policy.py` | 当前职责/资格、issuer/epoch、来源 ACL、安全、可信政策发布模式 | CAPA 验证/有效性/关闭精确用途矩阵和版本化观察/接受规则；现风险 policy 不含这些完整规则 |
| `domain/quality_followup/ports.py`、`quality_followup_bootstrap.py` | 已完成措施的固定 action/completion 摘要、受控调查分类出版及本地有限 profile 模式 | 复验仍须独立核措施要求是否满足；现合成调查分类不能变成真实正式变更实施证据，上传分类材料入口仍缺真实 bytes 桥 |
| `quality_followup_host.append_issue` 与 common Command/证明/Receipt/Audit/Outbox | 同 Session 聚合追加、CAS、一次 T1/T2 证明和原子回滚模式 | 当前 append hook 只接根因/完成；`_module`、`OP_TIERS`、同事务 consumed marker 只覆盖本波三项，`quality_execution.TransactionCommands.confirm` 也未接新 T2。有效性/关闭必须另冻精确公共协议；不另建 Issue/CAPA 真值 |

旧 `tests/quality_issues/` 已覆盖独立性、观察期、自然类型、无效/有效历史和关闭后来源失效，可按影响选取。其 fake policy/evidence 不能作为新持久接口的可信事实；本波需真实 owner、SQL 事务及 UI 验收。

## 4. 操作分级与 66 操作对应

| 操作 | 原合同地位 | 本草稿建议 |
|---|---|---|
| `verification.request.create` | canonical T0 | 复用真实新逻辑请求与保存回执，当前具名专业资格仍必需；不新造第二套请求 |
| `verification.handoff.offer/accept`、`test.results.import` | canonical T1 | 复用实际交样/接收和原报告导入；一次共同确认，不授有效性 |
| `test.result.compute` | canonical T0 | 复用固定规则与 projection basis；不新增同义计算操作 |
| `test.disposition.decide` | canonical T2 | 仅该 Run 的专业处置，不代 CAPA 决定；是否需要某类处置须由版本化 CAPA 规则指定 |
| `test.run.plan`、`verification.schedule.promise`、`test.run.start`、`test.run.review` | 已接入辅助操作，不是 66 表中全部都有 | 保持既有 T1/T2 与真实时钟/资源边界，不因本波重新命名或降级 |
| `quality.capa.effectiveness.decide` | **canonical T2**，事件 `capa.effectiveness_decided` | 本波拟接真实 owner 后开放；具名品质专业人决定，AI 只能准备 |
| `quality.issue.close` | 原纯核辅助 **T2**，不在 66 列表 | 须显式注册并冻结关闭政策；另一次具名决定，不与 effective 合并 |
| 候选、观察、专业验证记录 | 尚无公共操作合同 | 建议辅助 `quality.capa.verification.candidate.record` T1、`quality.capa.observation.record` T1、`quality.capa.verification.review` T2；名称与职责先由主线冻结，不因本文自动注册 |

三项新辅助操作不改变 66 个 canonical 的 tier。候选/观察 T1 只记录来源事实；专业适用与独立核验属于具名 T2，不允许以 accepted=true、ProductGrant、AI Qualification 或 model/client 参数授予。真实规则出版继续走宿主持有可信 issuer 的内部入口，不能提供公开自授政策 API。

新增实体/namespace 在已授权的全量目标与共同模型合同内按实际 head 迁移，本文不预留迁移号、不宣称已实施。公开新操作及其 T2 技术协议由主线冻结后接线，不因此新增用户审批。不得把降低现有独立性、允许无观察或合并关闭作为实现细节；真实 T2 具名决定、生产、真实外发和原人工 Exit 的批准关卡保持。

## 5. 最小对象与 typed owner 合同（待冻结）

推荐保留一份 Issue/CAPA 聚合，增加必要的证据 owner，不另建新的 CAPA 状态账：

1. **版本化验证规则出版及 Current**：固定 policy ref、issuer/version/epoch/nature、project/purpose、CAPA requirement 摘要、方法/接受规则、原失败覆盖规则、观察范围/采样覆盖/时间要求、必要 review/disposition 及参与者独立规则、有效期、精确来源与读集。可信缺项/冲突即 unknown，不解析自由文本 acceptance 补造量化阈值。
2. **候选保存**：复用 `CapaVerificationEvidence`，固定 `FollowupBasis`、回链、全部 `FailurePairMapping`、实际候选 inspection/hash/读集及保存人的 T1 proof。旧表 CHECK 规定 null/indeterminate，继续保留；候选本身从不获得专业通过状态。
3. **观察事实版本及 Current**：固定 Issue/CAPA/requirement、范围与被观察的样件/配置/批次或确定群体、实际 observed_from/until、采样/记录完整性依据、结果/未知、执行者、发生与服务器接收时间、IANA、sources/security basis、issuer/epoch/nature。public T1 输入只选精确原件并记录事实，完成范围由真实 owner 和规则核验，不能填 observation_complete=true。
4. **不可变具名验证 Review**：固定候选、规则、方法/判据/实际配置映射、完成事实、所有原报告/投影/观察 refs、验证人及完整参与者证明、applicable/not_applicable/unknown 结论、理由、专业/政策/来源摘要、实际 T2 proof。每条 action 还须有独立的履行核对，绑定 action_sha/completion_sha、实际分类与出处；回链里的 `ACTION_FULFILLMENT_PORT_MISSING` 只能由真实核对解除，不能因对象存在或人工按钮删除。它是新增 companion 事实，不覆盖旧 candidate 的 null 字段，不直接写 CAPA effectiveness。

候选可以分别保存尚缺观察/尚缺实际 Run 的部分证据。具名 Review 可保存不适用或未知并显示缺项；只有完整、当前、符合规则的已保存事实集合才能由证据 owner 适配成旧 `VerificationEvidence`。不建议另加公共“effective compute”按钮；计算由 inputs/preview 的确定性 owner 检查复用。

建议 B 先冻结下列接口，参数均为调用者同一 Session，默认无 effect、无 commit/连接或另发 Receipt：

```text
inspect_candidate_input(s,ctx,product_id,CandidateBinding,at) -> SavedCandidateInput
load_rule(s,ctx,scope,purpose,requirement_digest,at) -> RuleProof | Missing
inspect_applicability(s,ctx,basis,candidate,rule,at) -> ApplicabilityProof | Missing
inspect_observation(s,ctx,basis,observation_refs,rule,at) -> ObservationProof | Missing
load_verification_evidence(s,ctx,evidence_id,issue,at) -> VerificationEvidence
refresh_evidence(s,ctx,fixed_proof,at) -> StableProof | DomainError
recheck_capa_semantics(s,ctx,issue,stable_anchor,transition_refs,at) -> CapaSemanticsProof | DomainError
```

`SavedCandidateInput`/proof 至少固定 immutable row id/revision/hash、logical scope、全部 failure→新 Run/sample/item/实际配置/measurement/projection 映射、`required_source_read_set`、安全/政策/issuer/professional epoch、有效期和 nature。客户端不传可信 verifier_id、executor 集合、current/applicable/complete/pass 或 hash 作为授权事实。缺真实端口明确 `INTEGRATION_REQUIRED`；读取可以返回结构化 missing，决策不得以默认 false/true 装配一个假的完整证据。

证据 owner 组装旧 `VerificationEvidence` 的 id 必须是实际不可变证据/Review 身份；sources、failure_ids、run_ids、verifier_id、executor_ids、result、requirement_digest、observed_from/until、applicable/current/nature 均由上述 owner 核出的真实事实给出。观察事实的保存时刻不是观察发生时刻；CAPA `observation_until` 是要求，不是实际观察完成证据。

上述新 Review/Observation 等 companion 的 domain `SourceRef` 必须由 owner 校验真实 row、精确 version/hash、scope/owner、当前签发者职责资格和全部来源。任意领域 UUID 或按钮保存的结论不能替代它。`recheck_capa_semantics` 是待冻结的新窄 owner 合同，不能假定现有宽 FollowupBasis 相等检查已支持它；新增接口或必要的旧接口扩展归属须由主线明确后实施。

## 6. 不可省略的守卫与状态

- **Current 与稳定 basis**：新写精确 CAS 当前 Issue；历史重放先核当前身份、权限、原失败与所有证据，再返回原 Receipt，不再次 consume。固定 evidence read_digest 排除纯观测 `checked_at/now`，保留全部相关版本、源、安全、issuer、负向事实与 effects。关闭须沿下述稳定语义锚重核，并与有效性保存的 evidence read_digest、policy ref 完全相同；当前认证闭包仍读齐全部原源与合法新增源。
- **新复验与原值**：必须新 logical Run，不使用原失败 Run 的后续 pass 版；全部原失败精确覆盖且没有额外失败，固定实际 sample/config/item/method/criterion。最终原报告缺覆盖、null/非有限值/未知、陈旧规则或 projection basis 漂移不能 effective。一般 Run pass 不能证明措施文本履行或 CAPA 专业适用。
- **时钟**：原件测量/新复验和实际观察须在措施真实完成后；`observed_from >= max(action.completion.occurred_at)`，区间递增，实际结束覆盖 requirement 截止且不在未来。单次短测试不能冒充长观察期；观察完整性缺 owner 就保持 unknown。计时器醒来只触发重核。旧 Start 窗口自然结束可沿 retained 读历史，不能放宽新 T2 操作者当前资格/政策。
- **独立性**：旧核在所有风险下均排除原失败测试者、措施/遏制执行者、根因决定者、新测试/测量执行者。高/critical 或 independent_verification 政策另要求决定者就是独立证据 verifier 本人。宿主须从实际执行、报告与措施 owner 收集完整集合，不能只信客户端名单。无法证实完整参与者集合即 unknown。当前私有系列的 owner 不能借 peer Grant 或代用 Context 补成独立人；缺合法读取权时保留阻断。
- **受众与来源**：读取/写入均核 tenant/product/project/purpose 和最窄来源受众，完整 union≤20，超限明确拒绝不截断。独立人无权读取私有 Issue、原件或样件时不得决定；不克隆同失败共享 Issue、不扩大旧 visibility、不代签。原生登记文本可作具名事实出处但不冒充仪器原报告；有 UploadedOriginal 仍核真实 bytes/hash/安全/epoch。
- **撤回/ABA/TOCTOU**：全部 bytes/owner IO 后重新核源、原件门禁、Current、政策、issuer、专业及实际配置/样件使用 epochs。相关撤销→恢复必须不同指纹；既有 Artifact withdrawn 为终态，不借恢复绕过。没有跨 inputs/preview/execute 的缓存。新无关资格与历史 Start 的处理只沿现 retained 精确旧 refs 合同，不忽略相关新事实。
- **原子组**：候选/观察/Review 各自和共同 proof/Receipt/Audit/Outbox 同事务；有效性/关闭追加既有 IssueVersion/Current，同事务一次 T2。模型 immutable/RLS/Agent 零直写、精确 scoped FK、Current 首版/连续前版/owner与范围、生命周期引用覆盖、Receipt/proof/事件 deferred pairing 由主线统一加固。允许提前存在的只读捕获不随后续失败被错误销毁；失败不得留下业务新版本或消费 proof。
- **决定语义**：旧纯核要求 effective 的全部证据为 pass，ineffective 分支要求至少一个确定 fail；不能声称旧核已拒绝所有 fail 与 indeterminate 的组合。新 owner 对完整适用性、覆盖和未知混合结果的装配规则必须先随政策冻结，不篡改旧核，也不能把缺项补为确定失败。effective 后 Issue 仍 awaiting_verification，关闭另次 T2 且由有效性决定人本人办。ineffective 不关闭、不自动增措施；新措施/根因更正另冻修订合同。关闭后来源失效保留历史结论，当前适用性标需重核，不静默改写旧事实或自动重开。

稳定 CAPA 语义锚须在公开接线前冻结为两份相互关联的闭包：

1. **`StableCAPASemantics`**：固定 tenant/product/project/purpose、owner/visibility/nature、精确 Failure、根因、遏制、actions/completions、requirement，以及这些原 CAPA 材料的完整来源版本与安全闭包。相关原来源撤回、epoch/版本变化、措施或完成/要求改变仍使锚失效。只排除后续合法 effectiveness/close 动作专属追加的来源与聚合身份变化；不能为求稳定删除全部 sources、readset 或 security。
2. **`CurrentAuthorizationClosure`**：每次核齐原 CAPA 来源及新增候选、规则、Review、Observation、有效性/关闭出处的完整 union、当前 ACL、原件门禁、安全/政策/issuer/专业事实与有效期。合法新增源虽不改变原材料锚，仍不可少读、少授权或忽略相关 ABA。新增源的分类只来自服务器核实的实际操作、固定 companion 与共同 proof/Receipt；客户端不能声明“这条源应排除”。

现 `capa_verification.service._basis_material` 仅排除聚合版身份，仍含 sources/readset/source_basis；`inspect_verification → inspect_candidate → recheck_followup_basis` 以及已保存 Link 的 `_link` 都会在合法有效性追加后自失效。因此不能只在新 wrapper 顶部换一个摘要就复用整条旧链。应由新窄 owner 重核接口复用其真实失败、Run、原值及来源检查，或由主线明确分配最小既有接口扩展；不能全局放松 Wave16 的固定基底守卫。必须用“真实 effective 追加 → 同一证据完整再核 → 另次 close”和“更改原完成/要求/来源或撤回新增证据 → 拒绝 close”对照验证；没有稳定合同就不能开放关闭。

共同具名批准协议也是冻结前置。Root 必须逐操作明确 effectiveness/close 的严格 payload、event、subject family、tier，真实已消费 T2 批准 UUID 到 `Invocation.decision_id` 的绑定，以及同一 Session/Transaction 的 consumed marker。不可借现三操作的 host allowlist、用 bool 充当 proof 或自行另发 Receipt。新增 IssueVersion/Current 与固定 Review/Observation/Candidate、实际批准和唯一 Receipt/Audit/Outbox 必须有精确 deferred 原子配对。预览中的新 NamedConclusion/History 服务器时钟使用 `server_on_save`，仅 apply 保存；原实际观察时钟保留，不能用 preview 的 now 改写发生时间或进入确认材料导致漂移。

## 7. 并行归属与依赖关口

| 独占包 | 建议文件归属 | 交付与依赖 |
|---|---|---|
| A：可信验证事实 | 新 `server/pdos_next/domain/capa_effectiveness_facts/**` + 同名 tests | 规则出版、观察事实、适用/独立 Review typed owner、scope/参与者/epoch；先交 DTO/ports，缺 bridge 明确失能。只读复用方法/Run/原值 owner，不另建请求/占用 |
| B：聚合决定适配 | 新 `server/pdos_next/domain/capa_effectiveness/**` + 同名 tests | 候选保存 adapter、旧 `QualityIssueHandler` 的 effectiveness/close、稳定 evidence 与 CAS/重放；先依 A typed ports，可并行实现未知路径与事务测试声明，成功依 A 完整真实 owner |
| C：办理页面 | 新 `web/src/components/quality/build-capa-effectiveness.tsx`、对应 lib/helper/tests | 单 Issue 固定候选、failure/pair 映射、事实与未知、独立人/T2 预览、有效/无效/另次关闭和恢复；不从 UI checkbox 造专业/观察事实 |
| Root：公共接线与验收 | 现 registry/professional/host hook/model import/API/BFF/迁移/lifecycle catalog/schema guards/集成工具/唯一清单 | 固定辅助 op/tier/receipt family、按真实 head 单调 DDL、同 UOW 与 deferred atom、统一候选及 PG/HTTP/浏览器/原出口；公共区只一人修改 |

正式施工合同冻结前先落实三项前置：①新的共享合法失败场景与独立人的实际读取/专业范围，旧私有系列保留阻断；②稳定 CAPA 语义锚、当前完整认证闭包及窄 owner 重核接口；③新 T2 的共同批准/追加与 companion 原子协议。三项未冻结时，本文继续为草稿；不自动扩大旧 ACL、修改旧候选或开放效果/关闭。

之后顺序：①主线确认范围、辅助动作及独立政策，A 冻 typed proofs/完整 rule 的可信出版入口，B 冻稳定锚与 owner 重核接口，Root 冻 T2 host/atom；②B/C 并行做候选与未知路径，Root统一最小模型/Receipt/Current 接线；③从合法共享新失败场景建立 CAPA，通过既有 owner 办真正的新请求/接收/Run，取得原报告、Review及实际观察，A 逐值核验；④先保存候选与独立 Review，再接 canonical effectiveness，最后单独接辅助 close；⑤冻结同一候选集中验证，不把旧波或不同 candidate 的通过数拼成全部验收。

真正不可推进的前置包括：独立人读取权、真实专业/政策与 rule 来源、要求变化、正式改版措施的实施 owner、完整新 Run/方法/原件、观察范围和全部参与者证明。这些只阻断依赖动作；候选草稿、缺项页面、纯规则适配与负向守卫仍可并行建设。若实际观察窗还未结束，保留已保存候选并明确待事实，不靠 clock mock 冒充真实经过，也不为了本波成功改 CAPA 截止时间。

## 8. 最小验收与仍保留的出口

1. 正向调查从真正 product 可读原始来源与另一个合法已发生的失败场景初建共享 Issue/CAPA，具名根因和全部本人完成、不同真实 Run/样件/完成/观察均可追溯；不重复旧 Failure、不改旧 visibility。真正新复验逻辑请求/Run 有 owner 回执，原失败历史和原报告字节不变。固定候选能够保存 planned/partial/unknown，不误授专业能力；旧私有调查和 peer 仅有 Grant 的情形必须保持独立决定阻断。
2. 新方法/实际配置/判据对每个原失败有精确当前适用依据；原报告原值、rule/version、完整 pair 和 projection 可重算。确定 fail/缺项/撤回/不适用不落入 effective。
3. 观察实际发生且可核完整范围；未来、仅日期、无源、未全覆盖或过期政策保持阻断。独立人是不同具名主体且不在完整参与者集合，缺读取权/资格拒绝，AI 所有 T2 零执行。
4. 真实隔离 DB 验证新候选/事实及聚合的 CAS、跨 key 单 Receipt、same-key 冲突、proof 一次、末端 Outbox 回滚、source/issuer/qualification ABA、private、late retained 与实际配置/usage 漂移；具名 proof UUID 与 companion/Issue/Current/Receipt 原子组精确配对。有效性/关闭专属合法新增源不改变原材料锚，全部新旧源仍核当前读取权；原源或新增证据撤回、原措施/完成/要求变化必须阻断。
5. effective 与 close 是两次不同命令；关闭前证据/政策变化拒绝且保留有效性历史；ineffective 保持 awaiting_verification。页面能恢复原请求，显示全部 missing 和相关历史，不把未完成的分支汇总成成功。亮暗/窄屏与 HTTP 整链按冻结候选统一检查。

对应 AT-23/25 的原失败去重与专业结论、AT-07/09/10 的实际配置和证据适用、AT-27/33 的时效/目标变化、AT-35 的人工维护保护、AT-36/38 的 T2 身份与当前撤权、AT-40 的同键冲突，以及 AT-42/46 的撤回保护/传播；黄金路径 D 的新配置/新 Run/适用独立验证仍须逐项满足，不能只以 Issue closed 标记全路径完成。

本波即便本地合成闭环通过，仍不授真实 CAPA/产品有效性、生产资格或人工 Exit；完整 G3 的八 facet 图、ChangeOrder/实施/生效/独立 Change 验证与关闭、G4 放行、G5 外部接收/生效及原 Sprint/Q0–Q6 人工出口保持原批准与验收边界。真实工厂观察或可信政策缺失只暂停相关正式成功路径，不把本文升级为已执行结论。

## 9. 稳定 v6 锚与有限后继的最小冻结补丁（待主线冻结）

本节把上面的关口具体到待冻结字段和 owner 责任。本次只修订草稿以保持 Wave16 冻结候选，技术依赖确定后按既有连续建设授权施工，不等待新增用户许可。当前私有演练的原完成 Issue v6 仅作为主线已观察的固定锚范例，不构成独立有效性正例。实际 anchor 必须由 owner 读取精确 `QualityIssueVersion.id/revision/snapshot_sha256`；新的共享失败场景按真实完成版建立锚，不硬编码成 v6，也不搬用私有 v6 的 UUID/来源。

拟定 `StableCapaAnchor`，保存到新的候选/Review companion 的不可变 JSONB；不覆盖旧 `FollowupBasis`、Link/Candidate 或另建 Issue Current：

| 字段组 | 必须固定的实际内容 |
|---|---|
| 身份 | `schema_version='capa-semantic-anchor-v1'`、`scope{tenant_id,product_id,project_id}`、`issue_id`、`origin_issue_version{id,revision,snapshot_sha256}`、`capa_id`、`purpose`、`owner_id`、`visibility`、完整 `audience`、`nature` |
| 原调查材料 | 原 Issue snapshot 中的 title/risk、精确全部 failures、aliases/merged_into、containment、root_cause、CAPA hypotheses/actions/每条本人 completion/requirement、needs_recheck/recheck_reasons；完整对象参与摘要，不只固定 ID 或数量。初始须 awaiting_verification、未归并、无 needs_recheck、有具名根因且全部措施完成 |
| 原失败证明 | 每个 `FailureRef` 全字段及稳定 identity；沿现 `ResultBridge` 读取真实 `FixedQualityResult` 的 run_version/revision、measurement_id、projection_id/revision、basis_sha256、rules_version/sha256、固定方法/判据/实际配置/sample/item 与原报告原值证明、retained effects。重核仍逐项等于原 FailureRef，不用 Run 的新 Current 替代原失败版 |
| 原源闭包 | `origin_sources`、去重 `origin_required_source_read_set`、`origin_source_basis` 及各摘要，来自原完成版与全部原失败 bridge 的完整 union，≤20，不截断。保留原 action/根因/遏制/完成/requirement 出处；不能只收 failure.source 一条或移除专业事实出处 |
| 摘要 | `material_sha256` 固定调查材料；`failure_proofs_sha256` 固定原失败事实证明；`origin_source_basis_sha256` 固定原源安全；`anchor_sha256` 固定上述完整结构。数组保留业务顺序，只有合同明确为集合的 refs/reads 作规范去重排序；不自行用 SQL JSONB 文本哈希冒充现 Python canonical digest |

原源安全闭包沿现 `quality_execution.evidence.source_basis`：Artifact 的 id/revision/content_hash/status/owner/visibility；native text 的真实 `evidence.artifact.register` Receipt 与 actor/requester/run provenance；uploaded original 的真实 bytes/hash 门禁、OriginalSecurity epoch/source_state/disposition，并保留原失败 bridge 已核的 original binding。发生过撤回、隔离/恢复、安全 epoch 或原材料改变均不得复用旧 anchor。当前调用者 ACL 每次独立核验，不能把 caller 的身份或剩余 Grant 时间写进客观材料摘要，也不能把作者历史身份借作调用者授权。

拟定 `IssueLineageProof{anchor_ref,current_ref,steps,material_sha256,origin_source_basis_sha256,current_authorization_closure,proof_sha256}`。从精确 Current 反向按 `previous_issue_version_id/previous_revision` 走到 origin，要求同 tenant/product/project/logical Issue、连续 +1、无缺行/分支/循环、owner/visibility/audience/purpose/nature 不变。每一步核其真实 operation、输入、writer、专业/政策/来源、共同批准、Receipt/Audit/Outbox 与准确历史追加；不得仅比较删掉 revision/history 后的 JSON。

最小 v1 后继白名单仅包括：

- `quality.capa.effectiveness.decide`：至多一次，前后均 awaiting_verification；只追加准确 `capa.effectiveness`、`capa.effectiveness_history` 一项及 history 一项。其余原材料逐字段相等，准许的新增 sources/reads/source_basis 必须由本次真实证据/具名批准出处分类证明。ineffective 仍待验证，不能自动新增措施或关闭。
- `quality.issue.close`：至多一次，必须紧随有效性 effective，且由原有效性决定者当前具名批准；只追加 closure/history、status 改 closed。必须沿同一证据再算原核 read_digest 与 policy ref 相等，不更改 effective 结论或原观察时钟。

所以原 v6 范例的合法最小链只能是 v6 → effectiveness v7 → close v8；新的共享场景是 origin → origin+1 → origin+2。重复决定、recheck、merge、triage、containment、重定根因/措施/完成/要求或未知 operation 不在本期排除白名单，返回 RECHECK_REQUIRED，等待单独修订合同；不是删除历史。Link、候选、观察和 Review 是旁路 companion，不自行推进 Issue Current。该有限白名单本身须主线冻结，不能推断原核的更多操作均可安全沿用。

`CurrentAuthorizationClosure` 单独固定本次真实全部来源 union 与政策、issuer/专业 refs/epochs、当前原件安全，保留 originals + candidate/rule/Review/Observation + 已允许有效性/关闭追加 sources。≤20 超限明确失败。新专属来源不进入原材料锚不意味着不读；其撤回/ABA、受众变窄或权限失效仍阻断。所有 owner/bytes IO 后取 fresh closure 与谱系再比较，失败不返回 current=true，也不跨 inputs/preview/execute 复用正面判断。

旧 Link/Candidate 的新波读取采用新窄 `inspect_saved_followup`：先核真实旧 row/ref/保存摘要/原共同回执，重核其原 anchor 与有限 Current 谱系，再核保存的全部来源、输出及原签发者证明。旧 Draft 输出仍 planned/historical，不能升为 performed 或自动满足 mapping；新的真实结果要另存晚回链与固定候选。已成功同意图重放在这些当前门禁通过后返回原 Receipt，不新增版本或 consume；新写仍 CAS 当前 Issue。旧行/旧公共重放协议不全局改动，现 `_basis_material` 与 `_link` 不作通用放松；窄适配能证明的边界以外保持 missing/RECHECK_REQUIRED。

既有 `followup.link` 命令的 validate 目前仍走宽基底链，不能宣称新增只读接口就已使旧命令重放兼容。若要求其在两个合法追加之后继续返回旧 Receipt，Root 必须明确冻结该 handler 的窄 replay 适配：先用保存的 exact anchor/output 与新 owner proof 重核，沿原共同 semantic/key 回执返回；正常新写仍走当前版 CAS。未接此适配时旧命令可保守返回 RECHECK_REQUIRED，历史记录仍显示，不用过期 token 新消费来恢复。

## 10. paired Formal 与晚回链的真实 owner 证明

定向源码事实：`VerificationRunVersion.request_version_id/request_revision` 明确固定 originating Formal 版，后续 Run 仍保留它；Formal Current 通过 `FormalVerificationCurrent.request_version_id/request_revision` 独立推进。`VerificationLaunchFact` 保存 request_before、next_request 与准确 run ref；`TestResultActionFact` 保存 request_before、next_request、run_before、next_run 与 projection。现 domain `_intent` 与 common `Receipt.intent_digest` 的材料结构不同，不能将二者直接判相等来配对。

Root 拟提供只读 `read_paired_formal_output(s,ctx,product_id,output_ref,*,at,write=False)->PairedFormalProof`，专门扩展 Wave16 direct owner 的缺口；不是新建请求/回执的入口。proof 至少含 scope/build/purpose/owner/visibility、精确 Formal ref+snapshot hash、logical request_id、实际 pair 的 Run ref/hash、fact ref/type、真实 Receipt ref、来源/retained 摘要、full reads、current pointer refs、`meaning` 与 missing：

1. 精确读取输出的不可变 Formal 行及当前读 ACL/source；按相同 tenant/product/project/request/build 用 exact next_request ref 找真正 LaunchFact 或 ResultAction，不用任意同项目 Run 或字符串 intent 找配对。严格校验输入/输出前版链接和 scope，不收客户端 fact/receipt UUID 作为可信证明。
2. Launch 路线只接已实装的 Plan/Promise/Start：fact 的 request_version/revision、next_request_version/revision、run_version/revision 对应真实行；Promise 可不推进 Run，Plan 可不推进 Formal，不能强制每步两边都 +1。按实际 operation 返回 planned 或实际 Start 事实，不能以存在 LaunchFact 就称已执行。
3. Result 路线校验 `TestResultActionFact.next_request_version_id/next_request_revision` 与目标 Formal；run_before 与 `next_run_version_id/next_run_revision`、projection 与原值/结果按实际 import/review/disposition owner 规则准确匹配。动作允许 Formal 不变时仍须 exact 同一行，不制造一版配对。实际 Run 路线仍调用 retained 与原报告逐值核验，不因窗口自然结束新占用或新消费。
4. 共同 Receipt 的 tenant/product、operation、subject_type、subject_id/revision、result.id/revision、actor/requester/visibility 和真实 writer/provenance 精确匹配。Start/Result 的主体是相应 `test_run` 不可变版；Promise 主体是实际 `verification_request`，不能一律把 Receipt 主体猜成 Formal。系列 owner 与本次 writer 可以不同：actor/requester 按真实具名 action/fact 与 target.writer 核，不照搬 direct 输出中 `Receipt.requester_id==row.owner_id` 的简化前提；原 owner 的 private 读取限制仍保留。通过相同真实 target+operation+actor 与保存输入/事件配对，再核相关 Audit/Outbox；领域 intent 仅比较 domain fact 与其领域版本，不与 common intent 假定同格式。
5. 当前候选必须分别按精确 Current join 核 Formal 与 Run；origin request ref 仅是历史起点。Run professional review/disposition 没有推进 Formal 时，proof 保留两个真实 Current，不为方便令二者版本相同。capabilities/meaning 来自 owner 实际事实，绝不根据 request Draft 曾被保存推导。

本期最短路径：实际复验完成并获得规则要求的 review/disposition → 严格读取真正新 Current Formal/Run → `quality.capa.followup.link` 再保存真实晚回链 → 候选固定该晚回链和 performed Run 的 sample/item/measurement/projection。原 Draft Link 一直是可读 planned 历史，不回写、不用它替代新 ref。

若新回链接口需要证明 output 是旧 Draft 的合法后继，只能由 owner 返回同 logical request/run 的线性 predecessor 链及每步上述真实 pair/Receipt；保持 Build、准备来源、实际已接收 sample/item/config/method、执行计划与原值不可变规则。不允许全局“同 logical ID 即相等”、跳过 intermediate fact、拿 Run.request_version_id 当 Current 或由 wrapper 拼虚构 Receipt。缺 paired bridge 或遇未知 transition 返回 INTEGRATION_REQUIRED/RECHECK_REQUIRED。已有直接 canonical Formal 读取继续使用原门槛，不退回旧 Draft 冒充可选 Current。

## 11. 两项 T2 与数据库兼容点（只列待实现约束）

现 `QualityIssueVersion` 的 operation CHECK 不含有效性/关闭，status CHECK 不含 closed；next_0024 的 `assert_quality_followup_proof`、confirmation protection/consumption atom、`require_quality_followup_atom` 也只接旧三操作，且 Issue atom 前态限定 actioning。因此不能只加 registry 就复用成功；Root 需从实施时真实 head 单调新增迁移并同步 metadata，不修改已应用迁移或给 pdos_agent 业务写权限。

| 兼容点 | 新波必须冻结的最小约束 |
|---|---|
| 两个具名证明 | `quality.capa.effectiveness.decide` 和 `quality.issue.close` 各消费一个不同真实 T2 UUID；两者通过 sameSession consumed callback 返回 UUID，传给 `Invocation.decision_id`。`source_basis.shared_proof={id,tier:'T2'}` 固定实际证明，不保存 token，不允许 bool/客户端 ID 替代 |
| 共同 Confirmation 身份 | 仍是 `confirmations.subject_id=product_id`、revision 为确认时 Product 水位；同时 snapshot 精确绑定 before/after logical Issue+固定版、anchor、candidate/Review/Observation refs、当前 authority/policy/source/readset 与 operation。不要把 subject_id 改猜成 Issue。当前写入要求本人 human、无 AI run、精确专业用途与未过期证明，Current CAS 在新写分支；预览禁止消费 |
| proof 反向原子配对 | 仿已应用24的 reciprocal deferred false→true guard，扩充准确新 operation/目标 union；一个实际消费对应一个新 IssueVersion，所有被引用 companion 是固定 refs 而非第二个同 proof target。每个 target 又必须有该次消费及唯一合法 Receipt/Audit/Outbox。旧已 consumed proof不能复用；末端失败连新 Current/proof 消费一起回滚。允许真实 SAVEPOINT，不以 xmin/top xid 猜同事务 |
| authority 与历史 | writer 是本次专业批准人，不是系列 owner；authority.subject_id==writer_id、op/purpose/scope/qualified/角色与保存时间准确绑定，Current owner/visibility保持。历史 proof provenance 按当时保存时间、Product 水位、已保存 material 和原子组核对；不能用当前 Product revision/当前 now 把旧 proof重新当新消费，也不能因此跳过当前调用者、源、issuer/专业撤回检查 |
| Issue 精确变化 | 仅 §9 两项有限后继字段白名单；history/effectiveness_history 必须原 prefix+准确一项，无少项、替换或额外项。effectiveness/closure 的 actor、text、evidence IDs、policy/read_digest/时钟与输入和核出的 companion 完全相符；NEW Current 在事务末端必须指 exact 新行。原材料锚逐字段保持，非白名单转移明确拒绝 |
| 审核材料与时钟 | 新 NamedConclusion、EffectivenessDecision/history 的服务器 at 只在 apply；preview 用冻结的 `server_on_save` 归一法，并校验 consumed snapshot before/after、authority/policy/source/readset 完全一致。原测量/完成/observed_from/until 原发生钟不归一成 null；不能扩大归一字段抹掉事实差异 |
| SQL 空值与 JSON | 所有 required JSON keys 用 `COALESCE(...,false)` 与必要 jsonb_typeof，缺 key/缺 SELECT 行明确失败；比较身份用 `ROW(...) IS DISTINCT FROM ROW(...)`。JSONB `@>` 两操作数都括号，不能重复0019优先级错误。result.revision 核真实 JSON number（如 `=to_jsonb(real_revision)`），不要宽松接受数字字符串。数据库结构配对不替代 Python canonical digest/实际 runtime/bytes 门禁 |
| 回执/键 | Receipt 主体为新不可变 IssueVersion UUID+聚合 revision，family `quality_issue`；严格 operation/actor/requester/visibility/result/Event schema+correlation_id+Audit+Outbox。初始新写一个 RequestKey，后来合法跨 key replay只追加键指向同 Receipt；历史检查不能把“当前 RequestKey 必须永远仅1个”当 provenance条件，也不能追加第二 Receipt |
| 降级与失能 | 缺 rule/paired owner/consumed proof/append callback 即503，不以 false替完整证据。既有数据涉及新 op/closed/companion 时 downgrade 不得直接恢复排斥它们的旧 CHECK、删事实、回退 Current 或留 consumed孤儿；必须明确保守拒绝并保留恢复条件，不假报完整可逆。无业务数据情况下的往返另由Root验收 |

旧纯核确认端口 `quality_execution.TransactionCommands.confirm` 也不是新 T2 接口。新 B adapter 必须只接受宿主实际 consumed marker/UUID，并按冻结 op allowlist接纯核 confirm/Invocation；不得传 accepted=true 绕过公共证明。effectiveness 使用 `capa.effectiveness_decided`，close 使用 `issue.closed`，都不是 T1 或 AI 执行资格。

## 12. 精确文件归属、最小 callbacks 与收口顺序

以下只是下一实施合同的建议归属，当前没有分配源码施工：

| 归属 | 明确文件范围与公共依赖 |
|---|---|
| A | 新 `domain/capa_effectiveness_facts/{schemas,models,ports,service,rules}.py`、同名 tests：可信 rule/Observation/具名 Review；导出 `load_verification_evidence` 和 `refresh_evidence`，不改旧 Issue/Run/原报告/资源使用；真实 source/participant/适用 bridge 缺失保持 missing |
| B | 新 `domain/capa_effectiveness/{schemas,models,anchor,lineage,adapters,service}.py`、同名 tests：StableCapaAnchor/窄 `recheck_capa_semantics`/`inspect_saved_followup`、候选 companion、旧纯核 effectiveness/close adapter；原失败沿现真实 ResultBridge，旧 `_basis_material/_link` 保持。anchor/lineage代码不另创建 Current真值，不自己 commit/Receipt/资格 |
| C | 新 `components/quality/build-capa-effectiveness.tsx`、`lib/build-capa-effectiveness-view.ts`、其 helpers/tests：共享新失败场景入口、真实当前/历史/晚回链/缺项、两次具名预览；不造 rule、pair、observer、参与者或专业 pass，不改旧调查受众 |
| Root | 公共 registry/专业矩阵/common proof/metadata/API/BFF/迁移/lifecycle/SQL atom/统一验证；明确追加白名单和窄 owner proof。建议新宿主 `capa_effectiveness_host.py`、`capa_effectiveness_integration.py` 与新 `verification_output_proofs.py` 承担 callbacks；若要旧Link命令重放兼容，明确占有 `domain/capa_verification/commands.py` 的窄 replay 接线和公共 owner候选适配，保留原语义/key。任何必要旧文件最小扩展须另明示归属并做受影响验证，不由A/B/C暗改 |

最小宿主 callback 协议（名称待主线冻结；所有参数为同一 Session，无新连接/commit/Receipt）：

```text
read_paired_formal_output(s,ctx,product_id,OutputRef,*,at,write=False) -> PairedFormalProof
require_consumed_proof(s,ctx,command,payload,*,tier='T2') -> UUID
append_issue(s,ctx,product,before_row,kernel_mutation,*,operation,authority,policy_snapshot,
             required_source_read_set,source_basis,input_snapshot,intent_digest,
             expected_issue_revision) -> QualityIssueVersion
```

前两项分别负责真实 owner pair 与实际同事务证明，append 只接已冻结两个新 T2 的单 Issue追加。B 的 anchor/lineage 读取可复用现 `_row/_snapshot`、精确 Current 和真实 ResultBridge/source checker，不另要一个可修改 Issue 的端口；新增 companion 的 source checker 必须由相应真实 owner 暴露。A 的 `load_verification_evidence/refresh_evidence` 不得返回假完整 VerificationEvidence。全部callback必须启动配置绑定，未配置不启用决定/关闭；公开 GET仍可返回固定历史+缺项。

依赖最短序列：①主线冻结共享合法新失败场景、anchor字段/有限谱系、paired output 与三个宿主协议；②A/B/C按DTO并行做未知/反例路径，Root先完成两个T2+companion guards而不启用positive；③从既有owner办理新场景及真正新复验，实际结束后新Current晚回链、保存部分候选；④有真实适用/独立/观察事实后具名Review，按原核核值，再有效性；⑤同anchor与同证据再次fresh重核后另次关闭。最小回归须同时覆盖旧private拒绝、旧Draft仍历史、paired缺fact/错scope/错Receipt拒绝、合法晚回链、effect追加不自失效、相关源/专业ABA拒关闭、两proof分离/反向原子/SAVEPOINT/回滚及跨key单Receipt。

本补丁仍为草稿；没有操作注册、DDL应用、公共 callback启用、实际独立观察或有效性/关闭验收结论。backend480及当前Wave16候选保持冻结。
