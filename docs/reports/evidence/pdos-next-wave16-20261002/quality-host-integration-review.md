# Wave16 Root 接线审查：同事务追加、已消费证明与完成核对

这是实施前只读接线审查。A `quality_followup` 与 Wave15 已冻结源码保持不改；未操作数据库、HTTP、pytest、浏览器或公共验证。下述新 host 函数为接线建议，不表示已实现或生产启用。

## 可复用的事务路径

`database.tenant_session` 已以单 `Session.begin()` 设置 tenant RLS；`service.execute` 先锁 Product、核当前身份/资格/完整来源，再执行模块 validate、RequestKey/语义 Receipt/模块 replay 去重；只有新意图才 `consume_material_confirmation → module.apply → append_receipt → RequestKey → flush`。宿主回调不能另开 Session、commit、二次 Receipt、二次消费或重复 Run/库存占用。

具体位置：

- [database.py:20](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/database.py:20)：唯一调用者 UOW。
- [service.py:470](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:470)：当前门禁先于所有重放；已存在意图跳过新证明消费。
- [service.py:605](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:605)：消费后进入 apply。
- [service.py:195](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:195)：唯一 Receipt/Audit/Outbox，subject 为新版本行 ID/revision/status。
- [quality_followup/service.py:617](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/service.py:617)：实际 UUID proof、核 mutation、末端刷新、一次 append。

Root 可将新窄回调放在新 host 模块（例如 `pdos_next/quality_followup_host.py`），通过 `configure_followup` 注入。仅调用既有函数与字段，不调用 Wave15 `_load` 偷接新操作。

## 1. `append_issue`：复用保存字段，不能直接调用首版 `_record`

固定回调签名已在 [quality_followup/ports.py:13](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/ports.py:13)：

```python
append_issue(s, ctx, product, before_row, mutation, *,
    operation, authority, policy_snapshot, required_source_read_set,
    source_basis, input_snapshot, intent_digest, expected_issue_revision) -> QualityIssueVersion
```

可以直接复用 [quality_execution/service.py:477](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/service.py:477) `_record` 的 IssueVersion 字段写法、flush 与 Current 更新模式；不能直接调用该函数，因为它还依赖首版 Bound/payload 分支，含 create/merge FailureMap/EventFailureLink 逻辑及旧分级。新回调只处理一个已有 Issue 的连续 successor。

必需结构断言与动作：

1. 接收同一 Session、同 tenant/product/project 的现有 `before_row`；验证 `before_row.snapshot_sha256 == service.digest(before_row.issue_snapshot)`，旧 snapshot.scope/id/revision/status 与列一致。只允许 root-cause/complete 两操作。
2. `mutation.changes` 恰一项；`insert_ids` 与 `deliveries` 为空；next.id 等于逻辑 Issue；next.scope 不变、next.revision=before+1。核 `expected_issue_revision == before.revision`、input_snapshot 的 target 相同。
3. 在 Product 共同门栓后锁 `QualityIssueCurrent`，显式筛 tenant/product/project/issue；其 issue_version_id/revision 必须精确是 before。A `_new_write` 已做前置 CAS，但宿主自己的安全边界仍应重复结构断言，不能把客户端 oldrow 当写权限。
4. 创建 `QualityIssueVersion(id=server uuid4)`：tenant/product/project/issue、previous rowID/revision、owner/visibility/purpose 均继承旧行；writer=ctx.requester；status/snapshot 取核 mutation；snapshot_sha256 用既定 `service.digest`；input_snapshot、authority_snapshot、policy_snapshot、required_source_read_set、source_basis、intent_digest 使用 A 已核的完整参数。不是原始 UTF-8 SHA。
5. `reason` 由已核载荷派生：根因 text；完成可用固定操作说明并保留全部完成 text 在 input/snapshot，不能填前版 reason 冒充本次说明。created_at 由 Row 服务器生成。可加动态 `action_result={issue_id,capa_id}` 供 Receipt 结果展示，但不另存真值。
6. flush 新版本，Current.issue_version_id/revision 指向新行，epoch 精确 +1，再 flush；不创建新 Current。返回新 ORM 行，供外层共同 `append_receipt`。异常全部回滚，包括已消费 Confirmation。

**sources 参数差异：** frozen AppendIssue 没有独立 `sources` kw。可以从可信参数完整重建：`union_sources(before_row.sources, issue_sources(next_issue), source_basis['followup_basis']['sources'], policy_snapshot['sources'], 每个 completion_assessment.sources)`。新根因与完成 event/evidence 都已在 `issue_sources(next_issue)`；旧失败精确来源保存在 FollowupBasis。authority 来源通过完整 required readset/source_basis 保留。不得只存此次 payload.sources 或只复制旧来源。保存前要求这些 SourceRefs 的 artifact 版本都被完整 required_source_read_set 覆盖（1..20，不截断），且完整 source_basis 已由 A 末端刷新核实。

