# R1 · 硬件 PLM / NPI / 研发管理产品 2025–2026 AI 能力与关键非 AI 能力调研

调研日期：2026-10-22｜范围：10 个指定产品，另加 2 个相邻工具（CoLab、Leo AI），以及一条国产 PLM 观察｜方法：WebSearch/WebFetch，优先读官方文档、发布说明和厂商新闻稿；部分官网（ptc.com、businesswire、autodesk 博客等）返回 403，改读同一新闻稿的转载或行业媒体报道。只读分析，未改动仓库。

## 0. 结论先行

1. **2026 年行业已从"问答助手"转向"受监督的任务型 Agent"，但真正 GA、有官方文档的仍集中在少数场景**：文件摘要与版本对比（Arena、Windchill）、BOM 检查与清洗（OpenBOM BOM Review、Aras BOM Assistant）、变更单预审（Oracle Change Order Auditor）、替代料与变更起草（Oracle Component Replacement、Teamcenter 2606 BOM Agent）、质量文档起草（Teamcenter Quality Copilot）、需求质量检查与测试用例生成（Codebeamer AI 1.0）。Autodesk 的"Agentic PLM"、Dassault 的"会做决定"的虚拟伙伴、OpenBOM 的成本权衡分析，目前还是**预览或路线图**，宣传多于证据。
2. **共性形态是"AI 起草、人批准、留痕"**：各家都强调人在环。但多数厂商并没有像 PDOS 这样，在命令层把"建议、确认、具名决定"分开。PDOS 的 T0/T1/T2（DC-11）、显式依赖与 AI 线索分栏（v1.1 §04.13）、计划配置与实际配置分开（§02.6），恰好对应评论界提出的三个疑问：建议和决定混在一起；助手读的是哪个配置；非正式讨论转成正式变更时证据会丢。**这是 PDOS 应保持的差异化，不需要向竞品靠拢。**
3. **PDOS 的主要缺口在"零件与供应链主数据层"，不在 Agent 内核**。竞品普遍提供而 PDOS 当前设计或代码里没有看到的有：零件 where-used 反查、AML/AVL（制造商料号与首选/替代状态）、近重复料识别、零件和材料级合规（RoHS/REACH/PFAS 声明、证书有效期）、供应商询价与比价、BOM 与规格书的导入清洗、客户文件修订对比、替代料/EOL 处置闭环、设计评审辅助（图纸与 DFM 检查）。对一家做充气泵、同时做自主品牌和 OEM/ODM 的中小企业来说，这些恰恰决定了报价速度、变更周期和出口合规风险。
4. **集成与上手是中小企业的硬门槛**：Arena Connect 号称 200+ 预置连接器；OpenBOM 有自助试用、只读用户免费、每席 30–90 美元/月；Propel、Teamcenter X、MCP 都在把 PLM 数据开放给外部 AI 客户端。PDOS 的连接器框架设计完整（§07.9、§08），但还没有面向金蝶/用友 ERP、钉钉、GoodJob CRM 的预置连接器，也不对外提供 MCP 服务端。
5. **AI 授权与部署方式差异很大**：Windchill 和 OpenBOM 的 AI 要单独买席位或许可；Teamcenter 可选 Azure OpenAI、Bedrock 上的 Claude 或本地 Llama；Arena 用 Bedrock；Dassault 只上自家主权云 OUTSCALE。境外 SaaS 在中国大陆的数据驻留没有找到官方说明，这对中国企业是现实障碍；PDOS 自建部署，模型可换（P26），这一点是优势。

## 1. 证据等级与口径

| 标记 | 含义 |
|---|---|
| A | 官方产品文档、发布说明、帮助中心（如 docs.oracle.com、support.ptc.com、blogs.sw.siemens.com 的版本说明） |
| B | 厂商新闻稿或官方博客（含转载） |
| C | 行业媒体与分析（Digital Engineering 24/7、CIMdata、engineering.com、Verdantix 等） |
| D | 竞品博客、聚合站、经销商页（Leo AI、BeyondPLM/OpenBOM CEO、Capterra/GetApp/SoftwareSuggest 等），只作线索 |

成熟度标记：**GA**（已发布、可用）、**预览/Beta**、**路线图**（只宣布方向）、**演示**（展会演示）。厂商给出的效果数字一律记为"厂商宣称"。

## 2. 逐产品卡片

### 2.1 Arena PLM & QMS（PTC）

- **定位**：云端 PLM+QMS，服务电子和医疗等中型硬件企业，以 BOM、变更、质量、供应商协同为核心。
- **AI 能力**
  - Arena AI Assistant（2025-09，GA，B/C）：对话式助手，可在 Arena 界面中配置，按步骤引导 BOM 评审、变更单、CAPA 和供应链风险监控；后续版本补充了更多帮助主题和完整多语言。公开材料只写到"引导"，没有说它能代为执行。
  - Arena AI Engine（2025-12，GA，C）：基于 Amazon Bedrock，提供 AI File Summary（长报告摘要）和 AI File Comparison（规格、设计、图纸等文件的差异识别），用于变更管理与培训。
  - 2026 春季版：AI Comparison 与 AI Workspace Data Search，用自然语言查询产品数据（B，PTC 页面）。
  - 2026.2（2026-08-04，B/C）：AI Item Redline 和 AI File Insights，用于汇总产品变更、比较修订、跨文档自然语言查找；同期发布 Automated BOM Compliance 与 Component Browser（元件合规与生命周期可见）。
  - Supply Chain Intelligence（SCI）：AI 驱动的元件监控与风险提示，电子元件法规合规按周检查（C）。
- **关键非 AI 能力**：BOM/AML、ECO/ECN 工作流、QMS（CAPA、NCR、投诉、培训）、供应商协同；Arena Connect（2026.2）是内嵌 iPaaS，提供可视化流程构建、200+ 预置连接器和模板，由 webhook、事件引擎和自定义动作触发，有执行监控与错误看板；Onshape 与 Arena 双向同步 BOM。第三方分析提醒：Arena Connect 更多是打包和治理层面的调整，要按版本档位、流程上限、连接器权限和审计要求逐项评估（D）。
- **定价与上手**：不公开报价。聚合站估算约 89–99 美元/用户/月，Capterra 标注起价约 2.5 万美元/年（D，口径不一）。
- **对充气泵企业的意义**：AI File Comparison 和 Redline 正对 OEM 客户规格书、图纸频繁改版的场景：自动标出 v1 与 v2 的差异，再转成变更请求，能缩短客户变更的响应时间。Automated BOM Compliance 与 SCI 适用于含 PCB、电机、锂电池的数显或无线款。
- **对 PDOS 的启示**：PDOS 有 `rfq_extraction`（逐条抽取）和 `derivative_diff`（型号派生差异），但没有"同一份客户原件两个修订之间的差异 → 需求差异 → ChangeRequest 候选"这一步，详见 §5 缺口 G4。

### 2.2 Propel（基于 Salesforce）

