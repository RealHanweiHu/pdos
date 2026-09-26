# PDOS vNext 项目控制闭环改造方案（待 PO 拍板）

> **2026-09-10 架构适用性**：本文为原版/早期设计基线，历史数量、旧实施顺序以及禁止一切联网/席位讨论的文字不覆盖已批准vNext增量。当前技术栈、SoR、Finding模型业务写边界与工程纪律保留；D25/D26、6+1职责、运行记录与业务写的区分、立项与阶段出口见[共同架构合同](2026-09-10-ai-native-architecture-consistency-contract.md)。模型不获得自由HTTP/SQL或业务写权限；受控研究工具不是自由执行通道。

> 日期：2026-08-24
>
> 状态：**产品与实施草案；不是 canonical 执行依据；未授权实现、部署或生产变更**
>
> 前置：当前唯一执行指针仍是 Sprint 5 Exit 候选；S5-1 真实钉钉身份与外发 smoke、生产切换仍按现有 canonical 处理。
>
> 关联：本方案吸收 `2026-08-21-product-usability-optimization-plan.md`，避免形成两条并行产品路线。

## 1. 结论

PDOS vNext 不应继续按“任务、问题、BOM、会议、时间线分别加页面”的方式扩展，而应建设一条可解释、可追责、可闭环的制造业项目控制链：

```text
内外部研究源 → 受控采集/证据库 → 竞品分析 → 市场细分/JTBD
                                         ↓
可衡量结果 → 机会树 → 方案与验证实验 → 产品策略 → 产品定义 → 产品矩阵/路线图
                                                        ↓
                                                候选需求 → Business Case / DCP
                                                        ↓
项目基线 → 任务/物料/试制/测试执行 → 偏差与问题 → 会议决策 → 行动与验证
   ↑                    ↓                         ↓              ↓
组合优先级 ← 跨项目依赖/共享资源 ← 预测排期与影响方案 ← 人工重基线 ← 组织记忆
                                                        ↓
                              实验/质量/服务结果 → 证据与假设更新
```

产品内部的职责分工固定为：

- **确定性引擎**计算日期、依赖传播、资源冲突、齐套率、Gate 规则、提醒 SLA；
- **领域 Agent**理解非结构化证据、发现异常、解释原因、起草方案；
- **人**确认责任人、问题关闭、基线变更、DCP/TR/Gate 与业务真值；
- **ERP/MES/PLM**继续持有各自事实，研究来源持有原始内容；PDOS 持有证据快照、产品判断、项目上下文、开发决策和可审计影响链。本次产品经理工作台不接 CRM、不建设销售分析。

## 2. 目标结果

### 2.1 用户结果

1. 工程师登录后无需逐项目查找，即可看到“今天由我负责什么、什么已逾期、什么待我验证”。
2. 项目经理能从任一物料、任务、问题或会议决策追到受影响里程碑、Gate 和下游项目。
3. 问题从发现到关闭始终有唯一 Owner、目标日期、关闭标准、验证人和证据。
4. 例会只讨论例外和决策；会后结论自动形成待审核的 Decision、Action Item、Issue、Risk 或 Change。
5. 项目堵塞后，系统自动更新 Forecast 并解释传播路径；正式 Baseline/Commitment 只有人能调整。
6. 产品经理能持续获得带来源的竞品与市场分析，把客户问题组织为机会树并通过实验验证，形成经审核的产品策略、产品定义与产品矩阵，再把候选需求、Business Case、IPD 决策和产品结果端到端回溯。

### 2.2 业务结果

- 延期更早暴露，跨项目连锁影响不再靠 PMO 人工拼表；
- 项目例会准备时间、会议时长和重复汇报下降；
- 关键物料齐套状态与试制/Gate 准出关联；
- 问题逾期率、验证退回率和同类问题复发率可量化；
- 从市场机会确认到 Charter/DCP 决策的周期缩短。

## 3. 当前基础与主要缺口

