# r2 · AI-native 硬件研发 / 制造 / 品类研究工具调研（2024–2026）

> 调研日期 2026-10-22。只读分析，未改仓库。外部资料以官方产品页、文档、发布稿为主，媒体与第三方点评为辅；所有效果数字一律标"厂商宣称"，未见独立验证。
> 成熟度标签：**GA**（公开可用、有付费客户）／**早期访问**（early access、内测、beta）／**研究预览**（厂商自己称 early、无评测）／**未核实**（只在新闻稿或第三方页面出现）。
> PDOS 引用格式：`v1.1:行号` 指 `docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md`；技能包指 `pdos-next/server/pdos_next/skill_packages/*.md`。

---

## 0. 一页结论

1. **成熟、能直接借鉴的 AI 用法集中在"第一遍检查 + 人逐条处置"**：CoLab AutoReview 按企业自己的标准和历史评审意见检查图纸和 3D，Cofactr 给 BOM 每行的替代料建议逐条接受或拒绝，Nominal 用检查清单扫测试 Run，每条违规由人决定"忽略"或"处理"，Fictiv 在报价前自动做注塑 DFM。这些工具都不让 AI 直接改受控对象，跟 PDOS 的 T0/T1/T2 分级（DC-11）和"AI 推测与显式依赖分栏"（v1.1:739）是同一思路。
2. **生成类能力（text-to-CAD、AI PCB 自动布局、AI 原理图）还在演示或早期阶段**：Zoo Zookeeper 厂商自称 early（2026-01 随 Design Studio v1.1 发布）；Leo AI 能从文字生成装配体，但零件还不会自动配合；Flux 自动布局只适合简单到中等复杂度的板子；Quilter 的效果数字没有第三方评测。对一家做充气泵的中小企业来说，这类能力只值得做"外部工具产物的版本引用"，PDOS 不应自建。
3. **采购和报价环节的 AI 做两件事：把乱格式的报价单、BOM、图纸整理成可比较的结构化行；比价、选方案由人定**（LightSource 的报价归一与授标方案，Paperless Parts Wingman 从报价包抽要素，Jiga 从图纸抽要求）。PDOS 已有 `rfq_extraction`（处理客户 RFQ）和确定性的 CostEstimate（v1.1:719），但**没有"供应商报价抽取与归一"这一环**，而模具、电机、电芯、气缸的多家报价比较正是充气泵 NPI 每天都在做的事。
4. **产线 / 测试数据的 AI 价值在于跨数据源关联，产出根因假设**（Instrumental 把每台单元的图像、功能测试和测量值关联起来；Nominal 用规则清单处理遥测）。PDOS 的 `test_verification` 和 `quality_issue` 已把假设固定标为 `ai_hypothesis`，但缺两样：对测试序列做逐条违规处置，以及跨 Run 的关联候选。
5. **品类和电商研究工具都已普遍 AI 化，而且越来越强调证据可追溯**：卖家精灵 AI 评论 2.0 有"证据抽屉"可回查买家原话，单次约 500 条样本、每个星级约 100 条，官方明说"不能单独判断一个产品是否值得做"；Amazon Customer Review Insights 给出每个主题对星级的影响；Opportunity Explorer 在 2025 年加了未满足需求洞察。PDOS 的 `review_pain_clustering`（条数和占比由代码算）和 `competitor_comparison`（区分实测、宣传、推断、未知）**在口径严谨上已经超过这些工具**。缺口在数据进入：卖家后台数据（搜索量、未满足需求、退货原因、NCX）只能从账号导出或经 MCP 获取，PDOS 还没有标准化的导入模板，也没有记录抽样元数据。
6. **"在业务系统里内嵌一个对话 Agent，同时把能力开放为 MCP"成为 2025–2026 年的通行做法**（CoLab Operator，Helium 10 的 Helium AI Agent 与 MCP，Zoo-MCP，Propel MCP，Teamcenter Copilot，First Resonance ION Intelligence）。这印证了 PDOS 单一小Pai加 MCP 连接器的路线（v1.1:86、v1.1 §06.2）。值得补的是：把 Helium 10、卖家精灵这类数据源作为只读 MCP 或导入源纳入准入清单。
7. **中国消费电子品牌的公开实践**：据 AWS 撰写的案例（2025-09），安克在 Bedrock 上接入 Claude，开发了需求生成、产品文档、VOC 洞察、代码审核等 Agent，研发 Agent 代码采纳率超过 50%（合作方宣称），AIME 平台上有 300 多个活跃 Agent；安克以亚马逊评论驱动迭代的 VOC 做法由来已久。**最值得 PDOS 吸取的反面教训**是安克 2025 年的移动电源召回：据台湾媒体引述安克台湾的声明，起因是电芯供应商擅自变更材料。PDOS 目前**没有供方变更（PCN）入口**（v1.1 全文"PCN"出现 0 次，"供应商变更"出现 0 次）。锂电充气泵受 UN 38.3 和 EU 2023/1542 约束，这个缺口优先级高。
8. **用户期待（信号）**：IoT Analytics 2026 年报告显示，87% 的制造企业期望 AI 内置在 CAD/PLM 里，但对 AI 做零件设计或选型决策的高信任只有 13%，"完全信任"在所有任务上都不超过 3%。提高信任的条件依次是可解释、结果可核验、追溯到需求、PLM 中的改动可审计可回滚。这几条几乎逐条对应 PDOS 已有的设计：引用片段可核、运行回执、按运行撤回、资格按"技能包 × 模型版本"授予（v1.1 §06.12）。

---

## 1. 工具速览表

