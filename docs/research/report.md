# AI-native 研发项目管理系统 · 调研综合报告

> 2026-07-22。基于 11 个研究/核验 agent 的全网调研（Attio、Lightfield、Linear、AI 工作工具横扫、AI-native 设计模式、研发/NPD 域、制造业数据底座、NPD 竞品扫描）。
> 逐主题原始素材见 [raw/](raw/)，本报告只做跨主题综合。Attio 与 Lightfield 的关键结论经过独立核验 agent 逐条对源验证。

## 一、核心结论（10 条）

1. **AI-native 的硬判据是「拆除测试」**：移除 AI 后产品即失效才算 AI-native；只是加聊天框/加功能的是 AI-enabled（CRV）。落到本产品：项目健康度、gate 就绪度、风险标注必须是 AI 持续生成的原生产物，而非人肉字段上的点缀。

2. **数据流向反转是本质**：Lightfield 的定义——原始交互（会议/邮件/消息）是 source of truth，字段、看板、摘要全是派生视图；数据由 AI 自动进入系统，人从录入者变成审核者。这是与「传统软件+AI」的分界线。

3. **但制造业的「原始交互」不在邮箱里**：研发痕迹分裂为治理层（PLM/ECO/BOM，厂商正把 agent 内嵌自家产品、不对第三方开放）、协作层（IM/邮件/会议/评审/共享盘 Excel，API 最开放、无人占据）、物理层（产线 build 数据，已被 Instrumental 类占据）。第三方 PM 层的空位在协作层：做「PLM 之外的过程记录系统」，与 PLM 保持只读引用而非竞争写入权。中国现实：SaaS PLM 仅占 PLM 市场 5.25%（IDC 2024），主采集面应是飞书/钉钉/企业微信 + 共享盘。

4. **Attio 数据模型是最值得整体继承的骨架**：Objects/Records/强类型 Attributes 承载「身份」，Lists/Entries 承载「流程」——同一 record 可进多个流程互不污染。迁移：交付物/任务/评审做对象，「NPD 阶段门管线」「认证流程」做 list；同一份 DFMEA 可同时挂在 Gate 2 评审和受控发布两条流程里各自带状态。AI 挂载点是强类型字段（AI autofill 受 schema 约束），不是自由文本。

5. **全自主已被证伪，建议-审批全部存活**：Height 2.0（全自主 AI 项目经理）发布 5 个月即宣布关停；而活下来的（ClickUp StandUp、Motion、Dart、Asana AI Studio、Lightfield For-review）全部是「AI 起草、人裁决」。配套模式：notify/question/review 三态（LangChain）、autonomy slider 分档自治（Karpathy）、diff 式审核 + citation（验证必须快于生成）。

6. **Agent 是团队成员但不可担责**：Linear 的 assignee（人）/delegate（agent）双字段、AIG 六原则（身份可辨/原生融入/即时反馈/状态透明/尊重叫停/人负最终责任）、AgentSession 结构化执行契约（六状态+五类活动+SLA）是「AI 接活」最可抄的工程规范。制造业更甚：gate 决议、金样本确认永远不能由 agent 签署。

7. **已验证的 AI 用例清单**（按 ROI 排序）：① 从工程信号自动起草状态汇报/周报（状态失真是激励问题，AI 必须读原始信号而非帮人填表，McKinsey 口径每 PM 每月省 13.5h）；② 会议/评审 → 决议/遗留问题/任务三级结构化闭环（飞书项目 IPD 验证的第一刚需）；③ 带 citation 的工作区问答；④ 字段自动填写/查重/intake 分诊（建议式）；⑤ 约束求解排程（确定性引擎，LLM 只做解释——Motion 的教训：不要用 LLM 直接排任务）。

8. **Gate 评审材料自动装配是全球空白且仍成立**：从交付物、测试数据、任务状态自动装配 DCP/TR 评审包并预判准出风险——中外全网扫描无任何厂商实现或宣称。Cooper 本人承认 stage-gate 常退化为文档官僚流程，正确目标是「gate 审例外、审数据，而不是审更厚的材料」。这是本产品最锋利的差异化点。窗口期约 12-24 个月（Teamcenter BOM agent 已能多步执行，PLM 大厂在向上爬）。