| 领域 | 可复用基础 | vNext 缺口 |
|---|---|---|
| 需求与立项 | Requirement → Development Case → Project、Decision 留痕 | 无 Market Signal、Opportunity、Roadmap、Portfolio Decision；当前关系偏一对一 |
| 产品管理 | 质量/服务反馈、现有产品与物料引用、文档抽取可作为部分内部输入 | 无自动信息采集、研究证据库、竞品/竞品产品、市场细分/JTBD、机会树、验证实验、产品策略、产品定义、产品家族/矩阵与产品经理工作台 |
| 时间 | Project 起止日期、Task 日期、项目内 Task dependency、Stage/Gate | 无 Baseline/Forecast/Commitment 分离、跨项目依赖、工作日历、资源约束和影响快照 |
| 问题 | Open→Analysis→Action→Verification→Closed、Owner/target date | Owner 可为空；无关闭条件、独立验证人、证据、退回/重开、提醒与升级 |
| 会议 | UI 基线曾规划“会议”页签；已有 Decision/Task/Issue/Event | 当前运行产品无 Meeting、Agenda、Transcript、Action Item、会后复查实体 |
| 物料 | Development BOM 三型、Build/Sample/Test、Supplier、ERP BOM/Handoff 引用 | 无项目批次物料需求、齐套快照、供给引用、短缺→时间/Gate 影响 |
| Agent | 6 个静态 Agent、事件调度、Finding 双人工动作、受限数据库角色 | 仅少量事件有路由；run/Finding 强制绑定 Project，立项前 Agent 无合法 scope；Apply 主要落 Risk/Memory；产出与业务现场分离 |
| 提醒 | 钉钉 outbox/通知基础 | 无业务级 reminder policy、逾期扫描、升级链和用户级通知中心；生产 delivery 仍为 false |
| 前端 | 驾驶舱、10 个项目标签、AI Review | 缺“我的工作”；标签按领域模型铺开，加入时间/物料/会议会继续膨胀 |

## 4. 不可退让的产品边界

1. Agent 对业务表继续零直接写权限；唯一写出口仍是创建 Finding。
2. Accept 与 Apply 是两个人工动作；问题关闭、基线调整、DCP/TR/Gate 永远由人确认。
3. 排期、齐套、SLA、Gate 阻断等确定性结果不得交给 LLM 心算。
4. 自动延期仅自动更新 Forecast；不得静默修改 Baseline 或 Commitment。
5. ERP 持有 Material Master、PO、库存、MBOM、Routing、Production Version；PDOS 只保存引用、带时点快照和派生影响。
6. 会议采集仅限明确纳入项目的会议/转写稿；不采私聊，不默认全量监听。
7. Agent 的 tenant/project/user scope 继续由服务端冻结，模型参数不是权限事实。
8. 每项业务写继续同事务产生 Event 与 Audit；迁移号单调递增，测试只连 `pdos_test`。
9. 本次产品管理链路不接 CRM，不建设 Deal/Account/Activity、销售漏斗、赢输单、订单或收入分析；仓库已有 CRM Requirement ingress 保持现状，但不进入 V5、不继续扩展。

## 5. 与原设计冲突的选择

除 D17 已由用户明确选择 B 外，以下选择在 PO 拍板前保持开放；执行清单不得将未决项写成既成事实。

