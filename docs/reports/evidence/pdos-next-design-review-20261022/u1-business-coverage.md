# U1 · PDOS v1.1 业务覆盖地图（消费电子研发 + NPI）

日期：2026-10-22 · 性质：只读分析，未改仓库文件，未运行数据库、迁移、服务或测试。

## 0. 读法、来源与评级口径

### 0.1 阅读范围

| 简称 | 文件 |
|---|---|
| v1.1 | `docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md`（§01–§04、§05.3/§05.8、§06.3、§07.9、§09、附录 A、附录 B 全读） |
| 确认稿 | `docs/design/2026-10-08-pdos-next-design-confirmation.md`（C1–C14、P1–P26） |
| 切片合同 | `docs/design/2026-10-17-pdos-next-s{2,3,4}-*.md`、`docs/design/2026-10-18-pdos-next-s5-*.md`、`docs/design/2026-10-17-pdos-v1.1-ui-contract-addendum.md` |
| 种子 | `docs/design/category-seeds/README.md`、`auto-tire-inflator.json`、`bicycle-pump.json` |
| 契约 | `pdos-next/contracts/operations.json`（87 条核心操作）、`auxiliary-operations.json`（54 条辅助操作）、`events.json`（86 个事件）、`acceptance.json`（63 个场景） |
| 代码 | `pdos-next/server/pdos_next/`（domain/ 46 个模块、skill_packages/ 17 个技能包）、`pdos-next/web/src/components/`（页面组件） |
| 状态 | `tasks/ai-native-integrated-todo.md` 当前队列（M0–M9 + UI） |

引用写法：设计写“v1.1:行号”或“确认稿:行号”；后端代码路径省略前缀 `pdos-next/server/pdos_next/`（如 `domain/...`、`change_order_store.py`）；前端路径省略前缀 `pdos-next/`（如 `web/src/...`）；设计稿 `ui-mockup.html` 指 `docs/design/2026-10-13-pdos-v1.1-ui-mockup.html`。

### 0.2 评级口径

- **深**：有一等领域对象 + 状态契约或不变量 + 附录 A 注册操作 + §05.3 页面契约 + 至少 2 条专属验收场景。
- **中**：有对象或操作，但关键子环节只停在原则、字段或视图层，或缺专属验收场景。
- **浅**：只在原则句、字段、视图或技能包说明里被提到，没有独立对象、操作或验收。
- **无**：设计与代码检索均未出现。

每个环节分两列评级：“设计深度”看 v1.1 与确认稿；“代码现状”看 `operations.json` 的 `implementation` 自报字段，再抽查代码。代码现状只是本地合成切片快照：唯一清单写明 S1–S5 都**未验收**（`tasks/ai-native-integrated-todo.md` 当前队列 M3/M6–M9 行），不能当作业务可用的证据。

### 0.3 契约规模（按 `operations.json` 统计）

- 核心操作 87 条：T0 27 / T1 39 / T2 20 / READ 1。实现字段：`implemented_local_slice` 67、`implemented_local_endpoint` 4、`g0_atomic_materialization_only` 1、`not_implemented` 15。
- 15 条未实现：`evidence.source.withdraw`、`product.definition.update`、`product.definition.publish`（规格冻结）、`work.baseline.approve`（G1）、`work.forecast.refresh`、`engineering.interface.update`、`quality.capa.effectiveness.decide`、`npi.tooltrial.create`、`npi.fixture.accept`、`customer.sample.send`、`customer.acceptance.record`、`supply.commitment.record`、`supply.alternate.approve`、`my_work.query`、`provider.agreement.register`。
- 按生命周期归并（核心 / 辅助）：证据 5/6；立项 16/1；定义 4/0；计划 10/6；工程与制造策划 9/6；Build·测试 14/11；问题·变更 8/13；试产·放行·移交 9/2；爬坡·反馈 2/4；AI 与平台 10/5。
- 验收场景 63 个，按阶段：S0 18、S1 22、S2 9、S3 3、S4 10、S5 1。`acceptance.json` 的场景都没有关联具体操作。
- 技能包 17 个：S1 立项类 12 个（`public_research`、`category_framing`、`proposal_drafting`、`rfq_extraction`、`competitor_comparison`、`price_band`、`review_pain_clustering`、`jtbd`、`option_comparison`、`opportunity_scoring`、`derivative_diff`、`gap_check`），S2–S5 类 5 个（`build_execution`、`test_verification`、`quality_issue`、`change_control`、`release_handover`）。计划、模具/工艺、供应/成本、认证、现场反馈、知识、组合这几类工作没有对应技能包。

---

## 1. 按生命周期的覆盖地图

### 1.1 总表

