# PDOS vNext 项目控制闭环执行清单（已被替代，仅存档）

> **2026-08-25：本清单已被 `tasks/vnext-unified-todo.md` 替代**（PO 授权执行）；保留为历史输入，不再维护。

> 本文件是 `2026-08-24-vnext-control-loop-upgrade-plan-draft.md` 的候选任务清单。
>
> **非 canonical、全部未开始**；不得据此修改 `tasks/todo.md`、现有执行计划 checkbox、生产配置或部署状态。

## Gate V0：产品决策与执行授权

- [ ] V0-1：PO 逐项拍板 D1-D24，记录选择、理由和不选方案代价
  - 验收：24 项均有明确 Owner/日期/结论；无“后面再说”却提前实现的项目
  - 验证：产品、技术、安全、数据 Owner 联合走查
  - 依赖：当前讨论
- [ ] V0-2：处置 Sprint 5 Exit 与 vNext 的关系
  - 验收：明确先补验、接受延期例外或仅本地并行三者之一；生产 `delivery` 状态不被隐式改变
  - 验证：canonical、AGENTS、`tasks/todo.md` 指针一致
  - 依赖：V0-1
- [ ] V0-3：冻结 vNext 对象/SoR/权限/事件/迁移兼容合同
  - 验收：新增对象、状态机、服务端绑定、错误码和降级边界完整；本地 `0033`/生产 `0032` 事实保留，vNext 从 `0034` 起
  - 验证：架构/安全/质量/ERP Owner 审查
  - 依赖：V0-1
- [ ] V0-4：冻结试点和基准指标
  - 验收：至少 2 个存在真实依赖或共享资源的项目；指定业务、数据、质量和 ERP Owner
  - 验证：能取得匿名化会议、Issue、排期、物料样本和当前基线
  - 依赖：V0-2、V0-3

### Checkpoint V0

- [ ] PO 明确回复“批准 vNext 合同与执行顺序”
- [ ] canonical 范围变更按项目纪律完成版本化，不覆盖历史计划
- [ ] 未发生代码、生产或外部系统变更

## Phase V1：我的工作、问题闭环与提醒

- [ ] V1-1：跨项目 My Work 查询合同与服务端聚合
  - 验收：按当前登录用户聚合 Task/Issue/Risk/CAPA/Gate/Finding；无跨租户/越权/N+1
  - 验证：角色矩阵 API 测试、分页/排序/空态与性能基线
  - 依赖：V0
- [ ] V1-2：My Work 前端与角色自适应落地页
  - 验收：工程/质量用户登录后零点击看到本人待办；PM 可切换个人/组合视图
  - 验证：桌面/移动/键盘/外部角色真实浏览器
  - 依赖：V1-1
- [ ] V1-3：Issue 责任与关闭合同
  - 验收：Open 可暂存未分派问题；进入 Analysis 前必有唯一 Owner、目标日期、关闭条件和 Verifier；高/严重级 Owner≠Verifier；assign/execute/verify 权限分离
  - 验证：迁移、数据库约束、API 正反例和历史数据兼容
  - 依赖：V0
- [ ] V1-4：Issue 验证、退回、重开和关闭证据纵向切片
  - 验收：Owner 只能提交验证；Verifier 可通过/退回；关闭证据不可静默覆盖；重开保留原关闭记录
  - 验证：状态机、并发、审计、RBAC 和真实浏览器闭环
  - 依赖：V1-3
- [ ] V1-5：Task 的 meeting action kind/source relation
  - 验收：会议行动复用 Task 的单一 accountable owner、due、status 和 reminder；可追到 Meeting/Issue/Decision 且不产生第二套待办真值
  - 验证：关联范围、重复转正式对象幂等、事件/审计
  - 依赖：V1-3
- [ ] V1-6：Reminder Policy、扫描与站内通知
  - 验收：接单、T-3/T-1/到期/逾期+1/+3、停滞、待验证和升级提醒；重跑不重复发送；有静默/汇总策略
  - 验证：时钟测试、幂等、租户/RBAC、失败重试和站内真实链路
  - 依赖：V1-1、V1-4、V1-5
- [ ] V1-7：钉钉 reminder delivery adapter（受 S5-1 人工 Gate 约束）
  - 验收：`delivery=false` 时明确停在站内；经授权后才进入真实 outbox；链接由服务端构建
  - 验证：fake provider、outbox 重放/对账；真实外发另行授权
  - 依赖：V1-6、S5-1 人工 Gate
