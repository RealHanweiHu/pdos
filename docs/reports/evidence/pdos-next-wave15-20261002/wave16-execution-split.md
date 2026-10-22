# Wave16 执行拆分与公共接线依赖审阅

状态：**只读施工准备建议，尚未冻结 Wave16 实施合同，未实施或验证本波。** 本文仅新增证据；Wave15 backend v3、已冻结源码、测试及原始日志均未修改。主线仍办理 Wave15 pg11/12 复验，本文不声明该波通过。

审阅依据：[Wave16 草案](../../../design/2026-10-02-pdos-next-wave16-quality-followup-draft.md)、[Wave15 实施合同](../../../design/2026-10-02-pdos-next-wave15-quality-loop-implementation-contract.md)及下列定向代码。未运行数据库、HTTP、pytest、构建或浏览器。

## 1. 本波可以交付的业务结果

建议首版接通当前 Issue/CAPA 的具名根因决定、执行者本人实际完成、固定 owner 输出回链和新独立复验候选。候选可以显示已建新请求、未执行、部分结果、未知或观察期缺项；只有既有 owner 真实办理的新 Run、原报告、确定判定及专业复核，才能成为对应的已发生事实。

`quality.capa.effectiveness.decide`、`quality.issue.close`、ChangeOrder 批准/实施/生效仍保持未开放。新表、候选 `pass`、新 Run 的 review/disposition 都不能授有效性或关闭。双线变更八 facet 的 UNKNOWN 继续保留。

## 2. 必须先冻结的公共缺口

| 接缝 | 当前实现及精确缺口 | 最小接线要求 |
| --- | --- | --- |
| 操作及分级 | `domain/quality_issues/handlers.py::OPERATIONS` 已有 `quality.issue.root_cause.decide` T2、`quality.capa.actions.complete` T1；`contracts.py::PAYLOADS`、`command_handlers.py` 和 `service.py::EVENTS` 尚无两项 | 两个辅助操作显式注册，不能把类存在视为 API 已开放。根因用共同 `approval_token`/具名 T2；完成用共同 `confirmation_token`/T1；回链及候选记录的新辅助名称和分级另由主线冻结 |
| 共同证明桥 | `quality_execution/adapters.py::TransactionCommands.confirm` 目前只接受 merge/triage/containment，字段仅 `accepted_confirmation` | 扩展为绑定 exact operation、subject、tier、material digest 的已消费证明；不能用通用 `True` 冒充 T2。共同 execute 拥有一次消费、一次 Receipt/Audit/Outbox，纯核适配器不二次确认、不 commit |
| 专业矩阵 | `professional_authority/service.py::OPERATION_ROLES` 未配置根因/完成。纯核一般职责 quality/engineering/test，T2 另外要求 quality | 根因限定当前具名 quality；完成除当前相应职责/精确 operation、purpose 资格外，逐项核 executor 为本人。只具 manufacturing 职责的执行者需另冻结合同，不暗授 test；可信签发与 AI Qualification、ProductGrant.can_write 分开 |
| Issue 数据库状态 | `QualityIssueVersion` 当前 CHECK 只允许 `open/triaged/actioning`，operation 只允许 Wave15 五项 | 新单调迁移扩至 `awaiting_verification` 及本次两项 operation；不开放 `closed`、effectiveness。同步模型、共同原子函数事件映射和受控 writer，不能只增加 handler |
| Issue Current/原子组 | 已有 `QualityIssueCurrent` 精确 scoped FK、连续前版/epoch/owner/visibility/purpose 守卫，`require_quality_change_atom` 要求新版本及精确 Current、合法共同回执 | 复用同一 Current 与聚合序列；CAS/当前权和来源重核先于新写，合法旧回执重放不回退指针。扩展原子守卫只接受对应动作增量：根因 null→具名结论；指定 action 的 completion null→真实本人完成，其他 action 身份/文本/执行者/顺序及原失败保持。不能借操作写入 effectiveness/closure |
| 来源与生命周期 | 已有精确 SourceRef、原生登记文本回执证明、真实 UploadedOriginal 安全/字节核对、完整来源并集和生命周期引用目录 | 新对象需登记不可变表、RLS、Agent 零直接写、生命周期引用保护及必要 scoped FK；完整并集最多 20，超限拒绝不截断。原生文本不能冒充仪器原报告；所有受控 IO 后再次核来源、专业/issuer/runtime basis |

迁移号由主线在实施时核实际 head 单调分配；不得预占号码或修改已应用的 Wave15 迁移。新增表/事件名/Receipt subject_type/API 路径必须与共同 registry 一次冻结，UI 和测试依据同一合同。

## 3. 新载荷和对象需要补齐的字段

以下为待冻结字段要求，不是已注册的 schema。

