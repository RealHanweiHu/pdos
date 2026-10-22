# Wave17 暂存 StableCapaAnchor / 有限谱系合同

状态：未挂载纯逻辑。没有数据库、HTTP、真实 Source/原件读取、操作注册、迁移、Receipt 创建、commit、第二份 Current、资源占用或资格授予。当前 Wave16 的 `server/`、`web/` 与 480 份候选保持。纯正例全部是明确 synthetic 结构输入，不是真实业务证明。

## 函数与 DTO

```python
build_anchor(origin: IssueVersionEvidence,
             failures: tuple[OriginalFailureProof, ...], *, source_basis) -> StableCapaAnchor
validate_lineage(anchor, versions, steps, closure, *, at: aware_datetime) -> IssueLineageProof
verify_from_host(host: LineageHost | None, anchor, current_ref,
                 *, clock: Callable[[], aware_datetime]) -> IssueLineageProof
```

`IssueLineageProof.structural_validation_only=True` 永远存在。它不是 `authorized/current/allowed=True`，不得用于自授 T2 或当作真实资料已读。结构错误拒绝（DomainError `RECHECK_REQUIRED` / `SOURCE_STALE` / `FORBIDDEN_SCOPE` 或 Pydantic ValidationError）；缺任何必需宿主 callback 为 `INTEGRATION_REQUIRED` 503。

复用现有 `Issue`、`FailureRef`、`FixedQualityResult`、`Scope`、`SourceRef`、`SourceRead`、`QualityPolicy`、`VerificationEvidence` 和 Python canonical `quality_issues.rules.digest`。未改旧 DTO、规则或状态机。仅复用 `QualityIssueHandler._verification` 的完整观察窗、独立性、精确失败覆盖、不同新 Run、nature 和 pass/fail/indeterminate 规则；纯 adapter 只喂宿主已核的输入，不以 SourceRef 存在充当实际可读/适用。

| DTO | 准确内容 |
|---|---|
| `VersionRef` | `id` 是不可变 QualityIssueVersion 行 UUID；严格正整数 `revision`；完整 Issue snapshot canonical SHA。与 logical Issue ID 分开 |
| `IssueVersionEvidence` | ref/完整 previous_ref、scope/logical issue、purpose、系列 owner、本次 writer、visibility/nature、operation/domain intent、真实 created_at；完整旧 Issue（含 history）、全部 sources/readset/typed安全闭包；原始 input/authority/policy/persisted_source_basis 原样保留 |
| `SourceSafety` | existing `quality_execution.evidence.source_basis` 的 Artifact id/rev/hash/status/owner/visibility 与两种来源。native 必须准确 registration Receipt/actor/requester/run；uploaded 必须准确 OriginalSecurity id/epoch/source_state/disposition。不收调用者 Grant/剩余时效，不默认干净；历史作者不能当当前授权 |
| `OriginalFailureProof` | 原 `FailureRef` + 完整 `FixedQualityResult`，准确 original RunVersion/revision≥3、Measurement/Projection/basis/rules、完整 VerifiedRun 原值/配置/方法/判据、原报告 source basis、固定真实 Start v2、计划、reservation、全部 occupancy/sample_usage/物理与来源/issuer epochs、current/reasons |
| `StableCapaAnchor` | 完整 origin + 按原业务顺序的全部 failure proofs；原行与所有失败来源/readset union、typed原安全闭包；material/full failure/stable failure/source safety/anchor SHA 分开保存 |
| `CurrentAuthorizationClosure` | 同 scope/purpose/audience、当前真人 Authority、完整原+合法新增来源/readset/basis、完整 current professional/policy/source ACL/runtime 宿主快照、真实 checked_at 与最近有效边界 valid_until。写入/关闭前由宿主重新实际取得，≤20，不能截断 |
| `TransitionHostProof` | exact before/after refs、op、command/writer、typed EffectivenessDecide 或 IssueClose、payload/domain/common SHA分别绑定、专业原 snapshot 和完整当前 signer_recheck、policy/evidence、由宿主分类的来源 delta、准确实际 T2 UUID/共同批准、准确 Receipt/Audit/Outbox 与完整 SHA |