| 工具 | 环节 | 输入 | AI 输出 | 是否直接进受控对象 | 人如何确认 | 成熟度 |
|---|---|---|---|---|---|---|
| CoLab ReviewAI / AutoReview / Operator | 设计评审 | 2D 图纸、3D CAD（Creo、NX 推送）、企业标准（PDF、Excel、SharePoint）、历史评审意见；2026-07 起含 ISO 标准 | 3D 视图中的定位标注和文字意见，作为可跟踪 issue 存储；援引标准；Operator 对话分析 | 否，意见是评审工作项 | 工程师处置意见；"不替代决定" | ReviewAI 2024-11 发布；AutoReview 2025-06 发布（TTI、TPI 曾参与 beta）；AutoReview 2.0 与 3D DFM 检查 2026-07；Operator 早期访问 |
| Instrumental | 试产 / 量产质量 | 每台单元在关键工位的图像（RGB、AOI、X 光）、功能测试、测量值、返修数据 | 异常检测、缺陷发现与分类、跨源关联排出可能根因、从历史图像追溯测量 | 否，进入问题调查；可对接 Teamcenter Quality 的 8D/CAPA（2023 年合作） | 用户反馈改进模型；正式结论由工程师作出 | GA（2015 年起） |
| First Resonance ION + ION Intelligence | 制造执行 / 质量 | 工单、库存、质量记录 | 半自主"工作流 Agent"（生产、供应链、质量） | 发布稿未说明 | 只说"制造商可理解、批准、扩展 AI 决策"；新界面有审计日志 | ION 自 2021 年 GA；Intelligence 于 2025-06 发布，细节不透明 |
| Cofactr | 电子料采购 | BOM | Ailana AI 清洗（无匹配料、合并重复、包装核对），逐行替代料建议；生命周期、合规、货源风险提醒；生成 RFQ/PO | 替代料须**逐条接受或拒绝**；未批准的变体即使有货也显示"需 RFQ" | 每行接受或拒绝 | GA；2025-10 推出零前期费用的采购到交付服务 |
| LightSource | 直接物料寻源 | 多层 BOM、工程图、各供应商格式的报价、品类成本模型 | 规范化 BOM、RFX、报价归一（单位、币种、价格结构）、应该成本模型、授标方案、关税暴露分析 | 不替代 ERP/PLM，叠加在 SAP、Oracle 之上 | 由人选择授标方案；未见正式审批流 | GA（偏大企业）；节省 3–25%、部署约 30 天均为厂商宣称 |
| Jiga | 定制件寻源 | 图纸、规格、沟通记录 | 从图纸抽要求、汇集沟通上下文、提前标风险；供应商 1–2 天给出真实 DFM 反馈和报价（明确不做"黑箱即时报价"） | Jiga 作为供应商签约方下单 | 工程师选供应商 | GA；2025-11 完成 A 轮 |
| Leo AI | 机械工程助手 | 文字、草图、规格；可连 SolidWorks PDM、Vault、Windchill、Teamcenter、Arena | 带出处的工程问答、零件检索（文字找件、CAD 找相似件）、设计计算、文字生成装配体 | 否 | 零件配合须手动完成 | 问答与检索 GA；装配体生成约 2026-03，属研究预览 |
| Flux | PCB 设计 | 提示词、原理图 | 先出计划→用户批准→执行；Copilot 选料、连线；自动布局；执行中跑 ERC/DRC | 修改须经批准后才在编辑器执行 | 计划可修改或整体拒绝 | GA；自动布局只适用简单到中等复杂度 |
| Quilter | PCB 布局 | 原理图与约束 | 并行生成数十个候选布局，按可制造性和约束覆盖排序 | 否，候选回到 Altium/Cadence/Xpedition | 工程师选择候选 | 2025-08 推出免费档；4 小时出可投板设计等为厂商宣称 |
| Zoo（Text-to-CAD / Zookeeper） | 机械 CAD 生成 | 提示词、现有项目 | KCL 代码与 B-Rep；能执行、截图、算质量和体积并自查 | 否 | 用户迭代修改 | Text-to-CAD 2023-12；Zookeeper 2026-01，厂商自称 early |
| CELUS | 电子方案 / 原理图 | 功能需求、电气/环境/机械/成本约束；图片或文字 | 架构、原生 ECAD 原理图、BOM、封装 | 否，导出到 KiCad、Altium、Eagle | 工程师在 EDA 中继续 | GA（2024 年起报道较多）；"20 分钟出原理图"为演示数据 |
| Nominal | 测试数据 | 遥测、日志、视频、仿真、HIL 数据 | 检查清单应用到 Run，定位失败时间段；趋势和自动报告（公开材料未强调 AI） | 违规逐条处置 | 每条违规由人选"可忽略"或"需处理" | GA；2025-06 B 轮，2026-03 估值 10 亿美元 |
| Bild（Meru） | PDM / 变更 | CAD 文件、版本 | Delta：版本间几何、特征、装配差异（文字加图）；Echo：语义检索与查重；Sigma：起草发布说明和 ECO 摘要 | 否 | 人编辑 ECO | PDM 为 GA；Sigma 曾标"即将推出" |
| Partful | — | — | 未检索到同名 AI 采购或硬件工具；同名英国公司做制造设备 3D 目录（2023） | — | — | 未核实；相近产品有 PartGenie（2025-11 上 Product Hunt）、QTex PartWise |
| Duro Design | AI-native PLM | CAD、BOM、供应数据 | AI 校验、影响分析、元数据补全、寻源数据前置、BOM 清理 | 走变更单审批流 | 可配置校验规则（UI、YAML、GraphQL） | 2025-06 重新发布；缺技术细节 |
| Siemens Teamcenter Copilot / AI BOM Agent | PLM | 自然语言、BOM 结构与版本、变体、有效性规则 | 识别要改的零件、发起 ECN、列受影响装配、比较备选、执行跨引用更新 | 在现有变更流程和权限内执行"已批准动作" | **BOM 更新前须人确认** | Copilot 自 2406 起；BOM Agent 博客 2026-06，未写版本号 |
| PTC Arena AI Assistant / AI Engine；Onshape AI Advisor | PLM / QMS / CAD | Arena 帮助库、文件 | 按 ECO、CAPA 操作的分步指引；AI 文件摘要与对比（服务变更管理） | 否 | — | Arena 助手 2025-09；Onshape 顾问 2025-04 推出，2025-10 内嵌到设计环境 |
| Propel One | PLM / QMS | 产品主线数据、附件 | ECO、CAPA、NCR 摘要，附件问答，缺信息时自动派任务 | — | — | 2025-10 首批客户；基于 Salesforce Agentforce |
| Fictiv 自动注塑 DFM | 报价前 DFM | 3D 零件 | 拔模角色标、壁厚热图、倒扣、初步分型线 | 否 | 工程师据此修改设计 | GA（2025-07 报道） |
| Vizcom | 工业设计 | 手绘草图、提示词 | 写实渲染、动画；粗网格（**不能**交给 CAD 或制造） | 否 | 设计师选方案 | GA；2025-10 B 轮 |
| 华秋 KiCad Copilot、嘉立创 EDA 社区 MCP 桥 | 国内 EDA | 原理图 | 解析整份图纸，识别核心器件和总线；社区插件做选型与局部编辑 | 否 | — | 华秋为 2026-03 发布稿；嘉立创相关为社区 0.0.x 测试版，作者提醒只在可丢弃环境中使用 |
| Jungle Scout AI Assist | 电商研究 | ASIN | 评论正负主题、改进建议、竞品对比；listing 生成 | 否 | — | GA（2023-09） |
| Helium 10 | 电商研究 | 账号数据、关键词、评论 | Listing Review Insights（Diamond 档）；Helium AI Agent；**Helium 10 MCP（2026-07-16，Diamond 专享）** | 否 | — | GA；2025 年底有卖家称评论洞察质量下降（未证实） |
| 卖家精灵 AI 评论分析 1.0 / 2.0 | 电商研究 | 亚马逊评论（单次约 500 条，每星级约 100 条） | 画像、优劣势、使用场景、预期、购买动因；2.0 增加主题、正负分歧、用户旅程，并有"证据抽屉"回查原话 | 否 | 官方定位为"产生待验证假设" | 1.0 于 2025-10；2.0 约 2026-09 |
| Amazon Product Opportunity Explorer / Customer Review Insights / VOC 看板 | 平台官方 | 搜索、点击、购买数据；近 6 个月评论；退货与 NCX | 主题对星级的影响、片段、趋势；2025 年新增"未满足需求洞察"和"细分品类概览"；Seller Assistant Agent | 否 | VP 表态"最终决定由卖家掌控" | GA；AI 增强于 Accelerate 2025 发布，区域可用性未核实 |
| Shulex VOC.AI | VOC | 多平台评论 | 按功能、可用性、服务打标签；提供 API | 否 | — | GA；"超 10 亿条评论""安克是客户"均为厂商宣称 |
| 魔镜洞察 CMI | 国内电商与社媒洞察 | 天猫、京东、抖音、Amazon 等电商数据，小红书、B 站等社媒数据 | 评论方面分类、情感、观点挖掘；高增长概念、赛道、品牌筛选；分析助手 copilot | 否 | — | GA（服务对象含研发部门） |
| Alibaba.com Accio、1688 遨虾 / AI 找厂 | 寻源 | 产品概念、图片、链接、自然语言需求 | 开发计划、批量向供应商发 RFQ；以图找国内源头工厂，提示目标市场合规风险 | 否（外部平台） | — | Accio 为 GA（据报道 9 个月 200 万用户）；遨虾 2025-09 内测、约 2025-11 上线 |