- **根因载荷**：logical `issue_id`、严格 `expected_issue_revision`、`text`、精确 `sources`、`reason`、`approval_token`；若最小入口限定已有 CAPA，另固定真实 `capa_id`。结论 actor/决定时钟由服务器产生，不能让客户端提交“已批准”或历史结论时点。纯核允许 actioning 且无根因，完成之后进入 awaiting_verification 时不能再用该动作补根因，因此 UI 要说明这一顺序限制。
- **完成载荷**：同一 Issue CAS、精确 `capa_id`、非空且 action key 唯一的 `completions`、reason/T1 token；每项沿旧 `Containment{id,text,executor_id,evidence,at:EventTime}`。服务绑定真实旧 action，不接受新 action 或更换执行者。事件原文需核同一 action、executor、实际 occurred_at；aware UTC/IANA 原时区、无未来、`effective_at` 的适用语义必须明确，不把通用可空字段变成客户端生效声明。服务器 received_at 与发生时间分开保存。
- **RemediationLink**：不可变行身份、server scope/project/purpose/owner/visibility、创建时 logical Issue+版行 ID/revision、CAPA/action key、requirement/原失败集合摘要、该 action 的完成 proof（未完成分支明确 null）、typed owner output refs、实际 owner 回执/来源 proof、nature、source_basis/readset、intent、server received_at。候选 output 必须区分配置草稿、已建请求、已发生实际输出，不能只收 UUID 或客户端状态。
- **复验候选**：同一固定 Issue/CAPA/requirement basis、RemediationLink、全体原失败到新 sample/item 的显式映射、新 logical Request/Run 及精确版行、Measurement/Projection/规则版本、实际配置/实际方法/判据依据、原报告定位、安全 basis、真实 executors/具名 reviewer 和各自来源。`observed_from/until` 必须来自真实 observation owner；仅有 observation_until 要求或新 Run 时钟时保持缺项。`current/applicable/result/nature` 由 owner 重核，不能由 public 请求填写。
- **固定要求变化**：不强制所有旧 link 的 Issue 版等于最新而造成自己的完成/回链动作循环失效；必须比较相同 CAPA/action/requirement/原失败/完成与输出的固定摘要。实际依据变化或归并需重核；历史不改。首版候选只追加不可变行，不另建第二个 Issue/CAPA Current。若需更正候选，先冻结其独立 logical series、连续前版/epoch/CAS 和引用失效规则，再增加 Current。

旧核允许本人记录已发生的措施完成而无根因先决；部分完成仍 `actioning`，全完成进入 `awaiting_verification`。根因仅 `actioning` 可决定是当前规则的真实限制，不能在 adapter 静默放宽。最小演练先根因后完成；若业务要求全完成后补根因，应另修改正式规则合同并验证，不能借直接 JSON 更新恢复。

## 4. Typed owner 端口与新复验的先后依赖

可复用 `quality_execution.service.get_issue(..., revision=固定版)`、已有 source/authority bridge、配置/Build/实际配置/批次/样件 owner，以及所有验证 owner。当前 `quality_execution/ports.py::FixedQualityResult` 和 `quality_result_bridge.py::fixed_failure_result` 专用于确定失败逐测量桥；不能原样变成新 pass/indeterminate 证明。

建议 B 先冻结以下窄接口，A 只调用，不复制算法或另造 Run：

1. `resolve_followup_outputs(s, ctx, product_id, fixed_issue, capa_id, action_id, output_refs)` → typed 固定 owner 身份/状态/proof/readset/basis/缺项。`output_refs` 按 owner kind 的 closed union，配置/BOM/工序 key 均取真实已有对象。缺 owner port 返回 503 或明确不可办理项，不造 current=true。
2. `inspect_verification(s, ctx, product_id, fixed_issue, evidence_ref, *, at, write=False)` → 固定候选、每原失败的真实新 pair/判据/方法适用证明、原值结果及完整读集/需重核原因。当前可保存部分候选，**不接通** `BoundPolicy.verification` 的有效性正例；后续完整政策冻结后才转换为旧纯核 `VerificationEvidence`。
3. A 的标准 `validate/semantic/preview_view/apply/replay_subject/inputs/list` → 同一调用者 Session 下的旧核 mutation，由主线受控 Issue writer 保存；B 回链/候选写入也由主线共同命令事务拥有 Receipt，不在 owner resolver 中创建业务输出或启动测试。

独立复验真实路线：**新准备/正式 Request → 固定专业方法与实际样件/实际方法 → offer/accept → 新 Run plan/promise → 当前资源/样件和具名资格核对后的实际 start → 原报告 import → 确定 compute → 独立具名 review/disposition → 候选精确回链**。已有 `VerificationRunIdentity` 一请求一 Run；不向原失败 Request 加第二 Run，不重用已破坏性消费样件，不从原失败/旧 Actual 时钟伪造新执行。新 Run 还不能替代整个实际观察期。