- **定位**：PLM+QMS+PIM（"产品价值管理"），构建在 Salesforce 平台上，打通产品、质量、市场和服务数据。
- **AI 能力**
  - Propel One（2025-03 发布；2025-10 首批客户在真实数据上使用，B）：构建在 Salesforce Agentforce 上的按角色划分的 Agent 套件，覆盖工程、质量、市场、产品管理、供应链、销售、服务。官方 BOM 页称 Agent 会读取 BOM、where-used、AML、在役资产和库存数据，找出受影响的物料、计算成本、标出受影响客户，并强调全程由人掌控（B）。早期用例包括按实时质量与供应数据提示替换元件（B，原文截断）。具体有哪些 Agent、能执行哪些动作，公开文档很少。
  - 生产级 MCP（2026-06，B/C）：Propel 自称首家提供生产级 MCP 的 PLM，Claude、ChatGPT、Copilot 等外部 AI 客户端可以在现有权限与治理规则下查询产品记录、执行"简单操作"；也可以在 Propel 内构建连接 NetSuite、SAP 等外部 MCP 服务器的 Agent，把库存、供应商风险、流程记录引入产品流程。写操作和审批边界没有公开。
  - DesignHub：多 CAD 集成，是 FY26（截至 2026-01）订单增长的主要来源之一（B）。
- **关键非 AI 能力**：BOM 与 where-used 反查，AML/AVL 内嵌 BOM（首选/替代状态、历史成本、准时交付、实时库存），多级成本汇总，在设计和报价阶段就能看到实时毛利（B）；QMS；PIM（产品内容）；Product Spotlight 面向售后与服务。
- **定价与上手**：报价制。聚合站给出约 73–120 美元/用户/月；AWS Marketplace 上 5 用户入门包含实施约 1.9 万美元/12 个月；可能另需 Salesforce 许可（D）。
- **对充气泵企业的意义**：设计阶段的实时成本汇总和 AML 内嵌 BOM，对 OEM/ODM 报价（客户问"换成无刷电机贵多少"）最直接；生产级 MCP 则意味着可以在常用的 AI 助手里直接查 BOM。
- **对 PDOS 的启示**：PDOS 的 CostEstimate 采用确定性计算（v1.1 §04.10），引擎已经处理报价有效期和数量阶梯（`pdos-next/server/pdos_next/engines/supply_cost/costs.py`），但面向立项与报价的"what-if 成本汇总视图"和 AML 还缺，详见 G1、G6。

### 2.3 Duro Design（Duro）

- **定位**：2025-06-17 重写后以"AI 原生 PLM"重新发布，面向硬件初创和中小硬件公司，新客户全部上新平台，老客户分批迁移（B/C）。
- **AI 能力**（C，行业媒体转述，官方文档少）：内建 AI 做校验、影响分析、元数据补全和寻源；自然语言搜索零件与装配；AI copilot 可以用自然语言生成业务逻辑（例如加一条校验或材料规则）；CEO 称方向是从历史变更记录学习，对新变更请求做预分析（路线图）。
- **关键非 AI 能力**：CAD/EDA 插件覆盖 Altium 365、SolidWorks、Onshape、NX；无代码配置（界面向导、YAML 编辑器、GraphQL API）；变更请求、变更单与 NPI 工作流；ERP 集成 NetSuite、SAP 等；寻源页可在一个视图里看到多家分销商的可比件，录入重复件时会告警；AWS Marketplace 列表称用 Octopart 做寻源（D）。
- **定价与上手**：聚合站显示起价约 9,000 美元（单位不明）；强调不需要顾问即可配置（C/D）。
- **对充气泵企业的意义**：Altium/SolidWorks 插件加分销商比价和重复件告警，适合电子料多、团队小的公司快速上手。但寻源数据以欧美分销商为主，国内供应链（立创商城、华秋等）不在其中。
- **对 PDOS 的启示**：自然语言生成"校验规则"的思路，可以对应到 PDOS 的确定性规则编辑。但 PDOS 的规则属于政策事实，AI 只能起草，发布要经人批准（§03.7、DC-11）。

### 2.4 OpenBOM

- **定位**：云端 BOM、PDM 与采购协同，SaaS 自助模式，面向中小制造企业。
- **AI 能力**
  - AI Assistant（GA）与 Agent 模式（2026-05，GA 但需单独 AI 许可，B）：Assistant 负责问答与指导，Agent 负责偏执行的流程；没有许可时 Agent 选项不出现。官方没有说明 Agent 写 BOM 时是否逐条确认。
  - CAD File Agent（SOLIDWORKS，2026-05 预览，B）：用对话方式锁定或解锁文件、同步、建修订、取旧版本。
  - BOM Review（2026-07-16，对所有客户 GA，B）：发布前的协作审查 Agent，用确定性"检查卡"校验料号、属性完整性和结构，结果分错误和警告；2026-08 增加 AI 检查卡 General BOM Health，查找近重复可合并零件、长交期元件、缺失的修订追踪字段；正在招募设计伙伴开发企业定制检查卡。
  - BOM AI Agent + MCP（2025-09 私测，B/C）：用自然语言提问（如某零件用在哪里），后端经 MCP 转成结构化查询；"产品记忆"把项目、零件和供应商连起来。成本与供应商方案权衡、多轮对话当时标为"即将推出"（路线图）。
- **关键非 AI 能力**：BOM、零件目录、库存、RFQ/采购订单、xBOM、ECO、PDM、REST API（不限调用次数）；CAD 插件覆盖 SolidWorks、Onshape、Creo、Fusion、Altium 365 等；有 Visma 等 ERP 同步。
- **定价与上手**（A/B，官网定价页）：Professional Team 30 美元/席/月（年付）；Company 90 美元/席/月（含 PDM、ECO、xBOM）；Enterprise 按报价。只读用户不限且免费，2,000 条记录以内免费，14 天试用；CAD 插件每 CAD 每席 25 美元/月；ERP 集成按单个集成固定价格。
- **对充气泵企业的意义**：最接近中小企业的预算和上手方式。BOM Review 用"确定性检查卡 + AI 检查卡"分层，RFQ 和采购在同一处，对 OEM 打样阶段的小批量采购很实用。
- **对 PDOS 的启示**：BOM Review 的分层与 PDOS 的确定性引擎 + AI 解释原则（§07.8）一致，可以直接借鉴为一个技能包，详见 G2。"只读用户免费"的做法，对应 PDOS 品质、工厂、供应商等只读角色的进入门槛。

### 2.5 Siemens Teamcenter / Teamcenter X（含 Copilot）

- **定位**：大型企业 PLM 标杆；Teamcenter X 是 Siemens 托管的 SaaS（AWS/Azure）；Essentials 档面向小团队（报价制，第三方称有 30 天试用，D）。
- **AI 能力**
  - Teamcenter Copilot（每个版本迭代，A/B）：嵌入式生成式助手，基于 Teamcenter 管理的数据作答。2512 版扩展到 MBSE、制造规划和质量；有第三方称 2512 支持一句话完成过滤、配置、建工作集等多步 BOM 操作（D）。
  - 2606（2026-06，A/B）：首个 Agent 能力 **BOM Agent**，能理解 BOM 上下文、提出变更，并在每一步保留人工监督的前提下执行多步流程（例如替换零件 → 影响分析 → 发起变更流程）；Copilot 进入 MBSE，可按可配置的 INCOSE 规则检查需求、并排给出改写建议、推荐测试用例并跟踪覆盖；知识库问答带可追溯来源；可在 Microsoft 365 Copilot 中结合 SharePoint、邮件使用 Teamcenter 上下文（数据仍留在 Teamcenter）；变更管理按历史推荐流程模板和任务分派、按规则自动路由、提供受影响物料视图、可批量撤回 BOM 变更。
  - Teamcenter Quality 2606（A/B）：Copilot 在审核与评估、问题解决（鱼骨图、5 Why）、质量措施和 FMEA 中给出预填建议；建议以表格展示，用户比较后挑选插入；提示词分三级（预置、授权用户可改、在结果上追问），带输出护栏。
  - 部署选项（A/B）：本地或客户云上可接 Azure AI（GPT 4.1/5.1）或 AWS Bedrock（Claude Sonnet 4.5），SaaS 版用 Teamcenter X，纯本地可用 Llama 4 Scout。
  - 成本：Product Cost Management 2606 引入 Copilot；Costing Add-on 和 3D Model-to-Cost（直接从 3D 模型取厚度、面积、体积算成本）计划在 2612（2026-12）上市（B，路线图）。
  - 平台层：Intelligence Center X（2026-06，B/C），是位于工业基础模型和各应用之上的 Agent 编排层，通过 MCP 连接各应用和企业数据；厂商宣称人工工作量减少 95%。