| 阶段 | 设计对象（v1.1） | 操作（附录 A / 辅助） | 页面（§05.3） | 黄金路径 / 验收 | 设计深度 | 代码现状 |
|---|---|---|---|---|---|---|
| ① 品类研究 / 立项 | Category、CategoryKnowledge（场景/竞品库/用户声音/法规认证/测试模板/矩阵）、ParameterVersion、Proposal、OpenQuestion、ProposalDecision(G0)、PromotionProof、PublicWebSnapshot、Claim（v1.1:278、286、322–357） | research.snapshot.register；category.* 6；proposal.* 6；platform.link.create；product.variant.derive；project.create（v1.1:1629–1648） | 品类、立项提案、客户输入、型号概览；立项视图三批（v1.1:786–789、857–862） | 路径 A（v1.1:1406–1417）；AT-01–06、49–57、63 | **深** | 中-深：16 条操作都有本地实现；M3 未验收 |
| ② 产品定义 | DefinitionRevision、SpecItem、Requirement、Variant、Platform（v1.1:310–320、359–369） | product.definition.draft / item.patch（T0，已实现）；update（T1，**未实现**）；publish（T2 规格冻结，**未实现**）；辅助 product.variant.rebase | 产品定义、平台/派生、型号概览（v1.1:789–791） | AT-04、05、06、51 | **中** | 浅-中 |
| ③ 项目启动 / 计划 | Project、WorkPackage、Task、Dependency、PlanRevision、Commitment、ExternalWait、ProjectStatusUpdate、StageInstance（v1.1:495）、FreezePoint（v1.1:576）、G1 | work.* 9（baseline.approve、forecast.refresh **未实现**）；辅助 work.task.accept/start/submit/review、work.commitment.review、work.risk.followup.record | 我的工作、项目列表、阶段与门禁、项目现在、工作与计划、组合与资源（v1.1:782–793、803） | AT-18、19、34、52 | 任务/承诺：**深**；阶段/门禁/冻结点：**中**；组合：**浅** | 任务/承诺：中-深；门禁、G1、组合：**无** |
| ④ 工程与制造策划 | Module、InterfaceContract、Part、BOMRevision、EngineeringConfiguration、ProcessRevision、Operation、Tooling、Fixture、ControlPlan、WorkInstruction、ManufacturingBaseline、MaterialDemand、SupplierReference、AlternateQualification、CostEstimate（v1.1:279–284、636–719） | engineering.* 3（interface.update **未实现**）；npi.process.revise；npi.fixture.accept（**未实现**）；supply.* 3（commitment.record、alternate.approve **未实现**）；cost.estimate.compute；辅助：制造基线/控制计划/作业指引/供应快照/成本输入 | 工程配置、制造准备（v1.1:795–796） | 路径 B（v1.1:1419–1423）；AT-17、20、21、22 | **中** | 中（BOM、配置、制造基线已实现；接口、模具、治具、替代料缺失） |
| ⑤ Build / 样件 / 测试 | Build、BuildLot、SampleUnit、ActualConfiguration、VerificationRequest、TestPlan、TestRun、Measurement、ToolTrial、Handoff（v1.1:391–401、671–701） | build.* 6、verification.* 4、test.* 3 已实现；npi.tooltrial.create **未实现**；辅助 11 条 | Build、品质接收、测试运行（v1.1:794、797–798） | 路径 C（v1.1:1425–1429）；AT-07–15 | **深** | 中-深（S2 多批 / 多 Run 合成联验，未验收） |
| ⑥ 问题 / 变更 | Issue、FailureMode、Containment、CAPA、ChangeRequest、ImpactAssessment、ChangeOrder、EffectivityPlan（v1.1:283、733–739） | quality.* 4（capa.effectiveness.decide **未实现**）、change.* 4；辅助 13 条（分诊/遏制/根因/CAPA/选择/实施/有效性/关闭） | 问题与变更（v1.1:799） | 路径 D（v1.1:1431–1435）；AT-10、23、24、25 | 开发期：**深**；量产后 ECN / 库存处置：**浅** | 中-深（S3 已贯通，未验收） |
| ⑦ 试产 / 放行 / 移交 | PilotRun、ManufacturingBaseline、ReleasePackage、Review、Decision、Waiver、Acceptance、CustomerSampleDelivery、ExternalHandoff（v1.1:285、703–747） | npi.pilot.* 2、release.* 3、integration.* 2 已实现；customer.sample.send、customer.acceptance.record **未实现**；辅助 release.exception.decide/withdraw | 试产、评审与放行、外部交接（v1.1:800–802） | 路径 E（v1.1:1437–1441）；AT-16、17、26–30 | 工程/制造放行与移交：**深**；客户承认：**中**；市场/认证适用性：**浅** | 中-深（S4 已接通，未验收）；客户样品：**无** |
| ⑧ 爬坡 / 反馈 | Field 反馈（v1.1:749–755，无正式对象名）、KnowledgeCandidate、DesignRule | knowledge.candidate.create、knowledge.rule.publish；辅助 field.feedback.create/locate/action.record/followup.link | 知识（v1.1:804）；`web/src/components/field/field-feedback.tsx` | 路径 F（v1.1:1443–1447）；**无专属 AT** | **中-浅** | 中（反馈与经验规则有本地实现） |

### 1.2 各阶段子环节

#### ① 品类研究 / 立项

| 子环节 | 设计依据 | 设计 | 代码 | 备注 |
|---|---|---|---|---|
| 品类边界、规格字典、品类知识 | v1.1:322–340；种子 README §3–§7 | 深 | 深 | 两个种子品类：汽车 31 参数 / 31 测试项 / 43 条法规目录，自行车 30 / 30 / 44 |
| 公开研究（竞品、价格带、评论痛点） | v1.1:1033–1039、986–988 | 深 | 深 | 有隔离子任务和片段核对；AT-56 |
| 客户 RFQ 抽取、标准品匹配 | v1.1:185、788；AT-02/03 | 中-深 | 中-深 | `agent_kernel/extract_schemas.py:102` 抽取类型含 compliance、packaging_labeling；`web/src/components/preproject/standard-match.tsx` |
| 方案对比、机会评分、市场规模 | v1.1:347、988；确认稿 C3（71–84） | 中 | 中 | 只做技能包和计算工具，不建对象（有意为之） |
| 商业目标（目标价 / 成本 / 数量） | v1.1:346 | 中 | 中 | `domain/preproject/schemas.py:159–162` CommercialTarget |
| 认证与销售地区 | v1.1:346 | 浅 | 浅 | 只是提案 section 的文本键 `certification_regions`（schemas.py:126） |
| G0 立项评审 | v1.1:616–627；确认稿 P24 | 深 | 深 | 单一具名评审人，不许自审；按 v3.1 设计稿说明，G0 不批预算 |
| 第二/三批立项视图（目标成本桥图、品类矩阵时间线） | v1.1:859–860 | 中 | 无/浅 | 代码检索“桥图 / cost_bridge”0 命中 |
| 专利 / IP | — | 无 | 无 | 见 §4 候选 H |

#### ② 产品定义

| 子环节 | 设计依据 | 设计 | 代码 |
|---|---|---|---|
| 结构化规格条目引用参数版本 | v1.1:312–316 | 深 | 中（草稿与条目补丁） |
| 规格冻结（T2） | v1.1:316、507、1646 | 中 | **无**：`product.definition.publish` 未实现；确认稿:601 写明派生链因此走不通 |
| 专业协审（按产品类型选专业，可标“不适用”） | v1.1:316、627 | 浅：附录 A 没有协审命令 | 无 |
| 定义转需求、需求-验证覆盖矩阵 | v1.1:627、853 | 浅：Requirement 只列在 §02.1 模块表（v1.1:278），没有命令 | 浅：`domain/products/models.py:34` requirements 是 JSONB 列表 |
| 派生（固定父版 + 覆盖 + 三方差异） | v1.1:359–369；确认稿 P23 | 深 | 中 |