SourceRef/readset/basis 是合同指定集合，规范去重排序；同 Artifact 两版本、缺任一 basis、basis 额外身份、>20 均拒绝。Issue/history/actions/failures/验证 evidence 等业务数组保持原顺序。完整 original failure proof 的 SHA 不用 SQL JSONB 文本表示替代。

初始 origin 必须为实际 `quality.capa.actions.complete` 的完成版（版本不硬编码 v6），`awaiting_verification`，未归并、无 needs_recheck/reasons、有具名根因、全部完成 id/本人/时钟一致，准确 requirement 覆盖全部失败，无 effectiveness/closure。原 material SHA 包含完整 origin Issue 和原 history；后继不以删除 history/source 的宽等式与它比较。

## 评估观察与固定材料的准确边界

只有以下三个完整路径从 **stable failure material** 的 deepcopy 中排除：

1. `result.retained.checked_at`：重新核对的服务器评估钟。
2. `result.retained.execution_window_elapsed`：实际窗口自然结束的评估观察；不抹已执行历史。
3. `result.source_basis.runtime_stamp`：当前桥的当次进程/入口/registry 观察；当前完整 runtime/issuer 证明仍由 fresh closure 独立重核。

完整 `OriginalFailureProof` 原样保存，上述值也在 `full_failure_proofs_sha256` 与完整 `anchor_sha256` 内。`stable_failure_material_sha256` 是另一个明确命名的摘要。不得递归按名字删字段；例如 `result.retained.plan_binding.checked_at` 或其中 `runtime_stamp` 是固定计划数据，仍参与摘要。原 Start intent/id/clock、完整计划、占用/使用、reservation、原件安全 epoch、原专业与资源 issuer/版本、原值/配置/规则全部保留。没有通用排除授权、issuer 或期限字段的代码。

调用者 actor/Grant/current剩余时效只在当前闭包，不掺入固定物理材料或原源安全摘要。当前 closure 的前后比较只排除自身 `checked_at` 与准确 typed `authority.now` 两个评估时钟；真实 expires_at/valid_until、epoch、完整 ACL/专业/政策/runtime 内容仍比较。宿主应提供固定到期 instant，而非每次变化的 remaining_seconds。

## 有限追加与真实证明协议

只允许 `origin → effectiveness → close`，最多两步；也可只验证 origin 或 origin→effectiveness。每步完整 previous_ref、revision+1、不可变版本 id不重复，scope/logical ID/系列 owner/audience/purpose/nature不变。

- Effect：至多一次，前后 awaiting_verification；准确增加 `capa.effectiveness`、effectiveness_history 一项与 Issue history 一项，按真实 kernel 规则取 policy/read_digest/evidence/actor/时钟。effective 须全 pass；ineffective 须有确定 fail且不自动 close；indeterminate 留缺项。
- Close：紧随 effective，由相同具名决定人另次 T2；重新按同材料/完整 evidence/policy 求 read_digest；只增加准确 closure/history 和 status=closed。两个命令、两实际 proof UUID、两 Receipt 不可复用。

代码逐步构造 kernel 应有的完整 Issue 快照与 actual after 全字段比较，因此原 history prefix、root/action/completion/requirement/failure/aliases/risk/全部其他字段都不能偷偷改。所有未知操作、重复 effect、跳版/分支/循环、换 scope、merge/recheck 都拒绝，不删历史。

每步 sources/readset 必须恰为 before + 宿主已分类的 verification/policy/professional/approval 增量；原安全 basis 原项全等，新增安全 basis 与最终 closure 全等。验证 sources 必须恰为实际 companion evidence 的 SourceRefs。sources 只是结构绑定，真实性/当前可读/有效期/实际观察仍由宿主建立。