- **关键非 AI 能力**：合规模块开箱覆盖 REACH、RoHS、冲突矿产，并新增 PFAS；可批量处理供应商声明；限制材料成分的访问；可用表格批量导入供应商账号（2606，A/B）。此外有完整的 BOM/变更/配置/MBSE/制造规划/质量体系，与 NX、Solid Edge、SolidWorks 深度集成。
- **定价与上手**：报价制；Essentials 面向使用 NX X、Solid Edge X、SolidWorks 的团队，SolidWorks 用户需要 1:1 购买集成附加件（B/D）。没有找到 Teamcenter X 在中国大陆托管或数据驻留的公开说明。
- **对充气泵企业的意义**：功能最全，但实施和许可成本对中小企业偏重。最值得借鉴的是**质量 Copilot 的"表格对比后插入"**和**合规模块的物料声明管理**。
- **对 PDOS 的启示**：Teamcenter 的"表格对比后插入"与 PDOS ConfirmationBatch 的逐组确认（§05.6）同构，说明这种交互已被大厂验证。BOM Agent "提出 → 影响分析 → 发起变更"的链条，PDOS 的 `change_control` 技能包已具备；但起点"替代料推荐"需要 AML 和 where-used 支撑，详见 G1、G5。

### 2.6 PTC Windchill + Codebeamer

- **Windchill AI Assistant**（2026-04-28 GA，以插件交付，A/B）：在 Windchill 内用自然语言问答和摘要，**只基于 vault 中文档的内容**，暂不回答元数据、其他业务对象或软件本身的问题；查询语言可以与文档语言不同，已本地化含简体中文；本地部署与 SaaS 都可用；可用模式取决于许可、AI 席位和管理员配置；2026.1.0.11 版加入 PTC 帮助中心和技术支持知识库作为可选来源，部分模式对没有 AI 席位的用户开放（A）。PTC 表示后续会把 Agent 扩展到零件和变更管理（路线图）。2025-03 汉诺威展上的 Document Vault AI agent 是它的前身。
- **Windchill AI Parts Rationalization**（2026-01，插件，B/C）：识别相似零件以防止新增重复，找出已有冗余件，并通过 Windchill 变更流程推动合并。后续计划智能分类、设计中复用零件、结构指引、重复件持续监控、材料与成本属性比较（路线图）。公开材料没有说明相似度是基于几何还是属性。
- **Codebeamer AI 1.0**（2026-01-15，B/C）：Requirements Assistant 按 INCOSE/ISTQB 指南发现需求中的歧义、不一致和不合规；Test Case Assistant 从需求生成并优化测试用例。同期的 Codebeamer 3.2 提供与 Windchill 的数字线程、流基线、Review Hub 批量审批与差异高亮；pure::variants 7.2 提供基于特性的产品线工程。
- **关键非 AI 能力**：Windchill 的 BOM、变更、配置、可视化，与 Creo 原生集成；Codebeamer 的 ALM、追溯和合规模板。
- **对充气泵企业的意义**：零件去重对多型号、多 OEM 客户的料号膨胀很有价值（同一颗 3.7V 电芯或同一款气嘴被多次建料）。需求质量检查和测试用例生成，可以把"10–20 条关键规格 → 测试项"做得更规范。
- **对 PDOS 的启示**：PDOS 的 `gap_check` 已检查缺单位、缺工况、缺方法、未映射参数等（`pdos-next/server/pdos_next/skill_packages/gap_check.md`），与 Requirements Assistant 思路相同，且规格字典的口径约束更严，属于已对齐。缺的是零件层面的去重，详见 G1。

### 2.7 Dassault Systèmes 3DEXPERIENCE（含虚拟伙伴）

- **AI 能力**（B）：2026-02-11 发布 Virtual Companions，2026-07-23 宣布在 3DEXPERIENCE SaaS 上全球可用。AURA 负责项目与业务（跨需求、项目、变更编排知识和上下文），LEO 负责复杂工程（生成装配结构、跑仿真、评估设计、修复错误），MARIE 负责科学（材料、化学、配方），合计 19 项能力，可以引导、给洞察、探索方案、执行任务。厂商还称它们能"做决定"、与人同等地工作。运行在自家主权云 OUTSCALE 上。SOLIDWORKS 2026 里的 AURA 目前以检索、摘要、翻译、对话为主，设计辅助角色在后续规划中（C）。官方没有列出 19 项能力的具体内容，也没有说明审批和审计机制。
- **关键非 AI 能力**：ENOVIA（PLM）、CATIA、SOLIDWORKS、SIMULIA、DELMIA 一体化平台；SOLIDWORKS 订阅含 3DEXPERIENCE 云端 PDM。经销商报价：Design Standard 约 3,480 欧元/年（D）。
- **对充气泵企业的意义**：如果研发已用 SOLIDWORKS，AURA 是零额外集成的知识检索入口；但 PLM 级的 AURA 能力和许可都不透明，属于**宣传多于证据**。
- **对 PDOS 的启示**：Dassault 把 AI 定位成"会做决定的同事"，与 PDOS "AI 永不取得 T2"（AGENTS.md 不可协商项 1）方向相反。对需要具名签核的中国制造业团队，PDOS 的边界更容易获得品质和工程负责人的信任，不建议跟随。

### 2.8 Aras Innovator（InnovatorEdge AI）

- **AI 能力**（2026-02 发布，B）：InnovatorEdge 包含 API Manager（低代码，把 Innovator 数据以 API 开放给外部应用和 Agent）、App Builder（轻量任务应用）、Edge AI（构建、部署、运行、治理 Agent）。首批 7 个 Agent，分两类：
  - 对话型：Analytics & Insights（自然语言或语音查数、出图）、Knowledge Analysis（检索非结构化知识，发现没有建模的关系）。
  - 任务型（由人调用或条件触发，监督或半监督；Agent 提议的新关系须经人批准才写入数字线程）：**Requirements Ingestion**（PDF/Excel/Word → 结构化需求，并与已有需求查重）、**Smart Variant**（从大量 BOM 归纳特性、选项、规则，生成配置 BOM）、**BOM Assistant**（把表格、PDF、供应商文件中的 BOM 映射到标准结构，比较 Rev A 与 Rev B）。
  - Variant BOM Agent（2026-04 汉诺威展上与 SICK 联合演示，基于 Microsoft Foundry，B，演示）：识别模块化零件，建议可跨产品线复用的标准变体。
  - 部署：Edge 云服务可连接任意版本的 Innovator，SaaS 或私有部署都可以。
