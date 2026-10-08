# 第十六波品质整改后续合同草案

状态：**只读衔接草案，待主线复核；未冻结实施合同、未开始本波施工或验证。** 第十五波公共 PG 与业务演练由主线继续，本稿不据此声明该波通过，不更新唯一清单。盘点时间：2026-10-02。

依据：[完整目标架构 §13 变更与黄金路径 D](2026-10-02-pdos-complete-target-architecture-v1.md)、[执行方案 G3.1～3 与 §12～13](2026-10-02-pdos-next-execution-plan.md)、[第十五波冻结实施合同](2026-10-02-pdos-next-wave15-quality-loop-implementation-contract.md)。代码中的 DTO、端口和纯规则是可复用实现，不等于对应持久动作、可信事实或人工出口已经交付。

## 1. 建议的下一段业务结果

以已有的当前 Issue/CAPA 为入口，接通“具名根因结论 → 本人记录真实措施完成 → 固定新对象/新复验分支回链 → 独立复验事实与观察期缺项”。用户能看到谁完成了哪项措施、实际发生时间、对应新配置/样件/Run、哪些原失败得到覆盖、为何仍待验证。**本稿建议的 Wave16 最小范围不注册或启用有效性决定、Issue 关闭、ChangeOrder 批准/实施/生效；这些能力保持明确阻断。** 后续另冻结完整政策与证据端口后，才考虑 canonical `quality.capa.effectiveness.decide` T2 和独立的 Issue 关闭。

首个可用检查点以根因、措施事实、精确回链和一条真实保存的后续复验分支为共同业务闭环，不能只交空白 Evidence 表或入口。新分支可先保存准备/正式请求与待办；实际测试条件齐备后沿既有 owner 办理新 Run 和原报告，保存可重核的复验候选。缺人员、材料、资源、方法、真实观察期等前置时保留具体阻断及已办事实，不补造 Run 或 pass。合成正例必须全程保留 synthetic 性质，不能作为现实整改有效、生产放行或人工 Exit；“复验候选满足目前可核项”也不等于 CAPA effective。

涉及正式工程/制造变更的措施，仍须先取得完整影响与 ChangeOrder 批准，才能声称正式实施。八 facet 未知时可以准备未批准方案、研究用新配置草稿及独立复验计划；不得将这些对象的创建回执登记成“批准变更已实施/已生效”。这一路的完整交付依赖下文第 5 节，不用 CAPA 完成按钮绕过它。

最小演练宜选择有实际来源、无需声称正式配置切换的调查/检查类措施。若某 action 的文本实际要求“正式改版并切换量产”，只有研究草稿或检查报告不足以记录该 action 完成，须保持未完成。设计/制造发生变化的独立复验须引用 owner 新增的固定双配置和新 Build；不改变配置的调查复验可以复用当前仍适用的固定 Build/实际配置，但仍须新请求/新 Run、当前实际方法/样件就绪/接收及资源资格。两条路线都不把原失败 Run 当复验。

## 2. 可复用的规则与实际接缝

