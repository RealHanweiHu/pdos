# Wave21 共享三人案例 · 权威与顺序只读核对

本报告只核当前实际服务与施工合同，未跑数据库、HTTP、浏览器或测试，未登记新人员/权限/资格、未修改源码。多scope配置仍按主线应用结果判断，暂存pure成功不能作为实际专业资格。

## 最小合法范围与职责

采用全新Product、全新共享Project、一个确定用途P、全新设备/库存池、两件具有真实Lot/ActualConfiguration身份的样件。Maker为Project负责人；三人为同租户三个不同的active human Principal，各自独立登录。三人均须有该Product当前有效can_write Grant；当前专业评估即使读模式也要求产品写授权（professional service `_project` 206起）。Grant只解决访问/办理前置，不授工程、制造、品质或独立资格。

所有实际链条从首次保存即为product共享：Project、Build、双配置、Actual/样件、准备/正式请求、Run、原报告/派生Artifact、Issue/CAPA、Link、Candidate、Rule、Observation及其原文。权限不能把旧private原件/Issue/Run扩大受众。Reviewer不能借Maker或Observer Context读取；原保存者专业依据与当前consumer ACL为独立守卫。

| 人员 | 必要职责与当前资格事实 | 合法办理分工 |
|---|---|---|
| Maker | engineering duty+qualification；manufacturing duty+qualification；另有quality duty+qualification精确覆盖根因，若本人导入Rule还覆盖规则导入 | 配置/Build、工程与制造两次具名批准、开工与实物ready/hold、交样Offer；固定失败建Issue、分诊/遏制、CAPA草稿；quality根因T2；本人措施完成T1；共享真实输出回链与候选 |
| Observer | quality duty+qualification精确覆盖请求/方法/接收、Run Plan/Promise/Start、原值/确定性结果、Run复核/处置、Observation | 原失败与新复验的品质链、实际executor、原报告upload/parse与测量登记、结果计算及必要专业Run动作、真实观察T1 |
| IndependentReviewer | quality duty+qualification只覆盖`quality.capa.verification.review`，相同项目、用途P、合法有效期 | 读取完整共享固定材料，按真实候选/Rule/观察/当前配对作一次具名T2 CAPA Review；不参与前述事实办理 |

Maker的engineering/manufacturing身份不足以办根因：`OPERATION_ROLES['quality.issue.root_cause.decide']`仅quality；host-only `quality.capa.verification.rule.import`也仅quality。Observer不能用FactInput不存在的test role替代quality。每个人每种适用role需要分别保存duty和qualification；资格缺失为null，已知失效为false，两者都不是true。

FactInput每份operations最多10项，须按真实操作拆组，使用不同稳定external_id，不把后一个组覆盖为同一Current系列。例如Observer的请求/方法/接收/Plan/Promise/Start/import/compute为一组不超过10项，Run review/disposition/Observation为另一组；每组均有同role duty与qualification。Maker工程组可覆盖Issue/CAPA/回链/候选，制造组覆盖Build授权/开工/ready/Offer，quality组覆盖根因与Rule导入。所有purposes精确P，不用相似标题代用途。

签发配置本身不授人资格。Root以实际server issuer和真实ApprovalBasis/精确原文调用host-only professional import；同范围独立key、合法marker与finite ledger仍必需。专业、政策、资源、Rule有效期须覆盖实际窗口和后续真实读取；不借延期proof或虚拟时钟解决长流程。

## 独立Reviewer的实际排除边界

`participants_owner.run`310–492遍历原失败固定Run和新当前Run的完整immutable lineage，核每版Receipt/RequestKey/Audit/Outbox及对应Launch/ResultAction事实；每一版writer都进入original_test/new_test。实际execution.executor_id也进入，不能仅看最终Run.owner。测量的真实executor及报告注册者进入measurement。

`report`230–308核native注册或Original upload v1及当前实际parse回执；actor、requester不同均记入，上传/解析人不会因报告内容由别人测试而被排除。Worker解析仍保留真实归属，不能以worker不显示名字来规避。

`issue_history`494–581核整个Issue固定历史：根因actor、遏制保存者和executor、每项completion保存者/本人executor全部进入。Observation读取704–718按真实保存事实executor加入。`named_review_owner._independent`逐当前actual participants检查，GET和最终late refresh均重新核对。

因此Reviewer不能是原/新Run任一历史writer、实际测试/测量executor、报告注册/上传/解析人、根因/遏制/完成者或观察executor。避免由Reviewer帮助办Run review/disposition，它们同样是Run历史writer。把Reviewer只放为专业签发subject或读取共享材料，不会自动进入这些参与事实；这也不自行证明独立，最终仍由实际owner判定。最小案例可让两位业务参与者分别固定为Maker与Observer，Reviewer只登记自己的实际Review事件来源并做Review。

