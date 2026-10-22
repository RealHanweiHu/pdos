# Wave17 事实持久化接线审查

本报告是实施前的只读方案。依据 facts v2、稳定锚/有限谱系及 Wave17 冻结草稿，未修改暂存或公共源码，未执行数据库、HTTP、测试或迁移。表名为实施建议，不预留迁移号，不注册操作，不授予 issuer、专业资格或独立读取权限；当前公共后端 v4 只作源码参照。

结论：新增 **Rule Fact/Current、Observation Fact/Current、不可变 NamedReview 共五张表**足以承载本段事实。沿用现有 `CapaVerificationEvidence` 候选和 `QualityIssueVersion/QualityIssueCurrent` 聚合链；事实指针只表示各事实系列的最新出版版本，不是第二份 CAPA/Issue 状态。尚须主线冻结持久 provenance codec、实际消费时钟和新 target 的共同原子守卫，才可接实际写入。

## 1. 可直接复用与实际缺口

| 现有资产 | 复用方式与限制 |
|---|---|
| `staging/wave17/facts.py` 的 Rule/Observation/NamedReview、FactOperations、FactAtom、FactReader | 固定完整 typed 材料、真实人/时钟、七类 owner gate、活动 Session/主子事务和末端刷新协议。纯结构通过不产生事实或 VerificationEvidence。 |
| `anchor.py` 的 StableCapaAnchor/SourceSafety、`lineage.py` 的有限后继核验 | 原完成版 Issue、完整 history、原失败精确证明及来源保持；只允许一次 effectiveness 后接一次 close。原失败不能替换为 Run Current，原锚不能删 history/source 后宽泛比较。 |
| `capa_verification.models.CapaVerificationEvidence` | 复用固定候选行、mapping/inspection/hash、精确 Issue 版与晚回链。保留 `candidate/indeterminate` 和三个 NULL；具名 Review 另存，不 UPDATE 候选字段为通过。当前迁移只授 app SELECT，且无可用候选保存命令；新增写入口/权限/原子组须主线显式接线。 |
| `RemediationLinkRecord`、原 owner paired facts | 读取真正新复验的固定输出、原报告/Measurement/Projection 和实际配对回执。旧 planned Draft Link 仍是历史，不能据其存在判断措施履行或补造实际新 Run。 |
| `QualityIssueVersion/QualityIssueCurrent`、`QualityEventFailureLink` | 复用唯一 Issue 版本链、当前 CAS 和固定原失败来源。原 event link 保存 exact RunVersion/Measurement/Projection；合并后的 FailureMap 不能代替原失败锚。只有以后 effectiveness/close 两个聚合决定推进该 Current。 |
| `QualityPolicyFact/Current`、`quality_policy_import.import_quality_policy_fact` | 复用 opaque issuer、来源/epoch、host-only import、同事务 Receipt/RequestKey 的模式。风险/独立政策不能冒充方法、采样及接受规则；现 policy 模型还明确 synthetic-only。Rule 需自己的 typed 出版材料和可信 issuer 配置。 |
| common Receipt/RequestKey/Audit/Outbox/Confirmation、`quality_followup_host` | 复用一次共同消费和回执组、同 key 冲突/跨 key alias、实际 Session/SAVEPOINT marker。现 host/SQL allowlist 只含根因、完成、Link 三项，不能直接接新 Observation/Review；纯核的 `Invocation.decision_id` 是领域参数，不能挪用 `models.Invocation` 的 AI 调用表。 |

## 2. 最少新增表及固定列

五表均由服务器从原锚/真实 owner 派生 scope、owner、visibility、purpose、nature；public payload 不接收这些字段作为授权。每张事实表保存不可变 typed body 及完整来源；Current 仅允许受控连续换版，不回写旧事实。