| 当前模块 | 可直接复用内容 | 需要新增或接通的事实 |
| --- | --- | --- |
| `domain/quality_issues/handlers.py`、`schemas/quality_issues/contracts.py` | `RootCauseDecide`、`ActionsComplete`、`EffectivenessDecide`、`IssueClose`；按聚合追加、状态守卫、本人完成、观察期、全部失败覆盖和独立性判断 | 持久 adapter 目前只开放建单/归并/分诊/遏制/CAPA 草稿；上述后续载荷和共同命令尚未接入 |
| `domain/quality_issues/handlers.py::_verification` | 措施全完成、根因先决、原失败 Run 禁止复用、实际观察窗、相同 nature、精确失败集合、有效/无效的确定证据分路 | `PolicyPort.verification` 必须返回真实固定新结果；`quality_execution/adapters.py::BoundPolicy.verification` 当前明确 `INTEGRATION_REQUIRED` |
| `domain/quality_execution/` | `QualityIssueVersion/Current`、当前政策、原失败精确桥、原件/原生文本来源核对、CAS、源并集、共同事务和历史只读 | 由主线扩展既有聚合保存入口，不能另建一套 CAPA/Issue 真值；现 `followup_needs.created_output=None` 只是下一责任建议 |
| `quality_result_bridge.py`、`domain/quality_execution/ports.py::FixedQualityResult` | 固定 Run/Measurement/Projection、真实原值出处、规则版本、原执行保留证明、当前来源和受众 | 现桥服务原失败逐测量读取；复验桥须聚合新 Run 的真实覆盖与独立复核依据，不能换成最新 Run 或仅比较 aggregate=pass |
| `domain/verification/rules.py::compute_results`、`measurement_evidence/`、`verification_results/` | 原值逐字符保存、部分/未知判定、单位/工况/方法核对、实际执行绑定、具名结果复核与处置 | CAPA 要求到新测试项/判据/实际配置的适用映射，及满足观察期的事实来源；一般“测试已通过”不能替代映射 |
| `domain/configurations/`、`builds/`、`build_start/`、`build_execution/` | 追加新 BOM/工程配置/制造工艺版本，真实新 Build、用途限定开工、实际双配置/批次/样件身份 | 草稿不是发布；新生产实际配置不能由修订草稿自动生成；变更批准/措施适用性仍独立核对 |
| `verification_execution/`、`verification_front/`、`verification_handoff/`、`verification_launch/`、`test_resources/` | 新准备请求 → 正式请求 → 实物/实际方法 → 接收 → 计划/承诺 → 原子资源与样件使用 → 新 Run | `VerificationRunIdentity` 当前每逻辑请求最多一个 Run；复验必须建新请求，不给原请求塞第二 Run，不复用破坏性已消费样件 |
| `domain/change_control/{handlers,rules,ports}.py`、其 `schemas` | 双线影响、固定计划/专业批准、实施/生效/未知对账、独立验证/关闭规则 | `change_execution/adapters.py` 的 selection/implementation/effectivity/verification 当前均为未接入端口，不能以 empty/true 代替 |

旧纯测试 `tests/quality_issues/` 与 `tests/change_control/` 可沿原样规则选取受影响场景，不重复复制算法。第十六波新增持久/HTTP 测试应验证实际 owner 接口、来源、事务和并发，不能把旧 fake host 的 complete graph 或 pass evidence 移植成真实资格。

## 3. 动作、分级与不可继承状态

| 动作 | 注册建议与真实前提 | 保存后允许的结果 |
| --- | --- | --- |
| 根因结论 | 旧核已明确 `quality.issue.root_cause.decide` **T2、具名人、quality 职责**；它不是 canonical 首版动作，持久主线仍须显式注册及专业矩阵。仅 actioning 且无已有根因时，用当前资格和固定来源提交 | 追加 `NamedConclusion`；actor/决定时点取服务器，保留原假设。不得把 AI 假设接受、测试处置或工程角色本身当根因结论 |
| 措施完成 | 旧核已明确 `quality.capa.actions.complete` **T1、具名人**，持久主线仍须显式注册；每条必须已指派执行者本人，completion.id 对应原 action，已发生 EventTime/精确证据且不覆盖旧 completion | 可按本人负责的部分措施逐次完成；未全完成继续 actioning，全完成进入 awaiting_verification。旧核不要求根因先于“记录已经发生的完成”，但有效性必须有根因；UI 推荐先根因，不伪造新增状态前置 |
| 新对象/复验回链 | 新辅助 T1 候选，名称/合同待主线冻结；对象由既有 owner 创建，再固定引用回链 | 保存实际输出身份与待验证范围，不授批准/实施/生效 |
| 独立复验办理 | 建新请求、实际方法/接收、`test.run.plan`/承诺/实际 start 沿现有合同；`test.results.import` **T1**、`test.result.compute` **T0**、`test.run.review`/`test.disposition.decide` **T2**。复验回链/候选记录为待注册辅助 T1 | 保存新 Run 固定原值、确定判定及独立复核事实；Run 的 review/disposition 不授 CAPA 有效性或 Issue 关闭，也不自动令整观察期合格 |
| 有效性（本最小范围未开放） | **canonical `quality.capa.effectiveness.decide`，T2**；需当前政策、品质专业、独立人、所有措施及全部失败的当前适用新证据；现 `BoundPolicy.verification` 为 503 | 后续才允许 effective/ineffective 分开；当前 capabilities=false，未知保持待输入，不自动关闭 |
| Issue 关闭（本最小范围未开放） | 旧核 `quality.issue.close` **T2**，属于待显式注册辅助动作；必须已有 effective、同一有效性复核人本人、同一政策/证据 read_digest 再核 | 后续另具名关闭；当前保持 false，历史关闭若存在只能保留并显示适用性，不授本次关闭 |
| ChangeOrder/实施 | **canonical `change.order.approve` T2、`change.implementation.record` T1**；完整影响、当前政策、分别专业批准、真实 owner 新输出 | 批准、实施、实际生效、独立验证和关闭分别推进，Issue 关闭不联动关闭 Change |