- [ ] V1-8：现有 Agent 事件覆盖、运行可见性与现场 Finding
  - 验收：高价值日常事件有明确 route/no-route 决策；操作后可见 debouncing/queued/running；项目现场可见相关 Finding
  - 验证：catalog/routes 一致性、golden/no-action、预算与浏览器
  - 依赖：V0
- [ ] V1-9：修复 Finding/Agent 前后端契约漂移
  - 验收：后端允许的 Agent/Finding 类型均可被前端解析、筛选和展示；未知类型 fail-close 但不拖垮整页
  - 验证：合同快照、API parser、Supplier/Executive 真实 Finding 浏览器回归
  - 依赖：V0
- [ ] V1-10：Typed Proposal 与白名单 Apply Adapter 基础
  - 验收：每类 proposal 有严格 payload、目标对象和真值复核；不得把会议/物料/排期建议一律压成 Risk
  - 验证：Accept 零业务写、独立 Apply、重放幂等、越权/陈旧真值 fail-close
  - 依赖：V1-9
- [ ] V1-11：六 Agent `capability_key` 运行合同
  - 验收：route 解析为 AgentKey+CapabilityKey；每个 capability 有独立版本化 prompt/tool/projection/quality control；无 Agent 间自由消息
  - 验证：前缀冻结、路由矩阵、预算/熔断、能力级指标和未知 capability fail-close
  - 依赖：V1-8、V1-9

### Checkpoint V1

- [ ] 一条 Issue 完成“发现→负责人→行动→提交验证→独立确认→关闭/退回→提醒”
- [ ] 所有新增 Agent 输出仍走 pending_review→accepted/rejected→applied
- [ ] 完整门禁和真实浏览器验收通过，等待人工 Phase Exit

## Phase V2：会议与决策闭环

- [ ] V2-1：Meeting/Agenda/Transcript/Link 数据与权限合同
  - 验收：会议类型、项目范围、参会人、议题、来源和保留策略明确；私聊/未授权会议不可接入
  - 验证：迁移、tenant/project/RBAC、审计与删除/归档政策
  - 依赖：V1
- [ ] V2-2：会议创建、议程、参会人与复查 API/UI
  - 验收：支持项目周会、物料会、专项会、TR、DCP/IPMT、试制复盘模板
  - 验证：API、BFF、桌面/移动浏览器和外部角色边界
  - 依赖：V2-1
- [ ] V2-3：会前例外装配
  - 验收：自动聚合逾期 Action、关键 Issue、物料短缺、Forecast 变化和 Gate 缺项；每项可跳源
  - 验证：确定性聚合测试、截断/分页、无数据与失败态
  - 依赖：V2-2、V1-6
- [ ] V2-4：Knowledge Lite `meeting_minutes` capability 与 golden cases
  - 验收：从转写片段提案 Minutes 与 Decision/Action/Issue/Risk/Change 候选；每字段有引用或明确无据；零直接业务写
  - 验证：中文制造词表、说话人不确定、提示注入、跨项目、敏感信息和预算测试
  - 依赖：V2-1、V1-11
- [ ] V2-5：会议提案人审 Apply 与会后闭环
  - 验收：首次 Apply 只固化 Minutes；每个候选项再单独确认 Owner/日期/关闭标准并 Apply 为正式对象；Decision 与 Action 可回到议题/片段；下次会议自动复查未关闭项
  - 验证：Accept 不写业务、Minutes Apply 与逐项 Apply 分离、重放幂等、Event/Audit、真实会议演练
  - 依赖：V2-3、V2-4

### Checkpoint V2

- [ ] 真实试点会议闭环通过，且无引用结论不能应用
- [ ] 会议时长/准备时间/行动项关闭率开始采集
- [ ] 人工确认 Phase Exit

## Phase V3：项目时间与延期传播

- [ ] V3-1：四类时间与 schedule node/dependency 合同
  - 验收：Baseline/Forecast/Commitment/Actual 语义、FS/SS/FF/SF、lag、日历、跨项目边界冻结；首发能力明确限制为 FS+lag+项目日历+Task/Gate
  - 验证：产品/PMO/工程 Owner 示例走查与兼容策略
  - 依赖：V0
- [ ] V3-2：Baseline 版本与 Forecast Snapshot
  - 验收：基线不可静默覆盖；Forecast 可派生；任何快照可重算/解释/审计
  - 验证：迁移、并发、版本、回放和有损 downgrade guard
  - 依赖：V3-1
