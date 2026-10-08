# G3 双线变更组件接线

组件在 `pdos-next/web/src/components/change_control/`，未接父页面、路由、BFF、公共 registry 或业务数据。合成 fixture 仅在 `__tests__/`，不从生产 index 导出。复用现有 Button、语义颜色、8px 圆角与 Phosphor，未写全局 CSS、依赖或公共文件。

## 父工作区合同

`ChangeControlWorkbench` 消费受控 `draft/onDraftChange`、服务器 `request/context`、父 `action` 和 `sharedReview`。`onPrepare(intent,contextKey)` 是唯一动作回调，只对接共同预览或 T2 候选准备。没有组件 `onConfirm`、token、命令 ID、回执存储或第二套确认实现。父将现有共同实质预览、一次确认、具名决定及原回执查询节点传给 `sharedReview`。

父组件每次输入变化须以 `editorIntent(draft,request,context).intent` 同共同已准备 intent 比较，编辑后使旧预览不能确认。来源、对象、权限、政策、取消或 scope 变化都必须改变 `context.key`，并重新校验共同预览摘要、有效期、读集和目标版本。失权/切换 scope 时清空旧敏感投影及预览，不能只更新 key。`onPrepare` 由共同 host 捕获错误并提供 `action.error/busy/unknown/receipt`；没有对应事实时设置 `portReady=false`，未注册动作 `registered=false`，不能默认放行。未知或成功无完整回执 ID 时停止准备，只由父核对原动作；主线稳定幂等意图和一次 token 消费处理重复点击及并发。

上下文中的 actor、capability、source status、current、serverVerified、independent、excluded IDs 都是服务器只读投影。提交只取固定引用或候选载荷，服务器端口仍独立核验；不要把这些 UI bool 上传作政策事实。T0 必须主线核对真实资格/当前授权。AI T2 的 `candidateAllowed` 只允许准备候选；父不能给 AI 显示具名提交按钮或消费 T2 proof。主线换到真实具名人时重新准备当前内容与读集，不能复用 AI 身份预览。

## 动作映射到封闭后端 DTO

当前后台入口以 ChangeRequest 为 aggregate CAS，UI `request.revision` 传共同 expected_revision；UI order/assessment/plan 的 revision 是固定聚合版本投影，不伪造独立持久版本。

| UI intent | 封闭 payload / 主线映射 |
| --- | --- |
| `change.request.create` | RequestCreate `{title,reason,roots,references,sources}`；来源剔除 UI status，Ref 保留 key；subject ID 由主线分配/绑定，不导入旧账号批准。 |
| `change.request.revise` | RequestRevise 同固定新根/来源字段；expected_revision 取 request，不抹旧 assessments/orders/history；T1候选，须主线注册。 |
| `change.impact.compute` | ImpactCompute `{snapshot:intent.snapshot,hypotheses:[]}`；snapshot.kind=`graph_snapshot`。`fixedInputs/sourceScope/audience` 只用于父预览说明，实际 GraphSnapshot 从 FactPort 绑定；hypotheses 若接入则来自独立候选和精确来源，不能转为边。 |
| `change.order.prepare` | OrderPrepare `{assessment_id:intent.assessment.id,plan:intent.plan,reason:intent.text}`；`CommandPlan` 原样保留 backend snake_case plan、items、selection.units、dispositions、expires_at；不从显示批次/序号重新构造。T1候选，须主线注册。 |
| `change.order.approve` | OrderApprove `{discipline,text,expires_at:intent.expiresAt}`；共同 T2 proof绑定此专业、scope、policy、content_digest/有效期。每个专业分别办理，不继承其他专业/客户承认。 |
| `change.implementation.record` | ImplementationRecord `{item_id:intent.itemId,fact_id:intent.factId}`；只选择所有者已持久、当前实施者本人、当前固定意图的 ImplementationFact，T1。界面不补写结果、outputs、时钟或实际配置。 |
| `change.effectivity.record` | EffectivityRecord 同 `{item_id,fact_id}`；实际回执由 FactPort 核验。sent/accepted 不投影为 effective，unknown/failed不补成功；相同外部回执去重由主线事务处理。T1候选，须主线注册。 |
| `change.verification.record` | VerificationRecord `{fact_id,text}`；结果来自已核验 VerificationFact，不从模型或浏览器下拉取 result/applicable/current。T2候选，须主线注册。 |
| `change.close` | Close `{text}`；具名独立复核人再次 T2，共同层重验当前全部覆盖和有效性。 |
| `change.recheck` | Recheck `{reason:intent.text}`；T1记录失效原因，历史不改写；具体重新根/来源修订使用上方独立 revise，不能使旧决定自动恢复。 |