研究草稿/未开测的新 Request 可以如实回链，不能记成正式改版措施已实施。实际要求配置改动的复验依新固定双配置、新 Build 和对应实际样件；无配置变化的调查复验可沿当前仍适用 owner 办理，但也需新的 Request/Run 和完整当期资格。原 retained 执行证明可支持迟到读取已发生事实；不支持现在新增批准或复用旧占用开新 Run。

## 5. 四路独占归属与冻结顺序

下面是建议归属，须主线正式分配后才能写代码；新增包路径均相对 `pdos-next/server/pdos_next/`。

| 并行路 | 唯一写入归属 | 独立交付及依赖 |
| --- | --- | --- |
| A：整改办理 | 新 `domain/quality_followup/{__init__,schemas,service,adapters}.py`；新 `server/tests/quality_followup/**` | 根因 T2/本人完成 T1 的标准 handler、typed 调 B、输入/历史/阻断 DTO。复用 `quality_issues` kernel；不写现有 `quality_execution` 文件或新增 Issue/CAPA 模型 |
| B：回链及复验桥 | 新 `domain/capa_verification/{__init__,schemas,models,service,ports}.py`；新 `server/tests/capa_verification/**` | 独占 RemediationLink/候选模型、固定 owner resolver、失败→新 pair 映射、来源及独立性缺项。先交 models/schema/signature 让 A/C/root 同时推进；不改原失败桥、Run/资源/样件账本或 PolicyPort positive |
| C：办理页面 | 新 `web/src/components/builds/build-quality-followup.tsx`、新 `web/src/lib/build-quality-followup-view.ts` 及其独占 helper 测试 | 真实来源/输出候选、T1/T2 material review、本人任务、部分结果/观察期/独立性 blocker；本机草稿和完全相同请求重试。只按具体 caps 启用，不输入资格/结果布尔值，不改公共 BFF/父组件 |
| 主线：共同接线/验证 | 既有 `quality_execution/{models,service,adapters,schemas}.py` 受控扩展；`contracts.py`、`command_handlers.py`、共同 `service.py`、专业矩阵；公共模型注册/API/BFF/父组件、实际 head 新迁移/原子函数、生命周期 catalog | 独占既有 Issue 聚合 writer/Current、共同证明与 Receipt/Audit/Outbox、模型 CHECK/原子/RLS/权限。统一 PG/迁移往返/HTTP/浏览器及最终候选；A/B/C 不并行修改这些文件 |

建议关口：**①公共分级/矩阵+A 请求 DTO+B 两个 owner DTO/模型先冻结 → ②A/B/C 独立施工与自身纯/static 检查，主线并行公共迁移/接线 → ③主线先核根因/部分完成/来源/事务，不必等独立复验真条件 → ④真实 owner 新分支办理、B 固定候选回链 → ⑤同候选集中闭环验证**。无根因或 completion 顺序合同、B 尚无 owner proof、数据库尚不接受新状态时只继续独立草稿，不能提前开放接口。

## 6. 受众、旧固定 Change 和仍不可推进的关口

scope/purpose/audience 从真实 Issue/CAPA 与 owner 身份服务器绑定；续版保持 Issue 原 owner/visibility。新输出及所有来源受众只能交集，ProductGrant 或独立 quality 身份不扩权。独立人看不到私有 Issue/原件/样件时，候选/复核关闭相应 caps；不能 duplicate 同一 Failure 到 public Issue、改旧 visibility 或代签。合法分享/受众变更尚缺接口，须另冻结授权合同。

根因/完成推进 Issue 后，Wave15 Change 的固定 roots/references 不自动追最新；旧 Change/capture/Impact 保留，旧固定 Issue 当前不可重核时新捕获/计算拒绝。未接 `change.request.revise`，不能复制旧批准或随意新 UUID；真正新固定 basis 按 server 语义身份建新 Change，八 UNKNOWN 不消除。明确展示 source_status 和固定旧版，不把历史 `not_evaluated_historical` 置为 current。

当前 `QualityPolicyFact` 模型仍限 synthetic，真实生产政策/观察期/独立适用 owner 缺失；本波可实现受控合成闭环和明确 blocker，不能声称真实整改有效、生产放行或人工 Exit。现政策的 risk/independent_verification 也不等于完整复验方法与观察政策。

最低受影响验证应覆盖 T2 本人及专业/current-source 先于 replay、completion 本人/精确事件/无覆盖、部分与全部状态、CAS/跨 key 同意图、末端 Outbox 原子回滚、原 owner 输出不随回链失败回滚、私有独立人失能、全 20 读集及 ABA、候选原值/实际配置/sample-item/观察期缺项。新增不能伪造有效性/关闭成功例；本次仅盘点，没有执行这些验证。