- [ ] V3-3：确定性依赖传播和关键路径引擎
  - 验收：只传播到可达后继；float、日历、lag 和 cycle fail-close 正确；错误路径零 LLM
  - 验证：属性/边界测试、性能基线、固定案例手算对账
  - 依赖：V3-2
- [ ] V3-4：跨项目 Forecast 影响 API 与计划视图
  - 验收：可查看基线/预测差、传播路径、受影响 Gate/Build/Test/客户节点；无隐式基线变化
  - 验证：API、UI、320/1440、复杂图分页和真实试点案例
  - 依赖：V3-3
- [ ] V3-5：Schedule Change Proposal 与人审重基线
  - 验收：多个恢复场景可比较；批准后生成新 Baseline version；Commitment 另行确认
  - 验证：权限、四眼策略、Event/Audit、重放和回滚依据
  - 依赖：V3-4
- [ ] V3-6：Project Agent 的延期解释与方案建议
  - 验收：Agent 引用确定性引擎结果，不自行算日期；解释原因、影响和假设；无据 no_action
  - 验证：golden cases、前缀冻结、受限工具和直接写零权限
  - 依赖：V3-3、V1-8

### Checkpoint V3

- [ ] “A 延 6 天、B 延 3 天、C 因 float/无依赖不变”的固定案例通过
- [ ] Forecast 自动变化、Baseline/Commitment 不变
- [ ] 人工确认 Phase Exit

## Phase V4：项目物料与齐套联动

- [ ] V4-0：补齐现有 BOM item、Build/Sample/Test 的 BFF/UI 操作面
  - 验收：内部角色可选择 Prototype BOM、维护 Build 并查看 Sample/Test；不扩张 ERP SoR
  - 验证：现有 NPI API 合同、BFF allowlist、桌面/移动真实浏览器
  - 依赖：V0
- [ ] V4-1：Project Material/ERP snapshot SoR 合同
  - 验收：BOM、项目需求、ERP事实、供给引用、数据时点、替代料和质量冻结边界明确
  - 验证：ERP/采购/工程/质量 Owner 联合走查
  - 依赖：V3-1
- [ ] V4-2：按 Build/阶段生成项目物料需求
  - 验收：Build 冻结 Prototype BOM version/snapshot/digest；需求关联 BOM item、数量、need-by schedule node、批次和版本；ECN 只产生 delta/new revision，不改历史
  - 验证：迁移、BOM/Build 兼容、重复生成幂等
  - 依赖：V4-0、V4-1
- [ ] V4-3：供给引用、as-of snapshot 与齐套计算
  - 验收：首版 ingress（只读 API/文件导入/两者）已拍板；captured_at/source_version/freshness SLA 完整；总齐套/关键齐套、短缺、长周期和 stale 状态确定性计算；不冒充实时库存
  - 验证：ERP fixture 对账、过期/缺失/部分到货/冻结测试
  - 依赖：V4-2
- [ ] V4-4：物料工作区与影响追踪
  - 验收：短缺可追到 Task/Build/Test/Gate/Project；同一物料/供应商的跨项目暴露可见
  - 验证：API/UI/权限/性能/真实浏览器
  - 依赖：V4-3、V3-4
- [ ] V4-5：物料短缺→Issue/Forecast/Meeting/Gate 闭环
  - 验收：短缺先成为确定性 Material Exception；转 Issue 走 typed proposal+人 Apply（或另行批准的 pending-triage 规则）；Issue 有内部 Owner；进入会议议程；必要时按 versioned policy 阻断 Build/Gate
  - 验证：端到端事件链、提醒、重放、ERP 零写
  - 依赖：V4-4、V2、V3
- [ ] V4-6：Supplier Agent 与变更影响增强
  - 验收：建议催交/替代/拆借/调整批次及假设；ECR/ECN 影响关联供给；仍只建 Finding
  - 验证：golden、跨租户、敏感联系人零泄漏、受限数据库角色
  - 依赖：V4-3、V1-8

### Checkpoint V4

- [ ] 一批真实 Build 完成 BOM→物料需求→ERP snapshot→齐套→短缺→排期/问题→关闭
- [ ] ERP 抽查一致且来源时间可见
- [ ] 人工确认 Phase Exit

## Phase V5：AI 产品经理工作台与市场到 IPD