## 实际命令顺序

1. Root/Maker先建立新的Product/共享Project和三份合法Grant，再配置该范围独立issuer、政策/完成分类及专用资源finite ledger，导入上述当前专业事实。保留所有旧scope，绝不通过旧default key跨产品重配。所有事实来源新建共享，不使用旧private Demo材料。
2. Maker办理人工定义、单行BOM、固定双配置、计划Build；按真实供应/资源前置取execution_scope完整读集计算准备度，再办工程和制造两份T2领域批准与带精确已发生来源的Build Start T1。已有外部产出不能当开工批准。
3. Maker登记真实已发生Actual配置/离散产出、分配两件真实样件；在实际Start/Actual/Lot时序满足后为相关用途记ready。Observer建立资料完整的Preparation与Formal draft，固定每项方法/判据；Maker Offer，Observer实际方法逐sample/item核对并接收。共享样件只是可读，不能跳过实物或品质状态。
4. Observer为第一件样件Plan→具名Promise→实际Run Start，使用当前可信资源Fact、明确真实窗口、固定executor；Plan/Promise零占用，Start才保存实际占用/样件使用。报告upload→clean/parse→精确原行capture→final import→canonical compute，原值/工况/方法/判据必须产生真正确定fail。indeterminate只可调查，不能转FailureRef/Issue。
5. Maker从固定失败的真实结果事件建立Issue(T0)→分诊(T1)→真实遏制(T1)→CAPA draft(T0)。CAPA action.executor_id为Maker，requirement完整覆盖真实failure IDs。先quality根因T2，再本人完成T1；完成事件为已发生九字段原JSON、原ISO微秒/IANA与完整来源。全部完成后旧核转awaiting_verification，不能再补根因。
6. 保持完成版Issue Current不变，建立真实新整改输出/Link。初始Candidate可无mapping以保存indeterminate固定anchor供host Rule出版；这份零mapping候选不能用于NamedReview。Rule只由实际host发布，完整method/criterion/identity/sampling/观察窗口依据须真实共享；不从人工checkbox生成Rule资格。
7. Observer为第二件样件建立新的Preparation/Formal/Run并完成实际复验。新实际Start和已知measurement观察不得早于所有措施实际完成时刻。原值保留，不把首件失败改为pass。若Rule明确要求Run专业review/disposition，Observer完成对应T2动作；即便仅如实unknown，不能把他们交给独立Reviewer。
8. 在所需Run动作全部保存后再选最终Current Run及实际advance Formal的精确不可变版本/回执建立晚Link与新Candidate mapping；不要先绑定Run v3再继续写v4/v5使原mapping变历史。完整FailurePairMapping由服务器真实选项产生，覆盖全部原FailureIDs、样件/Item/Actual配置/测量/Projection；version row UUID不是logical Run ID。Current Formal来自真实paired owner，不借旧Draft Receipt。回链/Candidate不推进Issue Current，不倒填早期Link。
9. Observer按当前真实Rule记录实际Observation T1。target来自发布Rule；records复制已核原行，实际区间与record时钟须落在约束内，at不早于区间终点，不填now假事件。不补未来观察。若只实际部分记录则保持部分，不能说观察完整。
10. Reviewer明确选择新实际有mapping的Candidate、当前Rule与完整实际Observation refs；GET实际独立与来源核对后，inputs→返回真实command/readset与13-key preview→人工具名T2→execute。保留原command/key/载荷恢复UNKNOWN；savedReceipt优先，刷新失败只能只读重试，401/403清私有状态。Review每个mapping逐项给method/criterion与来源、每个原action分别给结论/原因/来源，不能靠一份总评替代全覆盖。该过程不办effectiveness/close。

顺序允许第6步使用真实Draft输出作planned回链，但最终Review必须有performed完整配对。旧零mapping候选、旧private链和旧回执全部留历史，不能升级替换。

## 完整来源上限与可行预算

`anchor.canonical_reads`按Artifact identity/version并集计数，必须1～20且同identity不同revision拒绝。一个共享Artifact中不同真实行/不同精确SourceRef只计一个完整Artifact版本；Receipt/domain引用本身不自动算额外Artifact，但其真实owner读取所带Artifact闭包仍全部算。