`quality.issue.recheck`、`change.request.revise`、`change.order.prepare`、`change.effectivity.record`、`change.verification.record`、`change.close` 是已有纯核辅助候选，不能因为类或 handler 存在就宣称 public canonical 已开放。T2 保持具名决定、独立用途/专业资格；ProductGrant.can_write、AI Qualification、方法计划、结果 review 或测试 disposition 均不替代它。

纯核已固定独立性：CAPA 复核人不得是原测试执行者、措施执行者、遏制执行者、根因决定者或新证据的测试执行者；高/关键风险或独立政策还要求证据复核人本人决定。Change 独立复核另排除提出者、批准者和实施者。不要把两种独立性缩成一个“不是当前操作者”条件。

T1 完成事实同样须当前作用域/用途/操作资格，不能只检查 action.executor_id 或 ProductGrant。旧 quality 核一般角色为 quality/engineering/test，T2 另限定 quality；若现措施指定纯 manufacturing 人员，而主线尚未定义其本动作专业合同，应明确阻断/补合同，不能假授 test 身份。注册新操作矩阵不等于给任何人新增职责或资格；真实事实只能由可信签发入口提供，合成 profile 继续受独立目标/marker 限定。所有 T2 使用共同具名 approval proof，T1 使用共同一次 confirmation，均不由子适配器重复消费或另发 Receipt。

完成 EventTime 须有可核对同一 action、executor 和实际 occurred_at 的精确原文；适配器不能只因引用一段合法但无关文字就接受任意时间。实际发生/原始时区与服务器 received_at 分开，允许如实延迟登记，不能用计划日期、根因决定时点、录入时点或旧测试时钟补实际完成。根因的 `NamedConclusion.at` 是本次服务器具名决定时点，不能冒充实验/措施发生时点。

## 4. 最小新增对象与端口草案

建议仅新增整改回链与有效性证据两个不可变对象，不复制 Issue/CAPA 或 Run。

- **RemediationLink**：固定 logical Issue + 聚合版、CAPA key、措施 key、当前要求摘要，原失败 IDs、basis refs；实际输出 Ref（新配置/Build/Request/Run 的完整版本与必要 item key）、owner 回执及来源；purpose/受众/nature 服务器绑定。研究草稿、待开测、实际完成分别呈现。关联已有 Change 时保存 fixed Change/Order/item；未批准不得标 implementation。
- **CapaVerificationEvidence**：固定上述整改/要求、新 Run 行版本、Projection/规则、实际双配置/样件/测试项、每个原失败到新 pair 的映射、实际方法/判据适用依据、原报告定位、observed_from/until、全部 executors、具名独立 verifier、源读集/安全 basis、政策/专业版本。current/applicable/result/nature 由可信 bridge 重核后产生，不从公开请求收布尔事实。
- **聚合决定**：根因、完成、有效性、关闭继续追加 `QualityIssueVersion`；不另造 Current truth。两个新对象的撤回/更正需保留旧版并使依赖明确重核，不能直接改 pass/时间/原始输出。

待冻结的接口方向：`resolve_followup_outputs(s,ctx,pid,fixed_issue,capa_key,action_key,output_refs)` 逐 owner 核实际身份/状态；`inspect_verification(s,ctx,pid,fixed_issue,evidence_ref,*,at,write=False)` 返回旧纯核 `VerificationEvidence` 加固定 basis/完整读集/缺项；公共 validate/semantic/preview_view/apply/replay/inputs/list 均沿共同服务，不另开事务或另发 Receipt。这些名字只是草案，未定义 runtime 可调用协议。

