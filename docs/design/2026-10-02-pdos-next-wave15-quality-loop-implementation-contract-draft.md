# 第十五波质量闭环实施合同草案

状态：**草案，未冻结或开工；当前队列仍为 Wave14**。本文只供主线决定下一批派工与接缝，不改变唯一清单、操作注册、批准或验收状态。依据[衔接草案](2026-10-02-pdos-next-wave15-quality-loop-draft.md)、[定向复用审阅](../reports/evidence/pdos-next-wave14-20261002/quality-reuse-review.md)、[执行方案 G3/§13](2026-10-02-pdos-next-execution-plan.md)及[新设计的变更 §13、canonical 操作与 AT-23/24/25](2026-10-02-pdos-complete-target-architecture-v1.md)。

## 1. 用户结果与首版范围

从同一已实际执行的 Run 出发，分别看原值、固定规则结果、专业意见与请求分母；核对不确定项或选择确定失败，进入原问题/调查、遏制与 CAPA，再提出有来源的变更和双线影响，回到下一轮配置、Build 或验证准备入口。首版交付“确定失败 → 去重 Issue → 分诊/实际遏制/CAPA 草稿 → ChangeRequest/固定影响/UNKNOWN → 有依据的下一轮准备”。不把准备草稿当实施或整改有效；不覆盖旧结果、解除原占用、恢复已消费样件或授正式放行。

**不确定与失败必须分路，主线已明确此入口边界。** 旧 `quality.issue.create` 只接受确定 fail；旧 Issue 要求至少一项真实 FailureRef。当前 Wave14 工况差异 Run 保持 indeterminate，只读展示原值、缺项和调查提示，不能建失败单。原值/方法/资料缺失、无效或范围不足均不产生失败身份、确定失败 Issue 或 CAPA 有效性事实；本波不新增 uncertain Issue 辅助合同，也不放松纯核。闭环联验另行取得有可核合成原件与实际执行依据的确定失败，保留当前原值和旧 Run，不将工况差异改写为 fail。

## 2. 保留的对象所有权与规则

复用 `quality_issues` 的 FailureRef/Issue/CAPA、稳定身份、归并 alias、分诊/遏制、根因假设、措施及独立有效性/关闭规则；复用 `change_control` 的 ChangeRequest/GraphSnapshot/ImpactAssessment 与有出处边遍历。原纯包先冻结，新增宿主适配，不导入旧 `server/app` 写服务、可变记录或 ECR/ECN 批准。

当前 Run 版本链、`MeasurementRecord`、`TestResultProjection`、`TestResultActionFact` 仍是唯一结果真值。Issue 引用精确测量、实际 Sample/ActualConfiguration、方法/判据/出处、核 Run 版本和服务器性质，不复制第二份测量；`FailureRef.run.revision` 不取测量表 `revision=1`。CAPA 暂嵌入 Issue，不伪造独立版本：跨域引用使用 Issue 聚合版本与 CAPA key。根因假设、确定性 fail 与专业处置各自保存。

工程固定链为 Definition/Spec key → Part/BOM 行 key → EngineeringConfiguration → Build/Sample/Run；制造固定链为 Part/BOM 关联 → ProcessRevision 工序 key/SOP/资源要求。正式 Tooling/Fixture/ControlPlan/PilotRun 等未接时保留缺节点与 UNKNOWN，设备实体和 ResourceRequirement 描述不能替代它们。供应快照 `scope_complete=false` 不会在影响图中变为 complete。

## 3. 共同命令、事件与原子性

沿用实际 `contracts.Command`（本文称 CommonCommand）：`command_id/idempotency_key/operation/product_id/expected_revision/source_read_set/payload`；公共 expected_revision 是 Product 版本，Issue/Change 聚合版本单独绑定。不会新增 CommandAction、回执、确认或审计账本。具名身份、tenant/project、受众、风险/职责/资格、性质与当前时间由服务器取得，不由载荷布尔或 ProductGrant 推导。