#### ③ 项目启动 / 计划

| 子环节 | 设计依据 | 设计 | 代码 |
|---|---|---|---|
| 任务、分派、承接、承诺分离 | v1.1:509、543–549；S5 合同 | 深 | 中-深 |
| 四时间（基线/预测/承诺/实际） | v1.1:532–541；§05.12.1 B9 | 深 | 中（预测刷新、G1 基线未实现） |
| 外部等待 | v1.1:545–547 | 深 | 中-深 |
| 阶段模板（EVT/DVT/PVT）与门禁 | v1.1:493–499、610–614；§05.12.2 | 中：只有原则，附录 A 没有“阶段评审 / 门禁决定”命令 | **无**：`web/src/components/projects/project-workspace.tsx:57、64` 显示“阶段模板与门禁规则结果尚未提供”；代码检索 StageInstance 0 命中 |
| 冻结点（结构冻结、开模授权、长交期采购、认证样机冻结） | v1.1:574–580；补遗 A10（`2026-10-17-pdos-v1.1-ui-contract-addendum.md:38`） | 中：附录 A 无操作 | **无**：FreezePoint 0 命中 |
| G1 计划基线 | v1.1:627、1654 | 中 | **无**：`work.baseline.approve` 未实现 |
| 项目类型政策（OEM / 派生 / 小改 / 降本 / 认证） | v1.1:197、497、612 | 浅 | 无（project_type 0 命中） |
| 组合与资源容量 | v1.1:803、1206–1210；§05.12.1 B4 | 浅 | **无**：`web/src/components/app-shell.tsx:236` 显示“尚未接入”；`web/src/lib/global-navigation.ts:10` 标 `planned: true` |

#### ④ 工程与制造策划

| 子环节 | 设计依据 | 设计 | 代码 |
|---|---|---|---|
| ID/CMF（设计简报、色材工艺、样板） | v1.1:640 | 浅 | 无（0 命中） |
| 结构 / 硬件设计引用 | v1.1:641–642、375 | 中 | 中：`domain/configurations/schemas.py:21、108` ExternalDesignReference（mechanical / electronic） |
| 固件制品、兼容、刷写、回退 | v1.1:643、381 | 浅 | 浅：只有一个 `firmware` 引用（configurations/schemas.py:108） |
| InterfaceContract | v1.1:649–655 | 中 | **无**：`engineering.interface.update` 未实现，0 命中 |
| 研发 BOM（内部 / ERP / 客户料号、替代、适用变体） | v1.1:371–377 | 中 | 中：扁平行，带三种料号（configurations/schemas.py:38–60）；没有替代组、适用变体、制造商料号字段 |
| 工艺路线、SOP、控制计划、制造基线 | v1.1:403–409、657–669 | 中-深 | 中-深：S4 辅助操作已实现 |
| 模具（Tooling：模穴、进度、验收、寿命） | v1.1:671–677 | 中 | **无**：没有 Tooling 表；`domain/manufacturing_baseline/rules.py:171` 写明“模具真实验收与适用性尚未接通” |
| 治具与设备验收、校准 | v1.1:695–701 | 中 | 浅：`npi.fixture.accept` 未实现，测试资源由 `domain/test_resources` 承担 |
| 供应齐套 | v1.1:713–717 | 中 | 中：有快照和齐套计算；供方只是文本 `supplier_id`（`domain/supply_execution/schemas.py:20`） |
| 替代料资格 | v1.1:717；AT-21 | 中 | 无（approve 未实现） |
| 成本估算 | v1.1:719；AT-22 | 中 | 中：`domain/cost_execution/schemas.py:26` 覆盖物料 / 工艺 / NRE，绑定固定 BOM（service.py:152） |
| DFM、DFMEA/PFMEA | v1.1:669 | 浅（设计上有意按需选用） | 无 |
| 制造可行性结论（路径 B） | v1.1:1419–1423 | 浅：没有对象 | 无（“可制造性 / manufacturab”0 命中） |

#### ⑤ Build / 样件 / 测试

| 子环节 | 设计 | 代码 | 备注 |
|---|---|---|---|
| Build 双配置、多批、实际配置 | 深 | 深-中 | AT-07/08 |
| 样件占用、破坏性消耗 | 深 | 中-深 | AT-11 |
| 试模前验证策划、交接时钟、部分接收 | 深 | 中-深 | AT-12–15 |
| 试模 ToolTrial | 中（v1.1:673） | 浅 | handler 在 `domain/manufacturing_trials/handlers.py:26`，但原生注册只覆盖 pilot（`native_schemas.py:27–28`），`operations.json` 标为未实现 |
| 测试项与参数版本绑定 | 中（v1.1:331、340 要求测试模板引用同一参数版本） | 浅，待核实 | `schemas/verification/contracts.py:122–135` 的 TestItem 是自由 feature / criterion，没有 parameter_id/version；品类测试模板在代码里只作为种子原始材料保存（`domain/preproject/category_seed.py:38`） |
| 可靠性 / 寿命 / 环境测试计划 | 浅 | 无 | 见 §4 候选 F |
| 第三方认证实验室送样 | 浅 | 无 | 设计稿只把它当作一条外部等待（`2026-10-13-pdos-v1.1-ui-mockup.html:854`） |

#### ⑥ 问题 / 变更

| 子环节 | 设计 | 代码 |
|---|---|---|
| 失败建单去重、分诊、遏制、根因、CAPA | 深 | 中-深 |
| 双线影响（产品线 + 制造线） | 深（v1.1:735–739） | 中-深 |
| 变更批准、实施、有效性、关闭 | 深 | 中-深（`capa.effectiveness.decide` 未实现，由辅助链替代） |
| 库存 / 在制品处置、生产切换、培训 | 浅（v1.1:739 只在影响清单里列出） | **无**：`change_build_adoption.py:25` 写明不代表库存、在制、其他 Build 或 ERP/MES 切换 |
| 法规 / 客户专业批准 | 浅 | 冲突，待核实：变更审批专业包含 `regulatory`、`customer`（`change_order_store.py:132`），但专业资格事实只能授予 engineering / quality / manufacturing / knowledge（`domain/professional_authority/schemas.py:40`）。选择决定要求专业在本人角色内（`change_selection_service.py:222`），所以法规项可能无人能批 |