| 建议表 | 必需列/JSON 材料 | 指针及历史语义 |
|---|---|---|
| `capa_verification_rule_facts` | Row `id/tenant_id/created_at`；`product_id/project_id/issue_id/capa_id/origin_issue_version_id/origin_issue_revision/purpose/owner_id/writer_id/visibility/nature`；`series_id/revision/previous_fact_id/previous_revision`；`anchor_snapshot/anchor_sha256/requirement_sha256`；`issuer_key/version/epoch/external_id`；固定 `valid_from/valid_until`；完整 Rule body：policy ref/hash、所有 FailureRef/ActionBinding、方法/判据、targets、sampling/window/minimum_records、rule/independence material；来源及共同原子字段见下文。 | 出版事实不可变。若需主动撤回，用同系列新的不可变 publication envelope 与 Current 推进；其 `publication_state` 是真实 owner 元数据，不能给冻结 RuleVersion 添客户端 `current/applicable` 字段。撤回入口/分级须另冻，未接时只能由现来源/issuer 失效保守阻断。 |
| `capa_current_verification_rules` | 固定 scope/issue/capa/purpose/anchor/series/issuer identity；`fact_id/fact_revision/epoch`；固定首创时钟。 | 一系列一个指针；首版 v1，无前版；后版 +1、前版精确等于旧指针、epoch 单调，owner/受众/锚/用途不能换绑。Current 指向 withdrawn 或有效期外的事实须返回失效，历史 Rule 可读不等于当前可用。 |
| `capa_observation_facts` | 同上基础列及独立 `series_id/revision/previous_*`；精确 `rule_fact_id/rule_revision/rule_sha256`；issuer；`executor_id`；实际 `observed_from/observed_until/EventTime`；完整 targets、records、missing_fields、coverage_sources、sampling_material；原件/来源安全闭包；T1 原子字段。 | partial/缺项原记录可以保存，不能填 `observation_complete=true`。同系列不得改 Rule、targets/实际配置、executor、purpose 或受众；另一次观察范围/不同 Rule 用新的系列。修改/撤回的实际入口须明确，不自动暴露任意重写 API。 |
| `capa_current_observations` | 固定 scope/issue/capa/anchor/Rule/观察 series；`fact_id/fact_revision/epoch`；固定首创时钟。 | 每个独立观察系列一个 Current，多个实际观察系列可共存。不能设一个“CAPA 最新观察”覆盖其他范围。后继连续、原记录保留；选择的旧观察在其系列被替换/撤回后必须标明历史/需重核。 |
| `capa_named_verification_reviews` | 同基础 scope/原锚/完整来源；精确 candidate 行/hash、Rule 行/rev/hash、**有序完整** Observation refs；`reviewer_id/EventTime/valid_until`；逐 failure-pair 的方法/判据/actual-config applicability、逐 action/completion 的 fulfillment 与 owner material、完整 participants/实际角色依据；保存时 authority/policy；T2 原子字段。 | 每次具名复核为新的不可变记录，首版 rev1、previous NULL；无需 Review Current。后续决定选择精确 Review ref；并存或冲突由真实 owner/政策处理，不能拿 max(created_at) 自动选通过。unknown/not_applicable 保留原结论，来源/签发者/Rule/Observation 后变可令当前可用性失效，不能改历史。若将来需 Review 系列或撤回，另冻合同。 |

`origin_issue_version_id/revision` 是建立 StableCapaAnchor 的精确原完成版，不随两次允许聚合后继滚动。`anchor_snapshot` 可重复保存在 Rule/Observation/Review 作为各自不可变输入，不新增可修改的 Anchor Current。其完整原 proof 摘要与稳定失败材料摘要分别保留；只有既定三个完整路径可排除当次评估值：`result.retained.checked_at`、`result.retained.execution_window_elapsed`、`result.source_basis.runtime_stamp`。原 Start/计划/占用/usage、原件安全、相关 issuer epochs 不排除。

事实公用持久列建议为：

```text
operation, tier, command_id, actor_id, requester_id
payload_sha256, intent_digest
sources, required_source_read_set, source_basis
input_snapshot, authority_snapshot, policy_snapshot
shared_proof_id(nullable), shared_proof_tier(nullable), proof_consumed_at(nullable)
token_sha256(nullable), material_sha256(nullable), read_set_sha256
transaction_proof_id, transaction_proof_sha256
```