---

## 2. 分环节详述与对充气泵企业的意义

### 2.1 设计评审、DFM 与工程知识

**CoLab**
- **AI 所在环节**：设计评审的"第一遍同行检查"。ReviewAI（2024-11）先找相似图纸和模型，把历史评审中的技术意见带进本次评审。AutoReview（2025-06）读取原生 CAD 和工程图，对照团队自己的标准（PDF、Excel、SharePoint 均可）和历史评审反馈检查设计，在 3D 视图中定位问题并附意见，意见作为可跟踪 issue 保存。AutoReview 2.0（CoLab 4.0，2026-07-09）把覆盖范围扩到尺寸、公差、GD&T、BOM 一致性，并新增机加、钣金、**注塑**的 3D 可制造性检查。同月宣布与加拿大标准委员会合作，可对照 ISO 标准（几何、公差、表面、边缘、焊接）检查并援引条款，可用范围未说明。
- **人如何确认**：CoLab 的定位是"把判断留给工程师"，CoLab 4.0 的标题就是"为人类决策者而建"。公开资料没有写明"接受或拒绝意见后如何反哺规则"。
- **客户信号**：TTI（Ryobi 母公司，总部香港，在中国有大量制造）参与过 AutoReview beta。TTI 也做无绳充气泵，是与本项目用户**同业、同供应链地区**的参照。
- **厂商宣称**：受访工程领导者中 95% 认为须在 12–24 个月内采用 AI，预期评审提速约 2.8 倍（CoLab 委托的调研）；一个典型工程组织一年评审 35,000 多张图纸。
- **对充气泵的用处**：外壳和气缸等注塑件的拔模、壁厚、倒扣，气嘴螺纹和公差，按键与 USB 口的防水结构，都可在试模前做第一遍自查。前提是企业有自己的检查清单和历史 8D 经验。**中小企业未必买得起或用得上 CoLab，但"按企业清单加历史教训做第一遍检查、意见逐条处置"这个模式可以直接搬进 PDOS。**

**Leo AI**：带出处的工程问答（厂商称基于 100 万份书籍、标准和数据手册），连接主流 PDM 做"文字找件、CAD 找相似件"。文字生成装配体约在 2026-03 推出，零件配合仍须手动。G2 上有评论希望标准覆盖更广。对中小企业的价值主要在**查重复零件和带出处的计算或标准问答**，生成功能尚不可靠。

**Bild（Meru）**：Delta 比较两个 CAD 版本，列出几何、特征、装配层级的变化；Echo 做语义查重；Sigma 起草 ECO 摘要。对应 PDOS 的工程变更：同一结构件从 v3 改到 v4 时，"改了什么"可自动列出供评审核对。

**Siemens Teamcenter AI BOM Agent（2026-06 博客）**：理解 BOM 的 Agent 能识别要改的零件、发起 ECN、找出受影响的装配并比较备选，**BOM 更新前须人确认**，在原有变更流程和权限内执行。**这与 PDOS `change_control` 的分栏（显式影响 `explicit_impact` 由计算工具给出、`ai_leads` 标 `ai_hypothesis`）高度一致**，可视为大厂对 PDOS 路线的印证。

**PTC Arena AI Assistant（2025-09）/ AI Engine**：前者是按帮助库给 ECO、CAPA 操作指引的对话助手，后者做 AI 文件摘要和**文件对比**，用于变更管理。**Onshape AI Advisor** 是 CAD 内的操作指导。这类"教人怎么用系统"的助手价值有限，PDOS 不必效仿。

**Duro Design（2025-06）/ Propel One（2025-10）**：自称 AI-native PLM，功能是 AI 校验、影响分析、BOM 清理，以及 ECO、CAPA、NCR 摘要与缺信息自动派任务。公开资料缺技术细节，只能参考其功能清单。

**Fictiv 自动注塑 DFM（2025-07）**：在**报价前**即时给出拔模角色标、壁厚热图、倒扣和初步分型线，改变了"DFM 在报价后数周才回来"的节奏。对充气泵的启示：模具 DFM 前移到结构评审阶段，PDOS 可以记录"DFM 结论来自哪个工具或哪家模厂、针对哪个版本"作为证据。