#### ⑦ 试产 / 放行 / 移交

| 子环节 | 设计 | 代码 |
|---|---|---|
| PilotRun、首次通过率与最终合格率口径 | 深（v1.1:703–711） | 中-深 |
| 固定放行包，工程与制造分别具名决定 | 深 | 中-深 |
| 有限例外（Waiver） | 中-深 | 中-深 |
| ERP/MES 移交与回执对账 | 深（v1.1:745–747） | 中：人工证据路径 |
| 客户样品外发与客户承认 | 中（v1.1:727–731） | **无**（两个操作均未实现） |
| 市场 / 认证适用性（第四种放行） | 浅：v1.1:594 定义了，附录 A 没有命令 | 无 |

#### ⑧ 爬坡 / 反馈

| 子环节 | 设计 | 代码 |
|---|---|---|
| 现场 / 客户反馈来源、配置定位、遏制改进 | 中（v1.1:753） | 中：`domain/field_feedback/schemas.py:38–45`，channel 取值 field / customer |
| 经验候选到具名规则 | 中-深 | 中-深 |
| 爬坡目标、过程偏差、成本偏差 | 浅（v1.1:751） | 无 |
| 停产、平台替代、备件 | 浅（v1.1:755） | 无 |
| RMA、退货率、上市后差评回流 | 无 | 无 |

---

## 2. 按角色的覆盖地图

v1.1 的职责表在 v1.1:199–213。代码里的专业资格角色只有 engineering、quality、manufacturing、knowledge 四种（`domain/professional_authority/schemas.py:40`），映射见同目录 `service.py:22–80`。产品管理权限是 Grant 上的布尔字段（`models.py:159`）。

| 角色 | 默认工作空间（v1.1:203–211） | 设计中主要对象与操作 | 页面 | 专业资格 / 技能包 | 设计深度 | 代码现状 | 主要缺口 |
|---|---|---|---|---|---|---|---|
| 产品经理 | 品类、立项提案、我的工作 | category.*、proposal.*、product.definition.*、G0 提交 | 品类、提案、型号、定义 | Grant.product_manager；12 个立项技能包 | **深** | 深（S1 本地） | 规格冻结未实现；上市准备、IP、产品损益缺 |
| 项目负责人 | 项目现在、计划、交接 | work.*、外部等待、状态更新 | 项目列表、阶段与门禁、工作与计划 | 无专属专业角色；无计划技能包 | **中** | 中 | 阶段门禁、G1、冻结点、项目类型模板、资源容量都没有实现 |
| 结构 / 硬件 / 固件 | 工程工作包、配置、问题 | engineering.configuration / bom、change.* | 工程配置、问题与变更 | engineering；change_control | **中-浅** | 浅-中 | 接口契约未实现；没有设计评审 / DFM 检查；没有固件发布对象；ID/CMF 无 |
| 模具 / 工程 / 自动化 / 治具 | 制造准备、试模与设备 | npi.tooltrial.create、npi.fixture.accept | 制造准备 | manufacturing（无 tooling 细分） | **中** | **浅-无** | 两个核心操作都未实现，没有 Tooling 对象；模具进度、费用、寿命缺 |
| 生产 | Build 执行、试产、交接 | build.start / output.record、npi.pilot.result.record、样件就绪 | Build、试产 | manufacturing；build_execution | **中-深** | 中-深 | 爬坡阶段只停在原则层 |
| 品质 / 测试 | 待接收、测试、验证、质量问题 | verification.*、test.*、quality.*、change.verification/close | 品质接收、测试运行、问题与变更 | quality；test_verification、quality_issue | **深** | 深（S2/S3） | 可靠性计划、来料/供方质量、量产质量指标缺 |
| 采购 / 供应 | 承诺、齐套、替代与异常 | supply.commitment / kit / alternate | 组合与资源（未接入）、Build 供应面板 | **无专业角色**；无技能包 | **中-浅** | **浅** | 两个关键操作未实现；没有供应商对象、AVL、供方 PPAP/FAI |
| NPI 协调 | 制造准备、试产、放行 | npi.*、release.*、外部移交 | 制造准备、试产、评审与放行 | 只借用 manufacturing（`domain/projects/service.py:314` 用了 "npi" 专业名）；build_execution、release_handover | **中-深** | 中 | 制造转移、多工厂、爬坡指标缺 |
| 管理层 | 组合、决定、产品与资源 | 附录 A 没有专属命令（无组合取舍、投资批准） | 组合与资源 | 无 | **浅** | **无** | 预算、项目损益、组合优先级、资源冲突决策都没有 |
| 认证 / 合规负责人（补充，v1.1 职责表无此行） | — | 种子 D3 要求认证负责人确认适用性（`category-seeds/README.md:115`）；v1.1:644 把品质与认证合并 | 品类“法规认证”视图 | 无 regulatory 角色（见 §1.2 ⑥ 的冲突） | **浅** | 浅 | 没有认证计划、证书、DoC，没有第四种放行命令 |
| 售后 / 客服 / 电商运营（补充） | — | 只有 Field 反馈的入口 | 现场反馈 | 无 | **无** | 浅 | 见 §4 候选 C、I |

---

## 3. 显式非目标与边界（原文位置）