这些列是查询/约束所需的真实持久出处，不是 public 自填参数。host_import 没有伪造 Confirmation；Observation 用 T1；Review 用 T2 且实际 proof UUID 必须等于传入旧核的 `Invocation.decision_id`。不保存原 token，不在 JSON 中保留 `approval_token/confirmation_token`。

## 3. 精确唯一约束及 FK

令 `S=(tenant_id,product_id,project_id,issue_id,capa_id)`，`O=(tenant_id,product_id,project_id,issue_id)`。JSONB 中这些字段、row `id/revision`、来源和 published body 必须与列一致，NULL 不得让 CHECK 以未知值绕过；Root 实施时沿既有 `COALESCE(...,false)`、严格类型和已修正的 JSON 箭头/算术括号。

- 所有事实版本有 `UNIQUE(S,id,revision)`，另 `UNIQUE(tenant_id,product_id,id)`；Rule/Observation 有 `UNIQUE(S,series_id,revision)` 及供 Current FK 使用的 `UNIQUE(S,series_id,id,revision)`。原完成版 FK 为 `(O,origin_issue_version_id,origin_issue_revision) → quality_issue_versions(O,id,revision)`。服务器核其 CAPA id、purpose、anchor 与完整 issue_snapshot 对应，不能只存在一个 Issue UUID 就通过。
- Rule/Observation 前版 FK 带 `S,series_id`；首版 `series_id=id/revision=1/previous=NULL`，其后 `revision=previous_revision+1`、不同 row id。Current 有 `UNIQUE(S,series_id)`，精确 `S,series_id,fact_id,fact_revision` FK；固定锚/Rule/purpose/owner/受众不可换绑。各 Current 的新指针须在同 UOW 有对应新事实和共同回执，而非裸 UPDATE。
- Rule host external series 的重试键由真实 issuer 和固定 scope 决定：`S,purpose,anchor_sha256,issuer_key,issuer_version,external_id` 对应唯一 `series_id`，可用 RuleCurrent 的 UNIQUE 实现，勿另造 issuer/series 身份表。issuer epoch 更新不创建同名双指针；旧 ref、epoch 和原出版回执仍保留。
- Observation 的 Rule FK 带 `S` 和 exact row/revision；规则完整 SHA 在 JSON及owner核验。观察系列的 Rule/targets/executor 不能换绑。各物理 target 的 sample/lot/actual-config 只由实际 owner 解引用；若暂存任意 population 尚无 owner/原始身份，保存未知和明确缺口，不以字符串或 hash 编造集合。
- Review 的 candidate FK 复用 `capa_verification_evidence(S,id)`（旧 candidate rev 固定1），Rule FK 用 `S,id,revision`。其 Observation refs 数组必须非空、无重复，每项完整 scope/rule/row/rev/hash；最小方案用 deferred 原子校验逐项核真实父行，不必额外建映射真值表。所有 Rule/Review 的全 FailureRef 和 ActionBinding 仍由真实锚核对；target physical scope 由 owner 核，不以客户端数组长度作权威。
- owner/writer/executor/reviewer 的 Principal FK 带 tenant；写入要求本人 human 和当前合法专业角色/用途，`ProductGrant.can_write` 不授品质资格。Review.authority 的 subject==reviewer/writer，private 原锚保持 owner-only；为独立复核提供 peer Grant 不能放宽既有 private Issue。
- Observation/Review 设置实际 proof 唯一约束（例如 `UNIQUE(tenant_id,shared_proof_id)` 的非 NULL 部分），并绑定 `(tenant_id,shared_proof_id) → confirmations(tenant_id,id)`；后者若尚无复合 unique，由 Root 同步父约束。还要跨所有旧新 target 的反向唯一消费守卫；仅本表 UNIQUE 不能阻止一个 proof 同时写另一个表。
- semantic 去重沿 common Receipt 的 `tenant/product/intent_digest` 和 RequestKey 的 `tenant/actor/key`；事实表可再唯一 `tenant/product/writer_id/intent_digest`。same-key 异体拒绝；same-intent 新 key 必须先重核当前安全门禁后 alias 原回执，不重复事实、不回退 Current、不再次 consume。完整 subject_type/version id/revision 必须匹配，不能只凭 logical Issue id 查到任意 Receipt。

