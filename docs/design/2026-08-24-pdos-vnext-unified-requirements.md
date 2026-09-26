# PDOS vNext 统一需求设计稿（整合版，待 PO 拍板）

> **2026-09-10 适用性修订**：全量业务范围继续继承；与后续合同冲突的授权/联网/辩论原句已校准。共同架构以[一致性合同](2026-09-10-ai-native-architecture-consistency-contract.md)解释；旧Phase顺序与本页“待拍板”状态保留历史意义，当前按[整合计划](2026-09-09-ai-native-integrated-execution-plan.md)及有效用户决定施工，不重新询问已确认事项。

> 日期：2026-08-24
>
> 状态：**整合草案；非 canonical 执行依据；未授权实现、部署或生产变更**
>
> 整合来源：
> - 来源 A：`2026-08-24-vnext-control-loop-upgrade-plan-draft.md`（项目控制闭环方案，D1-D24 + Phase 0-6）
> - 来源 B：《PDOS_Module_Optimization_and_Roadmap_V1.0.docx》（模块优化与研发数字链，五域 + P0-P3）
> - 用户新决策（2026-08-24 口头确认，细节合同待冻结）：允许 Agent 受控联网（agent-reach）；允许 Agent 间带立场的结构化对话
>
> 冲突处理原则：两来源一致处直接合并；冲突处在本稿第 3 节决策台账中显式列出并给出推荐；用户已明确决策的项标注"已决策"。本稿发布后，来源 A/B 保留为历史输入，需求以本稿为准（待 PO 确认）。

## 1. 统一产品主线：一条数字链 + 一条控制链

两份来源文档各自回答了半个问题，合并后 PDOS 的主线是：

- **研发数字链（来源 B）**：`Requirement → Spec → BOM/设计 → Sample → Test → Issue → Change → Decision → Knowledge`——回答"工程对象长什么样、证据如何串联"。
- **项目控制链（来源 A）**：`基线 → 执行 → 偏差 → 会议决策 → 行动验证 → 预测与重基线 → 组织记忆`，向前延伸到`研究 → 竞品/市场 → 机会树 → 产品策略/定义 → 候选需求 → DCP/IPD`——回答"谁负责、何时暴露、如何闭环追责"。

数字链是控制链的证据底座：没有 Sample Configuration 和结构化 Test Run，延期解释、Gate 准出和 Agent 辩论都拿不出证据。因此两条链**同期建设、数字链对象骨架优先**（见第 7 节阶段计划）。

职责分工（两来源一致，直接冻结）：

- **确定性引擎**：日期/依赖传播、资源冲突、齐套率、Gate 规则、提醒 SLA、TAM/SAM/SOM、机会分数、组合评分、项目健康度；
- **领域 Agent**：理解非结构化证据、发现异常、解释原因、起草方案、参与结构化评审辩论（新增，见 5.4）；
- **人**：责任人确认、问题关闭、基线变更、DCP/TR/Gate、产品策略/定义发布、辩论后的最终决策；
- **外部系统**：ERP 持物料/交易真值，MES 持制造执行，PLM/CAD 持设计文件真值；PDOS 持证据快照、对象关系、判断与可审计影响链。

## 2. 统一产品边界（合并两来源，全部保留）

### 2.1 不可退让边界（来源 A 第 4 节，D25/D26 修订处已更新）

1. **（2026-09-10 按后续合同校准）**模型业务变更只产出Finding，接受与独立应用两个动作；pdos_agent对业务表零直接写。D32历史分区仍用于区分动作性质，确定性规则/导入按已批准窄合同，可信运行记录另行授权；不能从“草稿可逆”推导模型直写权。
2. 模型Finding双动作和目标领域批准分别保留；高/严重Issue四眼不变。只读研究、比较和解释不新增接受/应用，批量办理展示共享差异，撤销受后继引用和领域规则约束。
3. 确定性结果（排期、齐套、SLA、Gate 阻断、健康度、市场量化指标）不交给 LLM 心算。
4. 自动延期只更新 Forecast；不静默改 Baseline/Commitment。
5. ERP/MES/PLM SoR 不复制；PDOS 只存引用 + as-of snapshot + 派生影响。
6. 会议采集仅限明确纳入的会议/转写稿；不采私聊、不全量监听。
7. Agent scope 由服务端冻结；模型自报参数不是权限事实。
8. 业务写同事务产生 Event 与 Audit；迁移号单调递增（本地 head `0033`、生产 `0032`，vNext 从 `0034` 起）；测试只连 `pdos_test`。
9. 产品管理链不接 CRM（D17 已决策）；已有 CRM Requirement ingress 保持现状、不扩展。
10. **（修订）Agent 联网走受控 agent-reach 技能**：只读研究 GET、抓回即证据快照、默认放行 + blocklist；禁止 POST/表单/登录态/带凭证请求；对外发送仍属高风险动作强制人批。
11. **（修订）Agent 间对话仅限服务端编排的结构化评审辩论**：席位制、图内 turn-taking、全程落 transcript、产出带分歧记录的 Decision Brief；run 之外的自由消息、无主持群聊仍禁止。