CAPA requirement 的 method/acceptance 目前是有来源的文本，不足以证明新测试适用。新增映射必须固定每条原失败、新测试项、实际方法/判据、改变配置及作用范围的可核查依据；不得只填相同 requirement_digest 或复用原样件 ID。无相应 owner/专业适用端口保持 unknown/503。

### 固定版本与需重核边界

写入始终用当前 logical Issue 的 CAS、真实 CAPA/action key、当前操作者资格及完整来源。历史版本可读不等于允许续写：`not_evaluated_historical`、merged source、`needs_recheck`、源撤回/安全 epoch 漂移或 owner proof 不可再核都不能借“确认已看过”清除。原失败的固定 measurement/configuration/判据/原值不变时，不应只因无关 Run 聚合版增加就否认失败；主线仍须通过既有精确 FailureRef 与 retained owner 接口证明，不能放宽成整个历史都 current。

根因或完成会推进 Issue 聚合版本；Wave15 Change 的 roots/references 固定原 Issue 聚合版和 CAPA key，**不会跟随推进**。旧 Change/capture/Impact 原样保留，但新 capture/compute 当前会因固定 Issue 成为历史而要求重核；已有 capture 还受十分钟期限、authority/source/issuer/runtime basis 约束，不能续期或重命名复用。未接 `change.request.revise` 的首版，只有确实改变当前固定 basis 的新 Change 才能经正常 server 语义身份创建并重新捕获；不复制旧批准、不任意换 UUID 绕幂等，也不以新单消除八项 UNKNOWN。后续若开放 revise，必须单独冻结前版 CAS、旧评估/批准失效与恢复规则。

当前私有 Issue/原件/实际样件只对其受控 owner 可读时，独立复核人即使有 ProductGrant 与 quality 资格也无读取权。可以继续本人根因和措施事实，独立复验/有效性保持不可推进；不得重建同一 Failure 的公共 Issue、改旧 visibility 或代独立人签字。需另冻结合法受控分享/受众变更接口，或对真正的新对象在创建时就满足适当受众；新的受众也不得扩大所引用私有来源。原私有历史仍保留，不把开发便利当用户分享授权。

RemediationLink/复验候选应保留创建时的 Issue 版、CAPA/action/requirement/失败集合摘要和对应 completion/输出的精确 proof。后来合法的聚合追加不改旧 link；使用候选前再与当前相同 CAPA/action/要求、源和真实 owner 状态核对。不能无条件要求所有历史 link 的 Issue 版等于最新而使自己的完成/复核动作循环失效，也不能跳过根因/措施/归并/政策或配置变化。改变这些依据时保持旧候选并标需重核；新决定绑定重新核出的当前 read_digest。

### 尚缺政策和可信端口

现 `QualityPolicy` 给固定风险与 independent_verification，可信发布本身不是全部验证政策。Wave16 须先定义根因/完成的 professional operation matrix、措施输出类型/适用依据、复验方法与判据映射、独立 verifier 的固定专业依据以及观察期证据 owner；缺任何依赖端口时只关闭对应动作，保留可办理的事实。Observation_until 是 CAPA 要求，既非实际 observation 完成时钟，也不是定时器醒来即可判 pass；一次新 Run 通常不足以证明覆盖到该时点，须真实观察事实和来源。

现新请求/Run 资源、方法、原值及结果复核可原样复用，但现 `BoundPolicy.verification` 尚未建立当前/适用的 CAPA 新证据端口，不能从 `aggregate=pass`、旧假的 PolicyPort 或人工布尔值构造 VerificationEvidence。未完工的 action、独立人员缺失、未知风险/政策冲突/撤回、原件不安全、真实/合成混用、未覆盖观察期、遗漏原失败和图完整 owner 缺失都是事实关口；开发可并行实现候选读取和 blocker 展示，但不能通过这些关口授有效性/关闭。