- [ ] V5-0：产品管理域、D20-D24与SoR合同
  - 验收：研究、竞品、市场细分/JTBD、机会树、实验、产品策略、产品定义、产品矩阵的对象/Owner/状态/发布权限冻结；明确排除CRM、Deal/Account/Activity、销售漏斗、赢输单、订单/收入分析；PDOS与研究来源/ERP/PLM边界明确
  - 验证：产品、市场研究、工程、质量/服务、财务、IPMT、ERP/PLM Owner和安全联合走查
  - 依赖：V0
- [ ] V5-1：Research Source、Collection Job与Evidence Snapshot底座
  - 验收：来源许可、用途、频率、保留、抓取时间、source version、digest、新鲜度和证据冲突可记录；快照不可静默覆盖
  - 验证：迁移、租户/RBAC、重复内容、版本变化、来源撤回、过期和跨租户测试
  - 依赖：V5-0
- [ ] V5-2：受控采集调度器与首批连接器
  - 验收：只访问租户批准的allowlist来源；支持计划任务、限流、退避、失败隔离、去重和增量更新；Agent无自由HTTP/浏览器
  - 验证：fake source、内容变化、robots/许可策略、恶意页面、超大内容、编码和网络失败；真实外部采集另行授权
  - 依赖：V5-1
- [ ] V5-3：竞品与竞品产品情报纵向切片
  - 验收：市场比较边界、直接/间接/新兴竞品、Competitor/Product、规格、功能、目标细分/JTBD、公开价格带、区域、认证、商业模式、生命周期和版本变化可维护；矩阵、优劣势、威胁与差异化结论可跳来源
  - 验证：边界错误、冲突来源、未知值、版本diff、重复产品、过期证据和桌面/移动工作台
  - 依赖：V5-2
- [ ] V5-4：Market Space、市场细分与JTBD纵向切片
  - 验收：品类边界/地域/周期/替代方案、Segment/JTBD/Use Case/Persona Role/Region/Price Band/Regulation，以及趋势、痛点、购买标准和未满足程度可建模；TAM/SAM/SOM保存公式、参数、范围和来源
  - 验证：可复算指标、问题型机会而非功能型机会、事实/估计/假设区分、反证、数据不足状态和真实品类样本
  - 依赖：V5-1
- [ ] V5-5：Opportunity Solution Tree与验证实验闭环
  - 验收：每棵树只有一个可衡量Desired Outcome；Opportunity绑定证据和版本化`Importance × (1 - Satisfaction)`评分；重点机会收敛前至少3个Solution Candidate；Value/Usability/Viability/Feasibility假设、实验阈值、Owner、日期和结果完整
  - 验证：树关系/循环、评分复算、无证据机会、少于3方案告警、实验通过/证伪/中止、失败知识保留和浏览器
  - 依赖：V5-3、V5-4
- [ ] V5-6：Product Strategy Canvas、Concept与Definition
  - 验收：Canvas包含愿景、细分/JTBD、相对成本、价值主张、明确取舍、NSM/OMTM、采用/增长路径、能力/合作、防御性；Definition包含目标客户/场景、差异化、目标规格/体验、目标成本/价格带/单位经济假设、法规、服务、上市窗口和成功指标；每项标记evidence/assumption/decision并由产品经理Review后版本化发布
  - 验证：九区完整性、机会/实验/证据反链、策略冲突、草稿/评审/发布/替代状态、四眼策略、不可变发布版本和浏览器
  - 依赖：V5-5
- [ ] V5-7：产品家族、产品矩阵与路线图
  - 验收：Product Line→Family→Platform→Series→Model/Variant层级和市场/场景/价格带/区域/渠道/规格/生命周期矩阵；能识别空白、重叠、蚕食和平台复用
  - 验证：层级循环、重复定位、矩阵稀疏/冲突、版本和场景比较；不复制ERP/PLM正式主数据
  - 依赖：V5-6
- [ ] V5-8：AI typed scope v3安全底座
  - 验收：run/context/Finding支持服务端绑定的tenant/market_space/product_line/opportunity/product_definition/portfolio/project scope；模型自报scope无效；禁止虚拟Project
  - 验证：迁移、受限投影、跨scope/跨租户、上下文泄漏、PII和运行生命周期测试
  - 依赖：V5-1、V1-10
- [ ] V5-9：Product Management Intelligence Agent（取决于D21）
  - 验收：research_planning/competitor_analysis/market_analysis/opportunity_mapping/experiment_design/product_strategy/product_definition/product_matrix能力各自有prompt/tool/projection/typed Finding；只读已采集证据，不自动发布或立项
  - 验证：真实模型golden、no-action、引用、来源冲突、提示注入、陈旧证据、数值与指标层一致性、成本和延迟
  - 依赖：V5-3、V5-4、V5-5、V5-6、V5-7、V5-8、V1-11