| # | 边界 | 原文位置 |
|---|---|---|
| 1 | 不是通用聊天软件、无限自定义数据库、任意拖拽流程搭建器；不要求员工维护全部内部状态 | v1.1:259（§01.9） |
| 2 | 不替代 CAD/EDA、实验室、ERP/MES 作业，但要完整管理开发期配置、制造准备、验证和移交；边界是为了防止双权威版本 | v1.1:259–261（§01.9） |
| 3 | 客户商业沟通和报价留在 CRM（GoodJob），不另建销售漏斗；不需要开发的标准品询价不进 PDOS | v1.1:192（§01.4）；`web/src/components/preproject/standard-match.tsx:180`（“在 CRM 继续办理”） |
| 4 | 研究期间不建项目；标准品匹配不建项目；不建虚拟项目、虚假负责人、假定客户批准 | v1.1:189–190、308；AT-02 |
| 5 | OEM 不重做客户已决定的市场策略 | v1.1:191；路径 B（v1.1:1423） |
| 6 | 删除 Research / Opportunity / Experiment / 策略对象及其页面，研究方法做成技能包 | 确认稿 C3（71–84）；v1.1:223、290、807；ADR A24（v1.1:1601） |
| 7 | 数据所有权：ERP 管库存、采购、正式核算和物料生效；MES 管生产执行；CAD/EDA/Git 管专业原始制品；CRM 管销售管道；PLM/QMS 按绑定策略，不双写 | v1.1:447–451（§02.13）；v1.1:1212–1218（§07.9）；§06.6.2 外部系统边界（v1.1:1030） |
| 8 | 不编辑 CAD/EDA 源设计，不直接控制设备 | v1.1:647（§04.1） |
| 9 | 量产执行仍在作业系统，PDOS 只关注爬坡目标、偏差、复发与变更生效 | v1.1:751（§04.15） |
| 10 | SampleUnit 只做开发追溯，不扩展为仓储交易系统；二维码不扩展为仓储 / 借还系统 | v1.1:397、870 |
| 11 | CostEstimate 不替代 ERP 正式成本和财务批准 | v1.1:719（§04.10） |
| 12 | DFM、DFMEA/PFMEA、控制计划、8D 按风险或客户要求选用，不给所有项目自动加表单 | v1.1:669（§04.4） |
| 13 | 外购电池 Pack 不虚构内部电芯 BOM | v1.1:701（§04.8） |
| 14 | G0 不产生规格冻结、专业签名、BOM 批准、客户承诺；设计稿说明 G0 不批预算 | v1.1:627（§03.14）；唯一清单 v3.1 修订条（`tasks/ai-native-integrated-todo.md:39`） |
| 15 | 准备度和健康度是规则投影，不是 AI 分数；不作门禁依据，不抵消硬阻塞 | v1.1:551–566；确认稿 P17（548–554） |
| 16 | 看板不可拖拽；组合层只暴露冲突，不提供改期、改承诺、改资源的直接动作 | v1.1:891–892（§05.12.1 B3/B4） |
| 17 | 只有一个 Agent，不设领域 Agent，不做 Agent 群聊或投票；工具不开放任意 SQL / HTTP / Shell | v1.1:930–933、1019；AGENTS.md 不可协商项 6 |
| 18 | AI 永不取得 T2；G0、规格冻结、对外发送都是 T2 | v1.1:1007；I13（v1.1:467） |
| 19 | 客户私有资料不进入共享品类知识、对标和矩阵 | I22（v1.1:476）；v1.1:353–357 |
| 20 | 客户原件不可变，翻译与 AI 抽取只是派生 | v1.1:318 |
| 21 | 第一个闭环不建本地全文索引和爬虫订阅 | v1.1:1202；确认稿 C13（232–246） |
| 22 | 不无条件引入 Kafka、Neo4j、Kubernetes、多套向量库、微服务网格 | v1.1:1147 |
| 23 | 原工程数据不迁移 | 确认稿 C12（216–230） |
| 24 | 第一个闭环只验收路径 A，B–F 后续纳入；P13 例外提前恢复 S2 | v1.1:1404；确认稿 C4（86–98）、P13（519–524） |
| 25 | M3 不做规格冻结；G0 决定撤回、提案撤销本期不做 | 确认稿 P6 Q4、Q7（458、461） |
| 26 | 会话没有删除功能；不做“项目成员视角预览” | 确认稿 P20（569–574）、P16（542–546） |
| 27 | 多服务商自助配置不在 P26 施工范围内 | 确认稿 P26（626） |
| 28 | 切片合同不得加严规则或扩大范围 | v1.1:137（§00.4）；AGENTS.md 不可协商项 7 |
| 29 | 错误码不为单个场景新增顶层码 | v1.1:1341（§08.7） |
| 30 | 竞品营销效果不作收益承诺；不预先承诺节省百分比 | v1.1:135、1470 |
| 31 | 经验不自动污染平台知识，AI 总结不直接成为企业标准 | v1.1:753；路径 F（v1.1:1447） |
| 32 | 复杂 BOM 与多版本比较保留桌面优势，不强迫在手机上做重型编辑 | v1.1:866 |

---

## 4. 疑似覆盖浅或缺失的业务环节候选（供后续核实）

**检索口径**：在 v1.1、确认稿、切片合同、四个契约 JSON、技能包、`pdos_next/**/*.py`、`migrations/*.py`、`web/src/**/*.ts*`、种子 JSON 九个范围检索；英文缩写用区分大小写的词边界匹配，避免子串误命中（例如 ISTA 会命中 existing，ECO 会命中 become，ASIN 会命中 increasing）。下文“命中”只写有意义的结果。

**行业对照**：同类 PLM / NPI 产品通常带合规、供应商、需求与可靠性模块（例如 v1.1 来源 S06 Arena 的产品化 QMS）。这一点按通用行业认识写出，本轮没有联网逐项核实。

### A. 认证 / 合规计划与证书管理

- **业务场景**：充气泵含锂电、电机、无线（部分带蓝牙数显）、充电器，要做 CE（LVD/EMC/RED）、FCC、UKCA、PSE、KC、CCC、IEC 62133、UN 38.3、RoHS/REACH、WEEE/电池法规与 EPR。每个市场、每个变体都需要认证计划、送样批次、实验室排期、证书和报告编号、有效期、DoC，以及变更后重认证判断。
- **现状**：
  - 品类知识里有“法规认证”目录（v1.1:330），种子三态分记来源、适用和合规（`category-seeds/README.md:42`；`domain/preproject/category_schemas.py:101–111`）。
  - 提案有“认证与销售地区”文本（v1.1:346；schemas.py:126）。
  - 冻结点列了“认证样机冻结”（v1.1:576），Build 用途列了“认证样品”（v1.1:723）。
  - §03.11 定义了第四种放行“市场 / 认证适用性”（v1.1:594），但附录 A 没有对应命令。
  - 代码基线块 `certification` 恒为 `unknown / baseline_block_not_available`（`domain/preproject/baseline_blocks.py:27`）。
  - 设计稿只把认证实验室排期当作一条外部等待（ui-mockup.html:854）。