- **关键非 AI 能力**：低代码可建模的 PLM，开源授权模式加订阅；需求、变更、配置、质量、制造过程规划。
- **对充气泵企业的意义**：Requirements Ingestion 和 BOM Assistant 正对"客户 RFQ 或规格书 → 结构化需求"和"供应商 BOM 或旧 Excel → 系统 BOM"两大高频手工活；Smart Variant 对 OEM 多客户变体的料号收敛有价值。
- **对 PDOS 的启示**：PDOS 已有 `rfq_extraction`（隔离子任务、保留原文位置、映射规格字典，比 Aras 更严），属于已对齐；BOM 导入与清洗缺失，详见 G3。Aras 的"Agent 提议关系须人批准才写入"与 PDOS 的 T1 一致。

### 2.9 Autodesk Fusion Manage / Upchain

- **AI 能力**
  - Autodesk Assistant：在 Fusion 中 GA（2026-10-06 起有调整，B），在 Inventor 中可经 API 和 iLogic 改参数、建模型状态，在 Vault 中可用自然语言检索并推荐复用零件（B）；Fusion 提供 3 个 MCP 服务器（C）。Fusion Manage 的自定义属性可以通过 Assistant 用自然语言管理（C）。
  - **Agentic PLM on Fusion Manage**（AU 2026，2026-09 预览，B/C）：一个共享"画布"，以产品问题为起点（例如一封供应商邮件）把受影响数据和同事拉进来，再从同一处发起变更请求。演示中，系统在 Assistant 对话里处理电机缺货：评估影响、找到已批准的替代件、准备变更单。宣传语是"变更单自动流转、审批不用追"。产品记录、规则和变更历史仍由 Fusion Manage 管控，必要处保留人工审批。**订阅条款、区域和上线时间要到 2027 年才公布**。
  - 评论（BeyondPLM，作者为 OpenBOM CEO，D）：关注三点：建议、工程决定与已完成的生命周期动作是否区分清楚；助手读的是当前设计、已发布配置还是导入的副本；非正式调查转成正式变更时证据和推理是否保留。
- **关键非 AI 能力**：Fusion Manage 云 PLM（变更请求/变更单、BOM、项目、质量、供应商流程可配置），Vault 本地 PDM 连接器（传 item、BOM、属性和中性格式文件）。Upchain 在 2022 年以 "Fusion 360 Manage with Upchain" 捆绑推出，云 PLM+PDM 一个价，没有查到它 2025–2026 年的独立 AI 路线。
- **定价与上手**：聚合站显示约 93 美元/用户/月（D）。
- **对充气泵企业的意义**：缺料 → 替代 → 变更单的演示正是中小厂最常见的突发场景（电机或芯片缺货）；但目前是预览，不能作为采购依据。
- **对 PDOS 的启示**："画布从一个问题开始"对应 PDOS §05.5 的三种输入路径（"说情况"），已对齐。评论提出的三个疑问，PDOS 在设计上已有答案（T0/T1/T2、五视角配置快照、EvidenceReference）。缺的是替代料闭环所需的数据底座，详见 G5。

### 2.10 Oracle Agile PLM → Oracle Fusion Cloud PLM

- **Agile PLM 的去向**（C/D）：多方二手来源称 9.3.6 为最终版，Premier Support 到 2027-12-31 结束；Fusion Cloud PLM 是全新平台，不是原地升级。PTC 撰文称多数 Agile 客户因功能差距和"只有 SaaS"没有迁移到 Fusion（立场明显）。
- **Fusion Cloud PLM 的 AI**（A，docs.oracle.com，本次证据最扎实）：Oracle 称内嵌 Agent 不额外收费（B），并可用 AI Agent Studio 自建 Agent。
  - **Change Order Auditor（26B）**：管理员把企业自定义审核规则写成 PDF 上传，Agent 解析规则并生成专门的校验 Agent，调用 REST API 检查变更单的头信息、扩展字段、受影响对象和行字段，同时核对当前和下一状态的进出条件，然后邮件发出三份报告（汇总、进出条件、自定义规则）。文档没有说它会修改变更单，修正由人通过链接完成；只支持变更单，不支持变更请求、问题报告和纠正措施；由业务规则控制谁能运行。
  - **Product Readiness Workspace（26B，Agentic App）**：面向产品经理和 NPI 干系人，专家 Agent 评估 BOM 完整性与合规、未关闭的变更单、缺少替代供应源、元件相关问题报告、EOL 通知对库存/采购协议/工单的影响，输出准备度简报、变更单报告、质量问题报告和缓解计划，可回答"什么在阻塞上市准备"。值得注意的是，其合规判定只看制造商料号附件的**文件名是否包含 "compliance certification"**，规则相当粗糙；文档也没有描述审批环节。
  - Component Replacement Assistant（25D，26A 改进）：识别被替换元件、推荐替代、分析供应链影响、生成变更单。
  - 其他（25C–26D）：Product Regulatory & Compliance Advisor（按管理员挂载的法规文档检查物料属性）、Manufacturer Onboarding & Risk Assessment Advisor、Master Data Governance Standards Advisor、Product 360/Product Comparison Advisor、Workflow Policy Advisor、Quality Inspection Standards Advisor、Quality Assurance Workspace（26D）。
  - **Design-to-Source Workspace（26B）**：把规格转成供应商选项，模拟成本与交期的取舍，执行 RFQ 和买卖双方沟通，把 CAD 更新自动带入寻源（B/C）。
  - 供应侧：Supplier Qualification Workspace（26C）、Autonomous Sourcing Assistant（26A/26B）、Sourcing Command Center（26B/26D，含授标模拟）等。
- **对充气泵企业的意义**：Oracle 的场景切分最贴近 NPI，例如"上市准备度"和"设计到寻源"。但它是大型 ERP 套件的一部分，中小企业不会为此上 Oracle。可借鉴的是**场景划分和规则文档驱动的预审**。
- **对 PDOS 的启示**：Product Readiness Workspace ≈ PDOS 阶段门与准备度（§03.7）。PDOS 坚持"准备度是一组规则而不是 AI 分数"，比 Oracle 依赖 Agent 判断加文件名启发式更可信，**应保持**。Change Order Auditor 的"规则文档 → 校验"可以直接借鉴到 PDOS 的变更单、放行包和 G1 提交预审，详见 G7。

### 2.11 相邻工具（不在指定名单，但与设计评审或知识检索直接相关）

- **CoLab AutoReview**（2025 年发布，早期访问/Beta，B/C）：对 Creo、NX、SolidWorks、CATIA 的 3D 模型和 2D 图纸做错误与 DFM 检查；几何或零件相似时推送历史项目的经验教训；2026-07 与加拿大标准委员会合作，按 ISO 标准检查图纸并给出引用。**Beta 用户包括 TTI（RYOBI 母公司）**，这是与充气泵最接近的电动工具与户外品牌。
- **Leo AI**（D，基本是厂商自述）：跨 CAD、PLM、ERP 的工程 copilot，称用标准、数据手册等工程资料作答，接入 1.2 亿零件目录。它批评各家内建 Copilot 只能看到本 PLM 内的数据。

### 2.12 国产 PLM 观察（只作提示，未深入）

