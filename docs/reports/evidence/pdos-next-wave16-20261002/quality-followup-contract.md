# Wave16 品质后续宿主接口冻结

本文件记录 A 新目录实现的接线合同。仅本包纯测试与静态检查已完成；尚未执行数据库、HTTP、浏览器或共同出口验证，未授予真实资格。Wave15 文件与旧品质核未修改。

## 操作与载荷

导入路径：`pdos_next.domain.quality_followup.schemas`。

| 操作 | DTO | 分级 | 载荷 |
| --- | --- | --- | --- |
| `quality.issue.root_cause.decide` | `RootCausePayload` | T2 | `issue_id`（逻辑 UUID）、`expected_issue_revision`（严格正整数）、`text`、`sources`（1..20 精确 SourceRef）、`approval_token?` |
| `quality.capa.actions.complete` | `ActionsCompletePayload` | T1 | 同一 IssueTarget、`completions`（1..1000，同 action 不能重复）、`confirmation_token?` |

每个 completion 为旧核 Containment 的严格包装：`id` 是已有 action UUID，`text`、`executor_id`、`evidence`（1..20）、`at`。`at` 为 `occurred_at`、`original_timezone`、`source`；`effective_at` 必须空。SourceRef 继续采用 `{kind,id,revision,position}`，artifact position 为 `line:N;quote_sha256:整行UTF8_SHA256`。载荷不收具名 proof ID、classification、nature、服务器接收时钟或权限字段。

实际完成来源须为 JSON 单行，精确九个键：

```json
{"issue_id":"UUID","capa_id":"UUID","action_id":"UUID","executor_id":"UUID","operation":"quality.capa.actions.complete","occurred_at":"带偏移的ISO时间","original_timezone":"IANA时区","purpose":"固定用途","text":"实际完成文本"}
```

身份、CAPA、action、执行本人、操作、固定用途、文本、时区和发生时刻须逐项相等。Z/offset 按真实 UTC instant 比较，保留小数精度；拒绝 naive/numeric/future clock、重复 JSON 键、NaN、数组、缺键及额外键。整行证据需核当前 ACL、安全、内容 hash 与原生登记 provenance 或已上传原件来源。原生文本不能替代仪器测量原件。

## 同一事务的宿主回调

`quality_followup.service.configure_followup(engine, *, append_issue, consumed_proof, assess_action_completion=None)`，Runtime/Protocol 位于 `quality_followup.ports`。

```python
append_issue(s, ctx, product, before_row, mutation, *,
    operation, authority, policy_snapshot, required_source_read_set,
    source_basis, input_snapshot, intent_digest, expected_issue_revision) -> existing IssueVersion row

consumed_proof(s, ctx, command, payload, *, tier: str) -> UUID

assess_action_completion(s, ctx, product_id, basis, action, completion, *,
    policy_snapshot, observation, write=False) -> CompletionAssessment
```

`append_issue` 仅在同 Session 追加原 QualityIssueVersion 并 CAS 原 Current；没有新 aggregate/table/Receipt/commit。`apply` 返回 `(next_row, "quality_issue", original_visibility)`，subject.id 为新版本行 UUID。所有 Receipt/Audit/Outbox/RequestKey/T1/T2消费仍由主线一次完成。

`consumed_proof` 只读取并核对共同已消费证明，不重复消费。apply 前后均核同一真实 UUID；T2 UUID 绑定旧核 `Invocation.decision_id`。preview 不调用证明或 append 回调，也不将拟议 UUID 宣称为实际签核。

`CompletionAssessment` 为 host-only DTO，完整绑定 scope、Issue/CAPA/action/executor/purpose、FollowupBasis/action/completion/policy hash、真实 event SourceRef、classification、nature、当前允许、期限、完整来源/读集及自校验 proof hash。unknown、过期、不匹配、不允许、无 callback 均阻断。investigation 需要受控当前专业政策证据；formal_change 需要实际已批准实施的 owner proof（固定 id/revision/Receipt/hash/status/current），不能用 source 存在、字符串类别或未批准 Change 草稿代替。没有真实默认 positive 配置。