### 2.2 明确不做的范围（来源 B 第 3.1 节，与 D17 对齐后冻结）

- **ERP**：采购订单、库存、MRP、应付、正式物料主数据、生产成本核算；
- **MES**：工单、排产、工位执行、OEE、生产序列号、设备采集;
- **完整 PLM/PDM**：CAD Vault、复杂配置管理、全企业物料生命周期、完整 Effectivity 执行；
- **完整 QMS**：全量检验、计量设备、审核体系、企业级文控；
- **SRM/CRM**：商务采购协同、询价交易、销售流程、Deal/Account/漏斗/赢输单/订单收入分析（D17）。来源 B"集成优先钉钉、ERP、CRM"修订为：CRM 仅保留现有 Requirement ingress，不进入产品管理链路。

### 2.3 八条产品原则（来源 B，直接采纳）

工程工作优先／Object-first／Issue > Task／Evidence-based／轻量但结构化／AI 建议人决策／知识来自闭环／边界清晰。

## 3. 统一决策台账（D1-D31）

D1-D24 全文见来源 A 第 5 节，此处只记录整合后的状态变化与新增项。

### 3.1 状态变化项

| ID | 原内容 | 整合后状态 |
|---|---|---|
| D2 | 不加 Agent、无 Agent 间对话 | **被 D26 修订**：运行时 Agent 仍收敛（6+1），但开放服务端编排的席位制评审辩论；"无自由对话"红线保留 |
| D17 | V5 不接 CRM | **已决策 B**，并覆盖来源 B 的"CRM 集成优先"表述 |
| D18 | 会议 Action 作为 Task kind | **被 D28 扩展**：全部 Action 必须有来源对象 |
| D20 | Agent 无自由 HTTP，仅离线采集层 | **被 D25 修订**：开放 agent-reach 受控联网技能 |
| D21 | 新增第 7 个 Product Management Intelligence | 维持推荐新增；且该 Agent 承担辩论中的"产品经理"席位，理由增强 |

### 3.2 技术必然项（推荐直接采纳 B，不占 PO 决策带宽）

D3、D4、D7、D13、D15、D16、D22、D23、D24（理由：选 A 均破坏可审计性或安全边界）。

### 3.3 新增决策项 D25-D31

| ID | 决策 | 内容 | 状态 |
|---|---|---|---|
| D25 | agent-reach 受控联网 | 见 5.5；受控GET + 证据快照 + 默认放行/blocklist；替代D20的仅离线采集 | D25已生效，全席位可用，无首次域名人工审批；运行参数按N0合同冻结 |
| D26 | 结构化评审辩论 | 见 5.4；席位制、立场锚定对象所有权、图内编排、Decision Brief 人终审；替代 D2 的"禁止对话" | D26已生效，授权run内可自行发起、不设业务场景白名单；协议/预算参数按N0合同冻结 |
| D27 | P0 工程对象骨架并入 Phase 1 | 来源 B 的 Sample Build Configuration、结构化 Test Run、Requirement-Spec-Test 追溯、Decision 一级对象、Evidence-based Gate、Action 来源对象，作为 Phase 1 工程轨与控制轨并行 | 推荐采纳 |
| D28 | Task 全面降级为 Action | 所有 Action 标记来源对象、预期输出、完成证据；个人工作台聚合各来源 Action；扩展 D18 | 推荐采纳 |
| D29 | Test/Verification 升一级模块 | Test Plan→Case→Run→Result→Evidence→Issue 结构化模型；关键指标（条件/目标/结果/单位/设备/样机/操作者）入库不入附件 | 推荐采纳（来源 B P0） |
| D30 | Decision 一级对象 P0 | Context/Options/Evidence/Trade-offs/Rationale/Approver/Consequence；实现成本低、长期知识价值高 | 推荐采纳（来源 B P0） |
| D31 | 两层信息架构 | 全局域导航（来源 B 附录 A 十项）+ 项目工作区 9 标签（来源 A D9）+ 独立产品管理工作台；合并而非二选一 | 推荐采纳 |