当前 Outbox 无业务 payload。结果导入/复核/处置事件的 subject 是精确 RunVersion；计算事件的 subject 是 Projection。`RunPort.delivery` 沿 Outbox → Receipt 核 tenant/product/operation，再读取该 RunVersion 或 `Projection.run_version_id`，验证所选 Measurement、判据和失败；模型或浏览器 event UUID 不直接成为事实。Inbox 的 `(tenant,consumer,event)` 只记一次投递，另设 `(scope,event,failure_identity)` 映射支持同事件多失败；业务失败稳定唯一映射再单独保存。稳定失败排除 event/key/title 和无关 Run 续版，归并保留原单、别名与历史。

适配函数遵循主线 `validate/semantic/preview/apply/replay`：dedup 前核当前身份、读权限、精确来源、安全/issuer epoch 与专业授权；新写再核聚合 CAS/current pointer。合法重放返回原 Receipt，不回退 Current、不重消费证明。纯 handler 的 begin/replay/confirm/record 绑定调用者同一 Session 与共同层已接受的证明；record 仅暂存领域 mutation，不双执行或自行 commit。锁序统一 Product → 稳定失败门栓/Issue；归并按稳定 ID 顺序锁全部聚合。领域、唯一映射、证明消费、Receipt/Audit/Outbox 任一步失败整组回滚。

原件 I/O 与纯核值之间不长期持事务锁，回到保存阶段重核当前 ACL、原件安全/完整性、issuer epoch 和保存的执行证明。自然窗口到期与真实撤回分开；历史可追溯不代表可再次执行。来源并集去重超过共同 20 条上限清楚拒绝，不截断读集或隐去未读范围。

## 4. 待主线采纳后冻结的 DTO 与端口

以下是**派工候选合同**，不是已经上线的新 API。全部 payload `extra=forbid`；服务器专用 adapter 映射到旧纯包封闭 DTO，不能把 UI 阅读对象直接交给 handler。

| DTO/操作 | 候选载荷或输出；关键守卫 |
|---|---|
| `FixedQualityResult`（只读） | `run:{id,revision,version_id,sha256}`、`measurement_id`、`projection:{id,revision,basis_sha256,rules_version}`、固定 sample/item/config/method/criterion/source、原值读取投影、`result`、服务器事件引用、`source_status/currentness/nature`、`required_source_read_set`、当前 authority/capabilities/blockers。只提供已核可读原值，不接受客户端值或资格。 |
| `quality.issue.create` T0 | 保留 `{run_id,measurement_id,event_id,title}`；由事件及权威结果绑定精确版本。服务器复算具体测量为 fail 且与核 Run/Projection 一致，稳定身份解析原 Issue；领域目标为 Run、前版 0，新 Issue ID由稳定失败确定。 |
| Issue 目标信封 | 其他操作在宿主 payload 绑定 `{issue_id,expected_issue_revision}`，再映射专用字段；不混公共 Product revision。CAPA key 为 `capa_id`，引用水位为所属 Issue revision。 |
| 分诊/遏制/CAPA | `quality.issue.triage:{reason}`；`quality.issue.containment.record:{action:{id,text,executor_id,evidence,at}}`；`quality.capa.draft:{capa_id,hypotheses:[{text,sources}],actions:[{id,kind,text,executor_id}],requirement:{method,acceptance,observation_until,required_failure_ids}}`。risk/独立政策来自服务器；草稿禁止 completion，真实事件时钟不默认 now。 |
| 后续根因/完成/重核 | 保留旧DTO：`quality.issue.root_cause.decide:{text,sources}` T2；`quality.capa.actions.complete:{completions:[Containment]}` T1；`quality.issue.recheck:{reason}` T1。首版不默认注册这些辅助操作，根因不可覆写、执行人须实际本人、完成只到待验证。有效性/关闭没有可信新 Run/观察端口时能力 false，不能作合成正例旁路。 |
| Change 目标与建立 | 宿主绑定 `{change_id,expected_change_revision}`，create 为领域前版 0；ID由稳定准备意图分配且 insert-only，换 UUID 不绕过 Receipt 去重。`change.request.create` T0 专用字段沿旧 `RequestCreate:{title,reason,roots,references,sources}`，引用固定 Issue/CAPA；Spec/BOM/工序等 Ref 必须含精确 key。分配/重放策略须主线冻结。 |
| 图捕获/影响 | 服务器依据固定 roots 构造 `GraphSnapshot:{id,revision,scope,audience,roots,nodes,edges,coverage,sources,captured_at,expires_at,nature}`。客户端只选 roots 和现存来源；不提交 graph/complete/nature。`change.impact.compute` T0 只接 `{snapshot:Ref(kind:'graph_snapshot'),hypotheses}`，保留 known paths、双线、八 facet UNKNOWN 和独立假设。 |
| 下一轮回链（只读） | 沿旧 `FollowupNeed:{kind,source_issue:Ref,failure_ids,reason}` 扩展读取固定 ChangeRef、受控意图与所有者真实输出引用/原回执。没有真实输出时为空并显示待准备；不由建议 ID 构造已创建 Build/Run。是否新增持久关联命令见待定点。 |