## 4. 两个须先冻结的 provenance 接口

### 4.1 完整事实摘要生成时间

`facts.fact_payload_sha256` 排除 provenance 和自身 ref.sha；`fact_sha256` 则包含完整真实 FactAtom，包括 Receipt/Audit/Outbox UUID。当前 common `append_receipt` 在 handler.apply 之后才分配 Receipt id，Audit/Outbox 也随后建立。因此 **apply 内不能组装合法完整 FactBase 并随意生成“将来的回执”，也不能在回执创建后 UPDATE immutable fact**。

推荐最少改动方案：持久记录采用另冻的严格 `fact_body` codec（完整 FactBase 材料减去 provenance/ref.sha），保存 `payload_sha256` 和实际 shared proof 列；common 创建唯一回执组。实际 owner 读取已提交的事实＋准确 Receipt/Audit/Outbox＋proof，才组装 FactAtom、计算完整 FactRef.sha256 并通过冻结 FactBase 校验。所有 child payload 内的完整 FactRefs 仍固定该真实全摘要；SQL FK 绑定 scope/id/rev，完整 SHA 由 owner 精确复核。不得把 payload hash 当 full fact hash，也不得对缺出处的 body 强行调用 FactBase.model_validate 或填占位 UUID。

若 Root 要求数据库直接存完整 FactBase JSON，则须另冻 common 原子组 ID 预分配接口：由同一共同 writer 预分配并最终使用实际 Receipt/Audit/Outbox ids，apply 只接可信包。两方案选一；不新增私人 Receipt/commit，不由纯 DTO 自证同 UOW。本文推荐 body＋真实原子组 reader，五张表不因此增加另一套审批账。

### 4.2 真实消费钟及 transaction proof

现 Confirmation 只有 `consumed:bool`、created_at 和 expires_at，**没有 consumed_at**。现 consumed hook 证明本次 false→true、真实 Session/主或 SAVEPOINT、token/material/readset，但没有可直接持久恢复的消费时钟。冻结 FactAtom 对 T1/T2 要求实际 consumed_at，不能由历史 bool、Receipt.created_at 或 reader.now 反推。

最小可行接线是 Root 扩窄 live marker：紧随本次实际 false→true、在任何 SQL/autoflush 之前记录真实消费事件的服务器时钟，返回同 Session 绑定的可信 provenance；把这个值作为 `proof_consumed_at` 与事实一起保存，历史 reader 不重采钟。事实 deferred guard 核其对应 proof、真实消费/目标组以及 `created_at ≤ proof_consumed_at ≤ fact.created_at < expires_at`。如 Root 选择在 Confirmation 加持久消费钟，必须同步准确 transition guard，不能直接添字段让旧“只变 consumed”守卫失配。

`transaction_proof_id/sha256` 也必须由真实宿主协议冻结：T1/T2 可将实际 Confirmation UUID 作为同一批准原子组的身份，摘要覆盖实际消费记录、目标及共同回执组；host_import 可用实际 internal publication Receipt 身份与真实 UOW 出版证明。必须由 owner 读实际账验证，不是输入一个任意 UUID/hash。只有持久 reciprocal guard 和本次真实 marker 同时成立，才提供事实读协议；不把 DB transaction xid/xmin 当 SAVEPOINT 同事务证明。

## 5. 写入原子组与新旧守卫

| 路径 | 唯一原子组与办理边界 |
|---|---|
| Rule host_import | 可信服务器 importer＋opaque issuer＋当前具名 scope/source 核对 → 新 Rule/Current → common Receipt/Audit/Outbox/RequestKey，同 Session 无独立 commit。复用 policy_import 包装模式，不公开 self-grant。重放检查当前 issuer/来源后回原事实；历史重放不倒退指针。 |
| Observation T1 | 标准 validate/semantic/preview/apply；读真实 targets/原件/观察事实，全部 IO 后 fresh closure；common 消费一次 T1，紧接真实 marker → 新 Observation/Current →共同回执组。不得第二次确认或借 Review T2 代 Observation T1。 |
| NamedReview T2 | 核精确 candidate/Rule/Observation、原失败和真实新 paired output、全参与者及措施履行、当前专业/政策；common 一次本人 T2及实际 UUID → 不可变 Review →共同回执组。无 positive 时可保存 unknown/not_applicable，但不能宣称独立性/完整观察已核或变更候选 NULL。 |