## 4. 统一对象架构

### 4.1 五个核心域（来源 B，作为全局导航与权限域）

| 域 | 对象 | 目的 |
|---|---|---|
| Product Definition | Product / Requirement / Spec /（V5：Research、Competitor、Segment/JTBD、Opportunity、Experiment、Strategy、Definition、Matrix） | 明确做什么 |
| Engineering | BOM / Sample / Test / Issue / Change / Decision | 把产品做出来 |
| Quality | Failure / FMEA / CAPA / Verification | 证明可靠性 |
| Delivery | Project / Gate / Risk / Supplier / Cost / Certification /（vNext：Baseline-Forecast-Commitment、跨项目依赖、物料齐套、Resource Pool） | 确保可量产 |
| Intelligence | Memory / Knowledge / Agent / Analytics /（vNext：Finding、Proposal、Evidence Snapshot、Decision Brief） | 让系统持续变聪明 |

### 4.2 P0 最小对象清单（来源 B 附录 B + 来源 A 补充）

Product、Project、Requirement、Spec、Part/BOM Revision、Sample（含 Build Configuration）、Test Case/Test Run、Issue（含 Hypothesis/Root Cause/Verification/Closure）、Decision、Change、Risk、Gate Review（Entry/Exit Criteria + Evidence + Conditional Pass）、Action（来源对象 + 完成证据）、Knowledge Candidate；vNext 补充：Meeting/Agenda/Action Item（Phase 2）、Baseline/Forecast/Commitment（Phase 3）、Project Material Requirement/齐套快照（Phase 4）、Evidence Snapshot/Research Source（Phase 2 提前，服务 agent-reach）。

核心要求（两来源一致）：链上每个对象必须有唯一标识、版本/状态、负责人、证据和上下游关系；Agent 上下文从对象图读取，不只拼接页面文本。

### 4.3 四条核心闭环（来源 B）× 六条功能轴（来源 A）

来源 B 的四闭环是对象级模式，来源 A 的六轴是产品交付分期，映射关系：

| 来源 B 闭环 | 落在来源 A 的轴/Phase |
|---|---|
| 需求到验证（Requirement→Spec→Test） | Phase 1 工程轨（D27）+ Phase 5 候选需求回链 |
| 问题到知识（Issue→Root Cause→Verification→Knowledge） | Phase 1 控制轨（Issue 闭环）+ Knowledge Candidate |
| 变更到影响（Change→Impact Graph→Retest/Re-cert） | Phase 4（物料/ECN）+ P1 工程闭环 |
| 数据到主动提醒（Rules/AI→Candidate→Human Review） | 全部 Phase 的 Agent 介入模式，即 Finding/Proposal/HITL |

## 5. 统一 Agent 架构

### 5.1 运行时 Agent（收敛为 6+1，不按模块扩张）

保留现有 6 个（Project / Knowledge Lite / Engineering / Quality / Supplier / Executive Intelligence）+ D21 新增 Product Management Intelligence。来源 B 的"五 Agent"与现有六个合并映射：PM Agent→Project Intelligence、Engineering→Engineering、Quality→Quality、Supplier→Supplier、Executive→Executive；Knowledge Lite 保留承担会议/文档/记忆。能力扩展一律走版本化 `capability_key`（能力包全表见来源 A 第 5 节），每个 capability 独立 prompt/投影/tool allowlist/Finding schema/golden cases/预算/指标，并按 shadow→Finding→Apply 灰度。

### 5.2 动作风险分级（来源 B 7.3，与 Finding/Apply 合并）

- **低风险自动**：搜索、总结、Brief、分类、候选、草稿、提醒——对应 Finding 前的分析动作；
- **中风险确认后执行**：创建 Issue/Action、建立关联、Test Plan、Knowledge Candidate 发布——对应 Accept+Apply；
- **高风险强制批准**：Stage/Gate、BOM Freeze、ECN、价格、供应商选择、关键质量关闭、外部发送、删除——对应 Apply + 授权角色 +（高/严重项四眼）。