9. **中国市场格局已变**：飞书项目 2024-07 发布 IPD 专版后实质占领品类（100+ 客户，蔚来/小米/雅迪等；MCP/CLI/AI 节点/AAMP 协议完成平台级 AI 布局）。但 NPD 特定 AI（自动汇总/预警/gate 装配）全部由客户自建（雅迪「IPD 智能项目助手」）——「AI PMO」是实践叙事不是产品模块。剩余缝隙：① NPD AI 原生产品化；② 服务不用/不能用飞书体系的客户（飞书项目 2025-09 才宣布未来出独立单品）；③ 项目层与 BOM/交付物内容/试产数据的结构化连接（飞书最弱、华为 IPDCenter 最强但无协同与 AI）。中国客户会拿华为术语逐项对表：TR/DCP/准出/PCR/CBB/IPMT/PDT 必须原生支持。

10. **反复失败的陷阱**：① 全自主定位（Height）；② AI 作为强推付费上层建筑 + credit 计费混乱（Notion 涨价反弹、Asana「genuinely confusing」、ClickUp 关不掉的弹窗）；③ AI 补不了核心产品劣势——护城河是结构化工作数据与流程绑定，不是 AI 功能本身；④ 无 provenance 的 AI 汇总（51% 受访者把幻觉列为最大采用障碍；错误的状态报告比没有报告更糟）；⑤ chat 作为唯一 UI（Saarinen：chat 是「非常弱和通用的形式」；正解是 workbench——AI 长在结构化对象的原生动作里）。

## 二、分主题一页摘要

### Attio（[raw/attio.md](raw/attio.md)，已核验）
数据模型灵活性本身就是产品：五层模型（Objects→Records→Attributes→Lists→Entries）+ 身份/流程分离。AI 路径是「先把数据做成 AI 可消费的结构，再让 agent 进来」：AI attributes（2024）→ Call Intelligence（2025）→ Ask Attio（2026.2）→ agent 编排 Workflows（2026.6，agent 继承执行人权限、按 token 计费）。工程侧：Universal Context（graph-relational + 语义索引 + 外部一致性，为上万并行 agent 设计，经 MCP 对外）、Thread Agent 框架（统一 agent 定义 + Jest 式 evals + 全链路 token 归因）、Ask Attio 的 interests 机制（前端声明「屏幕上可见什么」自动注入上下文）。教训：无 SLA 宕机丢数据投诉——实时系统必须配可用性承诺。

### Lightfield（[raw/lightfield.md](raw/lightfield.md)，已核验）
Tome 创始人 pivot（放弃 2500 万用户），$81M 融资。「为公司建 world model」：schema 只是给 AI 的索引；narrative-first 记忆架构（Chronology/Attribution/Causality/State 四要素，放弃知识图谱改用编年叙事流喂强模型）；schema 变更时 AI 重新分析全部历史回填新字段；自然语言 automation 编译为 Python 沙箱执行；For-review 审批队列；agentic 迁移（agent 写确定性迁移脚本，1 小时替换 HubSpot）。第一大投诉：AI 自动创建错误记录/不存在的公司——「AI 直写库」必须有确认门槛。注意：商业上 Attio 的「人管理系统」路线（ARR 4x）目前比 Lightfield 激进路线验证更充分。

### Linear（[raw/linear-agents.md](raw/linear-agents.md)）
Opinionated 默认值赢过可配置性；速度是数据质量的前提（自研 sync engine）；为 IC 设计而非报表设计。Agent 战略：assignee/delegate 分离（「An agent cannot be held accountable」）、agent 是独立用户类型（OAuth actor=app，不占席位、能力由 scope 刻画）、AgentSession/AgentActivity 结构化契约、分层 guidance 注入、Loops 例行自动化（配置全团队可见）。内部实践：agent 按任务类型分级授权——dead flag 清理成功率 100%，复杂排查仅 33%；「agent 5 分钟修好 bug 但报障流程走一周」——AI 提速执行后，流程开销成为最显眼瓶颈。

