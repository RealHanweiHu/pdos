# Wave16 B typed binding contract v1

状态：新包独占预备接口；未公开注册、未导入现有 API、未应用迁移或执行 PG。Wave15 303 路径保持冻结。本合同定义候选读取，不授 CAPA effective/Issue close。

## 冻结路径与载荷

`pdos-next/server/pdos_next/domain/capa_verification/schemas.py` 是 typed 字段权威。所有 DTO extra forbid/frozen；revision 为 strict integer ≥1。

- `FollowupBasis`：server scope，logical Issue/精确版行/revision，真实 CAPA，purpose/owner/visibility/nature，完整 requirement+hash、固定全部 failure_ids+hash、所有 `ActionBinding`（action/executor/action_sha/completion_sha/原 EventTime）、root cause hash，完整 SourceRef/readset/source basis 与整体摘要。客户端副本必须重新核；不能以任意 scope/hash 授权。
- `OutputRef{kind,id,revision,key:null}`：id 总是 immutable owner **行 ID**。closed kinds 为 definition/bom/engineering_configuration/manufacturing_configuration/build/actual_configuration/build_lot/sample/verification_preparation/verification_request/verification_run。key 仅固定 BOM line 或制造 operation 可用，服务核真实存在。Request/Run 的 logical ID 由读取结果另给，不用猜 logical UUID 当版行。
- `FollowupLinkPayload{issue_id,expected_issue_revision,capa_id,action_id,output_refs,sources:DefinitionReference[],reason,confirmation_token}`：辅助 `quality.capa.followup.link` T1 **由 B 独占 `commands.py` 标准 handler**，共同服务负责证明与回执；A 仅根因/完成。B 不另发 Receipt、不创建输出、不接 public route。
- `ResolvedOutputs`：上述 basis/action、完整 typed outputs、受众交集、来源并集（≤20，超限拒绝）、固定 basis/resolution hash及 missing。`action_fulfilled=null`；读取到对象或配置草稿不代表措施满足/变更实施。
- `RemediationLink`：revision=1 的不可变回链视图，固定 basis/action/output refs/resolution hash、真实 owner/visibility、server received_at、sources/readset/reason。首版只追加，不建立另一份 Issue/CAPA Current。
- `CandidateBinding`：固定 basis、精确 RemediationLink refs、显式 `FailurePairMapping`。映射含原 failure_id、新 Run row ref、实际 sample/配置/revision/item、measurement/projection 可空、专业适用 sources；所有值仍须服务器逐 owner 核对。
- `CandidateInspect`：固定 binding、actual owner outputs、完整 readset/basis/hash、结构化 `missing{dimension,code,detail,output_ref?,failure_id?}`。`applicable/independently_verified/observation_complete/observed_from/until=null`，result=indeterminate；effective/close caps 永远 false。`current` 仅表示已核的固定对象/来源依据，不能解释成候选适用或有效性合格。

## 冻结公开 Python 接口

`service.py`：

```python
load_followup_basis(s, ctx, product_id, issue_id, expected_issue_revision, *, write=False) -> FollowupBasis
load_exact_followup_basis(s, ctx, product_id, issue_id, revision, *, write=False) -> FollowupBasis
basis_from_issue(row, issue, *, sources, reads, source_basis) -> FollowupBasis
recheck_followup_basis(s, ctx, product_id, basis, *, write=False) -> FollowupBasis
resolve_followup_outputs(s, ctx, product_id, basis, action_id, output_refs, *, at=None, write=False) -> ResolvedOutputs
inspect_candidate(s, ctx, product_id, binding, *, at, write=False) -> CandidateInspect
inspect_verification(s, ctx, product_id, basis, evidence_ref, *, at, write=False) -> CandidateInspect
```

上述 owner 读取均同调用者 Session、不 connection/commit/insert/确认/占用；write=True 只允许共同事务授权/必要门栓，绝不生成 Run 或效力事实。exact loader 逐原失败/来源核历史版，供合法 replay，Current CAS 留 newwrite；pure basis helper核保存 Issue digest，不构成授权。`inspect_candidate` 是未保存候选的只读输入核查；`inspect_verification` 读取真实既存候选行再核，缺行不能构造 positive。

`commands.py`：`validate/semantic/preview_view/apply/replay_subject_type/replay_subject/inputs` 沿共同 handler 签名。`configure_consumed_proof(engine, require_consumed)` 只由服务器安装 callback；callback `(s,ctx,command,product,payload)->UUID` 必须核实际已消费共同 T1 exact-proof、actor/product/operation/material digest，并返回真实 proof UUID；缺 callback 或 bool/None/string 返回为503。`apply` 返回 `(RemediationLinkRecord,'capa_remediation_link',visibility)`，不推进 Issue Current。保存无 token semantic 与 `input_snapshot.shared_proof={id:<UUID>,tier:'T1'}`，供主线原子 guard；Root消费唯一 proof，B 不再消费。旧回执重放先当前人/专业/政策/原失败/输出/来源 gate，不再次请求 proof。

预览 `before=null`，`after={id:null,revision:1,issue_id,issue_revision,capa_id,action_id,resolution:ResolvedOutputs,visibility,received_at:'server_on_save',action_fulfilled:null}`，同时给 authority/policy/required_source_read_set/reason。输入回 `{operation,allowed:true,required_source_read_set,authority,review}`；真实阻断抛对应 DomainError。公开 GET/候选选择列表/envelope 由主线与 A 冻结，本包没有自建 API。

`models.py` 仅声明两 append-only 表：`RemediationLinkRecord` (`capa_remediation_links`) 和 `CapaVerificationEvidence` (`capa_verification_evidence`)；两者 revision=1，无新 Current。含 exact Issue/CAPA/action/requirement/failure basis、server scope/owner/writer/visibility、input snapshot/sources/readset/source basis/hash/intent/reason。Link 另含 current authority_snapshot/policy_snapshot 和实际 shared-proof；Candidate 的 applicable/independent/observation列被 CHECK 限为 null，result 限 indeterminate。Root 统一模型注册、scoped FK、不可变/RLS/Agent0/共同原子回执和生命周期门禁迁移；未迁移前不调用持久表。

## 可复用与缺口

直接使用既有配置/Build/Actual/Lot/Sample/Preparation/FormalRequest owner 当前来源和私有 ACL；Run 使用真实 retained execution 端口，不从计划构造实际证明。原失败结果桥继续只证明原失败；后续候选需真实新 Run，原失败 Run 拒绝。

本版缺 CAPA 专业适用、独立 reviewer 和实际观察期 owner bridge，稳定输出明确 missing/INTEGRATION_REQUIRED；不以 Run pass、客户端布尔值、录入时间或 requirement observation_until 补这些事实。原报告与原值核验只复用受控测量 owner；缺真实原件/结果读取端口时不得返回 measurement 已核。

当前 Issue aggregate 推进不自动让旧 Link current；核同 CAPA/action/requirement/failure/completion 的固定语义和来源，合法不相关聚合追加不引入“每个旧链接必须最新版本”的自失效循环。归并、根因/完成/要求/失败依据真实变化需重核。私人引用不扩受众，独立人无读取权即失能，不能代签或改旧 visibility。

本接口供 A/C 并行依赖；公共专业矩阵、根因 T2/完成 T1/回链 T1、append_issue hook、迁移/API/BFF 均由主线后续冻结并接线，本包不修改 Wave15 候选。