### 5.3 Agent 质量评估（来源 B 7.4 并入 DoD）

事实正确性（引用对象/字段/证据真实存在）、建议可执行性、采纳/修改/拒绝分场景统计、越权/重复执行/注入专项测试、业务效果（提前发现、减少复发、缩短关闭与 Gate 准备）。

### 5.4 结构化评审辩论（D26，新增）

**设计核心：立场来自对象所有权，不来自 prompt 扮演。**每个席位 = 运行时 Agent + 立场投影（该角色负责对象的只读快照）+ capability 组合：

| 席位 | 承载运行时 Agent | 立场锚定对象 | 辩论中守什么 |
|---|---|---|---|
| 产品经理 | Product Management Intelligence | 已发布 Product Definition、定价带、Strategy Canvas | 目标规格、价值主张、价格带不被工程妥协侵蚀 |
| 项目经理 | Project Intelligence | Baseline/Commitment、关键路径、Gate 日期 | 任何方案的时间代价显性化 |
| 结构工程师 | Engineering Intelligence（persona A） | 结构 BOM、公差/装配约束、结构类 Issue/Test | 结构可行性、模具影响 |
| 硬件工程师 | Engineering Intelligence（persona B） | 电子 BOM、原理图版本、电气 Test Run、热/EMC 数据 | 电气可行性、器件风险 |
| DQE | Quality Intelligence | FMEA、CAPA、复发历史、转产 checklist | 可制造性与转产准出 |
| 供应商席（可选） | Supplier Intelligence | Supplier Engineering Profile、交期/质量历史 | 供应可行性 |

**辩论协议**（Phase 0 冻结细节）：

1. 按D26，Agent可在已授权run内自行发起，不设业务场景白名单；ECR/Gate/定义变更是示例，不是放行清单；
2. 单次编排 run 图内执行：主持节点分发议题与共享证据包 → 各席位独立出立场（必须引用各自锚定对象）→ 有限轮交叉质询（每轮针对对方具体证据，禁止复读）→ 收敛检测 → 输出；
3. 以预算熔断为主控，保留运行期限、取消、停止原因和全程transcript；预算停止不等于达成共识；
4. 输出为 typed proposal `Decision Brief`：一致项、**分歧项及各自代价**、各方引用证据；进入 pending_review→Accept→Apply，由人终审；
5. 禁止：run 外自由消息、Agent 私下互发、无主持群聊、辩论结果直接写业务真值。

### 5.5 agent-reach 受控联网技能（D25，新增）

1. **形态**：Tool Registry 中的 capability 级技能包，含 `web_search`、`web_fetch`（只读 GET）、`source_snapshot`；按D25全席位可用，仍绑定run范围和预算；
2. **红线**：禁止 POST/表单/登录态/带凭证请求；"外部发送"仍属高风险人批动作；
3. **抓回即证据**：每次抓取生成 Evidence Snapshot（URL、时间、digest、可信度分级）；Agent 结论只能引用快照 ID，走统一引用 preflight；
4. **注入防御**：原文可落快照并标不可信，外部指令不执行；投影区分事实/推断、保留无损来源指针，引用和应用检查权限与版本，不能因进入证据库而获得指令权限；
5. **默认放行 + blocklist**：沿D25只拦内网地址、登录/凭据和可执行下载等已规定边界；无首次域名人工审批。每跳与解析IP校验保留，不将GET方法等同于任意动作链接都安全；
6. **首批受益场景**：需求评审外部规格核对、供应商画像、认证矩阵、竞品/市场研究（V5）、硬件工程师 datasheet 查询。

## 6. 统一信息架构（D31）

**全局导航**（来源 B 附录 A）：Home（个人工作台/待办 Action/AI Brief）｜Portfolio（含 **D38 管理层看板**：决策请求中心 + 例外式组合视图）｜Products｜Projects｜Engineering｜Quality｜Delivery｜Knowledge｜AI Workbench（对话/Proposal/Review Queue/评估）｜Admin。

**项目工作区 9 标签**（来源 A D9）：概览·控制塔｜计划·资源｜工作项｜物料·供应｜工程·变更｜例会·决策｜Gate·交付物｜试制·测试·质量｜文档·知识。