- **为何怀疑缺失**：没有 Certification / ComplianceMatrix / Certificate 对象和操作，没有证书有效期与变更触发重认证的规则，也没有认证负责人这个职责。
- **检索与命中**：认证（v1.1 10 处，全是清单或字段）；certif（v1.1 0，代码 20 处均无关）；证书（设计与代码 0）；certificate（代码 1 处无关）；合规 / complian（v1.1 0）；UN 38.3、IEC 62133、FCC、CE、RoHS、WEEE、EPR（只出现在种子里）；MSDS / SDS（全 0）。
- **初判**：设计浅，代码浅（只有目录）。
- **待核实**：第四种放行是否计划落地；法规专业审批的角色冲突（§1.2 ⑥）。

### B. 包装、说明书、标签、多语言资料

- **业务场景**：彩盒、说明书（多语种警示）、铭牌与合规标志、条码、电池运输标识，属于跨境电商和多国认证的硬性交付物，有版本与印刷打样。
- **现状**：
  - 制造配置与制造基线含“包装标识”（v1.1:383、409、659）；ID/CMF 的接口列了包装（v1.1:640）。
  - 代码只有一个文本字段 `packaging_label_basis` 和缺项码 `PACKAGING_LABEL_UNKNOWN`（`domain/manufacturing_baseline/schemas.py:180`、`rules.py:130–131`）；工序类型含 packaging（`domain/configurations/schemas.py:121`）；RFQ 抽取类型含 packaging_labeling（`agent_kernel/extract_schemas.py:102`）。
- **为何怀疑缺失**：没有 artwork / 说明书 / 标签版本对象，没有多语言版本，没有与认证标志、规格的一致性校验，也没有打样承认。
- **检索与命中**：说明书（v1.1 1 处，指公开 PDF 研究来源，v1.1:1192；代码 0）；多语言（设计 0）；翻译（v1.1:318，指客户原件派生）；artwork、丝印（设计与代码 0）。
- **初判**：设计浅，代码浅。

### C. 电商上市资料与上市准备（listing、主图、A+、SKU/ASIN、上市计划）

- **业务场景**：自主品牌跨境电商需要上市清单：卖点与参数口径（须与规格、认证一致）、主图与视频、A+ 页、FBA 入仓所需的危险品资料（锂电）、首单与备货、上市日期。
- **现状**：提案只有“上市窗口”（v1.1:346；schemas.py:127 `launch_window`），渠道在品类知识里（v1.1:328）；生命周期止于制造放行与爬坡（v1.1:80）。
- **为何怀疑缺失**：没有 Launch / GTM 准备对象，没有上市准备度规则，宣传参数与实测口径的一致性检查没有落到上市物料上（研究侧已经区分“宣传 / 实测”）。
- **检索与命中**：listing、主图、A+、亚马逊、SKU（设计 0）；电商（v1.1 1 处，研究来源，v1.1:1036）；上市（v1.1 1 处）；ASIN（代码命中为子串误报）。
- **初判**：设计无，代码无。
- **注意**：这可能被视为 CRM 或电商系统的范围（边界 3、7），需要用户确认归属。

### D. 目标成本管理与 BOM 成本卷积

- **业务场景**：立项定目标成本，每个 Build 和每次变更后按 BOM、工艺、模具摊销重算，跟踪差距与降本行动，结合售价看毛利。
- **现状**：
  - 提案有 CommercialTarget（`domain/preproject/schemas.py:159–162`）；CostEstimate 在 S4（v1.1:719），代码覆盖物料 / 工艺 / NRE、报价、汇率，并绑定固定 BOM（`domain/cost_execution/schemas.py:24–82`、`service.py:152`）。
  - “目标成本桥图”列在第二批立项视图（v1.1:859）。
- **为何怀疑缺失**：目标成本与估算之间没有跨版本跟踪对象或视图实现；变更影响分析是否含成本差（v1.1:739 未列成本）不明；毛利 / margin 0 命中。
- **检索与命中**：目标成本（v1.1 1 处，视图）；target_cost、成本卷积、cost roll、rollup、毛利、margin（全 0）；桥图（只在 v1.1:859）。
- **初判**：设计中，跟踪部分浅；代码中（只有估算）。

### E. 供应商协同与 PPAP / FAI / 来料质量

- **业务场景**：电机、电芯、PCBA、气管、壳体等关键件的供方选择、样件承认（FAI / 承认书）、供方变更通知（PCN）、来料检验，以及合格供方清单与制造商料号。
- **现状**：§02.1 列了 SupplierReference（v1.1:284），但没有状态契约；代码里供方只是快照中的文本 `supplier_id`（`domain/supply_execution/schemas.py:20`、`schemas/supply_cost/dto.py:84`）；Part 没有制造商料号和供方字段（`domain/configurations/models.py:41–47`）；首件只在 PilotRun 结果里（v1.1:705）；采购没有专业角色（`domain/professional_authority/schemas.py:40`）。
- **为何怀疑缺失**：供方资质、承认、PCN 没有对象和操作；`supply.commitment.record` 与 `supply.alternate.approve` 均未实现。
- **检索与命中**：PPAP、IQC、SQE、AVL、合格供方、来料（全 0）；FAI（词边界 0）；首件（v1.1 1 处）；供应商（v1.1 3 处）。
- **初判**：设计浅，代码浅。

### F. 可靠性 / 寿命 / 环境测试计划

- **业务场景**：电机寿命（连续或循环工作小时）、电池循环寿命与保护（过充、过放、短路）、高低温存储与工作、湿热、振动、跌落、运输包装测试（ISTA）、气管和接头耐久，并要明确样本量与判据。
- **现状**：TestPlan / TestRun 是通用结构（v1.1:399）；种子测试项偏性能，有 drop_robustness、operating_temp、continuous_run_time、surface_temp、storage_retention，但没有寿命、循环、振动、湿热、运输测试（种子 JSON 参数清单）；§04.1 只把可靠性写成结构专业的接口（v1.1:641）。
- **为何怀疑缺失**：没有 DVP&R / 可靠性计划对象，没有样本量与置信度规则，旧证据复用的适用性（AT-10）没有落到可靠性项目上。
- **检索与命中**：可靠性（v1.1 3 处，含 §07 标题和 §09.3 系统可靠性）；reliability、寿命、lifetime、老化、burn-in、MTBF、高低温（设计 0）；跌落（只在种子）；ISTA（词边界 0）；DVP（0）。
- **初判**：设计浅，代码无（专属部分）。