| ID | 冲突 | 选项 A | 选项 B | 推荐 |
|---|---|---|---|---|
| D1 | 旧提案“AI 关闭后系统只读”与已上线手工业务流冲突 | 严格 AI-only，无手工日常录入 | AI-primary：人工事实可录入，Agent 负责预填/建议；AI 停止时主动智能显式失能 | **B**，符合已实现系统和制造业可用性 |
| D2 | “所有环节有 Agent”与当前冻结 6 Agent/禁止多 Agent 协作冲突 | 每个模块新增一个 Agent/自由协作 | 原则上保留 6 Agent并增加版本化`capability_key`；产品经理角色是否作为唯一例外见D21；继续静态路由、无Agent间自由对话 | **B**；不走“一模块一Agent” |
| D3 | Agent 主动帮助与 Finding 唯一写出口冲突 | 允许 Agent 直接建任务、改问题、改排期 | Agent 只提案；规则引擎可自动写派生 Forecast/Reminder，业务真值仍人审 | **B**，保持安全边界 |
| D4 | 用户口语“自动延期”与正式计划治理冲突 | 自动改正式基线 | 自动改 Forecast、生成影响方案；人批准后重基线 | **后者** |
| D5 | 当前 Issue 五态与独立关闭确认冲突 | 保持单向五态，任何有权限的人可关闭 | 保留 Open 作为待确认；进入 Analysis 前强制 Owner/Verifier/日期/关闭条件；新增 Verification Round、reject/reopen；高/严重问题四眼关闭 | **B**，兼容存量未分派 Issue |
| D6 | Meeting 不是当前实体，且现 UI 已移除会议页签 | 继续用 Document+Task 模拟会议 | Meeting/Agenda/Decision/Action Item 成为一等对象 | **B**，否则无法形成会议控制闭环 |
| D7 | 项目物料视图可能越过 ERP SoR | 在 PDOS 复制库存/PO/物料主数据 | 保存 ERP reference + as-of snapshot + 项目需求/齐套派生，不成为库存真值 | **B** |
| D8 | 真正的市场→IPD 是多对多，当前 Requirement→Case→Project 偏一对一 | 保持一对一，只加字段 | 增加 Opportunity/Requirement、Case/Requirement 关联；兼容已有 primary link | **B**，需版本化迁移 |
| D9 | 原 UI 基线 9 页签、现产品 10 页签，新增功能会到 13+ | 原样追加到 13+ | 重组为 7 个大标签或 9 个制造业业务标签 | **推荐 9 个**：比 7 个更易发现专业域，比 13+ 更可控；需 UI baseline 版本升级 |
| D10 | 提醒需要钉钉，但 S5-1 真实外发未通过 | vNext 等钉钉后再做提醒 | 先做站内提醒/升级和 outbox；钉钉作为经人授权的 delivery adapter | **B** |
| D11 | Issue 与质量 NCR/CAPA 语义重叠 | 合并成一个万能问题对象 | Issue 管项目协调；NCR/CAPA 保持质量事实，两者可双向关联/升级 | **B** |
| D12 | 8 月 21 日可用性计划与本方案并行会争夺优先级 | 两条路线并行 | 将其 P0/P1 合并为本方案 Phase 1 基础 | **B** |
| D13 | Agent run/Finding 当前强制 Project scope，市场机会发生在立项前 | 建“虚拟 intake project”绕过 | 将 runtime/context/Finding 演进为服务端绑定的 typed scope（project/opportunity/portfolio 等） | **B**；改动较大但安全语义正确 |
| D14 | 现 Gate 是阶段退出硬闸，不能直接等同 DCP/TR | 给 Gate 塞 subtype 和动态签核槽 | 保留 Gate；新增 Decision Checkpoint 与 Technical Review，二者结果成为 Gate readiness 输入 | **B**，语义最清楚 |
| D15 | Build 物料若动态读取“最新 BOM”，历史齐套会随 ECN 漂移 | 始终读取最新 BOM | Build 选择并冻结 Prototype BOM version/snapshot/digest；ECN 产生新 revision/delta | **B**，保证可审计 |
| D16 | 当前多类 Finding 最终主要被 Apply 成 Risk，无法表达会议/排期/物料对象 | 所有建议继续压成 Risk | 引入 typed proposal payload + 每类白名单 apply adapter + 服务端真值复核 | **B**，同时保持双人工动作 |
| D17 | 原草案拟复用 CRM Requirement ingress 承担市场输入，与“产品经理工作台不接 CRM”冲突 | V5 继续接 CRM，并引入 Deal/Account 上下文 | V5 完全排除 CRM 与销售分析；已有 CRM Requirement ingress 保持现状且与新链路隔离；新增非 CRM 的 pre-project Research/Opportunity ingress | **B，用户已决策** |
| D18 | 会议 Action Item 与现有 Task 会形成两套待办/提醒状态机 | 新建独立 Action Item 全生命周期 | 将 Action Item 作为 Task 的明确 kind/source relation，复用责任、日期和提醒；必要时再升级为独立类型 | **B**，避免双真值 |
| D19 | 一次 Apply 会议纪要时是否同时生成所有业务对象 | 一次 Apply 自动创建 Task/Issue/Risk/Decision | 首次 Apply 只固化 Minutes；每个提取项再单独确认 Owner/日期/标准并 Apply 为正式对象 | **B**，多一步但降低错误扩散 |
| D20 | “自动搜集信息”与 Agent 永无自由 HTTP/浏览器工具的安全红线冲突 | 给 Agent 开放任意网页搜索与抓取 | 建独立受控采集层：allowlist connector/scheduler 采集、版本化和去重；Agent 只读证据投影 | **B**，保留安全、来源和可复现性 |
| D21 | 产品经理工作跨外部研究、分析、定义和组合，现六 Agent 无匹配职责 | 塞进 Executive/Project Agent capability | 新增第 7 个 `Product Management Intelligence`，仍使用同一 runtime、无 Agent 互聊、Finding-only | **推荐新增第 7 个**；这是对“六 Agent 冻结”的显式范围变更，需你批准 |
| D22 | 产品定义/产品矩阵可能与 ERP/PLM Product Master 冲突 | PDOS 复制已发布产品主数据 | PDOS 持有上市前 Concept/Definition/Portfolio/Roadmap；发布后的 Material/Product/CAD 主数据仍由 ERP/PLM 持有并建立引用 | **B** |
| D23 | Agent 自动产出产品策略/定义与产品经理决策权冲突 | Agent 自动发布策略/定义、调整矩阵和立项 | Agent 生成 Research/Analysis/Opportunity/Experiment/Strategy/Definition/Matrix Proposal；产品经理审核发布，IPMT/DCP 决策 | **B** |
| D24 | 市场规模、机会分数和产品组合评分可能被 LLM“心算” | 让模型直接从原始证据计算 | 确定性指标引擎计算 TAM/SAM/SOM、`Importance × (1 - Satisfaction)` 机会分数和组合评分；Agent 只解释、比较和提出假设 | **B** |