**产品管理工作台**（独立顶级，立项前工作）：研究中心｜竞品情报｜市场细分·JTBD｜机会树｜产品策略｜产品定义｜产品矩阵·路线图｜实验·决策。

## 7. 统一阶段计划

以来源 A 的 Phase 0-6 为骨架，来源 B 的 P0-P3 并入；映射：B-P0 ≈ Phase 1 工程轨，B-P1 ≈ Phase 2/4 工程闭环项，B-P2 ≈ 各 Phase 的 Agent 介入 + 辩论/reach，B-P3 ≈ Phase 6。

### Phase 0：产品合同与兼容基线（扩充）

原范围（拍板 D1-D24、S5 出口处置、迁移事实、试点与 golden cases）不变，新增：

- 继承已生效D25-D31；冻结辩论席位、预算、Brief及受控研究策略参数；不恢复场景白名单、首次域名人工放行或只开放少数席位的旧建议；
- 冻结统一对象关系图与最小字段字典（来源 B 11.1：Requirement/Spec/Sample/Test/Issue/Change/Decision/Knowledge）；
- 选定真实 Pilot 项目（来源 B 建议：锂电充气泵项目回放完整数字链，识别字段缺口与操作负担）；
- typed scope v3 合同提前冻结（实现可推迟，但 V1-10 依赖其语义）。

### Phase 1：个人工作、问题闭环 + 工程对象骨架（双轨）

**控制轨**（来源 A V1-1~V1-11 不变）：My Work 聚合、Issue Owner/Verifier/四眼、权限拆分、Reminder、Agent 事件覆盖、契约漂移修复、typed proposal 基础、capability_key 合同。

**工程轨**（D27 新增，来源 B P0）：

- Requirement/Spec 分层与 Verification Method、Coverage Dashboard；
- Sample Build Configuration（BOM revision、关键零件供应商、PCB/FW/结构版本、Build Date）；
- 结构化 Test Run（条件/目标/结果/单位/设备/样机/操作者/原始证据），失败自动关联 Issue；
- Decision 一级对象；
- Gate Entry/Exit Criteria + Evidence + Conditional Pass（Owner/Due/Closure Evidence）;
- Action 来源对象与完成证据（D28）。

**平台轨**（显式分离验收）：V1-10/V1-11 属架构改造，与用户功能分开排期与验收。

Exit 追加：Pilot 项目一条真实数字链端到端跑通（需求→规格→样机→测试→问题→决策→Gate 证据），关键数据不再只存附件。

### Phase 2：例会与决策闭环 + 辩论/联网底座

原范围（Meeting/Agenda/Transcript、会前装配、meeting_minutes capability、分步 Apply）不变，新增：

- **Evidence Snapshot/Research Source 底座提前**（原 V5-1，为 agent-reach 服务全体席位而非仅产品管理）；
- **agent-reach v1**：allowlist search/fetch + 快照落库 + 引用 preflight；先挂载工程/供应商/质量席位的查证场景，shadow 观测后放开；
- **辩论 runtime v1（shadow）**：辩论图（主持/席位/收敛/熔断节点）在 LangGraph 执行面实现；首批只跑 ECR 评审与 Gate 准备两个场景，Decision Brief 仅 shadow 产出供人比对，不进 Apply。

### Phase 3：项目时间与延期传播

范围不变（Baseline/Forecast/Commitment/Actual、FS+lag 首版、确定性关键路径、Change Proposal、人审重基线）。辩论席位"项目经理"的立场投影自此有真实 Baseline 数据。

### Phase 4：项目物料与齐套 + 工程闭环深化

原范围（BOM 操作面、需求生成、ERP snapshot、齐套、短缺闭环、Supplier Agent）不变，并入来源 B P1 工程项：

- Change Impact Graph（Part→BOM→Spec→Test→Certification→Cost→Supplier→Sample→Open Issue），自动生成 Retest/Re-review/Re-certification 清单；
- Living FMEA（新 Issue 未被覆盖时生成 Update Proposal；不自动改 S/O/D）；
- Supplier Engineering Profile、Design-to-Cost、Compliance Matrix；
- 辩论 runtime 转正：ECR 评审场景 Decision Brief 进入正式 Accept/Apply 流程。

### Phase 5：AI 产品经理工作台与市场到 IPD