现有 engine `_pdos_quality_result_bridge` 与 `_pdos_quality_result_refresh` 是必需依赖。每个 validate/preview/apply/replay 独立核全部固定原失败 bytes；本 phase 核完后调用 B `capa_verification.service.basis_from_issue`。最终完成来源/callback IO 之后，逐旧失败窄 refresh，再核完整来源、政策、当前办理专业资格、期限与 Runtime identity；后一个 IO 撤回前一个证明不能被阶段缓存隐藏。

## 公共模块接口与读视图

`quality_followup.service` 导出 `PAYLOADS`、`semantic`、`validate`、`preview_view`、`apply`、`request_subject`、`replay_subject_type`、`replay_subject`、`inputs`、`list_quality_followup`。`request_subject` 是逻辑 Issue UUID，replay subject type 为 `quality_issue`。幂等重放先核当前范围、来源、原失败、政策及新操作专业资格，只返已保存精确意图；不再追加或消费证明。

```python
inputs(s, ctx, product_id, Command) -> {
    operation, allowed, required_source_read_set, authority, review
}
list_quality_followup(s, ctx, product_id, *,
    issue_id=None, revision=None, run_id=None, build_id=None) -> {
    issues, current_by_issue, capabilities, unavailable_count, has_more
}
```

无显式范围返回空集合，不全产品扫描。issue_id+revision 窄读取支持固定历史。run/build 筛选继承 mutable FailureMap 目标与 immutable EventFailureLink 原 Issue 的 union，保留合并源单；每次最多 100 logical IDs/100 rows，并明确 `has_more`。私有对象仍按当前 owner/ACL 隐藏。

Issue row 包含 `id`（版本行）、`issue_id`（逻辑）、`revision/project_id/purpose/owner_id/visibility/status`、完整 `issue`、`is_current/source_status`、逐操作 `capabilities/authority`、当前 policy、完整 required reads、真实创建时刻/reason、当前 `followup_basis`、保存前版 `saved_followup_basis`、实际 `shared_proof/completion_observations`。`source_options` 只列已引用、当前可读的原文行 `{artifact_id,revision,title,line,quote,source}`，最多 100。

每个 actions row 返回 `action_id/executor_id/text/completion` 与：

```json
{"can_prepare_completion":false,"can_complete":false,"completion_verified":null,"blockers":[]}
```

当前真实状态、本人资格和 callback 存在只能将 `can_prepare_completion` 变 true，表示可以开始填候选核对；未给候选时始终 `can_complete=false`、`completion_verified=null`。成功 inputs.allowed 才表示该实际候选可进入共同 T1。操作能力仍不等于执行许可。历史版本写 caps 一律 false，当前专业结论未评估；旧真实事件/签核时钟保留。

Root 公共 route adapter 负责将本读视图一次映射到已冻结的单 Issue envelope：`issue/current/basis/operations/actions/output_options/links/candidates/source_options/integration`；A 不新增 RPC 或 public 注册。

review 的 `before/after` 是 `{logicalIssueUUID: pureIssue}`，保留全部原失败/假设/措施/历史。仅新增 NamedConclusion.at 与 History.at 标为 null/`clock_basis=server_on_save`，旧时钟与实际 completion.occurred_at 保留。`completion_observations/assessments`、完整 read_basis、effect/event_effect 均参与共同实质确认；未开放有效性或关闭。

## 原核与主线剩余接线

旧 QualityIssueHandler/DTO/规则直接复用：具名品质 root cause 只在 actioning 且尚无结论时；本人已发生部分完成保留 actioning，全部完成转 awaiting_verification。全部完成后不能补办首次根因；假设不被专业结论覆盖。owner 验证新 Run 仍由 B/真正请求 owner 负责，A 不创建/启动 Run。

Root 尚须实现并验证窄 append/proof/completion assessment callbacks、两操作角色与 T1/T2注册、原 Issue 表 operation/状态约束扩展、公共读路由映射，以及真实 PG 并发/CAS/末端失败回滚/当前来源与资格漂移/旧意图重放。无新增 A 表或 DDL。当前纯检查不能证明这些事务或真实专业资格。