`source_basis` 不能过滤 A 加入的字段：`artifact_sources/result_proofs/followup_basis/completion_assessments/shared_proof/completion_observations`。其中 `shared_proof={id,tier}`，完成观察同时保存服务器 received_at；实际 occurred_at 已在 snapshot 与结构化 fact 中，不重新生成。

当前模型 [quality_execution/models.py:37](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/models.py:37) 的 status 只有 open/triaged/actioning，operation 只有 Wave15 五项：Root 必须单调迁移扩到 `awaiting_verification` 与本次两操作，保持旧 CHECK、scoped FK、immutable、RLS、Current连续性和 agent 零写。不能仅注册 API 后声称已可保存。

现 [schema_0023.py:397](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/migrations/schema_0023.py:397) `protect_quality_current` 要求同身份、revision/epoch+1、exactprevious；[schema_0023.py:554](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/migrations/schema_0023.py:554) deferred atomic guard 要求 successor 对应 Current 与精确共同 Receipt/Audit/Outbox。新 proof 还应在主线新 guard 中核 `shared_proof` 的 Confirmation ID/tier/actor/op/material，避免直接插入伪根因。迁移编号由 Root 以真实 head 单调分配，本审查不预留号码。

## 2. `consumed_proof`：真实同事务证明读取，不能用 accepted=True

```python
consumed_proof(s, ctx, command, payload, *, tier: str) -> UUID
```

现 [service.py:450](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:450) `consume_material_confirmation` 已完整比较 material_digest 与 reviewed_view，成功后仅设 `Confirmation.consumed=True`。`confirmation_for`（:305）明确拒 consumed 行，所以新回调不能调用它；也不能复制它再重置 consumed。`Confirmation` 实际只有 consumed 布尔，没有 consumed_at、command_id 或 decision_id。

新回调只允许 tier=T2 的 root-cause 或 tier=T1 的 complete（B link 使用同协议但独立 allowlist）。从正确 token 字段取值，按 token_hash=digest(token) 锁真实 Confirmation，验证：

| 字段 | 精确绑定 |
| --- | --- |
| tenant/product/actor/op | ctx.tenant、command.product_id、ctx.actor==ctx.requester（当前 human、无 run）、command.operation |
| subject_id/revision | **product.id / command.expected_revision（Product水位）**，不是逻辑 Issue/Issue revision |
| consumed/expiry | consumed is True，expiry 在最终核对时仍未来 |
| payload_digest | `service.material_digest(ctx,command,payload,quality_followup.service)`，内含 IssueTarget、完整 source_read_set 与去 token 语义 |
| snapshot | 必须是本事务共同消费已核过的实质 preview；旧/new时钟规则沿 A稳定投影 |
| 返回值 | 真实 Confirmation.id UUID；不能随机UUID、token digest、bool或客户端 proofID |

**同事务来源缺口：** 仅 SELECT 历史 `consumed=True` 不能证明它由本次公共消费步骤消费。最小安全接法是在共同 consume 成功处，将实际 Confirmation.id、token/material/snapshot digest、command.id/operation/actor/product/revision、当前 Session transaction identity 登记到 private host assertion marker（或直接把真实行返回给 execute 后由 host 注册此 marker）。回调核 marker 与锁行相符。marker 只能由共同消费路径创建，不能通过 payload、API 或一般 `configure_followup` 参数注入；回滚/事务结束不能跨事务复用。它是证明这一步实际消费的局部 provenance，不缓存专业/来源肯定结论。不得依赖 ORM dirty history/autoflush状态来猜是否本txn消费。

公共消费已在 apply 前重算 snapshot，回调无需再递归执行一次 preview/full bytes；只读核上述真实绑定，避免第三个内核确认与深读性能重复。A apply 在末端 IO 后再次调用回调并要求 UUID 未变，且把 T2 UUID置入旧核 Invocation.decision_id。保存的 shared_proof 可以由 deferred DB guard再次独立验证。exact-key/跨-key已有 Receipt replay 在这之前已返回原回执，不再次消费，也不重新生成 proof。

## 3. `assess_action_completion`：显式有限合成 ledger，不是 completion JSON 自授

```python
assess_action_completion(s, ctx, product_id, basis, action, completion, *,
    policy_snapshot, observation, write=False) -> CompletionAssessment
```