范围同来源 A（研究/竞品/细分/机会树/实验/策略/定义/矩阵/IPD 衔接），修订：

- V5-1/V5-2 证据底座已在 Phase 2 建成，此处只扩展采集调度器与产品管理专用连接器；
- Product Management Intelligence（D21）上线即承担辩论"产品经理"席位；
- 8 个 capability 分两批灰度：先 research/competitor/market，后 strategy/definition/matrix，每个 capability 独立质量线，不达标单独停用。

### Phase 6：共享资源组合排程与 vNext Exit

范围不变（Resource Pool、受限排程、组合情景、Executive 简报、红队/迁移演练、Exit 报告）。红队新增两项：辩论投毒（经 reach 抓取的恶意内容影响 Decision Brief）与席位越权（席位读取非锚定对象）零穿透。

## 8. 统一指标

> **验收解释（2026-09-08）**：下列业务百分比为目标参考，按已生效 I9 以 **D14-04** Pilot 实测校准后由 PO 冻结阈值；不得直接视为 V1 已通过的硬线。分子/分母、采样、硬闸与安全指标的区别见 [V0/V1 验收合同 §6](2026-09-08-v0-v1-acceptance-and-pilot-contract.md#6-指标定义校准与通过规则)。

**北极星**（来源 A）：受 PDOS 持续预测的关键里程碑，按最新人工确认 Commitment 如期兑现的比例。

领先指标合并（来源 A 全表保留，来源 B 补充以下）：

- 需求可追溯覆盖率 ≥90%；样机配置完整率 ≥95%；结构化测试率 ≥80%；
- Issue 闭环完整率 ≥90%（High/Critical 有根因/验证/证据/批准）；复发问题占比持续下降；
- Gate 证据完整率关键项 100%；PM 手工更新减少 ≥40%；工程师额外录入时间逐版本下降；
- AI 事实引用正确率关键场景 ≥95%；AI 建议采纳/修改/拒绝分场景统计；
- **新增（D25/D26）**：reach 抓取证据快照覆盖率 100%（无快照不得引用）；辩论 Decision Brief 分歧项完整率（人工比对）；辩论场次预算达标率；投毒/越权红队 0 穿透。

数据质量守门规则（来源 B 9.1 全部采纳）：关键对象不得纯自由文本；测试/Issue/Change/Decision 必须关联正确 Product/Project/Version；AI 内容保留来源/时间/模型版本/审核状态；不得引用过期 Revision 或 Superseded 知识；跨系统同步幂等 + 冲突策略 + 审计。

## 9. 统一 Definition of Done

来源 A 第 9 节全部保留（迁移单 head、RBAC 正反例、同事务 Event/Audit、全量 make check、真实浏览器、320/390/1440、golden cases、shadow 灰度、运行手册回滚），追加：

- 辩论类交付：辩论协议版本化；transcript 可回放；Decision Brief schema 校验；席位投影越权负例；
- reach 类交付：allowlist 政策版本化；快照 digest 校验；注入样本库回归；抓取失败/限流/超大内容路径；
- 工程对象类交付：来源 B P0 DoD（关键 Requirement 有可测 Spec、关键 Test Run 有 Build Configuration、Critical/High Issue 有完整闭环字段、重大选择有 Decision 对象、Gate 自动聚合证据、Action 可溯源）。

## 10. PO 需要确认的事项（合并后）

1. 是否同意 D1-D24 推荐项 + D25-D31 作为统一 vNext 产品合同？（D17/D25/D26 已决策，确认书面化）
2. Sprint 5 Exit 处置（补验/延期例外/仅本地并行）？
3. 辩论首批触发场景是否为 ECR 评审 + Gate 准备？轮次与预算上限？
4. agent-reach 首批 allowlist 域名类别与首批挂载席位？
5. Pilot 项目是否选锂电充气泵项目？ERP 数据 Owner 是谁？
6. Issue 高/严重四眼是否硬规则、低/中是否项目可配置？
7. ~~会议输入首版~~ **已决策（D35）**：系统自动创建钉钉/腾讯会议并绑定链接；转写稿人工上传；深度转写拉取不做；飞书不做。
8. Phase 1 双轨（控制轨 + 工程轨）人力是否支持并行，还是工程轨先行？
9. 产品矩阵首版主维度选择？
10. 全局导航十项是否首版全开，还是 Home/Projects/Engineering/AI Workbench 先行？
