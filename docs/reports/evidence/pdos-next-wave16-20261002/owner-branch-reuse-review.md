# Wave16 新复验请求分支：既有 owner 入口复用审阅

状态：仅定向只读源码审阅；未读取私有配置，未运行数据库、HTTP、测试或页面。下列步骤供主线实际办理，不代表请求、回链或复验已保存。

## 结论与最短办理顺序

无需第二套请求账。既有 `verification.preparation.record` → `verification.request.create` 已能保存一条新的、具有真实 owner/Current/Receipt 的 FormalVerificationRequest；Wave16 输出选项适配器随后枚举该版本，`quality.capa.followup.link` 记录固定 CAPA action 与此真实输出的回链。新请求仍为 draft/planned，不能称独立复验完成。

1. **先核对当前 Issue/CAPA/action、范围和专业事实。** 采用当前可读 Issue 的同 tenant/product/project，选真实措施 ID。建议新分支标题明确“CAPA 本措施的独立复验请求”，purpose 采用已核对的精确用途值；若改成新用途，必须先由可信入口登记该用途的有效职责/资格，不能套用旧用途。Wave16 setup 六个新事实只覆盖根因/措施完成/回链三操作，**不能替代 `verification.request.create` 的 engineering/quality 职责与资格**。
2. **在“Build 验证准备”保存新的逻辑准备请求。** 可从旧准备版加载字段供人工核对，然后点击“作为独立新请求”：生成新 `request_id`、清空 previousId，初版 `expected_request_revision=0`。填写该措施真正需要的测试项/判据/材料/条件/数量/模穴/返回形式与依据，不能把原失败请求直接选作新分支。保留当前合法 Build/双配置的固定引用；新建准备不要求把 Build 草稿当正式放行。通过 `verification.preparation.record` T1 的共同 preview 与返回原 command 提交，取得实际 preparation 行 `id/revision/sha256` 和回执。
3. **在“专业验证”选择这个真实新准备版，建立新的正式草稿请求。** 页面“选择固定准备版，建立正式草稿请求”独立生成另一枚正式 logical `request_id`。提交 `verification.request.create` T0，当前专业能力必须明确通过；此操作不另索取 T1/T2 token。初版预期是 0，owner 为真实办理人，Formal 行 revision=1，previous=null，Current 精确指向该不可变行。核对实际共同 Receipt 的 `subject_type=verification_request`、`subject_id=新Formal行id`、`subject_revision=1`；同一事务包含行/Current/Receipt/Audit/Outbox。
4. **刷新 Wave16 单 Issue 后续页面，选“实际输出候选”中的新正式请求。** `quality_followup_integration.request_options` 只枚举同 tenant/product/project、当前 ACL 可读、Current 精确对应行 id/revision 的 Formal 请求，最多20项；公开 view 继续核 owner、实际保存 Receipt、来源与固定摘要。选择新标题并核新 logical request，不选择原失败请求。OutputRef 为 `{"kind":"verification_request","id":"<新Formal不可变行UUID>","revision":1,"key":null}`，**id 不是 logical request_id，也不是 preparation_id**。若已续版方法/交接，应从真实当前选项选择相应当前不可变行，而不是猜 v1。
5. **固定当前 Issue/CAPA/action，办理 T1 回链。** 页面先调用单 Issue `/quality-followup/inputs`，使用其完整读集，再共同 preview；确认后原封提交返回的 command。保存的是 `capa_remediation_link` 的真实不可变回链行，不推进 Issue Current，不创建 Run/测量/候选资格。检查回链视图中的 owner 输出、固定 basis、来源、实际 received_at 与缺项；`action_fulfilled` 仍为 null，有效性/关闭仍未办理。

若某步来源/资格/政策/原失败 retained proof 失效，停止依赖办理并读出原因；不能删读集、重造 UUID、延长旧确认或选择旧失败请求凑分支。新建准备与正式请求的两个 logical ID 可不同，应分别记录。

## 精确既有契约

### 新准备（T1）

源码：`server/pdos_next/domain/verification_execution/{schemas,service,models}.py`；页面 `web/src/components/builds/build-verification.tsx`、helper `web/src/lib/build-verification-view.ts`。