### 2.2 电子与机械设计生成（以观察为主）

- **Flux**：最值得借鉴的是交互模式而非生成质量。先出计划，用户可改可整体拒绝，批准后才执行，执行中跑 ERC/DRC（官方入门文档和 2026 春季更新）。自动布局官方只推荐简单到中等复杂度的板子，关键线和高速线由人走。
- **Quilter**：基于物理和强化学习、"不是 LLM"，并行生成数十个候选并排序。时间压缩数字（从 30 天以上到 24 小时以内等）均为厂商宣称。
- **CELUS**：从需求和约束出发选料，导出原理图、BOM、封装到 KiCad、Altium、Eagle。
- **Zoo Zookeeper**：写 KCL 代码、执行、截图、算质量属性并自查，厂商自称 early，无评测结果。
- **国内**：华秋 2026-03 发布 KiCad Copilot（新闻稿）；嘉立创 EDA 只有社区 MCP 桥接项目（0.0.x 测试版）。
- **对充气泵的意义**：充气泵控制板（MCU、压力传感器、电机驱动、锂电 BMS 和充电）属于中低复杂度，国内企业多用嘉立创 EDA 或外包。这些工具可提升原型阶段效率，但**产物权威仍在 EDA/CAD 和工程师手里**。PDOS 只需按 v1.1:1216 的边界记录"引用加版本"，不应自建生成能力。

### 2.3 采购、报价与供应链

- **Cofactr**：BOM 上传后自动做 AI 清洗，"识别替代料"对每行给出建议，用户**逐条接受或拒绝**；未批准的变体即使分销商有货也显示"需 RFQ"。这正是 PDOS `AlternateQualification`（v1.1:717，"不允许模型因参数相近直接替料"）在产品层面的成熟实现。
- **LightSource**：把各供应商格式不一的报价归一（单位、币种、价格结构），建应该成本模型，模拟单一、多家、拆分授标方案，分析关税暴露；明确叠加在 ERP/PLM 之上、不替代。
- **Jiga**：从图纸抽要求、汇集沟通上下文、提前标风险；**明确反对黑箱即时报价**，由真实供应商 1–2 天内给 DFM 反馈和报价。
- **Paperless Parts Wingman**：从报价包抽关键信息，帮估价员不漏项。**Xometry** 即时报价引擎用 ML 从 CAD 推价格和交期（2023 年资料）。
- **Accio / 1688 遨虾 / AI 找厂（中国）**：从产品概念到开发计划再到批量 RFQ；以图找国内源头工厂（会筛小批量出口、跨境服务能力、响应速度），并提示目标市场的认证和环保风险。"选品报告从 100 分钟缩到 1–2 分钟"是产品负责人说法。
- **对充气泵的用处**：模具（多套外壳和气缸模、模穴数、模具寿命、含不含试模费）、电机（铜线或铝线、额定和堵转电流）、电芯（品牌、容量、UN 38.3 报告）、数显表头、软管和气嘴的多家报价，通常是 Excel、PDF 或微信截图，**口径极不统一**。"抽取、按口径归一、确定性比价、人定方案"直接节省工程和采购的反复核对时间，也让 CostEstimate（v1.1:719）有可追溯的报价来源。

### 2.4 制造、测试与质量数据

- **Instrumental**：在关键装配工位采图，形成每台单元可追溯的记录；Discover 做异常检测，关联功能会对图像、测试、过程信号排序出可能根因；能从已有图像追溯测量尺寸，不必重测；有"新 CM/JDM 伙伴"用例，跨工厂保持一致标准。厂商宣称：Meta 在 7 个项目上节省 900 多个工程周，NVIDIA 整机构建提前最多 14 天。2023 年与 Siemens 合作，把洞察接入 Teamcenter Quality 的 8D 和 CAPA。
- **Nominal**：把检查清单应用到 Run，查看失败时间段，**每条违规由人决定可忽略或需处理**，支持批量多清单多 Run 和通知。这是规则化的确定性审查，公开材料未把 AI 作为卖点。
- **First Resonance ION Intelligence（2025-06）**：生产、供应链、质量的半自主 Agent，"工作流提速最高 10 倍"为厂商宣称；输入输出、是否写受控记录、审批机制都没公开。**说明制造执行领域的 Agent 宣传多于实证。**
- **对充气泵的用处**：试产和量产测试主要是功能曲线和数值，例如充气时间（种子字典 `fill_time_full`，0→36 psi）、最大压力、自由流量、噪声（dB(A) @1 m）、压力显示精度、电池容量和能量（`docs/design/category-seeds/auto-tire-inflator.md`）。Nominal 式"清单 × Run × 逐条违规处置"能让品质判定可追溯；Instrumental 式"跨数据源关联"能把"噪声超标"关联到电机批次、气缸润滑工序或某个模穴，作为根因假设交给 `quality_issue`。外观缺陷的图像 AI 需要硬件和长期训练，中小企业可后置。

### 2.5 品类与电商研究

- **卖家精灵**：1.0 版（2025-10）基于全量评论提炼 6 个维度；2.0 版（约 2026-09）做成可追溯的结构化反馈，有证据抽屉回查买家原话。**明确披露样本限制**：单次约 500 条、每个星级约 100 条，"样本分布不等于全部评论的评分结构"。官方明说评论分析适合产生待验证的假设，不能单独判断一个产品是否值得做。
- **Amazon**：Customer Review Insights（2022 年起）按正负主题分桶，给出片段和**每个主题对星级的影响**，有 6 个月趋势，后来加了父 ASIN 汇总。Opportunity Explorer 在 Accelerate 2025 加了 AI：未满足需求洞察（识别"搜得到但买不到"的空白，生成提案和需求预测）、细分品类概览（功能、价格、搜索量基准）。Seller Assistant 定位为 Agent，"卖家掌控最终决定"。VOC 看板（NCX）按 ASIN 标出退货和差评原因；第三方指南提醒：**做 AI 归类时要固定类目表，否则模型每批都会造新标签，数字无法累计**。
- **Jungle Scout / Helium 10**：评论正负主题和改进建议是基础功能（2023 年起）。Helium 10 在 2026-07 推出 MCP，把关键词、广告、利润、库存、选品、listing 分析开放给 Claude、ChatGPT 等外部 Agent（Diamond 档专享）。有卖家称其评论洞察在 2025 年底质量下降（社区说法，未证实），提醒**第三方 AI 洞察质量会漂移**。
- **Shulex VOC.AI**：多平台评论打标签并提供 API。厂商称安克有 100 多名产品经理在用它监控 35,000 多个产品，此前人工每天只能打 200 条标签，退货率降低 40% 以上（均为厂商宣称）。
- **魔镜洞察 CMI**：整合国内电商（天猫、京东、抖音）、海外电商（Amazon、TikTok 等）和社媒（小红书、B 站、得物），做评论方面分类和情感分析，筛选高增长概念、赛道、品牌，有分析助手 copilot，服务对象包括产品研发部门。**数说故事**把能力封装成人群洞察、产品分析等智能体，2026-07 递表港交所。
- **对充气泵的用处**：自主品牌做 Amazon 和国内电商时，竞品评论痛点（如"显示压力不准""噪声大""充一次只能打两条胎""气嘴拧不紧漏气"）是立项规格的直接输入；OEM/ODM 客户的退货原因则是派生迭代的输入。**PDOS 的严谨口径已领先，弱项在数据进入**：卖家后台数据只能导出或经 MCP 获取，还需要记录抽样方式（样本上限、星级配额、时间窗）。