### Agent 能力包规划

“覆盖所有环节”通过窄能力包实现，不通过增加十几个 Agent 或让 Agent 互相对话实现；Product Management Intelligence是否成为第7个角色由D21单独拍板：

| Agent | capability_key | 覆盖环节 |
|---|---|---|
| Project Intelligence | `requirement_readiness`、`schedule_control`、`execution_followup`、`gate_readiness` | 需求澄清、时间、任务、问题、风险、行动、Gate |
| Knowledge Lite | `meeting_minutes`、`document_extract`、`project_memory` | 例会、文档和复盘 |
| Engineering Intelligence | `spec_bom`、`material_substitution`、`change_impact` | 规格、BOM、替代料、ECR/ECN |
| Quality Intelligence | `test_quality`、`issue_verification`、`capa_recurrence` | 测试、问题验证、CAPA 与复发 |
| Supplier Intelligence | `material_readiness`、`supplier_delay`、`sourcing_risk` | 齐套、交期与供应风险 |
| Executive Intelligence | `portfolio_schedule`、`resource_conflict`、`decision_brief` | 组合排程、共享资源与管理决策 |
| Product Management Intelligence（D21 待批） | `research_planning`、`competitor_analysis`、`market_analysis`、`opportunity_mapping`、`experiment_design`、`product_strategy`、`product_definition`、`product_matrix` | 自动研究、竞品/市场分析、机会树与实验、产品策略、产品定义、产品矩阵与路线图 |

每个 capability 必须有独立的版本化 prompt、只读投影、tool allowlist、Finding schema、golden cases、预算和质量指标。跨域协同只通过已经落库的系统事实和确定性事件，不让 Agent 互发自由文本消息。

### 产品管理工作台信息架构

产品经理工作发生在项目立项前，因此不塞进项目工作区，而是建立独立顶级工作台：

```text
研究中心 | 竞品情报 | 市场细分·JTBD | 机会树
产品策略 | 产品定义 | 产品矩阵·路线图 | 实验·决策
```

- “研究中心”管理来源、订阅、采集任务、证据快照、更新和冲突；
- “竞品情报”先定义市场边界，再管理直接/间接/新兴竞品、Competitor Product、规格/价格/区域/认证、版本变化、优劣势、威胁和差异化空间；
- “市场细分·JTBD”按客户问题、使用环境、待完成任务和购买标准划分市场，而不是只按行业或人口属性分组；
- “机会树”以一个可衡量的 Desired Outcome 为根，连接客户机会、至少 3 个候选方案及价值/可用性/可行性/商业可持续性实验；
- “产品策略”使用 Product Strategy Canvas 固化愿景、细分/JTBD、相对成本、价值主张、明确取舍、指标、增长路径、关键能力/合作与防御性；
- “产品定义”固化目标客户、场景、价值主张、差异化、目标规格、成本/价格带假设、法规、服务方式、上市窗口和成功指标；
- “产品矩阵·路线图”管理 Product Line→Family→Platform→Series→Model/Variant，以及覆盖空白、重叠、蚕食和生命周期。