来源边界冻结为两层：人工选择保留精确 `DefinitionReference{artifact_id,expected_revision,line,quote}`；纯核使用服务器映射的 `SourceRef{id,revision,kind,position}`，位置/全文摘要由同份原文核验派生。domain 资格/配置 UUID 不伪装 Artifact readset；专业 fact_refs/epoch/policy digest另纳入共同实质证明。私有来源或跨客户材料不得扩大输出受众。

须导出窄只读结果端口（例如 `fixed_failure_result`）给 A：装配 `VerifiedRun + Measurement/Projection + event + readset/source_basis/currentness`，重验历史 Start/计划/原占用/样件使用、原件与当前办理资格；不得直接复用结果操作专用 `_load/_new_write` 充当通用 Issue 服务。`RunPort.original` 必须按归档精确版回读；`PolicyPort.assess/verification` 提供固定风险/独立政策、新 Run/配置适用性、完整 failure_ids、全部执行人及真实观察起止；缺端口显式 INTEGRATION_REQUIRED/UNKNOWN。`qualified is True` 才映射旧 bool资格，null/false均不放行。

## 5. 公共入口与界面读模型候选

- A：`GET /v1/products/{pid}/quality-execution?build_id=&run_id=` 返回固定结果/不确定缺项、Issue历史、`current_by_issue`、真实责任人/可用独立证据、逐对象 authority/capabilities/readset/policy/blockers、`followup_needs/has_more/unavailable_count`。
- B：`GET /v1/products/{pid}/change-execution?issue_id=&change_id=` 返回固定 ChangeRequest历史与Current、graph/impact、双线 known/UNKNOWN、来源状态、逐对象能力与后续输出引用。图捕获 POST仅选择固定 roots/来源和理由；有效期/覆盖/性质由服务器决定，具体 route 与 DTO 待采纳。
- A/B：各自 `POST .../inputs` 接完整 CommonCommand，返回 `{operation,allowed,authority,required_source_read_set,source_status,binding,blockers}`；只读、不保存、不 mint token。T1/T2 沿共同 `/v1/commands/preview` 返回 `{command,expires_at,review:{before,after,effect,authority,...}}`，T2 明确 write_tier/approval_token；原封提交 prepared command。T0 没有额外人工确认但仍核授权与资格。

wrapper 使用已有 product/principalId/api/onSaved props。空选择不深读全部历史，按明确 Build/Run → 具体测量 → Issue → Change逐层读取；旧版只读。失败、调查缺项、CAPA假设、当前适用性与历史决定分栏；能力严格读服务器逐行字段。私有范围切换清空旧读取与预览；旧 READ_SUPERSEDED 不误报失败，真实失败仍显示；提交未知保留同命令/key/token，成功后刷新失败不重发。每次 T1/T2 展示全部固定来源、范围差异、风险政策及当前专业事实。

## 6. 回到下一轮，而非自动宣布整改成功

影响 UNKNOWN 时允许整理下一轮草稿需求，但禁批准、实施、生效及关闭。已有对象所有者可按原合同准备新定义/BOM/工程或制造配置 draft，并明确“尚非已批准变更输出”；不存在新对象时只留意图。真实 ChangeOrder 批准与 EffectivityPlan 后续接入时，工程与制造分别具名决定，逐对象/批次/序号、条件、期限、在制和培训处置固定；sent/accepted不当effective。