A 已在 [quality_followup/evidence.py:31](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/evidence.py:31) 核九键整行完成事实、原 executor本人、固定 Issue/CAPA/action/purpose/text/time，另经旧 `quality_execution.evidence.check_source/source_basis` 核 hash/ACL/native登记 provenance 或 uploaded-original安全epoch；缺 callback 的完成操作明确503。回调负责**调查类别政策或实际正式实施归属**，原文存在不能代替这层判断。

可复用 host有限ledger模式 [operational_bootstrap.py:14](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/operational_bootstrap.py:14)：先 verify_test_target，再严格闭合 host profile、bounded entries、exact digest、期限；以及 [quality_execution/policy.py:20](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/policy.py:20) opaque capability/issueridentity/epoch/disable模式。不能复用其 `verify_named_decision` 的业务字段做完成核对；需要新的有限完成评估入口。

最小 local synthetic profile：host 指定 exact tenant/product/project/purpose、当前 issuer key/version/epoch、有限 entries；每 entry 固定 Issue/CAPA/action/executor、action_sha256、固定依据/政策hash、`classification='investigation'`、真实分类来源 SourceRefs/full reads/sourcebasis、valid_from/until。可进一步绑定 beforeIssue/basis hash，续版需要新的明确 entry，不按任何客户端nature或text关键词扩展 ledger。profile只能核对独立标记实例后由host启用，任一scope/entry/issuer/epoch/source变更立即unknown/拒绝。默认 real 接口仍未接；synthetic不能升级生产资格。

回调从已核服务器 FollowupBasis/actions/observation 派生返回，不收公共用户 assessment：

| CompletionAssessment 字段 | 返回规则 |
| --- | --- |
| scope/issue/capa/action/executor/purpose | 与服务器 basis、原措施、实际本人相同 |
| basis_sha256 | 传入可信 B basis 的完整值；不客户端重建 |
| action_sha256 | B action binding：`digest(action.model_dump(exclude={'completion'}))` |
| completion_sha256 | `digest(completion.model_dump(mode='json'))`（包括 exact event/evidence） |
| event_source | completion.at.source 全字段一致 |
| policy_basis_sha256 | `digest(policy_snapshot)` 全字段，保留 issuer/pointer/expiry/来源 |
| allowed/current/classification/nature | literal bool；仅真有限ledger命中 investigation/current/allowed，nature 必须等于 basis.synthetic；未配置不能补 true |
| sources/full reads | 分类政策/owner证据+完成event全部当前完整 union，1..20；私有来源不能扩共享受众 |
| owner_proofs | investigation 可空；formal_change 必须真实owner已批准实施的固定id/rev/Receipt/hash/current，现 Change 尚未 implemented 则不生成positive |
| valid_until | host entry/issuer政策/当前专业事实/来源有效边界最小者，末端仍未来 |
| proof_sha256 | 既定 `digest(上述全部JSON字段，exclude={'proof_sha256'})`，不是自签权限 |

根因可办理状态不依赖 completion callback；完成 GET 的 `can_prepare_completion` 仅意味着当前本人专业/状态/接口存在，可以填候选。没有实际候选时 `can_complete=false/completion_verified=null`；inputs.allowed是候选通过当前真核对。不能将 GET能力或 policy.risk='low' 直接变成调查已经完成。

末端重核顺序见 [quality_followup/service.py:432](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/service.py:432)：完成callback与来源IO→所有旧失败窄refresh→当前policy/authority/期限/Runtime。所有回调每phase独立，无跨validate/preview/apply/replay缓存。若 callback最后一个IO撤销前一个issuer，应拒绝且 token/Issue/Receipt全回滚。

## 尚需 Root 定向验证的接线冲突

- 旧首版 writer仅accepted bool/T1，不可作为本T2 actual proof；新UUID窄assert+Invocation绑定必须通过真实共同消费验证。
- 首版 Issue Model/迁移状态与操作CHECK尚未允许本波；agent零写与 deferred atom必须一起保留。
- CompletionAssessment没有独立 issuer字段，issuer/epoch撤回必须进入其 policy/source/proof material或令host callback重新评估后拒绝，不能仅凭稳定proof_sha256永久重放。
- 正式 Change草稿/UNKNOWN impact不是 approved implementation，host formal_change必须拒绝。本波调查合成演练不能给正式实施positive。
- 新根因/完成版本继续同Current；不得为输入/历史另建 ResultCurrent，完成不得stage资源或重复消耗样件。
- Root应集中验证真实 proof未消费/错tier/过期/非本txn、Current竞争、不同key原意图、末端Outbox失败全回滚、原件/专业/hostepoch IO间撤回，以及部分/全部完成。A纯检查不证明这些PG事务。

主线只需注入 callbacks、公共注册/role/T1T2/events、单Issue route映射与单调迁移；本只读审查不改任何冻结源码。