### 推荐的项目工作区信息架构

若选择 D9 推荐项，项目工作区调整为：

```text
概览·控制塔 | 计划·资源 | 工作项 | 物料·供应 | 工程·变更
例会·决策 | Gate·交付物 | 试制·测试·质量 | 文档·知识
```

- “计划”：Baseline/Forecast/Commitment、依赖、资源与场景；
- “工作项”：Task（含 meeting action kind）/Issue/Risk 的统一列表与类型过滤；
- “物料”：批次需求、齐套、短缺、供应商与时间影响；
- “会议·决策”：Agenda、Transcript、Decision、Action、复查；
- “AI”：项目内联洞察 + 全局 Review Inbox + 右侧上下文助手，不新增标签。

## 6. 依赖顺序

```text
PO 决策 D1-D24 + Sprint 5 当前出口处置
  → Phase 0：契约/指标/兼容策略冻结
  → Phase 1：我的工作 + 问题责任/验证 + 提醒 + AI 可见性
  → Phase 2：会议 → 决策 → 行动/问题闭环
  → Phase 3：Baseline/Forecast + 跨项目依赖 + 排期影响
  → Phase 4：项目物料齐套 + 供应链/排期联动
  → Phase 5：产品经理工作台 → 产品定义/矩阵 → 需求 → DCP/IPD
  → Phase 6：共享资源组合排程 + 试点校准 + vNext Exit
```

Phase 1 是后续所有模块的共同执行出口；Phase 3 的时间影响合同是 Phase 4 物料联动的前提；Phase 5 可在 Phase 3 合同冻结后并行做市场对象，但不可绕过统一 Decision/Gate 模型。

## 7. 分阶段改造计划

### Phase 0：产品合同与兼容基线

**结果陈述**：让 PO、研发、测试和试点用户对“什么是业务真值、什么可自动、什么必须人签”达成一致，避免实现到一半重新定义。

范围：

- 拍板 D1-D24；
- 处置当前 Sprint 5 Exit（完成、明确延期例外，或批准仅本地并行）；
- 固化版本事实：当前本地 migration head 为 `0033`、最后生产验证为 `0032`；vNext 后续迁移从 `0034` 单调递增，不反向声称已部署；
- 冻结新增对象、状态机、SoR、权限、事件、错误码和兼容迁移；
- 选择 1 个具有跨项目、物料和例会痛点的真实试点组合；
- 建立匿名化 golden cases 与基准指标。

Exit：24 项选择有书面结论；试点数据 Owner、业务 Owner、质量 Owner、研究来源/ERP/PLM Owner 已确认边界；CRM 与销售分析明确不在 V5 范围；无代码实现先于合同。

### Phase 1：个人工作与问题闭环

**结果陈述**：让每个责任人零次查找即可接单、处理、提交验证并收到有节制的提醒，使项目问题真正可追责关闭。

范围：

- 跨项目 `My Work` 聚合：Task、Action Item、Issue、Risk、CAPA、Gate 签核、Finding；
- Issue Owner 必填、关闭条件、Verifier、Evidence、Reject/Reopen、严重级四眼；
- 把通用 `WORK_ITEM_EDIT` 拆成 Issue assign/execute/verify 权限，防止“能编辑就能关闭”；
- Task 增加 meeting action kind/source relation，复用既有责任、日期和提醒能力；
- Reminder Policy、扫描、幂等 delivery、升级链、站内通知中心；
- 现有 6 Agent 的高价值事件补路由、运行中可见性、Finding 回到业务现场。
- 修复前后端 Finding/Agent 类型契约漂移；建立 typed proposal/apply adapter 基础，不再把所有领域建议压成 Risk。

Exit：高/严重 Issue 不能由 Owner 自关；验证不通过可退回；逾期提醒可重放但不重复发送；登录后可看到全部本人待办；Agent 零业务表直接写。

### Phase 2：例会与决策闭环

**结果陈述**：让项目例会从“写纪要”变成“基于例外做决策、形成责任和复查”的控制动作。

范围：