Root 新单调迁移须把准确新 operation/tier/target 加入 actual consume marker 和 SQL 双向 target union。现 `assert_quality_followup_proof`、confirmation transition/consumption、Issue/Link 原子函数仅三操作；只加 PAYLOADS/EVENTS 不能完成接线。每次消费恰一新 target，各 target 又恰一实际消费/Receipt/Audit/Outbox；Review 引用的旧 Rule/Observation/Candidate 不是该 proof 的第二 target。初次 RequestKey 配对与后续 alias 区分，历史回读不能要求永远仅一个 alias。

旧 merge、根因、本人完成、Link 的守卫不替换成宽松通用守卫。新增 Current 首版/前版/连续 revision/epoch、immutable facts、scope/owner、强制 RLS、app 窄权限及 `pdos_agent` 零直写由 Root 加固。五表和 candidate 都保留全部来源引用及 `lifecycle_reference` 覆盖；所有 Current UPDATE 使用原有 Product→事实指针锁序，immutable facts 不为 FOR UPDATE 增 UPDATE 权限。任一新保留事实/消费/proof 回执存在时，downgrade 不得删除原账、回退 Current 或恢复排斥新事实的旧 CHECK，需保守拒绝并说明恢复条件。

effectiveness 与 close 以后仍分别是两个 T2、不同 command/proof/Receipt；这五表与 candidate 的保存不推进 Issue、不启动复验、不新增资源预约/样件消耗、不授 effective/closed。

## 6. 真实读、当前/历史与来源闭包

完整 row/ref/body 的历史读取与当前授权分开：历史结论/原时钟不改；返回明确 `is_current/current_evaluation/reasons`。缺当前评估时显示未评估，不以 false 冒充已核不适用。Rule/Observation 必须核实际 Current；Review 固定旧 refs，依赖被替换/撤回、原 reviewer 相关资格/issuer ABA、来源受众或安全变化时当前证据失效，旧记录仍按权限可读。

新源 owner 不能直接交现 `quality_execution.evidence.check_source`：该入口明确只接受 artifact。须增加窄 domain dispatch，按已冻的 source kind/position 解真实 Rule/Observation/Review/Candidate 版本＋完整 digest/共同原子组＋来源/签发者；缺对应 owner 明确 INTEGRATION_REQUIRED，不因 SourceRef 存在就通过。domain refs 不放进只含 Artifact 的 SourceRead 集冒充原文；递归读齐其全部 Artifact 原文闭包，精确合并不截断，≤20 超限失败。

原文来源沿两类既有 basis：合法 native 不可变文本须有实际 artifact.register 回执/provenance/hash/当前 ACL；uploaded original 须完整 bytes/hash/size/security epoch/parse/current 门禁。native 可承载观察/分类/方法出处，但不替代测量仪器原报告；后者继续真实 measurement verifier/result bridge。原锚全部来源及合法新增 source 均进入 CurrentAuthorizationClosure，即使新增 source 不进入旧稳定锚摘要，也不可省读/省权限或绕过撤回。

真实 facts owner 应实现七 gate：registry、sources、participants、applicability、observation、provenance、authority。每阶段由同 Session 读取固定 Rule/Observation/Review 和实际 owner；全部 bytes/participant/applicability/paired owner IO 后重新读完整闭包及同 UOW，最后取真实 clock 核期限。后一个 IO 撤销前一个 issuer/source/owner 的情形必须阻断。actor/Grant 剩余时效不混进稳定客观材料 hash，但当前 human/ACL/专业/完整相关 epoch 和未来激活边界仍独立核对；不跨 inputs/preview/apply/replay 缓存肯定结果。

## 7. 主线可并行接线及最小实际验收