`PreparationRecordPayload`：`request_id, expected_request_revision, build_id, expected_build_revision, title, purpose, return_form, items, documents, expected_at/expected_timezone, tentative_at/tentative_timezone, sources, reason, confirmation_token`。初版 expected_request_revision=0，所有时点/时区成对，可未知 null；items 是完整固定要求而非实物列表，sample_count 1–10000，cavities 显式且不重复，destructive 明确 bool。drawing/method/criterion.source/criterion_source/documents.source 使用实际 `DefinitionReference={artifact_id,expected_revision,line,quote}`。sources 1–20；建议选整行精确原文，不能用 UUID 字符串冒充出处。

具名当前 product writer 及 Build/配置/来源当前 ACL 是准备门槛，不需要虚构 quality 专业身份。继承 planned Build/工程/制造配置、全部嵌套来源的 SourceRead 并集；新建不可变准备版/Current，同系列续版 CAS 与 owner/Build/受众保持。私人来源令新请求收窄 private；续版不得改变原受众。服务器保存准备发生/接收时钟，资料、实物、正式接受与开测时钟不回填。

`GET /v1/products/{product_id}/verification` 可读准备版本、current_by_request、缺项与真实参考样件；参考样件不进入 draft.samples/acceptances。UI 的“复制当前”是**旧系列续版**，只有“作为独立新请求”才清空前版并产生新 logical ID。

### 正式初版请求（T0）

源码：`server/pdos_next/domain/verification_front/{schemas,service,models}.py`；复用纯 `domain/verification/handlers.py` 的 RequestCreate；页面 `web/src/components/product/verification-professional.tsx`、helper `web/src/lib/verification-professional.ts`。

实际 payload 只有：

```json
{
  "request_id": "<新的正式logical UUID>",
  "preparation_id": "<已保存的新准备不可变行UUID>",
  "expected_preparation_revision": 1,
  "preparation_sha256": "<GET真实sha256>",
  "reason": "<本措施独立复验请求的实际保存原因>"
}
```

外层 Command：`operation=verification.request.create`、当前 product expected_revision、完整 `source_read_set`、固定 command_id/idempotency_key；目的/内容/Build/双配置/项目/owner/受众均从服务器准备与上下文推导，不接收客户端资格、samples、实际时间或状态。

`GET /v1/products/{id}/verification-professional` 的所选 preparation 具有该 project+purpose 的 `authority.request_create` 和 `capabilities.request_create`，UI 用它及其 required_source_read_set；不能使用顶层 any-true 代替所选能力。来源读集为固定双配置+准备原文+当前专业事实，并集超过20明确拒绝，不截断。服务在共同旧回执重放前重核当前授权、职责/资格与来源；新写才检查 product/current CAS。网络结果不明必须保留同一个完整 Command 和正式 logical ID 重试；换 id 会产生另一合法新请求，不能用作“不明结果重试”。

服务使用 `verification_formal_requests` 与 `verification_current_formal_requests`。前者 immutable，保存 preparation id/rev/hash、固定 Build/配置、source/readset、authority_snapshot、scope/owner、原 request_snapshot；初版为 draft，样件、acceptances、returns、offered_coverage 空，实际交样/接收/承诺/开测/结果/处置时钟空。Formal 新 request_created 是本次服务器命令事实，不是原准备或原失败 Run 的时钟。后续版本沿 Current CAS 追加，不覆盖历史。

现有 owner 合同接受固定合法准备版本，不必凭空要求发布；最短实际分支建议选择新准备的真实当前版，避免混用历史内容。配置引用固定于该准备，之后不能靠 method 操作替换测试项或配置；要改范围应另建新准备/请求。

### 回链（T1）

源码：`server/pdos_next/domain/capa_verification/{schemas,service,commands,models}.py`，公开包装 `quality_followup_views.py` / `quality_followup_integration.py` 与 `web/src/components/builds/build-quality-followup.tsx`。

`FollowupLinkPayload`：当前 logical `issue_id`+`expected_issue_revision`、真实 `capa_id/action_id`、1–20个真实 `output_refs`、可选实际 DefinitionReference sources、reason、共同 confirmation_token。来源覆盖原失败、Issue/CAPA 固定 basis、真实输出、当前政策和专业事实；当前 caller 必须有精确用途回链专业资格与 product 写权限，依赖真实共同已消费 T1 UUID callback。IO后再次独立核原失败/输出/安全/ACL/政策/专业事实；不存在用准备时 capability 或 hash 绕过重核。