沿用实际 retained 执行证明时保留全部原专业 fact_refs 与其 epoch；后来新增仅适用于整改的新操作事实，可以按既有严格 operation/purpose/role 相关性规则不否认已发生 Start。原事实移除/撤回恢复 ABA、相关新事实或配置/样件使用变化仍必须阻断；新 root_cause/complete/复验动作自身始终核当前专业依据，不能借历史证明授权现在。现持久 writer、公共注册和数据库原子守卫均只按已冻结动作运行，扩后续操作须主线按实际 head 增加必要单调迁移与 Receipt/Current 守卫，不能只开放 handler 绕过它们。

## 5. 双线变更尚缺的八 facet 与正式后续

当前 `change_execution/graph.py::UNKNOWN_REASONS` 明确八项未完整。只读子图和后续新增一条配置边不会消除它们：

| facet | 至少还需的权威对象/覆盖事实 |
| --- | --- |
| engineering | 完整 Spec/Part/BOM/接口/专业版本依赖与正式工程范围；草稿配置不能代正式发布 |
| manufacturing | Operation → Tooling/Fixture → SOP/ControlPlan → PilotRun → ManufacturingRelease；工序声明不证明治具验收或试产 |
| evidence_applicability | 新旧配置/方法/判据/样件/结果适用性及具名专业依据 |
| in_process_builds | 内部在途 Build 与外部在制覆盖、受影响范围和实际处置；查询已登记集合不证明全覆盖 |
| customer_samples | 实际客户样件/外发版本、用途及接收范围，不能用内部 Sample 列表代替 |
| supply_inventory_wip | 真实供应承诺/库存/WIP/占用及处置范围，当前 snapshot.scope_complete=false 不能晋升 |
| production_switch | 固定对象/批次/序号、条件和实际切换事实；日历日期不是单位覆盖 |
| training | 具名培训对象、SOP/版本、实际完成及适用范围 |

`change.order.prepare` 可以保存完整已知对象的处置计划；`change.order.approve` 对任一 Impact.unknown 或 disposition.unknown 明确拒绝。不得通过删节点、截小图、client“不适用”或人工 T2 忽略未知来批准。完整 owner coverage、风险/专业政策和真实事实就绪后才接通 Order/Implementation/Effectivity；当前草案不提出降低旧规则。

实施必须核真实新 owner 对象、本人、批准后的发生时间；unknown attempt 只能核对同一 intent/执行/原回执，不换 ID 盲目重做。sent/accepted/effective 和 partial/unknown/failed 分开；独立 Change Verification 须覆盖全部实施输出及生效项，在全部实际生效之后观察，不能复用原失败 Run。ERP/MES 未连接时只能登记受控人工实际证据，不能伪装外部系统读写或自动生效。

CAPA ineffective 后现纯核保留 awaiting_verification 与历史决定，但**没有**追加/修订措施专用动作；root_cause 和 completion 也不能覆盖已有值。若要交付追加措施/根因更正，须另冻结版本化动作、失效传播和专业关口，不能直接 patch JSON 或再次调用 draft 绕过。归并产生 needs_recheck、历史 Issue 暂无固定版新写重核端口，也须单独恢复接口，不能把 not_evaluated_historical 改成 current。

## 6. 并行归属与依赖关口

正式施工前主线先冻结上述证据 DTO、Issue 聚合 writer 接口、source/专业操作矩阵、辅助动作分级及 API 形状，再按三路独占。建议边界：

| 包 | 可独占新增文件 | 依赖与禁止事项 |
| --- | --- | --- |
| A 整改办理 | `domain/quality_followup/{schemas,service,adapters}.py`、`tests/quality_followup/` | 调旧 quality kernel 与共同 Issue writer；负责根因/完成/回链，不能另建 CAPA 账或修改旧 Run |
| B 复验桥 | `domain/capa_verification/{schemas,models,service,ports}.py`、`tests/capa_verification/` | 先交 typed Evidence/binding，独占 RemediationLink/CapaVerificationEvidence 的模型、owner resolver 与候选重核；A 只调用其接口，避免两包争模型。复用原值/结果/retained/实际方法 owner，不创建第二套 Run 或授适用资格 |
| C 办理界面 | 新 `build-quality-followup.tsx`、对应 helper/test | 按真实 caps 和来源选固定输出/复验候选；T1/T2 原请求重试，未知/缺项/观察期显式显示 |
| 主线公共区 | 既有 quality_execution writer 的定向扩展、专业/注册/API/BFF、实际 head 单调迁移与生命周期 catalog | 一份确认/具名 proof 与 Receipt/Audit/Outbox 同事务；统一迁移/PG/HTTP/浏览器，其他包不并行改共享对象 |