### G. 固件版本、发布与 OTA / 产线烧录

- **业务场景**：数显、预设压力、自动停机都靠固件；需要固件发布记录、与 PCBA 和传感器的兼容矩阵、产线烧录工位与校验和、压力传感器标定参数、回退。带 App 的款式还涉及 OTA。
- **现状**：v1.1:643 要求管理“制品与源码版本引用、兼容性、刷写与回退”；AT-09 覆盖测试中途改固件；代码只有工程配置上的一个 `firmware` 引用（`domain/configurations/schemas.py:108`），Build 比较带“固件制品引用”（`domain/build_execution/comparison.py:124`）。
- **为何怀疑缺失**：没有 FirmwareRelease 或兼容规则；没有产线烧录与标定参数版本进入制造基线的显式字段。
- **检索与命中**：固件（v1.1 8 处，均为原则）；OTA（词边界 0）；烧录、bootloader（0）；刷写（v1.1 1 处）。
- **初判**：设计浅，代码浅。

### H. 专利 / IP / FTO

- **业务场景**：充气泵同质化严重，外观专利和实用新型风险高；跨境电商常见侵权投诉下架。
- **现状**：只有 `skill_packages/opportunity_scoring.md:75` 把“专利”列为硬性风险示例。
- **为何怀疑缺失**：G0 评审内容（v1.1:621）不含 IP 检查；没有专利检索技能包或证据类别。
- **检索与命中**：专利（技能包 1 处）；patent、FTO、侵权、知识产权（全 0）。
- **初判**：设计无，代码无。

### I. 售后 RMA、退货率、差评回流

- **业务场景**：上市后电商评论与退货原因、RMA 失效分析、DPPM / 退货率趋势，回流到 CAPA 和下一代定义。
- **现状**：立项前有“用户声音：评论、退货原因”（v1.1:329）和 `review_pain_clustering` 技能包；上市后 Field 反馈的 channel 只有 field / customer，类型只有观察、意见、变更要求、条件承认、正式承认声称（`domain/field_feedback/schemas.py:38–45`）；路径 F 没有专属验收场景（附录 B）。
- **为何怀疑缺失**：没有 RMA / 退货批量导入与统计口径，没有上市后评论监控的 AutomationRule 模板；设计稿只有“竞品价格周跟踪”一例（唯一清单 UI 条）。
- **检索与命中**：RMA（词边界 0）；售后（v1.1 1 处，停产语境 v1.1:755）；差评、DPPM、不良率、after-sales（0）；召回（3 处都是检索意义上的“召回”，与产品召回无关）。
- **初判**：设计浅，代码浅。

### J. DFMEA / PFMEA / 特殊特性

- **业务场景**：锂电与压力类产品的安全失效（过热、爆管、表头失准），客户或渠道（如车规相关 OEM 客户）可能要求 FMEA 与控制计划联动。
- **现状**：§02.1 列了 FailureMode（v1.1:283）；v1.1:669 写明按需选用；Operation 含关键特性与过程风险（v1.1:665）；代码有控制计划辅助操作，没有 FMEA 对象（failure_mode 0 命中）。
- **为何怀疑缺失**：FailureMode 没有命令；关键特性从规格到工序、控制计划的追溯没有专门规则。
- **检索与命中**：DFMEA、PFMEA（v1.1 各 1 处）；FailureMode（v1.1 1 处）；failure_mode（0）。
- **初判**：设计浅（有意按需），代码无。

### K. 量产后 ECN 与库存 / 在制品处置、断点切换

- **业务场景**：量产后改电机或电芯，需要定断点（批次或日期）、处置旧料（用完 / 返工 / 报废）、通知工厂与供方、更新 ERP 生效。
- **现状**：v1.1:739 在影响清单中列了库存 / 在制品处置、生产切换和培训；EffectivityPlan 在 §02.1；辅助 `change.effectivity.record` 只记“继任开发 Build 采用”（`auxiliary-operations.json`），代码注释明确不覆盖库存、在制和 ERP/MES 切换（`change_build_adoption.py:25`）。
- **为何怀疑缺失**：没有量产变更的断点与处置对象；ERP 生效回执与变更关闭的关联不明。
- **检索与命中**：ECN、ECO（词边界 0）；库存处置、cut-over（0）；断点（只在确认稿和切片里，指技术断点）；在制品（v1.1 1 处）。
- **初判**：设计浅，代码无。

### L. 多工厂、制造转移、外部代工厂协同

- **业务场景**：OEM/ODM 常把生产放在外协工厂，或从一厂转到另一厂；需要转移项目、过程证据适用性重判、外部工厂资料交换。
- **现状**：§01.1 范围含“制造转移”（v1.1:150）；v1.1:661 要求不同产线判断证据适用；制造放行按场地 / 产线定范围（v1.1:594）。
- **为何怀疑缺失**：没有 Site / 工厂对象（site_id 0 命中），没有转移项目类型，也没有外部协作方（客户、供方、代工厂）的受控访问入口（portal / 门户 / 外部协作 0 命中）。
- **检索与命中**：制造转移（v1.1 1 处）；转厂、多工厂（0）；工厂（v1.1 6 处）。
- **初判**：设计浅，代码无。

### M. 项目组合与资源容量

- **业务场景**：多个品类、多个型号并行，共用台架、模具厂、认证预算和工程师，需要组合视图、优先级与资源冲突决策。
- **现状**：§05.3 有“组合与资源”页面（v1.1:803），确定性引擎把设备、模具、线体、样件、人员算作资源（v1.1:1208）；S5 列了组合资源（v1.1:1485）；B4 只暴露冲突（v1.1:892）。前端显示“尚未接入”（`app-shell.tsx:236`），导航标 planned（`global-navigation.ts:10`）；排程引擎只做前推预测（`domain/planning/scheduling.py:1`）。
- **为何怀疑缺失**：没有人员容量和技能模型，没有组合取舍的决定命令，管理层没有可办理的动作。
- **检索与命中**：组合（v1.1 10 处）；portfolio（前端读集 `web/src/lib/portfolio-reads.ts` 只聚合项目）；容量（v1.1 6 处）；产能（v1.1 1 处，试产节拍）。
- **初判**：设计浅，代码无。