### 2.6 中国消费电子品牌实践

- **安克（AWS 撰写，钛媒体 2025-09-04）**：基于 Amazon Bedrock 接入 Claude，研发侧有需求生成、产品文档、VOC 洞察、代码审核、AI 运维等 Agent，研发 Agent 代码采纳率超过 50%；AIME 平台沉淀 300 多个活跃 Agent，覆盖研发、客服、营销、供应链。**文章未说明各 Agent 的输入输出和人工审核机制**，数字由合作方提供。
- **安克 VOC 传统**：媒体报道称阳萌早年专门开发系统抓取和分析评论来判断需求，"好评看需求、差评看痛点"。
- **安克 2025 召回（反面教训）**：PowerCore 10000 等多款移动电源全球召回。安克的全球通告说"单一电芯供应商的电芯不符合更新后的内部标准"；台湾媒体引述安克台湾称，是**供应商擅自变更了电芯材料**，可能导致隔膜绝缘失效、过热。后续据报道更换了电芯供应商。**这说明供方变更通知、来料关键特性复核、已签核证据的适用性失效，对锂电类消费电子是生死问题。**
- **TTI**：参与 CoLab AutoReview beta，说明华南和香港的消费硬件大厂已在试 AI 设计评审。

---

## 3. 跨产品模式

1. **按企业自有标准做第一遍检查，人逐条处置**：CoLab AutoReview，Nominal 检查清单，Fictiv 自动 DFM，Arena AI 文件对比。
2. **先出计划、人批准、再执行，执行中有确定性校验**：Flux 规划模式，Teamcenter BOM Agent 的人在环确认，Amazon Seller Assistant 的"最终决定在人"。
3. **逐行接受或拒绝的 AI 建议**：Cofactr 替代料，CoLab 意见作为 issue。
4. **把乱格式文件归一成可比较的结构化行**：LightSource 报价归一，Paperless Wingman，Jiga 图纸要求抽取，Cofactr BOM 清洗。
5. **证据可回查、样本可见的 VOC**：卖家精灵证据抽屉与样本上限，Amazon 片段与星级影响，Shulex 打标签。
6. **跨数据源关联产出根因假设，进 8D/CAPA**：Instrumental 与 Teamcenter Quality，Propel 的 CAPA/NCR 摘要。
7. **确定性或物理引擎负责正确性，AI 负责编排和解释**：Quilter 物理优先，Zoo 执行 KCL 并算质量属性，Nominal 规则清单，LightSource 应该成本模型。
8. **业务系统内嵌对话 Agent，同时开放 MCP**：CoLab Operator，Helium AI 与 Helium 10 MCP，Zoo-MCP，Propel MCP，Teamcenter Copilot，ION Intelligence。
9. **版本差异摘要服务变更单**：Bild Delta 和 Sigma，Arena AI 文件对比。
10. **经验复用和查重**：ReviewAI 带出历史意见，Bild Echo 与 Leo 查相似件，CoLab 4.0 的知识沉淀工具。
11. **从概念直接扇出到供应商 RFQ**：Accio，1688 遨虾与 AI 找厂，Jiga。

---

## 4. 用户期待信号

- 87% 的制造企业期望 AI 内置在 CAD/PLM/ALM 里成为标配；但高信任比例分别只有：文档和规格 24%，仿真输入 17%，验证与确认 16%，**零件设计或选型决策 13%**；"完全信任"在任何活动上都不超过 3%。61% 认为可解释性能提高信任。其他条件包括结果可核验、追溯到需求、PLM 中的改动可审计且能回滚。信任高低随后果轻重而变（IoT Analytics《Design & Engineering Software Adoption Report 2026》，样本 120 家制造企业）。
- 产品工程领导者在审慎扩大 AI 使用，优先看验证、可衡量结果和一次做对（MIT Technology Review Insights，2026-03，300 人，二手转述）。
- 42% 的工程师已把 AI 用进项目，中国工程师最积极（Avnet Insights，2025-02，1,204 人）。
- 95% 的工程领导者认为须在 12–24 个月内采用 AI，预期评审提速约 2.8 倍（CoLab 委托调研，厂商立场）。
- 卖家精灵官方：评论分析适合产生待验证假设，不能单独判断产品值不值得做；并明确披露样本上限。
- 第三方指南：AI 归类退货原因须固定类目，否则数字无法累计（SellerLabs）。
- 卖家社区称 Helium 10 评论洞察在 2025 年底质量下降（社区说法）：用户会察觉 AI 洞察的质量漂移。
- Jiga 主打"非黑箱即时报价、真实供应商给 DFM"：工程师对黑箱 AI 报价不信任。
- Quilter 自我定位"不是 LLM、物理优先"：对物理正确性，用户更信任确定性或物理引擎。
- Amazon 副总裁说 Agent 可以代卖家行动，但"你仍掌控最终决定"；CoLab 说 AutoReview "让工程师做工程师该做的事"。
- Leo AI 的 G2 评论看重"引用真实标准并给出处"，同时希望覆盖更广。
- 安克 AWS 案例以"代码采纳率超过 50%、300 多个 Agent"等可量化指标宣传：管理层期待 AI 带来可度量的净减负。

---

## 5. 对 PDOS 的映射：已领先之处、缺口与建议

### 5.1 PDOS 已持平或领先的地方（可作为对外卖点）