回链保存前后 owner 输出、来源、policy、authority、shared_proof 与真实 received_at；全事务一次共同 Receipt/Audit/Outbox。`ACTION_NOT_COMPLETED` 可以如实保留，`ACTION_FULFILLMENT_PORT_MISSING` 必须保留；存在一个新请求不等于措施文字已满足。若原回链输出随后成为历史版，历史仍存在，但当前适用与旧意图重放需据真实 owner 再核，不推定自动 current。

## 允许复用与后续未完成关口

| 对象/能力 | 本次新分支可复用的边界 | 不能继承的事实 |
| --- | --- | --- |
| 原准备项/资料 | 可作为人工填写模板；固定合法原文与明确判据/条件可重新选择并核出处 | 不能直接将原 failure request 身份、旧接收/结果、旧方法专业认可移入新 request |
| Definition/BOM/工程/制造配置 | 同产品/项目合法固定 Build 引用且当前来源可用时可复用；无需重建第二套配置账 | 固定草稿/出处当前不等于工程发布、制造发布或新Run适用 |
| 既有 Build | 可以作为新准备/Formal 的固定计划身份 | 原 BuildStart/Run 资格与窗口不自动延长；已到期仍可保存计划请求，不因此允许新的交样/开测 |
| 真实 SampleUnit/Lot/ActualConfiguration | 物理身份与链保持原样；是否可用于新请求须后续当前用途 readiness、实际 sample/item 方法适用、配置、Current 来源核对 | unknown/hold 不变 ready；原 accepted coverage 不自动接受到新请求；不可用原测试结果当新测量 |
| 旧非破坏性样件 | 仅在真实用途/配置/执行资格有效且新窗口无占用冲突时，由后续端口核可复用 | 不靠旧 availability 字段或已结束 Run 猜可用；新的完整窗口/占用不得伪造 |
| 破坏性消费样件 | 原身份/历史可读 | SampleRunUsage destructive 为永久消费守卫，禁止再次分配；不能新建 request 绕过 |
| 方法/日历/资源 | 原文可作为新准备依据，资源物理身份复用统一 OperationalAsset/ResourceOccupancy | 每新 request 的逐项专业核对、实际 pair 适用与测试资格仍需真正办理；制造资格不授测试资格 |

真正执行独立复验仍需：新请求完整资料与逐项专业方法、合适样件/实际配置与 purpose-specific ready、正式 offer/accept 的完整范围、可信测试事实/具名 executor、Plan/Promise、真实非未来 Start 与同事务资源+样件占用、原报告/原值导入与确定性判定，以及独立性/方法适用性/观察期/真实政策 owner 的真实证明。offer/accept 读取当前 Build projection，必须 `executing + limited_current + stop_required=false`。窗口终点本身在 BuildStart capabilities 中关闭的是新的 start 动作；已保存执行是否仍有有限资格还取决于当前操作事实、批准有效期、原签核人/来源及占用证明，不能仅凭窗口结束推定必定失效，也不能仅凭旧Start推定仍有效。retained proof 只证明旧已保存执行，不是新执行许可。

Wave16 的新 Formal 请求 owner 已存在可用，**CandidateInspect 的适用性、独立性、观察期 bridge 默认缺失**；公开 candidates 仍为空/显式缺项，不生成 Run 或有效性结论。八类变更 facet UNKNOWN、有效性决定、关闭和正式 Change 实施/发布关口仍保留。

## 核验范围及主线读回要点

本审阅只确认现存 DTO、服务、Current/FK、UI 提交与后续读取接缝。主线实际办理后应读回：新 preparation 当前 id/rev/hash；新 Formal logical ID 与不可变行 ID、初版 Current、实际初始 Receipt+Audit+Outbox；新 output_options 包含此精确行；T1回链的 action/basis/ref/真实 received_at；空 samples/acceptances/实际时钟以及 null action_fulfilled/effectiveness/closure。不得把本报告当上述实测证据。