父不得把整个 UI intent（含 request/order、阅读字段或 status）直接发送给闭合 DTO。`sources` 只映射 `{id,revision,kind,position}`，引用只映射域 Ref `{id,revision,kind,key?}`。客户端没有 tenant/project/actor/资格输入。

## 读模型映射与缺项

`ChangeControlReading` 独立展示来源、固定影响、各专业批准、生效计划、实际实施、实际生效、独立复核和关闭。`ChangeImpactReading` 需从固定 GraphSnapshot 的 known row.path 找到 exact Edge；保留全部节点固定引用及边出处，分别按 engineering/manufacturing lanes 构成路径。operational lane 的库存、WIP、培训、在制 Build、客户样件与证据适用性落 effects；unknown/facet 原因逐项落 unknowns。缺边显示 UNKNOWN；无列出的 unknown 只意味着本次固定来源范围未列缺项，不证明全系统无影响。AI hypotheses 始终独立分栏。

`EffectivityPlan.scopes` 每项对应真实 PlanItem.id，显示全部 selection.objects、完整 units token、条件、来源与服务器受众；显示 serialRange 只有来源确实提供明确区间时才填，不把离散序号强行压成全区间。`CommandPlan` 保留精确源载荷，逐对象 dispositions含 rationale/sources/item_ids；影响评估中任何缺边/来源/覆盖 UNKNOWN 或 UNKNOWN处置均阻止准备批准，后台仍独立以 IMPACT_UNKNOWN拒绝。库存/WIP、培训缺规则显示 UNKNOWN，不以空字符串当无要求。

`implementations` 时钟来自所有者原事实，occurredAt 与 recordedAt 分开；backend succeeded → 显示 completed，不触发生效。`effectivity` 需保留 stage、external_id、fact_id、item_id、output_refs、covered_units；`effectiveScopeIds/awaitingScopeIds` 必须由后端当前规则核算完整 item全部 units/conditions覆盖，不由 UI 按单次 success 或日期累计。局部 units 覆盖投影为 partial，缺真实回执不生效。新配置/Build/Run 的所有者固定输出放实际引用，未创建时 actualRef=null，受控意图不作真实对象。

`verification` 显示历史 pass/fail → effective/ineffective 的独立具名结论，保留原决定；FactPort 的新 Run/输出适用性、实际观察期、来源 nature、全部 item覆盖与专业政策均需后端通过。excludedReviewerIds 来自请求提出者/各专业批准者/全部实施及测量执行者，不能从用户输入猜。closure独立记录，不从最新 pass 推导。source/配置/政策漂移保留历史事实并展示 requiresRecheck，不授权新执行。

## 事务、失败恢复与未完成验证

本组件不执行数据库事务。领域事实、CAS、共同proof消费、stable receipt、Audit、Outbox、导入fact去重必须由主线同一个 caller Session 原子提交；任何失败全部回滚。公共接线后集中验证并发/重复回执、部分范围、失权、source/configuration漂移、取消/过期、实施故障、独立复核、真实DB/HTTP/浏览器亮暗/窄宽/键盘和恢复。不将本包合成组件检查等同这些验收，也不宣称 G/N/P/Q 出口通过。

当前未接线项：真实 owner fact入口、服务器 GraphSnapshot/plan候选、主线 capability/资格/currentness、共同预览/一次确认/T2 proof与回执恢复、aggregate阅读mapper、BFF/父页面/registry/迁移/RLS。后台最终接口复核包括 ImplementationFact/EffectivityFact 的 reconciles_id、FactPort.audience 的来源到目标受众使用授权及 handler 原未知实施/外部回执对账限制：这些均由服务器绑定核验，前端继续只发送 item_id/fact_id，不上传 reconciles_id、受众授权布尔或对账成功声明。恢复后原 unknown 历史仍保留，须后端核验同一次执行/外部ID/意图/时点与完整未知范围，未对账不能换新回执盲重发。公共验证由主线执行。