- Meeting、Agenda Item、Attendee、Transcript Reference、Meeting Link；
- 项目周会、物料会、专项会、TR、DCP/IPMT、试制复盘模板；
- 会前自动装配：逾期行动、关键问题、物料短缺、排期变化、Gate 缺项；
- Knowledge Lite 的 `meeting_minutes` capability：带片段引用地起草 Minutes 与 Decision/Action/Issue/Risk/Change 候选；
- 首次人审 Apply 只固化 Minutes；每个候选项再单独确认责任、日期、关闭标准并 Apply；会后摘要、通知和下次复查。

Exit：一场真实试点会议完成“会前议程→转写导入→AI 提案→人审→任务/问题/决策→下次复查”；无引用结论不得应用；私聊与未授权会议零采集。

### Phase 3：项目时间与延期传播

**结果陈述**：让 PMO 在问题发生后立即看到受影响路径、预测日期和恢复方案，而不是手工修改多个甘特图。

范围：

- Baseline、Forecast、Commitment、Actual 四类时间；
- Project/Stage/Gate/Task/Build/Test 统一 schedule node 视图；
- FS/SS/FF/SF 依赖、lag、工作日历、跨项目依赖；
- 确定性关键路径与 forecast snapshot；
- Change Proposal、场景对比、人审 Rebaseline；
- Project Intelligence 解释传播原因和恢复方案。

Exit：上游节点延迟只影响可达下游；有 float 的节点不误延；Forecast 自动变化、Baseline/Commitment 不变；人审重基线有版本、Event/Audit 和回滚依据。

实施分层：首版只开放 Finish-to-Start + lag + 项目日历 + Task/Gate；固定案例和试点稳定后再开放 SS/FF/SF、Build/Test 与跨项目复杂关系，避免一次性扩大排期语义。

### Phase 4：项目物料与齐套联动

**结果陈述**：让项目团队按 Build/阶段看到“需要什么、何时需要、缺什么、会影响什么”，且不复制 ERP 库存真值。

范围：

- 先补齐现有 BOM item、Build/Sample/Test 的 BFF/UI 操作面，再建设 Project Material Requirement；
- Build 选择并冻结 Prototype BOM version/snapshot/digest；需求关联 BOM item、Build batch、阶段和 need-by node；
- ERP/采购/供应商 supply reference 与 as-of snapshot；
- 齐套率、关键齐套率、长周期料、替代料、质量冻结与 stale 标识；
- Material shortage → Issue/Risk → Schedule forecast → Meeting/Gate；
- Supplier Agent 的跨项目暴露、缓解方案和内部 Owner 建议；
- ECR/ECN 对物料需求和已下单供给的影响。

Exit：选定 Build 的物料需求与 ERP 抽查一致；来源过期不得显示为“已齐套”；关键短缺可追到受影响任务/Gate/项目；ERP 零反向写入。

### Phase 5：AI 产品经理工作台与市场到 IPD

**结果陈述**：让产品经理从“到处搜资料、手工拼 Excel/PPT”升级为“审核持续更新的证据、市场问题、验证实验、产品策略、产品定义和产品组合建议”，并把批准后的产品定义转换为候选需求和 IPD 立项输入。

#### 5.1 受控研究与证据层

- `Research Source`：来源类型、URL/API/文件/系统、Owner、许可、采集频率、允许用途和保留策略；
- `Collection Job`：按日/周/月或事件触发，记录成功、失败、限流、重试和覆盖范围；
- `Evidence Snapshot`：不可变正文/结构化摘要指针、抓取时间、source version、content digest、语言、可信度和数据新鲜度；
- allowlist connectors：首版优先竞品官网与公开产品资料、指定行业/法规/标准来源、经来源策略批准的公开评价，以及产品经理人工上传的访谈、研究报告、质量/服务反馈和现有产品资料；
- 去重、版本差异、来源冲突和过期标识；市场网页、报告和转写均视为不可信输入；
- Agent 无自由 HTTP、浏览器、SQL或消息发送工具，只读取通过采集与安全投影的证据。

#### 5.2 竞品分析

- 先冻结品类、客户问题、使用场景、地域和比较周期，避免把不在同一市场的产品硬放入一张表；
- 识别直接、间接和新兴竞品，维护 Competitor 与 Competitor Product/Profile；
- 比较产品规格、功能、目标细分/JTBD、公开价格带、区域、认证、商业模式、上市/退市和版本变化；
- 输出参数矩阵、定位图、优势、弱点、替代关系、威胁等级和可防守的差异化机会，而不是只生成“功能清单”；
- 对新增型号、价格/规格/认证变化定期提醒；每个结论可回到来源快照，并明确区分事实、推断和未知。