依赖顺序建议：①主线先固定“只开放根因/完成/回链”的动作分级、共同 writer/T2 proof、精确读集和两个 owner DTO；②B 先落 typed binding/models/signatures，A 按同接口接旧核、C 同步做表单/历史/阻断；③主线统一单调迁移/注册/API 并集中核来源/事务，先完成无正式改版要求的根因及部分措施；④已有 owner 创建实际输出/新请求，A 固定回链，B 核新 Run 与原值的适用范围；⑤统一闭环联验并保留有效性/关闭 false。受影响纯核测试可按规则包选择，PG/HTTP/浏览器和候选冻结由主线统一，不并行改公共区。

根因/调查措施不必等待整个八 facet 图，复验候选 bridge 不必等待生产 ERP，未开测的新请求也可作为明确“已建、未执行”的回链输出。反之正式工程/制造切换依完整图与批准，实际新 Run 依已接收范围/专业方法/资源/样件事实，CAPA 有效性依完整新证据和观察期，关闭依当前有效性决定。这些是真实不可推进的前置，不是阻止其他草稿/事实实现的理由；不在 inputs/preview/execute 或跨事务间共享资格缓存。

## 7. 最小验收与尚未完成范围

- 同一当前 Issue/CAPA：假设保留 → 具名 T2 根因 → 本人 T1 实际完成 → 状态正确；代填、未来时间、未知 action、重复 completion/覆盖原结论拒绝。部分完成仍 actioning，全完成 awaiting_verification；不把这个状态当验证通过。当前权/来源复核先于旧回执重放。
- 精确新对象回链：原配置/Run/原值与旧批准不变；实际 owner 引用、同 scope/受众、配置/样件/方法/pair 映射完整；新请求 oneRun、破坏性样件不可重用；计划/草稿回执不能伪造实际输出。
- 部分/未知/非有限/工况不符结果、旧失败 Run、未到观察期、遗漏任一原失败、参与者自证、真实/合成混用不能 effective；确定 fail 可形成 ineffective，未知不强判无效。
- 新复验分支必须有真实保存的新请求/Run 或明确的未执行 blocker，已执行者保留原报告、确定判定及具名复核/处置。候选存在后有效性/关闭 capabilities 仍 false；不提交二者成功例冒充本波交付。后续完整合同的 T2 必须政策/证据全链和当前 digest，另次关闭再核；政策/来源/issuer/专业撤回恢复 ABA、失效或 actual deviation 阻断新决定，历史事实保留。
- 每次 CAS/幂等、跨 key 同意图、精确 key 冲突、完整源并集最多 20（超限明确拒绝不截断）、末端 Outbox 故障连同 proof/Current/Version/Receipt 回滚；既有实际 owner 对象仍保留，不冒充跨事务全回滚。
- 八 facet UNKNOWN 必须仍能看见并阻断 OrderApprove/正式实施；分别显示 CAPA 有效性、Issue 关闭、Change 验证/关闭和工程/制造/客户放行。页面成功刷新与恢复同请求，亮暗/窄屏按冻结候选统一验证。

对应 AT-23/25 延伸到真实整改/独立有效性，AT-07/09/10 覆盖新实际配置、时钟及适用证据，AT-24 保留完整制造穿透缺口，AT-27/33/35/42 覆盖有效期/CAS/人工/撤回保护。完整 G3.2～3 仍缺八 facet 权威覆盖、正式实施/实际生效和独立 Change Verification；G4 放行、G5 外部接收/生产连接、真实资格与人工出口仍按原关口办理。本文只盘点设计与当前代码，没有执行本波检查，也不继承历史测试数字作为本波验收。