可用19槽预算如下，仅为创建与引用规划，不是已测闭包：产品定义/BOM/工艺/统一方法判据材料1；三人真实职责资格来源1；质量风险/调查分类政策1；专用库存/制造资源依据1；测试设备/校准/人员资源依据1；Build实际开工/产出/ready已发生日志1；原失败准备/交接已发生日志1；原Run实际开测/结果专业事件1；原报告及派生完整来源1；Issue调查/根因/本人完成已发生记录1；新固定整改输出/回链依据1；Rule原出版/采样依据1；新准备/交样/接收已发生记录1；新测试可信资源Fact依据1；新Run实际开测与最终结果事件1；新原报告1；Observation原记录/实际区间1；Reviewer实际具名评议来源1；余量1。某份实际来源不满足内容上限或真实时序需分开登记时用余量；超过20必须缩小真实业务范围或另行具备完整合同，不能删依据/截断内容/省略失效分支。

只能把已真实发生、完整且符合现登记容量的行放入一份新不可变文本；不能预写未来事实来减少Artifact数，不能追加旧Artifact或把旧source audience改product。原报告必须走真实Original/scan/parse与原件字节核验，不为预算改为可信文本读数。资源、专业及policy事实可以共用一份真实共享来源的不同精确行；并不共用资格对象或省略原issuer/epoch。

Review完整并集至少包括origin、Rule、Candidate inspection、参与者与全部Run历史/report来源、Observation、当前Reviewer专业及政策、live paired owner与适用owner来源（named_review_owner `read` / capa_review_context `read_review_selection`）。主线在每步实际inputs/preview以整集核计数，保留identity/version及来源类别；不能凭表面19槽就宣称最终不超过20。Raw participant reader另有128行全闭包上限，最小单failure/单action/单item、不造多余版本可减少读取；不能为此省略真实历史。

## 当前可办状态与不能声称的状态

- 可真实构建共享固定fail→Issue/CAPA根因/本人完成→真实新Run/Current输出→晚Link/Candidate→实际Observation→独立具名Review。需要专业/来源/资格/当前scope实际通过；配置列表和纯例不是上述业务已保存。
- NamedReview严格至少一个mapping及一个Observation，全mapping须等于Candidate顺序且覆盖全部固定FailureIDs，actions覆盖全部固定完成项（NamedReviewPayload与`_coverage`）。Zero mapping候选不会凭空给Review资格。
- 所有pair/action/overall均unknown时，现`_applicability`允许如实保留未知选择；仍完整核actual Current、原件/参与者独立与performed pair，不是绕过专业证据。真有方法适用，可选实际owner证明的pair applicable，同时action unknown/overall unknown；整体由actual owner重算，不能只凭人工文字转肯定。
- 已保存completion只证明本人完成事件；调查分类investigation不是实际履行。`ActualActionFulfillmentOwner.read`在selection.conclusion非unknown时要求真实implementation_owner.read/refresh，本段缺该端口则503。Cannot把investigation动作描述、调查报告或新Run pass自动映射fulfilled/applicable；更不能推出物理纠正已落实。
- Rule sampling.require_run_review/require_disposition必须如实选，并执行实际要求；完整观察/应用性/履行/效果由各实际核门判断。Candidate三列NULL/indeterminate、Rule/Observation、独立Review保存不自动产生effectiveness或close决定。生产资格、正式放行、外发、八facet完整性及原人工Exit继续未通过。

## 读取字节绑定

- `docs/reports/evidence/pdos-next-wave21-20261003/implementation-contract.md`：`be207b5682e1a2c864c40e9aace7c73b4d777fc5ad23e09a28e93c3b91ffa486`
- `pdos-next/server/pdos_next/domain/professional_authority/service.py`：`d1920edd315ce26f8ea1ba3631e1aff67a820032e77c53374a0793c840e44433`
- `pdos-next/server/pdos_next/domain/capa_effectiveness/participants_owner.py`：`779d2dba1fb96e92f210792ff25adc8437a2f6e691c2faa6a72ff0a34f2c0b35`
- `pdos-next/server/pdos_next/domain/capa_effectiveness/named_review_owner.py`：`ca6c235254dbc25e140bdaa4876063a2e00a7fabad59809b1c27a3dd20c7ce6a`
- `pdos-next/server/pdos_next/capa_applicability_owner.py`：`a493490f3f860ef18bced0d82218884f3d20e57246897ccce906e81623afc208`
- `pdos-next/server/pdos_next/capa_review_context.py`：`e8358ae188c7b3a6d021f26bcc794626f3220b4d2f3254db356702d603348563`
- `pdos-next/server/pdos_next/domain/capa_effectiveness/fact_commands.py`：`d66a57d57b180f0c465138f989ccb19ca519906d249c86c3100c9a85becd7749`
- `pdos-next/server/pdos_next/domain/capa_effectiveness/anchor.py`：`2db9d275a2718fd1d0449e33372c3c2876fb73523c2120968e32f9fef70e7c82`