下一轮 Build或正式请求必须固定新双配置/用途，由现有入口另办准备、具名授权、实际产出与样件、交接、方法、资源和开测。当前限制一 request 一 Run；不换 Run ID伪造同请求多 Run。原样件消费/hold保持，新样件或经权威核对的可用范围独立取得。不从原 Run pass/失败、现有实物观察或任务 done推下一轮资格。

复验结果与实际观察满足政策后，CAPA有效性 T2、Issue关闭 T2、变更独立 Verification/关闭 T2仍分别记录；原失败 Run和措施执行人不能自证。没有真实观察期或完整范围时保留待验证，旧 CAPA 无效后的追加措施/修订能力另需版本化合同。工程/制造发布、客户/法规、外发/ERP/MES、自动资源释放均不在本波首版范围。

## 7. 三路独占与主线接线

| 路线 | 唯一新文件目录 | 先冻结的接缝 |
|---|---|---|
| A 品质持久宿主 | `pdos-next/server/pdos_next/domain/quality_execution/{models,schemas,adapters,service}.py`、`server/tests/quality_execution/` | IssueIdentity/Version/Current、稳定 FailureMap、EventFailureLink；CAPA/alias/历史随不可变聚合；FixedQualityResult/IssueRef/FailureRef/CAPA key与完整 readset/capability。 |
| B 双线提案宿主 | `pdos-next/server/pdos_next/domain/change_execution/{models,schemas,graph,adapters,service}.py`、`server/tests/change_execution/` | ChangeIdentity/Version/Current、固定Graph/Impact；消费 A固定Issue/CAPA Ref，先接 request.create/impact.compute，UNKNOWN时不开放 Order后续能力。 |
| C 办理wrapper | `pdos-next/web/src/components/builds/build-quality-loop.tsx`、`web/src/lib/build-quality-loop-view.ts`及同名测试；仅本波 `ui-*`证据 | 复用旧 quality_issues/change_control只读组件，按冻结 A/B DTO接同一结果→Issue/CAPA→双线影响→下一轮入口；不改旧结果组件或公共API。 |

A先交 typed引用/模型约束，B/C不等A全包完成即可并行；B图适配可独立核真实所有者边。旧纯包保持冻结，必要变更再明确归属，不以纯handler回调开第二套事务。

主线独占当前结果/配置窄端口、共同专业/操作/tier/event/Receipt注册、旧版本链、模型导入、真实 head单调迁移及RLS/全scope FK/CAS/immutability/alias防环、原件生命周期引用保护、API/BFF/Workspace、统一 PG/公共构建/浏览器与唯一清单。先冻模型/DTO，再集中公共接线与受影响联验；Wave14候选运行期间不并行修改其生产代码。

## 8. 候选验证与待定点

公共验证统一覆盖：精确fail与unknown分路；同失败跨key/event一单、同event多失败不漏、不同失败/相似标题不误并；归并alias并发/CAS；Product/领域版本及预览来源漂移；private/RLS/Agent零直写与当前资格前置；真实Outbox/Receipt桥接；末端故障回滚映射/证明/业务/回执/审计/事件全组；原件安全/issuer撤回与自然期限区分；真实图工序/SOP已知、正式治具/八facet缺边UNKNOWN与禁批准；本机恢复/未知重放、成功后刷新失败、亮暗/窄屏及历史回读。纯包旧结果不拼接成本波通过，AT-23/24/25/33/35/42及G3完整验收仍按实际覆盖记账。

派工前主线须决定：①当前风险/独立政策的可信发布来源、操作职责/用途及T0资格；②Change新ID/图捕获意图、有效期和跨key去重规则；③下一轮需求/真实输出的持久关联是否需辅助T1；④明确要接的辅助动作/event/subject_type（canonical等级不改）。确定失败与不确定只读的入口差异已明确，不再作为待定合同。完整制造图、新复验/观察事实、CAPA续措施、实施/生效与分别关闭保留后续条件，不用合成fixture补成生产事实。本草案不授真实整改效果、生产启用、正式发布、外发或任何人工Exit。