### N. 财务预算 / 项目损益 / 投资批准

- **业务场景**：开模费、认证费、样机费等 NRE 预算，投资回报，项目费用实绩与预算对比，开模和长交期下单的金额审批。
- **现状**：冻结点要求写明“用途 / 数量 / 金额”（v1.1:578）；长交期投入需写明费用与取消影响（v1.1:717）；管理层负责“投入”（v1.1:211）；G0 不批预算（`tasks/ai-native-integrated-todo.md:39`）；成本估算不替代财务批准（v1.1:719）。
- **为何怀疑缺失**：没有预算、费用或投资批准对象与命令；冻结点本身也没有操作。
- **检索与命中**：损益、P&L、ROI、NPV、投资回报、开模费、capex（全 0）；预算（v1.1 8 处，多为 AI 运行预算）。
- **初判**：设计浅或无，代码无。

### O.（补充）阶段门禁、项目类型模板、冻结点、G1

- **现状**：设计有原则（v1.1:493–499、574–580、610–614、627），附录 A 没有阶段评审、门禁决定、冻结点授权的命令；`work.baseline.approve` 未实现；前端写明阶段模板与门禁规则结果尚未提供（`project-workspace.tsx:57、64`）。
- **为何重要**：EVT / DVT / PVT 节奏是消费电子 NPI 的主骨架，开模授权与长交期下单是最大的不可逆投入。
- **检索与命中**：StageInstance、FreezePoint、project_type、stage_template（代码 0）；G1（代码 0）。
- **初判**：设计中，操作层缺；代码无。

### P.（补充）规格冻结、专业协审、需求到验证的追溯

- **现状**：`product.definition.publish` 未实现（确认稿:601）；协审和“定义转需求”没有命令（v1.1:627）；覆盖矩阵只是视图（v1.1:853）；TestItem 没有绑定参数版本（`schemas/verification/contracts.py:122–135`，待核实）。
- **检索与命中**：需求追溯、DVP（0）；traceab（代码 3 处无关）。
- **初判**：设计中，代码浅。

### Q.（补充）锂电池危险品运输资料

- **现状**：种子法规里有运输、航空运输条目和 UN 38.3（种子 16 处），设计正文 0 处；MSDS / SDS 0 处；没有运输鉴定、DG 标识与样品寄送限制。寄样（CustomerSampleDelivery）和 FBA 入仓都依赖这些资料。
- **初判**：设计无，代码无（可并入候选 A）。

### R.（补充）模具管理（开模、试模轮次、模具验收、费用、寿命）

- **现状**：设计 §04.5 为中（v1.1:671–677）；代码没有 Tooling 表，`npi.tooltrial.create` 未注册（`domain/manufacturing_trials/handlers.py:26` 与 `native_schemas.py:27–28` 对照）。
- **初判**：设计中，代码无。

### S.（补充）客户样品外发与客户承认（OEM / ODM）

- **现状**：设计中（v1.1:727–731；AT-28）；`customer.sample.send`、`customer.acceptance.record` 均未实现。
- **初判**：设计中，代码无。

### T.（补充）设计评审与 DFM / DFA 评审

- **现状**：“设计评审 / design review”0 命中；Review 是通用对象（v1.1:285、516），没有结构或硬件评审、DFM 检查清单的命令。
- **初判**：设计浅，代码无。

### U.（补充）竞品拆解与 BOM 对标

- **现状**：研究技能包针对公开规格、评论和价格；拆解、teardown 0 命中。
- **初判**：设计无，代码无。是否属于范围待用户定。

### V.（补充）爬坡 KPI 与停产 / EOL

- **现状**：v1.1:751 的“已承诺的爬坡目标”没有对象；v1.1:755 的停产义务（在售变体、售后、备件）没有操作；EOL 0 命中。
- **初判**：设计浅，代码无。

### W.（补充）实际集成落地（钉钉、GoodJob CRM、ERP、MES）

- **现状**：设计有边界与人工证据路径（v1.1:745–747、1212–1218）；pdos-next 代码中 dingtalk、GoodJob 0 命中，外部移交走受控人工路径（S4 合同“外部接口未接时建设受控人工证据路径”）。
- **初判**：设计中，代码浅。影响“减少重复录入”的目标（v1.1:148）。

### X.（补充）法规 / 客户专业批准的角色缺口（代码一致性，待核实）

- 变更审批专业允许 regulatory 和 customer（`change_order_store.py:132`；`schemas/change_control/contracts.py:11`），但专业资格事实的 role 只允许 engineering / quality / manufacturing / knowledge（`domain/professional_authority/schemas.py:40`）；选择决定要求条目专业在本人角色内（`change_selection_service.py:222`）。可能导致法规类变更项无人有权决定。

---

## 5. 小结

1. 覆盖最深的是三段：立项前（路径 A）、Build 到测试（路径 C）、开发期问题与变更（路径 D）。对象、状态、操作、验收和技能包都比较完整。
2. 设计有原则、但操作层缺口最大的是“项目骨架”：阶段模板与门禁、冻结点、G1、规格冻结与协审、组合与资源。这些在附录 A 里没有命令或未实现，前端也明示尚未接入。
3. 对充气泵这类锂电、电机、跨境电商产品，最明显的业务空白依次是：认证与合规计划（含危险品运输）、包装 / 说明书 / 标签、上市准备、可靠性计划、供应商质量、量产后 ECN 与库存处置、售后 RMA 回流、模具管理、项目预算与损益。
4. 角色上，品质 / 测试与产品经理覆盖深；采购 / 供应、模具 / 工程、管理层，以及缺席的认证负责人与售后 / 电商运营覆盖浅。
5. 设计明确划在边界外的有 32 条（§3）。其中候选 C（上市资料）和 K（ERP 生效）可能被视为外部系统范围，需要用户确认归属后再判断是缺失还是有意不做。