#### 5.3 市场细分与 JTBD

- `Market Space` 冻结品类边界、地域、时间范围、替代方案和不纳入范围；
- `Market Segment` 不只按行业/区域划分，而要绑定客户问题、使用环境、JTBD、现有替代方案、购买标准和未满足程度；
- 管理 Use Case、Persona/Role、Region、Price Band、Regulation/Standard，以及趋势、增长驱动、技术替代和法规变化；
- TAM/SAM/SOM 等量化结论必须保存公式、参数、币种、时间、地理范围和来源，并由确定性指标引擎复算；
- 分析输出必须保留反证、数据缺口和待验证假设，不能把没有证据的市场叙事标为事实。

#### 5.4 Opportunity Solution Tree 与实验闭环

- 每棵树以一个可衡量的 `Desired Outcome` 为根，避免同时追逐互相冲突的抽象目标；
- `Opportunity` 只描述客户问题、痛点或 JTBD，不提前写成功能；绑定证据、受影响细分、重要度、满意度、战略匹配和状态；
- 机会分数使用版本化量表和确定性公式 `Importance × (1 - Satisfaction)`，Agent 不自行编造分数；
- 优先机会在收敛前至少形成 3 个 `Solution Candidate`，防止锁定第一个点子；
- 每个方案显式登记 Value、Usability、Viability、Feasibility 四类关键假设和最小验证实验、通过阈值、Owner、期限及结果；
- 实验结论可证伪并回写机会/方案状态；失败实验保留为组织知识，不被静默删除。

#### 5.5 Product Strategy Canvas 与产品定义

- Product Strategy Canvas 固化 9 项内容：愿景、市场细分/JTBD、相对成本位置、价值主张、明确取舍、NSM/OMTM、采用/增长路径、关键能力/合作伙伴、防御性与竞争者难以复制之处；
- `Product Concept` 从已验证机会与候选方案生成，绑定目标细分、价值主张、差异化和仍待验证的关键假设；
- `Product Definition` 固化目标客户/场景、核心价值、目标规格与体验、目标成本/价格带/单位经济假设、法规认证、服务方式、上市窗口和成功指标；
- 每个定义项必须标记 evidence-backed、assumption 或 decision，并链接机会、实验、策略取舍和竞品证据；
- Product Strategy 与 Product Definition 均版本化发布：Agent 只起草和比较，产品经理审核发布；已发布版本不可静默覆盖；
- 批准的定义生成候选 Requirement，不自动建项目、不自动批准 Business Case/DCP。

#### 5.6 产品矩阵、组合与路线图

- Product Line→Family→Platform→Series→Model/Variant 分层；
- 按细分市场、使用场景、价格带、区域、渠道、能力/规格和生命周期建立矩阵；
- 识别覆盖空白、产品重叠、内部蚕食、平台复用、升级/替代和退市候选；
- 场景比较：新增、升级、合并、延后、退市；指标引擎计算组合影响，Agent解释取舍；
- PDOS持有上市前概念、定义、组合和路线图；正式Product/Material/CAD主数据仍由ERP/PLM持有并建立引用。

#### 5.7 Agent与IPD衔接

- 若批准D21，新增 `Product Management Intelligence`，能力包为 `research_planning`、`competitor_analysis`、`market_analysis`、`opportunity_mapping`、`experiment_design`、`product_strategy`、`product_definition`、`product_matrix`；
- AI runtime/context/Finding scope v3支持 tenant/market_space/product_line/opportunity/product_definition/portfolio，全部由服务端冻结；
- 每类分析和定义是typed proposal，必须经过产品经理Review与独立Apply；
- Opportunity↔Requirement、Case↔Requirement多对多兼容层保留现有primary链；
- Decision Checkpoint（商业GO/KILL/HOLD/REDIRECT）与Technical Review双轨，Gate继续作为阶段退出硬闸；
- Charter批准后再实例化IPD v2项目模板、Baseline、会议节奏和初始物料计划；
- 用户研究、验证实验、试点、质量、服务和生命周期结果回链到原 Opportunity、Strategy、Product Definition 与关键假设。