1. A 新事实 owner：按上述五表/body codec 实现 host-import 与 Observation/Review 标准 handler，固定 FactReader/来源 dispatch/实际参与者及履行接口；缺端口可返回明确 missing，不装配完整 VerificationEvidence。
2. B 现 anchor/lineage/paired owner：接真实 origin/current 窄读、有限两后继、晚回链、完整原/新 Run paired proof；不新增 Issue Current，不放宽旧 Draft，也不改原失败版。
3. Root 公共接线：冻结 FactOperations、body/fullSHA 与消费 clock/group identity；模型/FK/registry/专业矩阵/common hook/deferred atom/lifecycle/RLS、candidate 写权限与入口、API；只主线迁移及真实数据库验收，不预分配迁移号。
4. C 只读/表单：只信逐 scope 的 capability、精确 Current/ref/readset；unknown、历史、缺端口显式显示。Observation 保原事件钟，Review preview 的新服务器保存钟使用既定 server_on_save；原观察钟不归一化。

下一候选至少实际验证：Rule 同 key/跨 key/换版撤回与 issuer ABA；观察真实范围/partial/未知、实际来源及时区/接收钟、同系列禁止换 Rule/target；Review 全失败与措施映射、不同实际新 Run、本人/完整参与者/独立性/private/专业撤销；新 proof 错 tier/UUID、历史 consumed 重用、跨 target 双用、SAVEPOINT、末端 Outbox 故障全组回滚；历史行/Current 不倒退、全部 owner IO 后撤销与 expiry；candidate 三 NULL 保持；以后 effect→close 新来源不自失效且相关新旧来源漂移仍拒关闭。本文未执行这些验证，不以暂存88项纯结构测试冒充持久闭环。

## 8. 只读源码依据与冻结范围

关键位置（行号为本次读取版本）：

- `staging/wave17/facts.py:49/98/156/231/273/345/376/384/805/846/887/962`：操作注入、真实原子结构、三 typed 事实、两类摘要、七 gate、活动 UOW/末端刷新。
- `staging/wave17/anchor.py:134/196/436`、`lineage.py:511/560`：完整原 Issue/失败证明、当前 closure、有限谱系与最后 IO 后时钟。
- `domain/capa_verification/models.py:21/90/113`、`service.py:57`：固定 basis、Link/Candidate、只描述客观 basis 的纯转换。
- `domain/quality_execution/models.py:37/99/142/238/318`、`evidence.py:34/108`：现 Issue/Policy 指针、固定事件失败、安全来源及 artifact-only checker。
- `models.py:252/285/302/315/332/479`、`domain/quality_issues/ports.py:23`：共同回执组、无 consumed_at 的 Confirmation、AI Invocation 与领域 decision_id 区别。
- `service.py:198`、`quality_followup_host.py:24/231/307/356`、`quality_policy_import.py:16`：实际回执创建次序、三操作 marker/append、宿主内部出版模式。
- `migrations/versions/0024_quality_followup.py:22/101/132/302/611/629` 及 `0025_quality_followup_json_operators.py`：三操作双向原子组、RLS/权限/保留及后继修正。仅读源码，没有查询实际 head 或应用迁移。

facts v2 三文件 SHA256：

```text
facts.py          a9c06b974300729fe8953f1c7b85ec5a5c3ceb57416bc4d81c0c79f708083f50
test_facts.py     0e7351bf6edc93c23005e9b352545b32eb1679c6f6e297e33b216618b251f94f
facts-contract.md 1e0e393fcc86466737b0f20bd4352bc77106943b0dff03d7756b5e893c6dcb0f
anchor.py         55a8446b68e9bbd466b9bf80ba7de44680ad587da353a4b56b3ed0b93156073e
lineage.py        252a11c5a48f9d6db8a270e07f979ae1437de4156bd1b16d6fe4bd7dcea6dcce
Wave17 draft     05163de7294e0150995f21e75a4cee2dc10032d1ad2cce5330f0c68e6330cdb9
```

这些事实/锚协议仍是未挂载的暂存代码。报告不宣称业务接通、生产 real 资格、G3 通过或人工 Exit；不覆盖原候选、停止运行及失败证据。