### AI 工作工具横扫（[raw/ai-work-tools.md](raw/ai-work-tools.md)）
Height 关停 vs Motion（$50M ARR，确定性排程引擎+具名 AI Employees：Alfred/Millie/Chip）、ClickUp（$300M ARR，AI StandUp 最被用起来）、Notion 3.0（$500M+ ARR）、Asana AI Studio（变现慢：$6M ARR vs 主营 $8 亿）、Dart（功能被验证、生意未被验证）。具名角色 agent 划定预期边界是关键交互创新；credit 计费是集体踩坑区。

### AI-native 设计模式（[raw/ai-native-patterns.md](raw/ai-native-patterns.md)）
可操作模式库：ambient capture、事件流驱动的 proactive agents + Agent Inbox（待裁决收件箱取代任务列表作为高频入口）、notify/question/review 三态、autonomy slider、generation-verification loop + diff 审核、citation + stream of thought、三类系统记忆（semantic/episodic/procedural，CoALA）、Declarative generative UI（agent 输出结构化描述、应用渲染原生组件）。审批要建成策略引擎而非确认按钮：低风险直通可回滚、中风险批量待审、红线强制四眼；人工改写 AI 提案的记录本身是最高价值的训练/评估资产。

### 研发/NPD 域（[raw/rnd-domain.md](raw/rnd-domain.md)）
痛点有实证：技术人员约 20% 时间耗在非生产性数据管理；PM 每周 3-4h 拼状态报告且存在两级失真（乐观偏差+粉饰偏差，高管「不能按面值相信绿灯报告」）；变更成本 rule of ten 倒逼 AI 价值左移（变更创建瞬间给出影响分析）。成功初创的共同模式：先把一类工程原语变成干净数据资产（CoLab=评审意见、Flow=需求参数、Instrumental=缺陷影像、nPlan=历史排期）。硬件域根本约束：迭代少而贵、单项目数据永远稀疏——AI 预警必须靠跨项目组织记忆。

### 制造业数据底座（[raw/mfg-data-backbone.md](raw/mfg-data-backbone.md)）
Ambient capture 在制造业「分层成立」：云原生层就绪（Duro GraphQL+MCP、Onshape、Arena），存量层封闭（Teamcenter/Windchill 无官方 MCP，社区连接器全部玩具级，须自研+按客户实施字段映射）。必须支持 LLM 可替换（on-prem/客户云端点）——Teamcenter Copilot 三形态部署证明这是真实需求；军工/涉密全离线是硬边界。冷启动排序：共享盘 Excel 导入 > 旧评审 PPT/纪要 AI 摄取（CoLab ingestion engine 先例）> PLM 只读同步 > 邮件回填（无先例，空白点）。架构铁律（Duro）：UI 与 agent 共用同一套带权限审计的 API。

### NPD 竞品扫描（[raw/npd-competitor-scan.md](raw/npd-competitor-scan.md)）
全球：执行层空窗在，但 Flow/Rollup/Nominal/Stell 已围住相邻数据层（「先占工程数据层再扩平台」）；组合层 AI（Sopheon/ITONICS）20 年未下沉到执行层。中国：飞书项目已占 IPD 品类；IPD 与 Cooper stage-gate 的结构差异（5 DCP + 7 TR + 4 准出，双轨评审、PCR 可回退状态机、CBB 跨项目复用）必须在数据模型层原生支持。中文竞品调研要防飞书系内容农场软文。

## 三、遗留 Gap（设计前需解决）

1. **目标市场与方法论未定义（需问用户）**：自用还是商品化？中国还是全球？IPD 还是 stage-gate 双轨？这改变流程模板、竞品对标、集成对象（飞书/钉钉 vs Slack/Teams）、模型合规、定价。
2. **质量体系对 AI 产物的硬约束未调研**（ISO 9001/IATF 16949/APQP/PPAP 下 AI 生成材料的签核责任与审计接受度）——取决于目标行业，确认后补研。
3. **「人从操作者变审核者」缺实证**：review fatigue、橡皮图章化、信任校准无公开数据——适合在原型阶段用自家真实项目小规模验证，而非继续网络调研。