| PDOS 设计 | 竞品对照 |
|---|---|
| 竞品库区分实测、宣传、推断、未知，报价注明口径（v1.1:328）；`competitor_comparison` 和 `price_band` 的数值比较交给计算工具 | 电商工具普遍不区分宣传值和实测值，价格口径不统一 |
| 用户声音由 AI 归类并显示样本量（v1.1:329）；`review_pain_clustering` 的条数和占比由代码算，可沿用已有分类，每类有可核片段和判别规则 | 卖家精灵 2.0 证据抽屉，Amazon CRI 片段；PDOS 多了"代码算数字、模型不写数字"，并关联到参数版本 |
| AI 推测与显式依赖分栏（v1.1:739），`change_control` 中 `ai_leads` 标 `ai_hypothesis` | Teamcenter AI BOM Agent 的人在环确认（2026-06），PDOS 的约束更明确 |
| AlternateQualification 不许模型因参数相近直接替料（v1.1:717） | Cofactr 逐条接受或拒绝替代料 |
| CostEstimate 由确定性引擎计算，AI 解释敏感项（v1.1:719） | LightSource 应该成本模型 |
| `quality_issue` 的假设固定标 `ai_hypothesis`，根因由专业本人确认 | Instrumental 只给"可能根因" |
| 单一小Pai加 MCP，管理员准入、逐项授权、外部写入按 T2（v1.1 §06.2） | CoLab Operator、Helium 10 MCP、Propel MCP 的方向一致，PDOS 的权限分级更细 |
| T0 资格按"租户 × 技能包 × 模型版本"授予，持续抽检（v1.1 §06.12） | 对应 IoT Analytics 报告中"可审计、可回滚、经验证的领域模型"等信任条件 |

### 5.2 缺口与建议（按对充气泵中小企业的业务价值排序）

**高优先**

1. **供方变更（PCN）入口和证据失效联动**。
   - 现状：`change_control` 的变更根对象是规格条目、零件、接口、工序等内部对象；v1.1 全文没有 PCN 或供方变更的概念。
   - 建议：增加"供方变更通知"作为变更来源，例如电芯、电机、气缸材料、润滑脂的变更。把它关联到受影响的零件、配置、Build 和已签核测试，按 v1.1 §03.12 让已签核证据失效，并生成来料复核的 VerificationRequest。AI 只做两件事：从供方邮件或通知中抽取变更要素（T0 草稿），以及列出待核影响线索；是否接受变更由品质和工程本人决定（T2）。
   - 依据：安克 2025 年召回的起因据报道是供应商擅自变更电芯材料；锂电充气泵要承担 UN 38.3 和 EU 2023/1542 的持续合规义务。
2. **设计与 DFM 第一遍自查技能包（建议命名 `design_precheck`）**。
   - 现状：17 个技能包中没有设计评审或 DFM 类；v1.1:669 允许按风险选用 DFM，但没有对应的 AI 办理路径。
   - 建议：在结构评审和试模前 VerificationRequest（v1.1:681）之前，按三类依据检查：企业检查清单（注塑拔模、壁厚、倒扣、螺纹、密封等）、已发布的经验规则（S5 中"经验候选→具名规则"的产物），以及规格字典和 BOM 的一致性。先做文本和表格层面（图纸标注、技术要求、BOM 与规格是否一致），不做 CAD 几何分析。输出带定位的意见作为 T0 草稿或 T1 建议问题，由工程师逐条处置（采纳、不采纳加理由、转问题），处置结果回流为经验候选。
   - 依据：CoLab AutoReview 2.0、Fictiv 自动 DFM。
3. **供应商报价抽取与归一（建议命名 `supplier_quote_extraction`）**。
   - 现状：`rfq_extraction` 只处理客户 RFQ。
   - 建议：新增供应商报价侧的对应技能，把模具、电机、电芯、表头等报价（Excel、PDF、截图）逐行抽取，记录币种、含税运、MOQ、阶梯价、模穴数、模具寿命、交期、有效期和原文位置，并关联到零件或模具对象。比价和价格带交给确定性计算（复用 calc 风格），授标由人决定。PDOS 只记录"依据哪版报价作了什么决定"，不建 PO（ERP 边界，v1.1:1216）。
   - 依据：LightSource、Paperless Wingman。
4. **测试 Run 的检查清单与逐条违规处置，以及跨 Run 关联候选**。
   - 现状：`test_verification` 已经导入实测结果并交确定性工具判定。
   - 建议：补"同一测试模板 × 多个 Run"的检查清单视图。每条违规由具名的人选择"可忽略（附理由）"或"建问题"，后者直接进入 `quality_issue`。AI 只做跨 Run 和跨批次的关联候选，例如把噪声超标关联到电机批次或某个模穴，标为 `ai_hypothesis`。外观图像 AI 后置。
   - 依据：Nominal 数据审查、Instrumental 关联分析。

**中优先**

5. **电商与卖家后台数据的标准导入模板，以及只读 MCP 准入**。
   - 建议：为卖家精灵、Helium 10、Jungle Scout 的导出文件，以及 Amazon VOC 看板和退货报告，定义导入映射。导入时必须记录抽样元数据：样本上限、星级配额、时间窗、站点、导出时间、工具和版本。`review_pain_clustering` 输出时显示"样本非全量"。Helium 10 MCP 一类可作为管理员准入的只读连接器（§06.2）。数据进入时去除个人信息（参考 SellerLabs 的做法）。
   - 依据：卖家精灵 2.0 的样本披露、Helium 10 MCP。
6. **售后和退货 VOC 到 Field 反馈的闭环与趋势提醒**。
   - 现状：v1.1:753 要求 Field 反馈关联批次和配置。
   - 建议：把 ASIN 或批次的退货原因、差评主题按固定分类（沿用 `existing_labels`）做周期统计，通过 AutomationRule（v1.1 §06.4）在主题突增时生成"问题候选"，不直接建单；无法定位到配置时保持未知。
   - 依据：Amazon Review Trends 和 VOC 看板，安克产品经理监控产品的做法。
7. **变更单的文件版本差异摘要**。
   - 建议：ECO 引用的规格书、图纸说明、SOP 有前后两个 artifact 版本时，先用确定性文本差异，再由 AI 解释差异（带引用），帮助评审和客户承认外发时核对"改了什么、没改什么"。
   - 依据：Bild Delta 和 Sigma、Arena AI 文件对比。
8. **新项目启动时主动带出相似历史问题**。
   - 建议：G0 后建项目时，按品类、平台、参数版本检索同品类历史问题、8D 和已发布经验规则，作为"注意事项"推给项目负责人（只读、带引用）。
   - 依据：CoLab ReviewAI、Leo 查重。