搜索结果多为带推广性质的二手文章，提到鼎捷流程行业 PLM 已有配方推荐、合规稽核等 AI 能力，引用 IDC 称 2025 年中国 PLM 市场 40.9 亿元（D，未核实）。华天软件、思普等没有检索到 2025–2026 年可信的 AI 资料。建议另开一轮专项调研（含飞书项目、钉钉 Teambition/宜搭类低代码方案）。

## 3. 能力矩阵（按调研维度）

记号：●=GA 且有官方说明；◐=有但较浅、或证据弱；○=预览/路线图/演示；—=未见。

| 维度 | Arena | Propel | Duro | OpenBOM | Teamcenter | Windchill+CB | 3DX | Aras | Autodesk | Oracle Fusion | **PDOS（设计/代码）** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BOM/ECO AI（摘要、对比、影响、起草） | ●对比/摘要/Redline | ◐影响分析 | ◐ | ●BOM Review / ◐Agent | ●BOM Agent | ○路线图 | ○ | ●BOM Assistant | ○预览 | ●替代料/审核 | ◐变更影响分栏（`change_control`），缺零件级反查 |
| 需求/规格 | ◐ | ◐ | — | — | ●INCOSE 检查 | ●Codebeamer AI | ◐AURA | ●需求导入 | — | ◐ | ●规格字典 + `rfq_extraction` + `gap_check` |
| 合规（RoHS/REACH/PFAS/认证） | ●自动 BOM 合规/SCI | ◐ | — | — | ●REACH/RoHS/PFAS | ◐ | — | ◐ | — | ●合规顾问（规则粗糙） | ◐只有品类级"法规认证"清单 |
| 供应商协同/报价 | ●供应商协同 | ●AML | ◐分销商比价 | ●RFQ/PO | ●供应商门户 | ● | ◐ | ◐ | ◐ | ●设计到寻源 | ◐SupplierReference/承诺，无询价比价 |
| 成本 | ◐ | ●实时成本汇总 | — | ○成本权衡 | ○Model-to-Cost | ◐ | — | — | — | ●寻源模拟 | ●确定性 CostEstimate（报价有效期/阶梯） |
| 质量 CAPA/NCR | ●QMS + AI 引导 | ●QMS | — | — | ●Quality Copilot | ◐ | — | ◐ | ◐ | ●QA Workspace | ●Issue/CAPA/复验 + `quality_issue` |
| 项目/阶段门 | ◐ | ◐ | ◐NPI 流程 | — | ● | ● | ●AURA | ● | ◐ | ●准备度 Workspace | ●G0/G1、阶段门、准备度规则 |
| 设计评审 | ◐文件对比 | — | — | ◐BOM Review | ◐ | — | ○LEO | — | — | — | ◐Review/Decision 对象，无图纸/DFM 辅助 |
| 文档/知识检索 | ●Workspace Search | ◐ | ●自然语言搜索 | ● | ●带来源知识库 | ●仅 vault 文档 | ●AURA | ●知识分析 | ●Vault 检索 | ●Product 360 | ●证据库 + 公开研究台账 |
| Agent 形态 | 对话 + 引导 | Agentforce 角色 Agent + MCP | copilot | 助手/Agent 双模式 | Copilot + BOM Agent | 插件式 | 虚拟伙伴 | 对话 + 任务助手 | Assistant + 画布 | 事件/按钮触发 Agent + Studio | 单一小Pai + 技能包 + AutomationRule |
| 审批与写入边界 | 未披露 | "人掌控"（营销） | 未披露 | 未披露 | 每步人监督 | 只读为主 | 称可"做决定" | 人批准才写 | 保留人审批 | 多为只读报告 | **T0/T1/T2 分级，T2 永不由 AI 执行** |
| 对外开放给 AI 客户端（MCP 等） | — | ●生产级 MCP | GraphQL | ○MCP 私测 | ●M365 Copilot / IC-X MCP | — | — | ●Edge API | ●Fusion MCP | ●Agent Studio | —（只有入站 MCP 连接器） |
| CAD/EDA/ERP 集成 | Onshape/200+ 连接器 | DesignHub 多 CAD | Altium/SW/Onshape/NX + NetSuite/SAP | 多 CAD + Altium + ERP | 原生 NX 等 | 原生 Creo | 原生 SW/CATIA | 多 CAD | Fusion/Inventor/Vault | Oracle ERP | 框架完整，无预置连接器 |
| 中小企业定价/上手 | 约 2.5 万美元/年起（D） | 5 用户约 1.9 万美元/年（D） | 约 9,000 起（D） | 30/90 美元/席/月，只读免费 | 报价，Essentials | 报价 + AI 席位 | SW 订阅 + 报价 | 订阅 | 约 93 美元/用户/月（D） | 套件报价 | 自建，无许可费；上手靠导入能力 |

## 4. 跨产品模式

1. **文件差异与摘要是最先成熟的 AI 能力**（Arena AI File Comparison/Item Redline、Windchill 文档问答与摘要、Aras BOM Rev A/B 对比）：用于变更评审、培训、客户来件改版。
2. **"确定性检查 + AI 检查"分层的发布前审查**（OpenBOM BOM Review 的检查卡、Oracle Change Order Auditor 的进出条件 + 自定义规则 PDF、Teamcenter 的 INCOSE 规则）：规则可配置，AI 负责解释和发现模糊问题。
3. **替代料/缺料 → 影响分析 → 起草变更单，人批准**（Oracle Component Replacement、Teamcenter BOM Agent、Autodesk 电机缺货演示、Propel 元件替换提示）。
4. **非结构化输入 → 结构化对象的导入型 Agent**（Aras 需求导入/BOM Assistant、OpenBOM 数据导入、Oracle 寻源中的规格解析）。
5. **AI 建议以表格或候选的形式由人挑选后写入**（Teamcenter Quality 表格插入、Aras 关系须人批准、Oracle 只出报告）：普遍回避 AI 直接改正式记录。
6. **PLM 作为 AI 的数据源向外开放（MCP/API）**（Propel 生产级 MCP、Teamcenter 接 M365 Copilot、Autodesk Fusion MCP、OpenBOM MCP、Aras Edge API、Siemens IC-X）。
7. **场景化的工作台（Workspace/Canvas）取代通用聊天**（Oracle Product Readiness、Design-to-Source；Autodesk 画布；Arena 引导式工作流）。
8. **AI 单独计费或单独授权**（Windchill AI 席位、OpenBOM AI 许可、Siemens Costing Add-on），以及**模型和部署可选**（Teamcenter 三种模型路径、Arena 用 Bedrock、Dassault 主权云）。
9. **零件主数据治理借 AI 回潮**（Windchill 零件去重、OpenBOM 近重复检测、Duro 重复件告警、Aras 变体归纳）。

## 5. 对照 PDOS：已对齐、缺口与建议

### 5.1 已对齐、应保持的差异化