`ConsumedApproval.subject_id` 必须是 Product UUID，不猜成 Issue；准确 tenant/product/actor/op/Product 水位、完整 readset、实际共同 material SHA、批准期限与 evaluated_at、after 的 shared_proof T2 UUID都绑定。`transaction_proof_id` 必须等于实际 consumed Confirmation UUID，**不是新事实表或自行生成的凭证**；其 SHA 仅是 actual approval + 全 next version + Receipt/Audit/Outbox 的规范组摘要。它和 `approved_delta_sha256` 都只能防结构错配，不能用输入 bool/UUID/hash 自证发生过同一 UOW 消费。

真正宿主必须先核共同消费 marker/Invocation.decision_id与批准 UUID、reciprocal deferred 持久原子组、原回执/审计/事件及实际提交，再形成这些 DTO。源仅有 ref、`consumed=True` 或自行计算 hash 都不足。纯 validator 没有读取真实事务的能力；`validate_lineage` 只能用于该 host 路径的结构子步骤，不可公开给 client 作为授权接口。Root 的 missing/default callback必须503，不能由本包构造一个 positive宿主。

Receipt 对准确 next不可变 IssueVersion 的 `quality_issue` subject UUID/revision、logical Issue result、真实 int revision、状态、actor/requester/writer（与系列 owner 分开）、op/command/common intent/visibility核对；domain intent只与领域行对应，**不要求其等于 common Receipt intent**。Audit 与 canonical Outbox事件/相关 command全部匹配。普通历史跨 key 不产生新决定或第二回执。

## 最小 Root-only `LineageHost`

```python
read_current_ref(anchor) -> VersionRef
read_version(exact_ref) -> IssueVersionEvidence
read_transition(before_row, after_row) -> TransitionHostProof
read_original_failures(anchor) -> tuple[OriginalFailureProof, ...]
read_current_closure(anchor, exact_current_ref) -> CurrentAuthorizationClosure
```

所有方法在同一 caller Session/事务/范围内，无新连接或 commit/Receipt。host必须：

- 先核当前 reader 对指定 Issue、全部原失败/原件和新旧来源 ACL；private Issue只原owner读，peer ProductGrant不能升权。product 正例必须从合法共享的新失败场景初建。
- 真实读取 Current，而非用 client current_ref。读取精确旧 Run/Projection/Measurement，原值真实 bytes 与 retained/current source/issuer专业核对；不能换 latest Run。
- 由 actual companion/专业 owner 读取 VerificationEvidence 与 source分类，保留完整参与者/实际观察、new Run/rule/coverage/nature。B 的真实 paired owner 证明接通之前，不能假 claim verification完备。
- 读取真实持久批准/回执组，并重核原 signer 当前撤回/issuer epochs。历史专业事实自然到期按真实保存期间评价，不凭新 caller Grant替原签发者证据。
- 所有 record/owner/bytes读取后形成 fresh完整 closure，并在末端再次独立读取 closure + Current；取 clock在这些读取之后，比较完整源/ACL/政策/专业/runtime/所有边界。过期、漂移、Current推进均拒绝。

`verify_from_host` 已实现首尾 Current + after-all-owner 两次 closure比较；不在 module/global/engine/session.info 保存肯定缓存，不跨 inputs/preview/execute/replay沿用证明。对本次结构输出，后续业务层仍须 newwrite CAS、真正具名 T2消费/append/原子回执与末端刷新。

## 本交付范围与剩余缺口

仅四个 owned 暂存文件。没有公共 models/API/OP_TIERS注册，也没有保存 candidate/review/observation 或实际 effectiveness/close。Root须后续统一迁入、实现真实 host与B paired owner/新事实、两项 T2/companion/SQL atom与页面整链。G3与真实资格/生产启用未通过，Wave16当前候选不改变。