**低优先 / 不建议做**

9. **供应商发现**（Accio、1688 遨虾）：可作为 `public_research` 的一种来源类型，产出"候选供应商清单"（`ai_draft`）。不得把客户资料带到这些平台。SRM 和准入仍在外部。
10. **text-to-CAD、AI PCB 布局、AI 原理图、AI 渲染**（Zoo、Leo 装配体、Flux、Quilter、CELUS、Vizcom、华秋、嘉立创）：**不自建**。最多支持"外部 AI 工具产物作为 artifact 版本挂到提案方案对比或工程对象上"，并标注来源工具。Vizcom 渲染图可作为立项方案对比的外观示意（要标为示意，不是设计输入）。
11. **"系统操作指引"类助手**（Arena AI Assistant、Onshape AI Advisor）：PDOS 的小Pai已是办理型 Agent，不需要另做帮助型助手。

### 5.3 对 PDOS 设计的风险提示

- **第三方 AI 洞察会漂移**（Helium 10 的社区反馈）：导入的第三方"AI 摘要"只能作为 `imported` 的推断性来源，不得当作评论原文；尽量导入原始评论，由 PDOS 自己归类。
- **抽样偏差**：卖家精灵每次约 500 条且每星级上限约 100 条，Amazon CRI 只看近 6 个月；混用时占比不可直接合并，按 v1.1 §08.11 的口径规则分组。
- **制造执行领域的"Agent 提速 10 倍"一类宣传缺乏可验证细节**（ION Intelligence）：PDOS 对外宣传应坚持 v1.1 §09.4 的维度化评估和净减负口径。

---

## 6. 证据局限

- CoLab、Instrumental、LightSource、Cofactr、Quilter、Leo、Bild、Duro、Propel 的效果数字全部来自厂商或其投资方，未见独立评测。
- 安克 Agent 实践来自 AWS 撰写的授权文章；安克与 Shulex 的合作来自 Shulex 自述（原页面抓取时返回 404，内容依据检索摘要）。召回的"擅自变更材料"说法只有台湾媒体引述安克台湾这一个来源，全球通告措辞不同。
- 卖家精灵 2.0 正文抓取被截断，细节依据检索摘要（官方知识库）。
- First Resonance ION Intelligence、Nominal 的 AI 能力公开材料很少；Partful 未检索到可核实的同名 AI 工具。
- 部分来源（Flux、Zoo、Nominal 文档）抓取时连接中断，依据检索结果中的官方文档摘要。

---

## 7. 来源