Exit：选定一个真实品类完成“自动采集→竞品/市场分析→市场细分/JTBD→机会树→验证实验→产品策略→产品定义→产品矩阵→候选需求→Business Case/DCP→IPD项目”的可跳源闭环；所有量化指标可复算，所有AI结论带证据，Agent不得自动发布产品策略/定义、调整产品矩阵、立项或批准DCP/TR。

### Phase 6：共享资源组合排程与 vNext Exit

**结果陈述**：让产品线负责人能基于人员、技能、设备、模具、实验室、试制线和供应商窗口比较组合方案。

范围：

- Resource Pool、Calendar、Capacity、Reservation，兼容当前 project-scoped Resource；
- 资源受限排程和优先级政策；
- 组合情景：加班、替代设备、外协、降级或顺延低优先项目；
- Executive Agent 的组合例外简报，不做人员绩效排名；
- 试点运行、预测校准、通知降噪、性能、安全和迁移验收。

Exit：共享资源冲突能稳定复现并给出不同情景；方案应用仍经人审；试点达到指标后才形成新的 canonical 发布计划。

## 8. 产品指标与质量门禁

### 北极星

**受 PDOS 持续预测的关键里程碑，按最新人工确认 Commitment 如期兑现的比例。**

### 领先指标

- 延期提前发现天数；Baseline 与 Forecast 偏差；Forecast 误差；
- 有唯一 Owner、目标日期、关闭条件、Verifier 的开放 Issue 比例（目标 100%）；
- Issue 首次响应时间、平均关闭周期、验证退回率、重开率、复发率；
- 会议准备时间、会议时长、行动项按期关闭率；
- 关键物料齐套率、短缺预警提前量、数据新鲜度；
- 研究来源覆盖率与新鲜度、证据可追溯率、分析事实错误率；
- 竞品变化发现提前量、产品定义证据覆盖率、产品定义审核周期；
- 机会→实验周期、假设验证/证伪率、机会→产品定义→Charter/DCP 周期；
- 产品矩阵覆盖空白/重叠数、策略取舍覆盖率、产品结果验证覆盖率；
- Finding 证据覆盖率（目标 100%）、接受率、Apply 率、误报率；
- Agent 直接业务表写入（目标 0）、跨租户/跨项目穿透（目标 0）。

## 9. 项目级 Definition of Done

每个垂直切片除自身验收外，必须同时满足：

- migration 单一 head、upgrade/downgrade/metadata drift 和有损 downgrade guard；
- tenant/project/RBAC/数据库角色正反例；`pdos_agent` 对新增业务表零写；
- 业务写与 Event/Audit 同事务；重复事件/提醒/outbox 幂等；
- 聚焦测试、全量 `make check`、真实 HTTP 与真实浏览器验收；
- 320/390/1440px、亮暗主题、键盘/焦点与外部角色零泄漏；
- AI golden cases、引用 preflight、no-action、预算熔断、停 LLM 可见失能；
- 每个 capability 先进入 shadow/no-action 观测，再开放 Finding，最后才开放对应 Apply；真实模型领域质量不能只用预制 JSON/schema 测试代替；
- 指标、日志、运行手册、回滚路径和兼容迁移说明；
- 人工验收后才更新 canonical checkbox 或移动执行指针。

## 10. PO 需要先确认的事项

1. 是否同意 D1-D24 的推荐项作为 vNext 产品合同？
2. 是否同意把 8 月 21 日可用性优化计划并入 Phase 1，不再独立实施？
3. 当前 Sprint 5 Exit 是先补验、正式接受延期例外，还是允许 vNext 仅本地并行？
4. 首个试点选择哪条产品线、哪些并行项目、哪个 ERP 数据 Owner？
5. Issue 高/严重级四眼关闭是否为硬规则；低/中级是否允许项目配置？
6. 会议输入首版采用“人工上传转写稿”，还是指定钉钉/飞书会议导出连接器？
7. 是否批准新增第7个 `Product Management Intelligence` Agent，还是先把能力临时放进 Executive/Project Agent？
8. 自动采集首版允许哪些竞品/行业/法规/标准来源，以及哪些人工上传研究、质量/服务和现有产品资料？频率、允许用途和首个真实分析品类是什么？（不含 CRM 与销售数据。）
9. 产品矩阵首版采用哪些主维度：细分市场、使用场景、价格带、区域、渠道、规格能力和生命周期中的哪些？