- **写入分级与具名决定**：AI 只能起草，T2 永不执行（AGENTS.md 不可协商项 1、`docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md:§06.5`，行 1000–1010）。竞品大多停留在"人掌控"的营销表述。
- **显式依赖与 AI 线索分栏**（v1.1 §04.13，行 733–739）：对应 Autodesk 评论里"建议与决定须分清"的担忧。
- **准备度 = 规则而不是 AI 分数**（v1.1 §03.7，行 551）：比 Oracle Product Readiness 的文件名启发式更可信。
- **逐组确认的 T1 批次**（v1.1 §05.6，行 837–843）：与 Teamcenter Quality 的表格挑选插入同构。
- **需求抽取与规格口径**：`rfq_extraction`、`gap_check` 加规格字典的参数版本（v1.1 §02.3a，行 322–357），在口径约束上严于 Aras 需求导入和 Codebeamer 需求检查。
- **"说情况"式输入和事件驱动规则**（v1.1 §05.5 行 829–835、§06.4 行 990–998）：对应 Autodesk 画布和 Oracle、Aras 的条件触发 Agent。
- **自建部署、模型可换**（确认稿 P26；v1.1 §06.9）：规避境外 SaaS 在中国的数据驻留问题；Teamcenter 也提供多模型路径，说明这是大厂共识。

### 5.2 功能缺口（按对充气泵企业的影响排序）

> 说明：v1.1 已冻结（AGENTS.md 不可协商项 7）。下表"落地方式"一栏区分两类：**技能包内细化**（技能包是版本化配置，不入库，v1.1 §06.3.2），以及**需决策记录**（新增领域对象、新的对外暴露面、改变边界）。

| # | 缺口 | 竞品参照 | 对充气泵 / OEM/ODM 的业务价值 | PDOS 现状 | 落地方式 |
|---|---|---|---|---|---|
| G1 | **零件主数据：where-used 反查、AML/AVL（制造商与 MPN、首选/替代、生命周期状态）、近重复料识别** | Propel AML 内嵌 BOM、Windchill 零件去重、OpenBOM 近重复、Duro 重复件告警 | 同一电芯、电机、气嘴、PCB 被不同项目重复建料；变更时找不全受影响型号；报价时不知道已认证的替代源 | `parts` 表只有内部/ERP/客户料号与映射版本、设计引用（`pdos-next/server/pdos_next/domain/configurations/models.py`）；v1.1 §02.5（行 371–377）没有 AML 或生命周期；有变更依赖闭包（`pdos-next/server/pdos_next/change_graph_closure.py`），但未见零件级 where-used 读模型 | 需决策记录（AML 和生命周期是新字段/对象）；where-used 可作只读投影，在 §02.5 内细化 |
| G2 | **BOM 发布前健康检查**（确定性检查卡 + AI 检查卡） | OpenBOM BOM Review、Oracle Change Order Auditor | 试模和试产前发现缺料号、缺单位、长交期、疑似重复，减少开模后返工 | 有准备度规则与 `gap_check`（只针对提案和定义） | 技能包内细化（新增 `bom_review` 技能，复用确定性引擎） |
| G3 | **BOM 与规格书导入清洗**（Excel、PDF、供应商 BOM → BOMRevision 候选，并做料号映射） | Aras BOM Assistant、OpenBOM 导入 | 上手速度：老型号 BOM 都在 Excel 和 ERP 里；ODM 客户或供应商发来的 BOM 格式五花八门 | §02.2 只支持存量型号规格从 Excel 导入（"导入，未复核"）；17 个技能包中没有 BOM 导入 | 技能包内细化（T1 候选，标"导入，未复核"） |
| G4 | **客户原件修订对比**（规格书、图纸 v1 与 v2 → 需求差异 → ChangeRequest 或提案修订候选） | Arena AI File Comparison/Item Redline、Aras Rev A/B | OEM 客户频繁改规格（噪音 dB、充气时间、外观、包装），手工比对容易漏项 | `rfq_extraction` 只做单份抽取；`derivative_diff` 针对型号派生；原件不可变（§02.3）已为对比提供基础 | 技能包内细化（在 `rfq_extraction` 中加修订对比模式） |
| G5 | **替代料 / EOL / 缺料处置闭环**（推荐已认证替代 → where-used 影响 → 起草 ChangeRequest → AlternateQualification 验证） | Oracle Component Replacement、Teamcenter BOM Agent、Autodesk 演示 | 芯片、电机、电芯缺货是中小厂最常见的突发事件；临时替料可能带来认证失效风险 | AlternateQualification 规定不能因参数相近直接替料（§04.10，行 713–719），方向正确；缺 G1 的数据底座和专门技能 | 依赖 G1；技能包内细化（`change_control` 增加替代料子流程） |
| G6 | **供应商询价与比价**（向供应商发 RFQ 包 → 报价归一化：币种、阶梯、MOQ、交期、有效期 → 成本对比） | Oracle Design-to-Source、OpenBOM RFQ/PO、Propel 成本汇总 | OEM/ODM 报价周期主要卡在 BOM 询价；按客户目标价倒推成本需要多套供应方案的 what-if | 成本引擎已处理报价有效期和数量阶梯（`pdos-next/server/pdos_next/engines/supply_cost/costs.py`）；没有供应商报价对象和询价流程；发出 RFQ 属于外发（T2） | 需决策记录（报价对象、对外发送边界）；报价归一化可放在计算工具内 |
| G7 | **规则文档驱动的提交预审**（变更单、放行包、G1 计划基线、客户交样包） | Oracle Change Order Auditor | 减少评审会上才发现缺件；把企业"变更单填写规范"直接变成可执行检查 | `gap_check` 覆盖提案和定义；准备度规则覆盖门禁 | 技能包内细化（扩展 `gap_check` 的 target 类型；规则仍由人发布） |
| G8 | **零件/材料级合规与认证生命周期**（RoHS、REACH SVHC、PFAS、Prop 65 声明；证书号、标准版本、覆盖型号/变体/配置、有效期；变更是否触发重认证） | Teamcenter 合规模块、Arena 自动 BOM 合规/SCI、Oracle 合规顾问 | 出口欧美的硬门槛。通用行业常识（本轮未专项核验）：PVC 软管涉及邻苯类 SVHC 和 Prop 65，锂电款涉及 UN38.3 与欧盟电池法规；改一颗料可能让 CE/FCC 报告不再覆盖 | 品类级只有"法规认证"清单（§02.3a，行 330）；"市场/认证适用性"作为放行类型存在（§03.11，行 594）；未见合规声明或证书对象（代码中没有 rohs、material_declaration 等） | 需决策记录（新对象：合规声明、证书范围）；AI 从供应商检测报告 PDF 抽取 → T1，判定交确定性规则 |
| G9 | **设计评审辅助**（图纸/DFM 检查清单、按相似零件推送历史 Issue/FailureMode 教训） | CoLab AutoReview（TTI/RYOBI 参与 Beta）、Teamcenter 知识库 | 注塑外壳、气缸、密封结构的 DFM 问题在试模后才暴露，代价最高；新人缺少老项目的教训 | 有 Review/Decision、DesignRule、KnowledgeCandidate（§02.1）；DFM/FMEA 按需选用（§04.5，行 669）；没有设计评审技能 | 技能包内细化（只读检查 + 历史教训检索，结论由专业本人作出） |
| G10 | **PDOS 对外开放**（只读 MCP 服务端，或钉钉 AI 助理/互动卡片承载 T1 确认与"我的工作"） | Propel 生产级 MCP、Teamcenter 接 M365 Copilot、Autodesk Fusion MCP | 团队协同在钉钉，在钉钉里直接确认交样、回复外部等待，能明显提高使用率 | 只有入站 MCP 连接器（§06.6.2，行 1021–1031）；拓扑中有"授权钉钉轻入口"（v1.1 行 1122），但未细化 | 需决策记录（新主体与暴露面；先做只读） |
| G11 | **预置连接器**（金蝶/用友 ERP 的 BOM 与物料移交包、钉钉身份与通知、GoodJob 客户与商机引用） | Arena Connect 200+ 连接器、Duro NetSuite/SAP、OpenBOM ERP 固定价集成 | 中小企业没有集成团队，没有预置连接器就只能长期人工导入 | 连接器框架（inbox/outbox、回执、对账）设计完整（§07.9 行 1212–1218、§08）；允许受控人工交接（§04.14） | 在 §07.9 内细化（先做文件包 + 回执，再做 API） |
| G12 | **从 3D 或 BOM 估算成本**（should-cost） | Siemens 3D Model-to-Cost（2612 路线图） | 塑件和五金件的目标成本 | CostEstimate 依赖报价和 BOM 输入 | 暂缓（竞品也只在路线图阶段） |
| G13 | **变体与模块化 BOM 归纳** | Aras Smart Variant / Variant BOM Agent（演示） | 多 OEM 客户变体收敛到平台模块 | 有 Platform/Variant/派生（§02.2、§02.4） | 暂缓，观察 |