**硬件研发与制造**
- CoLab：[ReviewAI 发布报道（2024-11）](https://www.electronicsworld.co.uk/?p=37868)；[ReviewAI 资金（2025-03）](https://www.businesswire.com/news/home/20250319968594/en/CoLab-Secures-5.6M-From-the-Hibernia-and-Hebron-Projects-to-Create-Local-Artificial-Intelligence-Talent-and-Accelerate-ReviewAI-Roadmap)；[CoLab 4.0（2026-07-09）](https://www.colabsoftware.com/post/colab-launches-4-0-built-for-human-decision-makers-in-an-ai-first-world)；[ISO 标准接入（2026-07-23）](https://www.01net.it/colab-brings-iso-standards-into-ai-powered-drawing-review/)；[C 轮与 AutoReview 时间线](https://pulse2.com/colab-72-million-series-c-raised-to-advance-ai-for-engineering-design-workflows)；[AutoReview 产品页](https://www.colabsoftware.com/product/autoreview)；[CoLab 委托调研](https://www.intelligentcio.com/north-america/2025/08/20/ninety-five-per-cent-of-engineering-leaders-say-design-teams-must-adopt-ai-within-two-years-survey-finds/)
- Instrumental：[NPI 页面](https://instrumental.com/accelerate-your-npi-programs/)；[Discover Relationships](https://instrumental.com/?p=1918)；[Siemens 合作（2023）](https://news.siemens.com/ja-jp/instrumental-teamcenter-quality-partner)；[CB Insights](https://www.cbinsights.com/company/instrumental)
- First Resonance：[ION Intelligence 发布稿（2025-06-24）](https://firstresonance.io/press/first-resonance-reshoring-manufacturing)；[Tech-Clarity 分析](https://tech-clarity.com/ion-ai-ux-marketplace/22209)
- Cofactr：[替代料逐条接受或拒绝（支持文档）](https://support.cofactr.com/articles/9453337607-choosing-an-alternate-and-why-it-makes-purchasing-easier)；[电子采购说明](https://www.cofactr.com/articles/why-generic-procurement-software-doesnt-work-for-electronic-hardware)；[采购到交付服务（2025-10）](https://www.businesswire.com/news/home/20251030380894/en/Cofactr-Democratizes-their-Complete-Procure-to-Ship-Automation-Service-at-a-Pivotal-Moment-for-US-Unlocking-Support-for-Agile-Hardware-Manufacturers-in-Americawith-No-Upfront-Costs)
- LightSource：[官方产品事实页](https://lightsource.ai/llm-info)；[Lightspeed 投资说明](https://lsvp.com/stories/reinventing-direct-sourcing-announcing-lightspeeds-investment-in-lightsource/)
- Jiga：[与即时报价的对比](https://jiga.io/articles/jiga-vs-rapiddirect-cnc-machining-comparison/)；[A 轮（2025-11）](https://www.supplychaindive.com/press-release/20251119-jiga-secures-12m-series-a-to-eliminate-hardware-sourcing-bottleneck-threat/)
- Leo AI：[装配体生成](https://www.engineering.com/leo-ai-can-now-generate-full-cad-assemblies/)；[产品页](https://www.getleo.ai/ai-for-mechanical-engineering)；[G2](https://www.g2.com/products/leo-ai-leo)
- Flux：[自动布局介绍](https://flux.ai/p/blog/introducing-ai-auto-layout)；[2025-07 更新](https://www.flux.ai/p/blog/ai-auto-layout-just-got-smarter)；[计划与批准（入门文档）](https://docs.flux.ai/tutorials/getting-started-copilot)；[2026 春季更新](https://www.flux.ai/p/blog/spring-2026-updates-faster-ai-better-layouts-smarter-sourcing)
- Quilter：[About](https://www.quilter.ai/about)；[Project Speedrun（2025-12）](https://www.businesswire.com/news/home/20251210722060/en/Quilter-Unveils-Worlds-First-Computer-Designed-by-AI)
- Zoo：[Zookeeper 研究文（2026-02）](https://zoo.dev/research/zookeeper)；[Zookeeper 发布](https://zoo.dev/press/zoo-introduces-zookeeper)
- CELUS：[EE Times Asia](https://www.eetasia.com/embeddednews-celus-ai-powered-design-platform-simplifies-electronics-design-process/)；[Power Electronics News](https://www.powerelectronicsnews.com/celus-design-platform-revolutionizes-electronics-design-with-ai)
- Nominal：[数据审查文档](https://docs.nominal.io/python/checklists/data-review)；[B 轮（2025-06）](https://www.vcaonline.com/news/2025061209/nominal-raises-75-million-led-by-sequoia-capital-to-modernize-hardware-testing/)；[B-2（2026-03）](https://siliconangle.com/2026/03/05/hardware-testing-startup-nominal-raises-80m-1b-valuation/)
- Bild：[Meru 概览](https://getbild.com/meru/overview)；[合作伙伴文档](https://getbild.com/meru/partner-program)
- Partful 与相近产品：[Partful（2023）](https://www.uktech.news/tech-hubs/the-north-of-england/manchester/partful-models-manufacturing-gear-20230726)；[PartGenie](https://www.g2.com/sellers/partgenie)
- Duro：[Duro Design 发布（2025-06）](https://www.automation.com/en-us/products/june-2025/duro-design-first-ai-native-plm-engineering)；[CIMdata](https://www.cimdata.com/de/industry-summary-articles/item/27926-introducing-duro-design)
- Siemens：[AI BOM Agent（2026-06）](https://blogs.sw.siemens.com/teamcenter/ai-bom-agent-plm-engineering-change/)；[Teamcenter Quality 2512](https://blogs.sw.siemens.com/teamcenter/whats-new-teamcenter-quality-2512/)
- PTC：[Arena AI Assistant（2025-09）](https://www.ptc.com/en/news/2025/ptc-launches-arena-ai-assistant)；[Onshape AI Advisor](https://www.ptc.com/en/news/2025/ptc-announces-latest-onshape-ai-advisor-release)；[Arena AI Engine](https://www.barchart.com/story/news/36527800/ptc-launches-arena-ai-engine-to-accelerate-intelligent-automation-across-plm-and-qms-workflows)
- Propel：[Propel One（2025-10）](https://www.propelsoftware.com/news/propel-accelerates-agentic-ai-adoption)
- Fictiv：[MoldMaking Technology 2025-07](https://mmt.mydigitalpublication.com/july-2025/page-10)；[Rubber World](https://rubberworld.com/fictiv-new-automated-injection-molding-software-saves-time-and-resources/)
- Paperless Parts：[Production Machining](https://www.productionmachining.com/products/paperless-parts-showcases-software-for-quoting-collaboration-2)
- Vizcom：[Radical Ventures](https://radical.vc/?p=3122)
- 国内 EDA：[华秋 AI EDA（2026-03）](https://news.pedaily.cn/20260326/126309.shtml)；[嘉立创 EDA 社区桥接](https://gitcode.csdn.net/69c3510d0a2f6a37c59a200d.html)

**品类与电商研究**
- Jungle Scout：[AI Assist](https://junglescout.com/solutions/ai-assist)；[2023-09 发布](https://www.junglescout.com/press/press-releases/jungle-scout-introduces-ai-innovations-to-accelerate-amazon-sellers-success/)
- Helium 10：[Helium 10 MCP](https://www.helium10.com/blog/helium-10-mcp/)；[竞品博客对评论洞察的评述](https://insight.shulex.com/blog/helium-10-review-insights-alternatives)
- 卖家精灵：[AI 评论分析 2.0](https://www.sellersprite.com/cn/v3/knowledge/article/sellersprite-ai-review-analysis-2-0)；[1.0 发布](https://www.sellersprite.com/cn/blog/ai-review-analysis1-ttgg)；[2026 自评](https://www.sellersprite.com/en/blog/sellersprite-review-2026)
- Amazon：[Customer Review Insights](https://sell.amazon.com/blog/customer-review-insights)；[Opportunity Explorer AI 升级](https://www.aboutamazon.com/news/innovation-at-amazon/amazon-ai-tools-sellers-product-launch)；[Accelerate 2025](https://sellingpartners.aboutamazon.com/amazon-accelerate-2025-a-new-era-of-tools-and-technology-for-independent-sellers)；[退货原因 AI 归类指南（SellerLabs）](https://www.sellerlabs.com/knowledge-base/ai-for-return-reason-analysis-find-whats-killing-your-margins/)
- Shulex：[评论分析 API](https://www.shulex.com/support/vocai-review-analysis-api-introduction)；[VOC 产品页](https://insight.shulex.com/product/voice-of-customer-analysis)
- 魔镜洞察：[中华网 2025-12-12](https://m.tech.china.com/articles/20251212/202512121780644.html)；数说故事：[同花顺 2026-07-09](https://stock.10jqka.com.cn/20260709/c678077918.shtml)
- Accio：[Digital Commerce 360（2025-08）](https://www.digitalcommerce360.com/2025/08/14/alibaba-b2b-search-engine-accio-agent/)；[SCMP](https://www.scmp.com/tech/big-tech/article/3321692/alibabas-new-ai-agent-revolutionise-how-merchants-source-goods-online)
- 1688：[量子位 2025-09](https://www.qbitai.com/2025/09/335835.html)；[界面新闻](https://www.jiemian.com/article/13697798.html)

**品牌实践与用户信号**
- 安克：[钛媒体·AWS 案例（2025-09-04）](https://www.tmtpost.com/7662942.html)；[Taiwan News 召回报道](https://www.taiwannews.com.tw/en/news/6141706)；[AppleInsider 召回扩展](https://appleinsider.com/articles/25/07/01/anker-extends-recall-to-five-more-power-banks-worldwide)；[安克召回通告](https://anker.ph/pages/product-recalls)；[卖家精灵博客引用阳萌](https://cn.sellersprite.com/en/blog/how-to-utilize-AI-for-niche-scenario-Innovation)
- 信任与期待：[IoT Analytics AI 信任差距（2026-09）](https://iot-analytics.com/the-ai-trust-gap-in-design-and-engineering-software/)；[Avnet 调研](https://itbrief.co.uk/story/global-engineers-optimistic-about-ai-s-role-in-development)；[MIT TR Insights（二手转述）](https://www.aap.com.au/aapreleases/cision20260316ae09827)
