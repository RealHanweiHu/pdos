# PDOS-next 架构设计整理稿

> **v1.1 更新（2026-10-08）**：目标架构已修订为 [v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)（用户批准并冻结），决策见[设计确认稿](2026-10-08-pdos-next-design-confirmation.md)。主要变化：主线是 pdos-next，原工程已停用归档；品类为权限范围根；立项前只交立项提案，唯一业务关卡 G0；规格字典与共用规格条目；研究方法改为技能包，不再有机会/实验/策略对象；唯一 Agent 小Pai（工具、MCP、技能包，§06 改写）；§08.11 一致性与性能规则；错误码约 15 类；建设阶段改称 S0–S5，先整体重构再做“品类研究到立项”。本整理稿下文按 v1.0 编写的部分，与 v1.1 冲突时以 v1.1 为准；§7 是 2026-10-05 的历史快照。


日期：2026-10-08。性质：**导读整理稿**。本文不改写、不取代任何权威文档；与上游文档冲突时以上游为准。权威链：[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)（v1.0 已被取代） + [pdos-next 执行方案](2026-10-02-pdos-next-execution-plan.md) + [Agent 运行架构收口合同](2026-10-07-agent-runtime-convergence.md)（均已生效）。实现与验收的**活动状态唯一来源**是[唯一清单 pdos-next 队列](../../tasks/ai-native-integrated-todo.md#pdos-next-queue)，本文 §7 只是 2026-10-05 队列的快照。

## 0. PDOS-next 是什么

PDOS 是 AI-native 的产品开发与 NPI（新产品制造导入）操作系统，面向消费电子的自主品牌、OEM/ODM、派生、降本、质量改进、客户变更、制造转移与认证开发。**pdos-next（`pdos-next/`）是为这个完整目标新建的独立工程**：拥有独立 Python 包、Next.js 应用、依赖锁、Alembic 迁移链（`next_00xx` 独立编号）、数据库与运行配置；不以旧 PDOS 代码、表结构、合同编号或已完成任务为约束。旧工程（`server/` + `web/`）的纯运行框架、协议算法、UI 资产按[复用矩阵](2026-10-02-pdos-next-reuse-and-parallel-plan.md)复制或抽取，但**业务模块、表、状态机、角色、正式决定与资格不继承**。两线并行、互不继承资格。

一句话定位（目标架构 §1 核心决定）：**产品/工程开发与制造导入两条主线，在每轮实物活动（Build）汇合；一套领域事实与证据内核，同时服务人员操作、确定性流程和自主 AI 执行。**

## 1. 总体架构

### 1.1 六层逻辑结构（非六个微服务）

```text
体验：用户工作空间 + 小Pai + 对象内协作 + 移动轻办理
工作：目标型委派、业务工作包、承诺、交接、决定、注意队列
领域：产品/工程配置/项目/Build/测试/NPI/品质/供应/发布
证据：原始资料、版本、关系、来源、适用性、权限与撤回
智能：上下文 → 计划 → Skill/工具 → 领域命令 → 结果复查
平台：持久工作流、身份、数据库、模型、存储、检索和连接
```

正式状态由领域模块拥有，其余层只使用投影和命令。

### 1.2 支撑全局的架构立场

- **三种体验共用一个业务内核**：对话委派、就地办理、主动执行三入口调用相同领域命令、权限与验收；对话不绕过页面权限，页面不因未用 AI 另设流程。
- **产品与 NPI 并行**：NPI 从产品定义即参与；Build 同时引用工程配置与制造配置两条主线的适用版本；多 Build 可并行，阶段与 Build 不一一对应。
- **Product ≠ Project ≠ Build**：无项目可做研究（不建虚假项目）；真实开发才建 Project 并经 ProjectProductLink 绑定明确有效定义版本；Build 是有目的、配置、实物与处置范围的一轮活动。
- **任务/聊天/看板是工作方式**，不替代产品定义、配置、承诺、测试、制造能力、专业决定这些一等对象。
- **前台信息架构**：我的工作｜产品｜项目｜组合与资源｜知识；小Pai 常驻；专业跨项目队列是事实的保存视图，不建第二套事实库。
- **三种起点轻重路径**：自主新品（先探索后投入）、ODM（平台匹配→差距→配置/派生/新开）、OEM（客户设计包→内部导入定义）；小变更可走 ChangeRequest 不必重新立项。

### 1.3 架构决定记录（ADR 摘要，A01–A20）

| 主题 | 决定 |
|---|---|
| 设计立场 | A01 全新目标而非兼容改造；A12 模块化内核优先于微服务；A20 按纵向业务切片交付（G0–G5） |
| 业务骨架 | A02 产品与 NPI 并行；A03 一套事实内核；A04 强类型领域 + 统一注意投影；A05 Product/Project/Build 解耦；A06 双配置与五视角；A07 固定父版+显式覆盖 |
| 工作与自动化 | A08 工作以结果完成（Run 成功 ≠ 业务结果）；A09 T0/T1/T2 按操作分级；A10 主协调者 + 按需专业能力；A14 四时间分离；A15 准备度是规则集 |
| 一致性与安全 | A11 Temporal 拥有长流程；A13 关系/版本/证据优先于向量召回；A16 发布与外部生效分开；A17 源权限贯穿记忆与输出；A18 Outbox+幂等+未知对账；A19 模型资格按能力/用途 |

## 2. 领域架构（对象与事实）

### 2.1 十一个领域模块

| 模块 | 核心对象 |
|---|---|
| 产品发现与定义 | Research、SourceObservation、Opportunity、Experiment、Product、Variant、DefinitionRevision、Requirement、Spec |
| 工程与配置 | Platform、Module、InterfaceContract、Part、BOMRevision、DesignReference、EngineeringConfiguration |
| 项目与工作 | Project、ProjectProductLink、WorkPackage、Task、Dependency、PlanRevision、Commitment、ExternalWait、Handoff |
| Build 与验证 | Build、BuildLot、SampleUnit、ActualConfiguration、VerificationRequest、TestPlan、TestRun、Measurement |
| NPI 与制造 | ProcessRevision、Operation、Tooling、ToolTrial、Fixture、Equipment、ControlPlan、WorkInstruction、PilotRun、Qualification |
| 品质与变更 | Issue、FailureMode、Containment、CAPA、ChangeRequest、ImpactAssessment、ChangeOrder、EffectivityPlan |
| 供应与成本 | SupplierReference、MaterialDemand、SupplyCommitment、AvailabilitySnapshot、AlternateQualification、CostEstimate |
| 评审发布与接收 | Review、Decision、Waiver、ReleasePackage、Acceptance、ExternalAcknowledgement |
| 证据与知识 | ArtifactVersion、EvidenceReference、Claim、ApplicabilityAssessment、KnowledgeCandidate、DesignRule |
| 智能工作 | WorkRequest、ProposalBatch、SkillVersion、AutomationRule、Run、ActionReceipt、AttentionItem |
| 平台与身份 | Principal、Grant、PolicyVersion、IntegrationMapping、Inbox、Outbox、Audit |

每个正式字段只有一个权威写入口；对象不必一对一对应表。`pdos-next/server/pdos_next/domain/` 现有 35 个领域子包即按此分工落地。

### 2.2 关键领域概念

- **定义与规格**：DefinitionRevision 版本化（draft→in_review→released→superseded/withdrawn）；Spec 条目带参数/单位/允差/测试条件/判定方法/适用变体；研究观察、AI 推断、已接受需求、已发布规格是不同成熟度，不用单一 confidence 混同。
- **派生复用**：固定父版本 + 显式覆盖；父版更新做旧父/新父/子版三方差异，不自动覆盖；子项目成果回平台走独立采用/发布动作。
- **双配置五视角**：工程配置（定义/BOM/机电固版本/关键件/偏差）与制造配置（工艺/工装设备/SOP/检验/产线）分离；As-designed/As-planned/As-built/As-tested/As-delivered 是快照用途，不是五份自动同步的最新版。
- **Build/Lot/Sample/TestRun**：计划配置与实际配置不得互相覆盖（I04）；混合配置拆批次或逐件明确；measurement、computed_result、professional_conclusion、ai_hypothesis 四者分开（I06）；测试中途关键变化按允许分段或新建 Run。
- **四种时间真值**：Baseline（批准计划）/Forecast（计算预测）/Commitment（明确承诺）/Actual（真实发生）分版本保存，预测不自动改承诺（I08）。
- **事实性质与可用性**：Claim 分 observed/extracted/computed/inferred/decided；可用性分 known/unknown/conflicted/not_applicable；事实发生、系统接收、业务有效三个时间分别记录。
- **证据适用性**：ApplicabilityAssessment 绑定证据版本×目标配置×用途；语义相似只产生候选线索，不能自动成为"已覆盖"；源撤回后失效传播（I07）。
- **工作对象不压扁**：Task、Decision、VerificationRequest、Handoff 各自保留语义；AttentionItem 只是只读聚合投影，不是第二份待办真值（I11）。
- **身份与责任**：human_owner、writer、requester、approver、verifier、receiver 分列；AI 可为 writer，不成为测试执行者或专业批准人。

### 2.3 二十条核心不变量（I01–I20，分组归纳）

- **所有权与版本**：I01 唯一权威写入口；I02 项目范围绑定有效定义；I03 发布/冻结不可静默修改；I17 删除/撤回不抹去受控历史。
- **实物与验证**：I04 计划/实际配置不互覆；I05 TestRun 绑定真实测试范围；I06 原始测量与 AI 解释分开；I07 复用证据须适用；I09 制造/工程/客户/外部接收分开。
- **计划与预测**：I08 预测/基线/承诺/实际分开。
- **AI 边界**：I10 AI 用受控命令而非任意表写；I11 T0 成功不产生人工待办；I12 T1 只确认真实载荷与目标版本；I13 T2 不授予 AI 决定权；I14 共享输出不突破来源受众权限。
- **一致性与外部**：I15 业务/审计/Outbox 同事务；I16 重复意图不产生重复副作用；I18 外部结果未知 ≠ 失败 ≠ 成功；I19 缺失/冲突/不适用/失败不混类；I20 软件测试通过不代表制造或模型真实资格。

### 2.4 外部系统权威边界

PDOS 拥有开发定义、研发计划/配置、验证与 NPI 准备、决定与移交状态；ERP 拥有库存/采购/核算与物料实际生效；MES 拥有生产执行；CAD/EDA/Git 拥有专业制品；CRM 拥有销售管道。已有 PLM/QMS 权威对象时按绑定策略选原生或引用，同一对象同一阶段不允许无规则双写；未连接系统用真实人工导入并标明未知，不伪装实时集成。

## 3. 工作流、决定与放行架构

### 3.1 三套状态各有所有者

领域记录状态（实际业务）、持久工作流状态（系统在等什么，Temporal）、Agent 步骤状态（一次执行到了哪）以稳定 ID 关联、互不覆盖。LangGraph interrupt ≠ 已批准的工程决定；Workflow completed ≠ Build 测试通过。

### 3.2 状态契约（代表性主状态）

DefinitionRevision、WorkRequest、Task、Build、VerificationRequest、TestRun、Handoff、Issue、ChangeRequest/Order、Review、ReleasePackage、ExternalHandoff、AutomationRule、Run 各有显式状态机（目标架构 03 §3 全表）。要点：Build 的 authorized 只覆盖本轮批准用途而非量产放行；VerificationRequest 的接收/承诺/开测时钟分别记录；TestRun 的 pass/fail/invalid 是结果维度不混入执行状态；变更的批准、实施、生效、有效性分开。

### 3.3 AI 直接写入分级（T0/T1/T2，与 DC-11 一致）

- **READ**：无业务写权，不与 T0 混同。
- **T0 受控自动写**：独立 AI 身份在明确资格+当前授权内做可逆、无签核/外发语义的操作（如建 Issue、记 Claim、维护 AI 专属字段）；成功只留活动回执，不产生人工待办。
- **T1 一次实质确认**：固定候选载荷（ProposalBatch 独立原子组）、目标版本与最小来源读集；版本变化只重新呈现真正受影响差异。
- **T2 具名决定**：签核、批准、正式发布、外发、专业处置；AI 只能准备，永不取得执行身份；提示注入中的"已获批准"文字始终是数据（AT-36）。

### 3.4 准备度、冻结点与四种放行

- **准备度是一组规则而不是 AI 分数**：每条规则有 predicate/required_evidence/freshness/severity/waivable/allowed_purpose；聚合优先级 BLOCKED > UNKNOWN > READY_WITH_CONDITIONS > READY；高分不抵消硬阻塞（AT-17）。
- **冻结点**覆盖 ID/结构冻结、开模授权、长交期采购、认证样机、客户承诺、制造发布；跨冻结点的变化自动进入影响评估。
- **四种放行分别成立**：工程发布（设计可用于什么）、制造放行（哪个场地/产线什么范围可造）、客户承认（接受哪个版本及条件）、市场/认证适用性；ERP/MES 实际生效是外部执行事实，独立于上述决定。

## 4. Agent 运行架构

### 4.1 运行体系与收口（2026-10-07 合同，已实施两线共用）

所有 Agent 完整能力经 **Temporal 工作流/Activity → LangGraph 执行图 → 受控模型网关/工具/领域服务**（AGENTS.md 不可协商项 6）；模型网关拒绝绕过注册执行图的正式调用。

| 责任 | 唯一边界 |
|---|---|
| 持久任务、定时等待、调度、Activity 重试 | Temporal；Workflow 历史只存固定工作引用 |
| 能力内执行与检查点 | LangGraph（独立 PostgreSQL 检查点）；检查点不拥有业务批准 |
| 模型选路、资格、出站、计量、未知调用 | 各工程自己的服务器网关；框架不授予资格 |
| 业务事实、幂等、版本、撤回、具名批准 | 原有领域服务与数据库合同 |
| 会话与共享范围 | 原服务器授权与引用守卫，每次执行与返回重核身份 |

共同运行时代码在 `packages/pdos-agent-runtime/`（不导入业务模块）。pdos-next 保留自己的 WorkRequest/Run、Outbox、SourceWork、领域命令与独立 AI 身份，用共同执行图并以自己的 ModelRuntimePorts 组装模型工厂；API/ASGI 默认开启持久队列，Worker 缺配置/资格时记 `MODEL_RUNTIME_PORTS_MISSING` 并保留人工办理。新旧工程不共享业务库、状态凭据或资格。模型默认关闭；模型不可用时领域操作与确定性引擎仍可用、AI 明确失能（AT-45）；worker 错误路径零 LLM。

### 4.2 执行模型

- **唯一 Agent 小Pai（v1.1）**：对话、页面、事件、定时都由小Pai 执行，经工具（由命令登记表生成）、MCP 连接器和渐进加载的技能包完成工作；不设领域 Agent，不构造 Agent 群聊。
- **SkillVersion 契约**：key/version/purpose/输入输出 Schema/allowed_operations/evidence_policy/failure_policy/budget/模型能力要求/评测套件/owner；Skill 不是提示词文本。
- **AutomationRule**（v1.0 的 Loop 统一改称）：trigger（domain_event/schedule/relative_milestone/manual）+ goal/stop_condition + 预算/冷却/去重/级联上限；触发风暴受控（AT-43）。
- **上下文与 Memory**：构建优先级为明确对象/版本→工作状态→显式关系→适用证据→授权检索→有效记忆；ContextSnapshot 记录读集并在写入前重验关键读集。Memory 五层（个人偏好/当前工作/项目事实/平台经验/正式规则），项目事实从领域查询重建，源权限贯穿检索、缓存、摘要与输出（I14、AT-37）。
- **Run 与 ActionReceipt**：工具返回成功字符串不是完成证明，必须收到真实命令回执；业务写入与回执/Outbox 同事务；取消以领域 cancel_epoch 为准，已发出的外部副作用先对账（AT-41）。
- **资格晋升链**：开发→离线评估→影子比对→T1 真实试用→限定 T0→持续监测；资格绑定能力/操作/版本/场景，不是模型全局授权；模型自报置信度不作放行条件。

### 4.3 单 Agent + 技能包（v1.1 已定）

见 [v1.1 §06](2026-10-08-pdos-complete-target-architecture-v1.1.md)：唯一 Agent 小Pai；技能包三要素（工具、数据语义、使用原则），版本化配置文件、渐进加载；工具由命令登记表生成；MCP 管理员准入、逐项授权、外部写入按 T2；公开研究子任务与不可信内容隔离；试点租户以本人审阅记录作为草稿类技能包 T0 资格。

## 5. 技术架构

### 5.1 拓扑与固定技术栈

```text
Web / 移动 Web / 钉钉轻入口
        ↓
Next.js 同源 BFF（TypeScript）
        ↓
FastAPI 领域命令与查询（Pydantic + SQLAlchemy）
  ├─ PostgreSQL（业务事实、版本、审计、Outbox）
  ├─ 私有 S3 兼容对象存储（版本化原件）
  └─ 读取投影 / 全文 + pgvector 检索
        ↓
Outbox → Temporal 持久工作流
           ├─ AI Worker → 模型网关 →（LangGraph 执行图）
           ├─ 解析/分析 Worker（隔离容器，如 containers/evidence-parser）
           └─ Connector Worker（ERP/MES/CRM/钉钉）
```

UI：shadcn/ui + Tailwind v4 + Geist + Phosphor，橙 `#c2410c`/`#fb923c`，8px 圆角，双主题（[UI 基线](2026-08-09-ui-baseline.md)）。Redis 仅作缓存/节流，不作唯一工作状态；不预设 Kafka/Neo4j/K8s/多套向量库。

### 5.2 四类状态存储

领域数据库（正式事实）、Temporal 持久库（执行位置/定时器/等待，独立库与凭据）、AI 检查点（能力中间结果，不拥有批准）、查询投影（可重建，带 as_of/watermark）。长人工等待在 Workflow 挂起；人经领域 API 决定，事务提交后 Outbox 发信号，Workflow 读取正式结果继续，不在两个引擎分别批准。模型与外部网络调用放 Activity/非确定性步骤。

### 5.3 命令、事件与一致性

- **单一领域命令入口**：页面/聊天/自动化/集成共用同一命令；`pdos-next/contracts/operations.json` 是 66 项关键操作目录（重建自合订本，标记 derived），涉及自主级别/正式状态/外部动作的命令必须显式注册。
- **可信上下文服务端绑定**：tenant、actor、grant、run、cancel_epoch、出站政策由服务器认证与运行上下文绑定，模型同名传参不成为授权（不可协商项 2）。
- **命令事务**：核身份/授权/取消标记→校验版本与关键读集→单事务写事实+ActionReceipt+Audit+Outbox→返回真实结果→异步更新投影；事务内不等 LLM/ERP 网络。
- **幂等**：同幂等键同载荷返回原结果，同键不同载荷冲突（AT-40）；稳定意图指纹由服务端按来源事件/目标/操作生成，不依赖模型自填 key。
- **事件**：EventEnvelope 至少一次投递 + Inbox 去重，同对象按版本处理；外部世界不承诺恰好一次，无法幂等的远端副作用走持久意图 + 结果未知对账。
- **错误契约**：FORBIDDEN_SCOPE / SOURCE_STALE / VERSION_CONFLICT / MISSING_REQUIRED_EVIDENCE / CONFIRMATION_REQUIRED / NAMED_DECISION_REQUIRED / QUALIFICATION_REQUIRED / DUPLICATE_INTENT_CONFLICT / EXTERNAL_OUTCOME_UNKNOWN / UNDO_BLOCKED_BY_DEPENDENCY / CANCELLED_RUN 等。

### 5.4 安全与运维要点

应用层角色+对象关系+操作属性检查，数据库 RLS 作纵深防御（PG 特权角色边界须实测）；应用连接非表所有者，迁移凭据独立，事务级绑定 tenant/actor；AI Worker 只经受控命令服务，对业务表零直接写权限。原件版本化、安全扫描、隔离解析（不执行嵌入脚本）、混合检索带 ACL 与撤回状态。备份覆盖业务 DB、对象版本、Workflow 持久库、密钥与映射；恢复演练核对配置→测试→决定→交接链且事件重放不重复外发。可观测性贯穿 request_id/work_request_id/run_id/command_id/event_id/delivery_id；自动化风暴、误建单、取消后动作、外发未知、资格降级是重点监控项。

## 6. 交付切片与验收

### 6.1 纵向切片（v1.0 编号 G0–G5；v1.1 改称 S0–S5，顺序为 S0 整体重构 → S1 品类研究到立项 + 小Pai 内核 → S2–S5）

| 阶段 | 交付结果 |
|---|---|
| G0 可信执行骨架 | G0.1 来源事实与可信命令；G0.2 可恢复委派与 AI 工具代理；G0.3 持久工作流与证据处理；G0.4 T1/T2 与恢复底座 |
| G1 产品起点 | G1.1 研究到结构化定义；G1.2 平台匹配与派生；G1.3 真项目与首版双线计划；G1.4 投入和定义发布 |
| G2 实物与专业交接 | G2.1 双配置与实物活动；G2.2 试模与验证策划；G2.3 实际交样与品质接收；G2.4 测试与结果返回 |
| G3 问题与迭代 | G3.1 失败归并与品质整改；G3.2 双线变更与实施；G3.3 新配置与复验 |
| G4 制造交付 | G4.1 供应齐套与成本；G4.2 制造基线与试产；G4.3 固定放行包与分别决定；G4.4 外部接收与生效 |
| G5 持续运营 | G5.1 主动 Loops 与协作；G5.2 组合与资源；G5.3 反馈记忆与规则；G5.4 正式联合验收与运营 |

完整依赖映射见[执行方案 §3](2026-10-02-pdos-next-execution-plan.md)。施工节奏按 [§3.1 收口规则](2026-10-02-pdos-next-execution-plan.md#execution-acceleration)：一个主业务结果连续做到领域保存与异常处理，最小受影响验证即时做，完整构建/整链/迁移往返集中到业务候选；正式出口仍按原人工门禁。

### 6.2 验收体系

- **66 项关键操作 / 65 类写入事件**：每操作标注 T0/T1/T2/READ 与 AI 执行范围（目标架构附录 A）。
- **48 个验收场景 AT-01～48**：覆盖业务负例（AT-06 未知规格、AT-17 高分不抵消硬阻塞、AT-23 同源失败幂等建单）、AI 边界（AT-31～36 T0/T1/T2 与注入）、可靠性（AT-37～47 权限撤销、幂等冲突、取消并发、恢复重放）与诚实性（AT-48 合成验证非真实资格）。
- **六条黄金业务路径 A–F**：A 自主新品/ODM 定义；B OEM 与制造可行性；C 试模到品质返回；D 失败到变更和复验；E 试产到放行和外部移交；F 爬坡反馈与复用。每条须真实贯通入口、操作、领域结果、异常、权限、回执与接续。
- **验收原则**：页面截图、编译通过、模型回答流畅或单一 API 成功都不构成闭环完成；模拟模型可验证编排，真实模型能力与权限负向单独评价。

## 7. 实现现状快照（截至 2026-10-05 唯一清单队列）

> 本节仅为导读快照，**活动状态以[唯一清单](../../tasks/ai-native-integrated-todo.md#pdos-next-queue)为准**；最新登记候选为第二十八波。

### 7.1 工程结构

`pdos-next/`：`server/`（独立 FastAPI 服务，`pdos_next` 包含 35 个 domain 子包及 model_gateway、evidence_processing、object_storage、workflows、dispatch、engines 等运行模块，独立 Alembic 迁移链当前测试头 next_0032）、`web/`（Next.js 同源应用 + BFF）、`contracts/`（合订本重建的 operations/events/acceptance/openapi/payloads JSON）、`tools/`（波次构建/检查/环境工具与 local_environment/workflow_environment）、`containers/evidence-parser`（隔离解析容器）、`staging/`。本地预览 API 8898 / Web 3028；测试仅用显式 `TEST_DATABASE_URL` 指向已核对独立 `pdos_test`，57432 存续联验库禁止 repo 测试。

### 7.2 各切片可用能力与必要缺口

| 切片 | 已可使用 | 必要缺口 |
|---|---|---|
| G0 可信执行 | 共同命令/回执、原件保护、不可变版本、RLS 与 Agent 零直接业务写；已支撑开测与原值返回 | 真实模型/golden-case/出站资格、生产扫描/OCR/S3、生产 Temporal PG、完整失效传播与恢复出口 |
| G1 产品起点 | 人工定义、同 Product 派生、固定项目定义、首版双线计划 | 无项目研究/OEM/机会实验、跨 Product 平台采用、计划续版/容量/承诺/实绩、具名投入与定义发布 |
| G2 实物交接 | 本地合成交样/部分接收、具名承诺、实际开测、原值导入、专业复核/处置；新开测 v2 完整凭证与原请求恢复经实际事务验证 | 多 Run/分段/纠正、资源释放、真实工厂与测试资格 |
| G3 问题迭代 | 失败→Issue/CAPA、根因/本人完成、固定回链、候选/规则与部分观察；正式变更接共同运行源，制造图/依赖水位与覆盖 owner 接线落地 | 完整覆盖 publication 正例、双线批准/实施/生效、完整新 Run 复验、独立 T2 Review/有效性 |
| G4 制造交付 | 固定供应/齐套/Decimal 成本、受限内部开工；WI/CP/制造基线保存/续版/Current/历史/UNKNOWN 恢复与原子回滚；固定工序资源只读入口贯通 owner/API/BFF/UI | 工装具名验收 `npi.fixture.accept` 施工中；设备验收/校准、人员资格、released 基线、试产口径、分别放行、外部接收/生效 |
| G5 持续运营 | 方案及验收已定义，尚未开工 | Loops/协作、组合资源、反馈/记忆/规则、六条黄金路径与正式运营出口 |

### 7.3 在制闭环与下一步

当前主交付为「受控变更后的制造准备与复验可办理」：①旧单依赖兼容 + 新 Start v2 保存/回读/UNKNOWN 恢复（已验证），按实测缩窄 Current 重复深读；②WI/CP 首存/续版→固定 Current 制造基线→历史/恢复 API 已过，补 GUI 整链；③八 facet 与政策选择→双线独立具名批准→实施回链→新 Run 复验→完整观察与独立 Review。下一单项建设为 `npi.fixture.accept` 独立不可变具名 Decision/Current。当前阻塞不含工程内部缺陷：真实办理依赖可信职责/资格、完整固定 Definition/Process/Source 及有效账号/Grant；Mac 解锁后补 GUI 亮暗/多尺寸。

## 8. 权威文档地图

| 文档 | 作用域 |
|---|---|
| [完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)（v1.0 已被取代） | pdos-next 目标权威：12 分册、领域/状态契约、体验/技术/集成、66 操作、65 事件、AT-01～48 |
| [pdos-next 执行方案](2026-10-02-pdos-next-execution-plan.md) | G0–G5 切片、依赖、验收映射与 §3.1 收口规则；§4 首轮窄路径、§8–13 各波施工前合同 |
| [复用与并行方案](2026-10-02-pdos-next-reuse-and-parallel-plan.md) | 新旧工程复用矩阵：可复制资产/可抽取算法 vs 不继承的表/状态机/资格 |
| wave14–18 冻结实施合同 | 结果返回、品质闭环、品质整改后续、CAPA 有效性首段、专业事实（具名复核） |
| [Agent 运行架构收口合同](2026-10-07-agent-runtime-convergence.md) | LangGraph + Temporal 边界，已实施，两线共用 |
| [设计确认稿](2026-10-08-pdos-next-design-confirmation.md) / [执行计划](2026-10-07-xiaopai-product-execution-plan.md) | v1.1 的决策记录（K1–K9、C1–C14）与 pdos-next 里程碑；[单 Agent 方案](2026-10-07-xiaopai-single-agent-runtime-plan.md) 已被取代，仅作决策记录 |
| [DC-11 T0/T1/T2 政策](2026-09-20-ai-direct-write-tier-policy.md) | AI 写入分级的原批准政策（两线共同遵循） |
| [完整设计合同 v1.1](2026-09-10-pdos-complete-design-contract.md) | 原工程领域基线，非 pdos-next 约束（术语与领域背景可参照） |
| [对象合同 `docs/contracts/pdos-v1/`](../../contracts/pdos-v1/) 与 [运行政策 `docs/contracts/pdos-runtime-v1/`](../../contracts/pdos-runtime-v1/) | 原工程冻结合同与 DC 冻结登记台账 |
| [唯一清单 pdos-next 队列](../../tasks/ai-native-integrated-todo.md#pdos-next-queue) | 活动状态唯一来源；wave2–25 详情在只读留存 |

注：[立项前改造](2026-10-05-preproject-redesign.md)（品类/立项提案/AI 先起草/小Pai 入口）原在原工程实施；v1.1 已把这些决定并入 pdos-next 设计（§02.3a、§03.14、§05），原工程实现只作复用参考。