### 5.3 体验与运营层面的优化（不改领域边界）

- **场景工作台，而非只有聊天**：Oracle 的 Product Readiness 和 Design-to-Source 证明，"准备度简报""变更单报告"这类场景化输出比通用对话更容易被管理层采用。PDOS 的阶段与门禁页（§05.12.2）可以由小Pai 生成"门禁准备度简报"（读规则结果，不另算分数）。
- **AI 检查卡可配置**：参照 OpenBOM 招募设计伙伴开发企业检查卡，把品质和工程的"必查项"沉淀为可版本化的规则集，由人发布；配合 G2、G7。
- **AI 用量与费用透明**：竞品把 AI 单独计费。PDOS 已有运行回执与预算（§06.10、§05.3"AI 工作详情：费用"），可以在租户层增加"按技能包统计调用量与成本"的视图，为后续加入多模型服务商（P26）留出成本依据。
- **只读角色零门槛**：参照 OpenBOM 只读用户免费，让工厂、品质、供应商侧的只读访问以最少配置开通（按品类 Grant 收窄）。

### 5.4 不建议跟随的做法

- **AI"做决定"或"自动审批流转"**（Dassault 的定位、Autodesk 的"审批不用追"宣传）：与 DC-11 冲突；可以做的是自动催办和聚合注意项（§05.2），不是自动批准。
- **用 AI 分数或文件名启发式判定合规与准备度**（Oracle 文档中的做法）：PDOS 应坚持证据适用性（§02.10）与确定性规则。
- **只基于本系统数据的 Copilot**：Windchill AI Assistant 只读 vault 文档，Leo AI 批评内建 Copilot 看不到系统外数据。PDOS 的证据库加 MCP 入站连接器已经覆盖跨系统读取，应保持"外部内容不可信、只读子任务处理"（§06.6.2）。

## 6. 用户期待信号（来自调研）

- 250 位欧美制造业工程负责人中，95% 认为 12–24 个月内设计团队全面采用 AI 很关键；他们估计约 73% 的图纸评审可自动化；较小企业担心数据不够规整，AI 用不起来；共识是 AI 做重复检查、判断留给工程师（CoLab 调研，厂商委托）。
- 400 位制造业高管中，49% 把 PLM 排为 AI Agent 通过 MCP 访问的首选系统，超过 90% 已实施或计划在 12 个月内实施 MCP（Propel 委托 Talker Research，厂商立场）。
- 评论者关注：建议、决定与已完成动作是否区分；助手读的是哪个配置；非正式讨论转正式变更时证据会不会丢（BeyondPLM，OpenBOM CEO 撰写）。
- 用户期望跨系统上下文：内建 Copilot 看不到供应商数据手册、ERP 记录和共享盘文件（Leo AI 博客，竞品立场）。
- 部署灵活性影响迁移：PTC 称多数 Agile 客户因功能差距和"只有 SaaS"没有迁到 Oracle Fusion（PTC 博客，竞品立场）。
- AI 单独计费已成常态（Windchill AI 席位、OpenBOM AI 许可），中小企业会在意 AI 用量与成本是否可控。
- 集成平台化要先看版本档位、流程上限、连接器权限和审计（对 Arena Connect 的第三方分析）。
- 大厂一致把"AI 辅助而不取代问责与治理"当作卖点（Autodesk AU 2026 表述；Teamcenter 每步人监督；Aras 须人批准）。

## 7. 成熟度速查（截至 2026-10-22）

| 能力 | 成熟可用（GA 且有文档） | 预览/演示/路线图 |
|---|---|---|
| 文档问答、摘要、对比 | Arena AI Engine、2026.2 Redline/Insights；Windchill AI Assistant（只读文档内容）；Teamcenter Copilot 知识库 | Windchill 零件和变更 Agent |
| BOM 检查与清洗 | OpenBOM BOM Review + AI 检查卡；Aras BOM Assistant | OpenBOM 成本权衡分析 |
| 变更起草与替代料 | Teamcenter 2606 BOM Agent；Oracle Component Replacement；Oracle Change Order Auditor（只读审核） | Autodesk Agentic PLM（2027 年公布细节） |
| 需求与测试 | Codebeamer AI 1.0；Teamcenter MBSE Copilot；Aras 需求导入 | — |
| 质量 | Teamcenter Quality Copilot；Arena AI Assistant 引导 CAPA；Oracle QA Workspace（26D） | — |
| 合规 | Teamcenter 合规（REACH/RoHS/PFAS）；Arena 自动 BOM 合规；Oracle 合规顾问 | — |
| 成本 | Propel 成本汇总（非 AI）；Oracle 寻源模拟 | Siemens Costing Add-on / Model-to-Cost（2612） |
| 对外开放 | Propel 生产级 MCP；Teamcenter 接 M365 Copilot；Fusion MCP；Aras Edge API | OpenBOM MCP（2025-09 私测）；Siemens IC-X 平台 |
| 自主执行 | 无一家公开承诺无人审批的写入 | Dassault 虚拟伙伴（称可做决定，治理未披露） |

## 8. 来源

Arena（PTC）
- PTC Arena Connect 2026.2 新闻稿（PR Newswire）：https://www.prnewswire.com/news-releases/ptc-launches-arena-connect-to-simplify-enterprise-integrations-for-manufacturers-302842413.html
- Arena 2026.2 第三方分析：https://windowsforum.com/news/ptc-arena-2026-2-packages-connect-workflows-with-enterprise-limits.441687/
- Arena AI Engine（DE247）：https://www.digitalengineering247.com/article/ai-engine-for-arena-plm-and-quality-management-boosts-automation/plm
- Arena AI Assistant 新闻稿：https://www.ptc.com/en/news/2025/ptc-launches-arena-ai-assistant
- Arena 春季版 AI Comparison/Workspace Search：https://www.ptc.com/en/resources/ptc-next-on-demand/spring-infocus-arena-ai-comparison-workspace-data-search
- Arena 定价（聚合站）：https://www.capterra.com/p/6101/Arena-PLM/