- [ ] V5-10：Product Definition→Requirement→DCP/TR→IPD兼容链
  - 验收：批准的Definition只生成候选Requirement；Opportunity↔Requirement、Case↔Requirement保留primary兼容；DCP商业决策与TR技术评审分离；批准后才实例化IPD v2项目
  - 验证：旧链无损、重复请求幂等、事务回滚、Gate兼容、Agent零自动立项/批准
  - 依赖：V5-6、V5-7、V2、V3、V4
- [ ] V5-11：实验、质量、服务和生命周期反馈回链
  - 验收：用户研究、验证实验、试点、投诉、质量、服务和退市结果回到原Opportunity、Strategy、Definition、矩阵位置和关键假设；verified Memory才进入Agent context
  - 验证：端到端引用、权限、数据新鲜度、指标复算和检索过滤
  - 依赖：V5-10、现有Quality/Memory

### Checkpoint V5

- [ ] 一个真实品类完成“自动采集→竞品/市场分析→细分/JTBD→机会树→验证实验→产品策略→产品定义→产品矩阵→候选需求→DCP/IPD→产品结果反馈”闭环
- [ ] 每个结论可跳证据，量化指标可复算，陈旧/冲突/未知不伪装成事实
- [ ] V5不接CRM、不包含销售分析；Agent无自由联网、自动发布产品策略/定义、调整产品矩阵、立项、Gate或业务表直接写权限
- [ ] 人工确认 Phase Exit

## Phase V6：共享资源组合排程与试点出口

- [ ] V6-1：Resource Pool/Calendar/Capacity/Reservation 合同与当前 Resource 兼容
  - 验收：人员、技能组、设备、模具、实验室、试制线的身份、容量、日历和租户边界冻结；现有 project-scoped Resource 可无损读取
  - 验证：兼容迁移、资源 Owner 走查和跨租户负例
  - 依赖：V3、V4
- [ ] V6-2：人员/技能组/设备/模具/实验室/试制线预约纵向切片
  - 验收：预约有项目、schedule node、容量、时段、Owner 和状态；重叠容量确定性校验
  - 验证：API/UI、并发预约、日历边界和真实资源样本
  - 依赖：V6-1
- [ ] V6-3：资源受限排程与项目优先级政策
  - 验收：只使用版本化优先级政策；相同输入输出稳定；无政策时 fail-close 而非模型猜测
  - 验证：固定手算案例、并发/性能、错误路径零 LLM
  - 依赖：V6-2、V3-3
- [ ] V6-4：组合情景比较与人工应用
  - 验收：支持加班、替代设备、外协、降级和顺延低优先项目；情景不改真值，人工 Apply 才生成变更提案
  - 验证：场景摘要哈希、权限、过期真值和重放幂等
  - 依赖：V6-3、V1-10
- [ ] V6-5：Executive Agent 组合例外简报和现场入口
  - 验收：只解释确定性组合结果，不排名个人；每项有来源和假设；业务现场与决策中心可见
  - 验证：capability golden、隐私/提示注入、前端回归和成本指标
  - 依赖：V6-3、V1-11
- [ ] V6-6：性能、通知降噪、预测校准、安全红队和迁移演练
  - 验收：项目组合规模基线达标；通知重复/噪音受控；跨租户/越权/过期引用/未审外发零穿透
  - 验证：负载、红队、迁移往返、真实受限账号和灾难恢复演练
  - 依赖：V6-4、V6-5
- [ ] V6-7：试点业务指标验收、运行手册、回滚方案和 vNext Exit 报告
  - 验收：指标与基线对比完整；未达阈值项有明确 NO-GO/延期例外；报告不把本地候选冒充生产事实
  - 验证：业务/Data/Quality/Security Owner 联合签字和人工 Exit Gate
  - 依赖：V6-6

### Checkpoint V6 / vNext Exit

- [ ] 跨项目依赖与共享资源案例均通过确定性对账
- [ ] 里程碑兑现率、预警提前量、Issue 关闭、会议、齐套和 Agent 指标达到 PO 阈值
- [ ] `pdos_agent` 新增业务表直接写为 0，越权/注入红队 0 穿透
- [ ] 完整 `make check`、真实 HTTP/浏览器、迁移、观测和回滚门禁通过
- [ ] 人工确认 vNext Exit 后，才更新 canonical 与发布计划