Propel
- 生产级 MCP（IT Brief）：https://itbrief.co.uk/story/propel-launches-production-mcp-for-ai-driven-plm-integration
- Propel BOM Management 页：https://www.propelsoftware.com/solutions/use-case/bom-management
- Propel One 首批客户（CIMdata 转载）：https://www.cimdata.com/zh/industry-summary-articles/item/28608-propel-software-accelerates-adoption-of-agentic-ai-for-plm-qms-pim-with-early-customers-using-live-data
- Intellyx 分析：https://intellyx.com/2025/11/26/propel-software-one-data-thread-for-product-engineering-quality-and-information/
- 定价（聚合站/AWS）：https://www.softwaresuggest.com/propel/pricing ；https://aws.amazon.com/marketplace/pp/prodview-54sj27wijruoi
- MCP 调研：https://www.propelsoftware.com/resources/survey-manufacturers-are-all-in-on-mcp

Duro
- Duro Design 发布（DE247）：https://www.digitalengineering247.com/article/ai-native-plm-solution-accelerates-design/plm
- 新闻稿：https://www.automation.com/en-us/products/june-2025/duro-design-first-ai-native-plm-engineering
- 寻源页：https://durolabs.co/products/sourcing/
- 聚合站：https://www.getapp.com/it-management-software/a/duro/

OpenBOM
- 2026-05 更新：https://www.openbom.com/blog/product-feature-updates/whats-new-openbom-may-2026-update
- BOM Review 发布：https://www.openbom.com/openbom-introduces-bom-review-collaborative-agent
- 2026-08 AI 检查卡：https://www.openbom.com/blog/plm-and-bom-management/ai-bom-health-check-card-bom-review
- MCP 私测：https://www.openbom.com/blog/press-release-openbom-announces-private-beta-of-ai-bom-agent-with-mcp-support
- 定价：https://www.openbom.com/pricing

Siemens
- Teamcenter Copilot：https://blogs.sw.siemens.com/teamcenter/teamcenter-plm-ai-copilot/
- Teamcenter 2606：https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/
- Teamcenter Quality 2606：https://blogs.sw.siemens.com/teamcenter/whats-new-teamcenter-quality-2606/
- Product Cost Management 2606：https://blogs.sw.siemens.com/teamcenter/teamcenter-product-cost-management-whats-new-in-version-2606/
- Teamcenter X Essentials：https://plm.sw.siemens.com/en-US/teamcenter/teamcenter-x-cloud-plm/essentials
- Intelligence Center X（Verdantix）：https://www.verdantix.com/insights/blog/siemens-realize-live-europe-2026--digital-twin-composer-and-intelligence-center-x

PTC Windchill / Codebeamer
- Windchill AI Assistant 新闻稿：https://www.ptc.com/en/news/2026/ptc-launches-windchill-ai-assistant
- Windchill AI Assistant 帮助中心：https://support.ptc.com/help/windchill/ai_plugin/en/Windchill_Help_Center/document_vault/NewandChanged_PTCHelpWCAIAssistant.html
- Windchill AI Parts Rationalization（DE247）：https://www.digitalengineering247.com/article/ptc-launches-windchill-ai-parts-rationalization-capabilities
- Codebeamer AI 1.0（CIMdata）：https://www.cimdata.com/en/industry-summary-articles/item/29186-ptc-delivers-new-ai-functionality-for-software-driven-product-development-with-new-alm-releases
- Agile 迁移观点（PTC 博客）：https://www.ptc.com/en/blogs/plm/transitioning-from-oracle-agile-plm

Dassault Systèmes
- 虚拟伙伴 GA 新闻稿：https://www.3ds.com/newsroom/press-releases/dassault-systemes-expands-3dexperience-ai-native-agentic-platform-new-virtual-companion-skills-co-engineer-humans
- ENOVIA 博客：https://blog.3ds.com/brands/enovia/meet-your-new-ai-experts-on-the-3dexperience-platform/
- SOLIDWORKS 订阅价（经销商）：https://ohmycad.com/en/?p=117142

Aras
- 首批 Agent：https://aras.com/en/blog/introducing-the-first-generation-of-agents-built-on-aras-innovator-edge-ai
- InnovatorEdge（engineering.com）：https://www.engineering.com/aras-adds-new-innovatoredge-services-for-plm-access/
- Variant BOM Agent：https://www.businesswire.com/news/home/20260416924846/en/Aras-to-Showcase-AI-Powered-Variant-BOM-Agent-in-Microsoft-Booth-at-Hannover-Messe

Autodesk
- AU 2026 产品发布：https://www.autodesk.com/solutions/autodesk-university-2026-product-announcements
- Agentic PLM on Fusion Manage：https://www.autodesk.com/products/fusion-360/blog/fusion-manage-agentic-plm/
- Autodesk 新闻：https://adsknews.autodesk.com/en/news/autodesk-ai-design-manufacturing-au-2026/
- BeyondPLM 评论：https://beyondplm.com/2026/10/11/autodesk-agentic-plm-canvas-assistant/
- Fusion Manage 定价（聚合站）：https://www.capterra.com/p/239932/Autodesk-Fusion-Lifecycle/pricing/

Oracle
- Fusion AI 特性表（SCM/PLM）：https://docs.oracle.com/en/cloud/saas/fusion-ai/aiafl/ai-scm.html
- Change Order Auditor（26B）：https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/plm26b/26B-plm-wn-f43270.htm
- Product Readiness Workspace（26B）：https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/plm26b/26B-plm-wn-f44464.htm
- Product Regulatory & Compliance Advisor（25C）：https://docs.oracle.com/en/cloud/saas/readiness/scm/25c/plm25c/25C-plm-wn-f38633.htm
- Design-to-Source Workspace（Oracle 博客）：https://blogs.oracle.com/scm/meet-the-agentic-ai-design-to-source-workspace-for-plm-from-cad-to-confident-sourcing-decisions
- 2026-02 SCM AI Agents 新闻稿：https://www.oracle.com/news/announcement/oracle-ai-agents-help-boost-supply-chain-efficiency-and-strengthen-resiliency-2026-02-10/
- Agile PLM 支持期（第三方）：https://www.traceone.com/oracle-agile-plm-when-does-support-end-and-what-are-the-options-trace-one

相邻工具与调研
- CoLab AutoReview：https://develop3d.com/ai/colab-autoreview-automates-common-design-checks-with-ai/ ；https://www.engineering.com/colab-launches-autoreview-ai-tool-for-design-review/
- CoLab 工程负责人调研：https://www.intelligentcio.com/north-america/2025/08/20/ninety-five-per-cent-of-engineering-leaders-say-design-teams-must-adopt-ai-within-two-years-survey-finds/
- Leo AI（竞品博客）：https://www.getleo.ai/blog/best-ai-tool-teamcenter-2026
- 国产 PLM（二手、推广性质）：https://www.csdn.net/article/2026-08-18/163858050

PDOS 内部依据（只读）
- `docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md`：§02.3a（行 322–357）、§02.5（行 371–377）、§03.7（行 551）、§03.11（行 592–598）、§04.5（行 669）、§04.10（行 713–719）、§04.13（行 733–739）、§05.5–05.6（行 829–843）、§06.3（行 960–988）、§06.4–06.5（行 990–1010）、§06.6.2（行 1021–1031）、§07.9（行 1212–1218）
- `pdos-next/server/pdos_next/skill_packages/`（17 个技能包）
- `pdos-next/server/pdos_next/domain/configurations/models.py`（parts / bom_revisions / bom_lines）
- `pdos-next/server/pdos_next/engines/supply_cost/costs.py`（报价有效期与数量阶梯）
- `pdos-next/server/pdos_next/change_graph_closure.py`（变更依赖闭包）
