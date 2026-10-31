# R3 · AI-native 工作/项目管理平台与企业 Agent 交互模式调研（2025–2026）及 PDOS 对照

调研日期：2026-10-22。范围是 Linear、Asana、Notion、Atlassian、monday.com、ClickUp、Microsoft 365 Copilot、Salesforce Agentforce/Slackbot、Glean、飞书、钉钉、企业微信，对照 PDOS 的“我的工作 + 项目 + 小Pai 单 Agent”体验。
只读分析，没有改仓库，也没有运行服务、测试或数据库。

## 0. 结论先行

1. **PDOS 的强项在“问责”和“可撤回”，弱项在“捕捉”和“触达”。** 行业最新做法（Linear 委派模型、Notion 逐条批准、Atlassian 审计日志、Asana 检查点）多数只做到“Agent 建议，人批准”和“权限等同于用户”。PDOS 的 T0/T1/T2 分级、ActionReceipt、按运行撤回、引用逐字核对、四时间、按接收者分开的承诺和不可变 Decision，问责粒度比这些产品更细（v1.1 §06.5、§06.10、§05.12.4）。差距在另一头：工作信息怎样进入系统、怎样回到人手里。竞品把 IM、会议、邮件、客服和通话直接变成结构化工作（Linear Asks 与 Gong/Intercom 代理、Notion 会议纪要触发 Custom Agent、钉钉听记生成待办、飞书 AI 风险分析读群聊），再通过每日摘要、优先收件箱和移动端推回给人。PDOS 的钉钉集成目前“暂缓”（`docs/design/2026-10-08-pdos-next-design-confirmation.md:331`），`pdos-next` 代码里没有钉钉相关实现。会议只设计到“已登记会议原件 → 显式建任务”（`docs/design/2026-10-18-pdos-next-s5-project-work-contract.md:5`）。
2. **“主动 Agent”的主流形态已从演示进入付费功能**，例如 Linear Loops（2026-07 起，Business/Enterprise，按 AI credits 计费）、Notion Custom Agents（2026-05 起收费）、Asana AI Studio 规则、Atlassian 的 Jira 内 Rovo agents。它们的共同点是：可读的自然语言说明、事件或定时触发、每次运行可回看对话、额度与限额。PDOS 的 AutomationRule（v1.1 §06.4）在治理上已经齐全（去重、冷却、级联上限、预算），缺的是**面向 NPI 场景的预置规则模板**和**用量与费用面板**。
3. **状态更新草稿是各家都有的“第一杀手级用法”**（Asana Smart status、Linear 的 Agent 起草项目/initiative 更新、Microsoft Planner Agent 状态报告、飞书 AI 个人周报和项目周报）。PDOS 的 P18 `work.status_update.create`（T1，具名发布、不自动发布）方向正确。还缺三样：定时起草、按受众分版本（管理层版、OEM 客户版，客户版外发按 T2）、个人周报。
4. **用户反馈的主旋律是不信任和噪音，不是功能不够。** Asana 2025 年调查中 64% 的员工认为 AI agent 不可靠；HBR/斯坦福的 “workslop” 研究中 40% 的人上月收到过低质 AI 产出，平均每次处理约 2 小时；Gartner 预测 2027 年底前超 40% 的 agentic 项目会被取消；Salesforce 自己的 CRMArena-Pro 显示多轮业务任务成功率约 35%。PDOS“成功静默、只把例外放进注意项、重复聚合”（v1.1 §05.2、§06.4）以及“健康度纯规则、模型不参与”（P17）正好对着这些痛点，应当坚持。但当前界面把太多内部词汇暴露给业务用户（见 §3.8），会抵消信任上的优势。

## 1. 证据口径

- 成熟度标记：**GA**（正式可用）、**Beta/预览**、**邀测**、**即将推出**、**厂商宣称**（营销数字，未经独立验证）、**第三方**（追踪站、咨询或评测博客）。
- 2026 年的信息优先取官方 changelog、help center 和新闻稿。少数日期或计划档位只有第三方来源，正文中已标出。
- 搜索词只用了通用的产品和行业关键词，没有带入本项目的任何内部信息。

## 2. 竞品逐个速览（重点：对中国消费电子中小企业的研发/NPI 有什么用）

> 读者画像：做汽车充气泵、自行车打气筒的中国中小企业，同时经营自主品牌和 OEM/ODM，日常协同在钉钉，客户沟通在 CRM，另有 ERP/MES。典型的外部依赖有电机/电芯/模具供应商、OEM 客户承认、认证机构。

### 2.1 Linear（用户点名参考）

| 能力 | 成熟度 | 要点 |
|---|---|---|
| Linear for Agents / Agent Interaction SDK | 2025-05 发布；SDK 2025-07 起为开发者预览 | Agent 是一等用户，可被委派 issue 或被 @。**issue 只能分配给人，只能委派给 Agent**，人仍是负责人；Agent 不占付费席位；管理员按团队授权 |
| Agent 交互准则（AIG） | 公开准则 | 六条：始终表明是 Agent；用平台原有 UI 和标准动作；立即确认收到；展示状态并允许检查推理与动作；被要求退出时退出；Agent 不能被问责，人对委派工作负责 |
| Linear Agent（内置） | 2026 年内 beta → GA（第三方追踪） | ⌘J、@Linear、在 Slack/Teams 中 @；查找 issue/项目/文档/代码，创建和更新对象，起草评论与状态更新；2026-09 增加“用 Agent 起草项目” |
| Triage Intelligence | GA，Business/Enterprise | 对进入 Triage 的 issue 建议团队/项目/负责人/标签，检测重复和相关项；**每个团队可按属性分别设为显示、自动应用或隐藏**；悬停可见理由；处理需 1–4 分钟；不用客户数据训练 |
| Asks | GA，Business/Enterprise | 在 Slack（表情回应、斜杠命令、@）或邮件里把请求变成 Triage 中的 issue；没有 Linear 席位的人也能提交；渠道级必填表单；Slack 与 Linear 评论双向同步 |
| Intercom/Zendesk/Gong 代理 | 2025-12 GA；Gong 仅 Enterprise | 从客服对话和**客户通话录音**生成 issue，带按说话人标注的原文摘录；跳过内部通话和 10 分钟以下的录音；过滤销售咨询；重复请求合并到已有 issue |
| Pulse / Priority inbox | Pulse 2025-04 GA；Priority 2026-09 | 个人的每日或每周更新摘要，可**语音收听**，早 7 点前送达；Priority 标签把“需要你处理的”和“可以等的”分开 |
| Loops | 2026-07-20 发布，Business/Enterprise，消耗 AI credits | 用自然语言描述重复性工作，选择定时或事件触发；2026-09 增加项目、initiative、cycle、issue 变化等触发，能编辑文档、建 issue、发 Slack；**每次运行开一段与 Agent 的对话，可回看和追加指示** |
| 成本治理 | 2026-08/10 | AI credit 用量浏览器，支持按工作区、用户、Loop 设限额 |
| MCP | GA | 2026-08 支持经 Okta 的企业托管 MCP 授权；MCP 中有 `list_customer_needs` 等工具 |

- **对目标企业的用处**：最值得学的是 Asks 和 Gong 代理“把外部声音变成带原文摘录的结构化工作”的做法。对应到充气泵企业，就是把钉钉群里的“供应商说周五到样”、OEM 客户邮件里的规格变更、售后群里的“气嘴漏气”投诉，变成带来源定位的候选。Triage Intelligence 的“按属性分别设显示/自动/隐藏”正好可以映射到 PDOS 的档位。Loops 文档里的例子（项目目标日期变了，就更新发布计划并通知相关人）几乎就是 NPI 场景中“试模推迟会影响哪些承诺”的原型。
- **成熟度提醒**：Linear 面向软件团队，没有 BOM、样件或制造概念，不能直接用于 NPI。

### 2.2 Asana（用户点名参考）

| 能力 | 成熟度 | 要点 |
|---|---|---|
| AI Studio（智能工作流） | GA；Basic 已并入核心产品 | 无代码 AI 规则。按账号层级给每月额度（Starter 50k / Advanced 75k / Enterprise 200k credits），Plus 附加包每月 100k；消耗取决于模型、输入/输出量、频率，联网另计；**额度用完后智能工作流停止运行** |
| AI Teammates | 2025-09 发布；公开 beta 只面向 AI Studio Pro；财报称 FY27 分阶段 GA（官方尚未确认是否完成） | 基于 Work Graph 理解项目/任务/目标关系；**权限与普通用户一致**；把复杂工作拆成子任务并边做边评论，让人审阅草稿或要求修改（检查点）；记得以往指示；发布时有 12 个预置角色，可自建；使用独立的额度池 |
| Smart status | GA（项目在 Starter 起；组合/目标在 Advanced 起） | 在项目概览点“Draft with AI”，选时间范围和主题后起草，**人编辑后发布**；规则可触发起草，但官方论坛承认“不是全自动”；smart digest 只对生成者可见 |
| 外部助手连接器 | 2026 春季发布 | 在 Claude/ChatGPT/Gemini 对话中建项目、分派工作、看状态、标风险 |
| 用户调查（2025 Global State of AI at Work） | 厂商调查 | 64% 认为 agent 不可靠；agent 出错时 39% 认为没有人负责；只有 19% 的组织跟踪 agent 错误 |

- **对目标企业的用处**：Smart status 的“选时间范围 + 主题 → 草稿 → 人改 → 发布”，与 PDOS P18 几乎同构，可以直接作为交互参照。AI Teammates 的“检查点评论”说明，**中间产物可见**比“一次给出最终结果”更容易被接受。Asana 的调查数据可以作为坚持“人对委派工作负责”的外部依据。
- **成熟度提醒**：AI Teammates 仍是高档位的受限可用，额度规则尚未公开，beta 用户已在担心“额度是黑盒”。

### 2.3 Notion

| 能力 | 成熟度 | 要点 |
|---|---|---|
| Notion Agent（个人） | 3.0（2025-09）GA | 多步执行超过 20 分钟，用页面和数据库做记忆；2026-10-19 起单任务可运行 24 小时以上，有自己的计算机和浏览器，后台有队列 worker，重启后可续跑 |
| Custom Agents | 2026-05-04 起按 credits 收费（$10/1000）；Business/Enterprise | 定时或事件触发，自主运行；2026-07 **AI 会议纪要完成后可触发 Custom Agent**；2026-09 可调用子 agent，增加会后工作触发；额度不足时暂停 |
| 人工批准 | 2026-08 / 2026-09 | Agent 可“建议修改”，人**逐条批准**；自定义 MCP 连接在改动外部工具前**需要确认** |
| 权限与归因 | 2026-10-13 | 列级权限同时限制人和 agent 能看和能改的属性；版本历史区分人和 agent 的修改；管理员可查看并撤销 MCP 连接 |
| “Review for me” | 2026-10-19 | 执行动作前由另一个模型检查动作是否安全 |
| AI 会议纪要 / 企业检索 | 2025-05 GA（Business 及以上） | 会议纪要是一种块，配合 Notion Calendar 可自动加入会议；企业检索覆盖 Slack、Drive、GitHub、Jira、Teams、SharePoint 等 |
| 成本治理 | 2026-10 新额度体系；AI Command Center 即将推出 | 每席每月 1,500 Standard + 500 Select credits；80%/100% 告警；可按成员或 agent 设限、限定可用模型 |

- **对目标企业的用处**：“会议纪要完成 → 自动触发后续 Agent”和“逐条批准建议修改”是两个值得借鉴的交互。前者对应“DVT 评审会结束 → 生成决定候选、任务候选、承诺候选”，后者 PDOS 的 T1 原子组已经做到（v1.1 §05.6）。“Review for me”用第二个模型做安全检查，PDOS 在 `verify` 节点用确定性校验替代（v1.1 §06.2），这一点更可靠。
- **成熟度提醒**：Custom Agents 收费后，第三方测算单次运行 1–30 credits，有团队一个月用掉约 $1,500（第三方）。主要抱怨是成本难预测，可靠性方面尚无系统证据。

### 2.4 Atlassian（Rovo / Jira Product Discovery / Loom）

| 能力 | 成熟度 | 要点 |
|---|---|---|
| Rovo（Search/Chat/Studio/agents） | 所有付费云计划都包含 | 额度：Jira/Confluence 每用户每月 25/70/150，Collections 250/700/1500，组织级汇总；**Rovo Search 不消耗额度**，额度用完也能用；基础交互每次 10 credits；**超额默认开启**（$0.01/credit，直到管理员设上限）；80%/100% 告警 |
| Jira 内的 agents | Team ’26（2026-05）；GA 状态只有二手报道 | 可被分配工作项、在评论中 @、放入 Jira 工作流，每个动作留审计；Studio 已 GA，可用自然语言建 agent 和自动化 |
| Teamwork Graph / Rovo MCP Server | 公开 beta | 把 Atlassian 的工作图谱开放给外部 AI 工具 |
| JPD + Feedback | 营销/大会材料 | 汇集 Slack、Gong、Salesforce 中的反馈，用 AI 浓缩成“已核实洞察”并链接到 JPD 想法 |
| Loom | 会议纪要 GA；“会议 → Jira 更新”即将推出 | AI 加入会议，把纪要和行动项发到 Confluence 并 @ 负责人；录屏 bug 报告一键转 Jira |
| 社区反馈 | 论坛 | OKR 生成器编造关键结果；**只读动作调用准确率接近 100%**（开发者自述）；日期类回答要显式传入当前日期才稳定 |

- **对目标企业的用处**：“检索不计费”的策略说明，检索是基础设施，应当便宜到不需要犹豫。社区反馈印证了一个对 PDOS 有用的分层：只读和归类最可靠，生成新内容最不可靠。PDOS 把 T0 限定在可逆的草稿和关联（v1.1 §06.5）是对的。
- **成熟度提醒**：“会议 → Jira 字段更新”至今仍是“即将推出”，说明会议到正式字段这一步，大厂也没有放开自动写入。

### 2.5 monday.com

- **能力**：monday agents（2026-06-08 起 Pro 及以下按 credits 计费，Enterprise 暂免）、sidekick 个人助理、Agent Factory（独立产品，独立条款）。营销页上的 Risk Analyzer / Dependency Risk Detector 会扫描看板中的延期、超支、依赖冲突，**按严重度排序**并通知负责人。支持 MCP 对接 Claude/ChatGPT/Copilot。
- **成熟度**：风险 agent 只有营销页描述，没有找到帮助中心文档。计费日期在多份官方帮助页之间互相矛盾。
- **对 PDOS 的启示**：自动风险排序是反例。PDOS P17 规定健康度是纯规则投影、模型不参与、不得抵消硬阻塞。对 NPI 门禁来说，“AI 风险分”会误导评审。可以借鉴的只有“依赖扇出提示”，PDOS 的 §08.11 扇出收窄已经覆盖。

### 2.6 ClickUp Brain / Super Agents

- **能力**：Super Agents（2025-12 发布，Brain2 平台）可以在任务评论、文档评论、Chat 中被 @，可私聊、被分配任务，也可按计划或自动化触发；厂商宣称“无限记忆”“500+ 工作技能”。Ambient Answers 自动回答聊天中的问题；另有 AI Notetaker。定价方面，Brain AI $9/人/月，Everything AI $28/人/月，Super Credits $0.001/credit。
- **成熟度**：以厂商宣称为主，独立评测少。
- **对 PDOS 的启示**：“像同事一样可私聊、可 @”与小Pai 的常驻侧栏一致。“无限记忆”这类说法与 PDOS 带来源、作用域、有效期的记忆（v1.1 §06.8）是两种路线，PDOS 的做法更适合承认、认证这类需要追溯的场景。

### 2.7 Microsoft 365 Copilot

| 能力 | 成熟度 | 要点 |
|---|---|---|
| Planner Agent（原 Project Manager agent） | 路线图 RM516576 标为 2026-06 “Launched”；已扩展到 basic 计划 | 可领取分配给它的任务；根据计划更新写状态报告（Loop 组件，可编辑、可共享）；先做核心任务和计划管理 |
| Facilitator / 频道 agent（Teams） | 第三方报道 2026-06 GA（未见微软原文） | 会议议程、实时笔记、行动项，**会议任务自动同步到 Planner**；频道 agent 从频道对话和会议记录生成状态报告 |
| Researcher / Analyst | 2025-05 GA | 深度研究和数据分析 agent |
| Copilot Memory | 2025-11 预览，GA 时间多次推迟 | 用户可在设置页查看和管理“已保存记忆”，管理员策略不变 |
| Agent 365 | 2026-05-01 GA（价格来自二手来源：$15/人/月，E7 $99） | Agent 注册表、Entra 身份、治理控制面；运行时 token 另计 |
| 采用 | 财报 | 付费席位 2026-01 为 1,500 万（约占 4.5 亿商业订阅的 3.3%），2026-04 为 2,000 万；分析师质疑“席位不等于使用” |

- **对目标企业的用处**：“会议行动项 → 计划任务”是 Teams 生态的标配。在中国企业的钉钉生态里，对应的是钉钉听记生成待办（见 §2.11）。PDOS 不该自建录音，应读取已有纪要。
- **成熟度提醒**：Copilot 的付费渗透率只有个位数，说明“一个通用助手 + 席位费”很难证明价值。领域内、对着具体对象工作的 AI 更容易被用起来。

### 2.8 Salesforce Agentforce / Slackbot

- **能力**：Agentforce 360 有 Agent Command Center，用于观测、成本与安全控制、**回放 agent 决策路径**；guardrails 在越界时把对话连同上下文交接给人；Einstein Trust Layer 在出站前遮蔽 PII 并记审计（第三方描述）。Slackbot 于 2026-01-13 GA，作为 Slack 里的个人 agent，遵守用户权限（底层模型为 Claude）。
- **数据**：Salesforce 内部 8 万员工中 5.3 万试用，80% 持续使用（厂商宣称）。Agentforce 2025-05 时约 8,000 家客户采用，而客户总数在 15 万以上，价格被认为是中型市场的门槛（第三方）。计费在按会话、按动作 credits（约 $0.10/动作）、按用户之间多次调整（第三方）。
- **CRMArena-Pro（Salesforce AI Research）**：领先模型单轮业务任务成功率约 58%，多轮约 35%；约一半失败是因为**没有追问缺失信息**；保密意识接近于零。
- **对 PDOS 的启示**：CRMArena-Pro 的结论直接支持 PDOS 的“Grill me 每次最多 3 个关键问题”（v1.1 §05.4）和“只追问会改变方向的问题”，也支持把正式结论留给人（T2）。“回放决策路径”对应 PDOS 的 AI 工作详情和运行回执。

### 2.9 Glean

- **能力**：2026-02-17 推出新一代 Assistant。它构建员工的**个人图谱**（角色、项目、目标、偏好），**用户可查看、编辑、删除**；预置主动 agent 包括每日“需要关注什么”、规划当天、每周成果回顾；可执行企业动作，经 MCP 的动作仍是 beta；实时语音 beta；价格不公开。厂商宣称每年超过 1 亿次 agent 动作。
- **对 PDOS 的启示**：个人图谱可看、可改、可删，正好对应 PDOS §06.8 五层记忆中的“个人偏好”和“当前工作短记忆”。v1.1 §05 的页面表里没有这样一个用户可见的界面（见 §3.9）。

### 2.10 飞书（飞书项目 / aily / 妙记 / 多维表格）

| 能力 | 成熟度 | 要点 |
|---|---|---|
| 飞书项目生态日（2026-04-23） | MCP 和 CLI 已发布；AI Coding 套件“将上线” | MCP 覆盖工作项、视图与度量、团队与个人待办等 40 多个工具，支持 OAuth；CLI 开源，**采用渐进式披露以节省 token**；“AI 节点”把智能步骤嵌入流程沉淀为 SOP；AI 助手正式发布，覆盖人力分析、个人周报、项目分析、图表生成 |
| AI 项目管理（官方文章） | 官方内容页 | AI 个人周报一键起草并定期推送；AI 进度总结生成项目周报/月报（节点进度、延期、风险、人力）；**AI 风险分析持续监控群聊、评论、任务状态，评级预警**；延期原因分析；会议纪要提取待办；自然语言生成视图；AI 复盘 |
| aily 个人智能伙伴（2026-03-19） | 已发布；有第三方称响应不稳定（来源质量低） | 以对话机器人形式**常驻联系人列表**，权限与本人一致，沉淀记忆，“主动跟进工作动态”；OpenClaw 插件已对接 MiniMax 等国内模型 |
| 妙记 / 智能会议纪要 | GA | 音视频转写和纪要；小鹏汽车上半年生成 63 万份纪要（客户案例，厂商宣称） |

- **对目标企业的用处**：飞书项目是国内最接近“项目管理 + AI”的对标，而且明确服务硬件研发团队（PDOS v4 设计稿也参照过它）。三项最贴近 PDOS：个人周报和项目周报的定期推送、对群聊的风险监控、AI 节点嵌入流程。飞书 CLI 的“渐进式披露”与 PDOS 技能包按需加载（v1.1 §06.3.3）思路一致，说明 PDOS 的工具下发方案（M2 提案）方向没问题。
- **成熟度提醒**：“风险评级预警”只见于官方内容营销文章，未见量化效果。它与 P17 冲突，只能借用“从非结构化信号发现线索”这一半。

### 2.11 钉钉（悟空 / AI 助理 / AI 听记 / AI 表格 / Teambition）

| 能力 | 成熟度 | 要点 |
|---|---|---|
| AI 钉钉 2.0（2026-03-17） | 悟空**邀测**；现有付费客户可免费用；“按效果付费”未公布价格 | 企业级 AI 原生工作平台“悟空”：把知识经验封装成“技能”，再组合成 AI 助理；**聊天、AI 听记、AI 表格、文档、通讯录已完成 MCP 改造** |
| AI 听记 / A1 硬件 | GA | 支持 15 种方言、79 语种同传，图文纪要、思维导图、AI 问答；第三方体验文称能识别任务、责任人和时间节点，并同步到钉钉待办 |
| AI 表格 | GA | 2026-03 增加透视表视图；**AI 表格 Agent 已接入钉钉群，用于工厂巡检反馈、SOP 流程校验**等场景 |
| 开源 dingtalk-mcp | 社区/官方开源仓库 | 待办、日程、工作通知等工具 |
| Teambition AI | 未找到权威说明 | 只有第三方介绍，不作依据 |

- **对目标企业的用处**：用户企业已经在用钉钉，钉钉是**移动端、现场、IM 和会议的真实入口**。钉钉自己已把聊天、听记、表格、文档做成 MCP，所以 PDOS 不需要自建会议录音或 IM，只需按 v1.1 §06.6.2 把钉钉作为管理员允许清单中的 MCP 连接器，只读接入，内容按不可信内容隔离处理。“AI 表格 Agent 接入群 + 工厂巡检反馈”说明国内工厂场景的 AI 用法已经落到 IM 群里。
- **成熟度提醒**：悟空仍在邀测，技能市场的现状未知；听记“自动生成待办”的细节来自第三方体验文。

### 2.12 企业微信

- **能力**：5.0（2025-08）推出智能搜索（跨聊天、文档、会议、邮件）、智能总结、智能机器人（学习 SOP 和制度，可通过 API 接业务系统）、智能表格。5.0.9（2026-06）增加服务总结（梳理客户需求和跟进情况），智能表格上线 100 多个“AI 字段”技能卡（如解析合同到期日、发票金额）；“记录面聊”把线下面谈转成文字并生成纪要和待办。
- **对目标企业的用处**：很多中小制造企业和外部供应商、海外客户的沟通走微信或企业微信。“记录面聊”和“服务总结”对应 PDOS 的“说情况”路径（v1.1 §05.5）。不过 PDOS 当前的身份和通知通道只定了钉钉，企业微信只能作为原件导入的来源之一。

## 3. 跨产品模式与 PDOS 对照

每个模式写三件事：行业做法、PDOS 现状（设计/代码）、差距与建议。建议优先级：**高** = 直接影响 S5 闭环的日常采用；**中** = 显著提升体验；**低** = 可后置。凡是会改变冻结规则或扩大范围的，标为“需用户确认（新 P 记录）”。

### 3.1 Agent 是“被委派的同事”，责任留在人身上

- **行业**：Linear 规定 issue 只能分配给人、只能委派给 Agent，AIG 第 6 条写明“Agent 不能被问责”；Asana AI Teammates 和 Notion agent 的权限与用户一致；Atlassian 的 agent 动作全部审计。
- **PDOS**：human_owner、writer_principal、requester、approver、verifier、receiver 是不同字段（v1.1 §02.12）；AI 永不取得 T2 执行权（AGENTS 不可协商项 1）；后台结果署名小Pai，并标明触发来源和技能包（v1.1 §06.1）。**已领先，无需改动。**
- **建议**：没有缺口。对外介绍时可以直接引用 AIG 这条行业共识来说明 PDOS 为什么这样设计。

### 3.2 主动 Agent / 循环（ambient、后台运行）

- **行业**：Linear Loops（自然语言说明、定时或事件触发、每次运行是一段可回看的对话）、Notion Custom Agents（会议纪要触发、子 agent）、Asana AI Studio 规则、Atlassian Studio、ClickUp Super Agents 的定时和自动化触发。
- **PDOS**：AutomationRule 支持 domain_event、schedule、relative_milestone、manual 触发，有版本、草稿/发布/回滚、去重、冷却、级联上限、预算，运行历史可追问（v1.1 §06.4）；`ai.automation.activate/pause`、`ai.automation.draft.save` 已在操作目录中（`pdos-next/contracts/operations.json`、`auxiliary-operations.json`），前端有 `pdos-next/web/src/components/automation-rules.tsx`。治理设计比竞品严格。
- **差距与建议（高）**：缺**NPI 场景的预置规则模板**。竞品都靠模板库降低上手难度（Asana Teammate 模板库、Linear Loops 示例、Atlassian 开箱即用 agent）。建议首批模板按充气泵 NPI 写成可一键启用的 AutomationRule 草稿，都走既有档位：
  1. 试模/Build 前 T-3 天检查齐套和资源，缺项聚合进原对象的注意项；
  2. 供应商或外部承诺到期前 2 天起草跟催消息（只起草，外发 T2）；
  3. 测试失败时建 Issue 候选并去重（v1.1 §06.4 已有“同一测试失败不重复建多个 Issue”）；
  4. 预测滑期时，列出受影响的下游承诺及各自接收者，并起草状态更新（Linear Loops 示例的 NPI 版本）；
  5. ECR 批准后列出受影响的 BOM/SOP/控制计划，生成待办候选。
  这些模板只是配置，不改模型，不新增档位。

### 3.3 自动分诊、去重与路由建议（Triage Intelligence 模式）

- **行业**：Linear 对进入 Triage 的条目建议团队/项目/负责人/标签和重复项，**每个团队按属性设显示、自动应用或隐藏**，悬停可见理由；Gong 代理合并重复的客户请求。
- **PDOS**：“我的工作”按动作类型分诊（要我决定/接收/验证/等外部回复，加“我作出的承诺”，见 v1.1 §05.3、P19）。这是**按责任关系分诊**，不是对新进入物的 AI 路由。进入物包括现场反馈（`field.feedback.create` T0、`field.feedback.locate` T1）、客户输入（§05.3）、测试异常、问题。
- **差距与建议（中）**：给“现场反馈、客户输入、问题候选”加**分诊建议**：建议型号/项目/负责人和疑似重复项，附理由（引用相似的历史 Issue 和样件），按类型分别设“显示 / 自动应用 / 隐藏”。自动应用只适用于 T0 可逆的关联动作；改负责人仍按 `work.task.assign` 的 T1。这不新增档位，但要在附录 A 中确认关联动作的档位，可能需要一条小的确认记录。对充气泵企业的价值：售后群里同一批“气嘴漏气”投诉会被合并到同一 Issue，并直接挂到对应 Lot 和样件配置上。

### 3.4 状态更新与周报草稿

- **行业**：Asana Smart status（起草 → 人改 → 发布）、Linear Agent 起草项目/initiative 更新（参考上次更新以来的变化和关联的 Slack 频道）、Planner Agent 状态报告、飞书 AI 个人周报和项目周报定期推送、Teams 频道 agent 从对话生成状态报告。
- **PDOS**：P18 `ProjectStatusUpdate` 只追加、具名，AI 可起草（T1 一次确认），不自动发布；状态更新里的日期不写进四时间（P18 硬边界）；S5 合同把“具名周报引用”列入联验（`docs/design/2026-10-18-pdos-next-s5-project-work-contract.md:17`）。
- **差距与建议（高）**：
  1. **定时起草**：用 AutomationRule 的 schedule 触发，每周一为本人负责的项目起草一条状态更新草稿，放进“我的工作”待确认，到期未确认就聚合提醒，不重复新建。草稿只引用本周实际回执和事件（v1.1 §06.10），每句话都能点开来源，不让模型凭印象写“进展顺利”。这是针对 workslop 的关键约束。
  2. **按受众分版本**：内部项目版、管理层组合版（跨项目只列冲突和需决定事项，对应 B4）、OEM 客户周报版。**客户版属于对外发送，按 T2 具名外发**（v1.1 §06.5），客户资料边界按 §02.3a 执行。OEM 客户通常要求每周项目进度表，这项能直接替代人工整理 Excel。
  3. **个人周报草稿**：从本人的任务、承诺履行和回执生成，供复制到钉钉日志。复制是用户自己的动作，不算外发。
  第 1、3 项是 S5 范围内的细化；第 2 项的客户版涉及外发，需要和现有外部移交（S4）的固定包机制对齐，建议写成确认记录。

### 3.5 个人摘要与优先收件箱（Pulse / Priority inbox 模式）

- **行业**：Linear Pulse 每日或每周个人摘要，可语音收听，早 7 点前送达；Linear 2026-09 推出 Priority inbox；Glean 每日“需要关注什么”；飞书个人周报定期推送。
- **PDOS**：“我的工作”有注意项、我的任务（今日/本周/稍后）、通知流和最近访问（`pdos-next/web/src/components/my-work.tsx`）。**通知流目前只显示小Pai 的运行动态**（同一文件第 178–184 行附近，“通知 · 小Pai 运行动态”），没有项目事实变化的个人摘要，也没有推送到钉钉。
- **差距与建议（中）**：增加**每日简报**：由代码预聚合今天到期的承诺、新增注意项、外部等待超期、本人项目的新状态更新，按 §06.7 动态内容追加在 context 末尾。可以不用模型，模型不可用时照常生成（满足 AT-45）。经钉钉工作通知推送（v1.1 §07.9 已把“钉钉身份通知”列为集成边界），点击深链回到 PDOS 原对象。管理层版只列跨项目冲突和待决定事项。

### 3.6 IM / 会议 / 语音捕捉 → 结构化工作（最大缺口）

- **行业**：Linear Asks（Slack 表情回应即提交，无席位者也能提）、Gong 通话 → 带按说话人摘录的 issue；Notion 会议纪要触发 Custom Agent；Microsoft Facilitator 把会议任务同步到 Planner；Loom 纪要和行动项进 Confluence；钉钉听记生成待办；飞书监控群聊发现风险；企业微信“记录面聊”。
- **PDOS**：v1.1 §05.5 有“说情况”路径（例如“供应商说周五才能到样”先建来源明确的外部承诺候选），但入口只在小Pai 对话里。S5 合同只支持“从已登记会议原件……显式创建任务”。AutomationRule 中“由外部来源（邮件、IM 建立的对象）触发”默认关闭（v1.1 §06.4）。确认稿第 331 行写明钉钉“暂缓，若定为 MCP 连接器，再按 A 类复制”；`pdos-next` 中没有钉钉代码。
- **为什么对目标企业最重要**：充气泵这类 NPI 的大量关键事实最先出现在 IM 和会议里，而不是系统里。比如模具厂说“T1 推迟到下周三”，电机供应商发来一张截图说“样品电流偏大”，OEM 客户在邮件里改了“压力显示精度”，DVT 评审会上口头决定“先放行外观、性能复测”。这些事实进不了 PDOS，四时间、承诺和准备度规则再严格也只能算“空转”。
- **建议（高，需用户确认，新 P 记录：钉钉定为只读 MCP 连接器）**：
  1. **钉钉转交入口**：用户在钉钉群里对一条消息“转给小Pai”，或在单聊中 @小Pai。由**转交的人作为 requester**（不是外部来源自动触发，因此不碰“外部来源触发默认关闭”的规则），原文作为不可信内容进入只读子任务（v1.1 §06.6.2），交回结构化候选：外部承诺候选（区分“声称”与“实到”）、Issue 候选、客户需求候选。候选回到“我的工作”，由本人一次确认（T1）。
  2. **会议纪要导入**：通过钉钉 MCP 只读获取听记纪要，作为“已登记会议原件”（已在 S5 合同中），生成决定待办、任务候选、承诺候选，并定位到原文段落。**会上的口头决定只生成“待具名决定”候选，不形成 Decision**（v1.1 §03.10）。不自建录音或转写。
  3. **现场语音和拍照**：在移动 Web 上，语音转写作为候选、不作为原始事实（v1.1 §05.9 已规定）。优先支持品质接收和现场异常。

### 3.7 对话到行动与逐条批准（Agent 收件箱 / 审批）

- **行业**：Notion 2026-08 推出“建议修改、逐条批准”，自定义 MCP 写外部前需确认；Linear 每次 Loop 运行都是可回看的对话；Asana 检查点评论。
- **PDOS**：T1 ConfirmationBatch 中独立组可分别选择、有依赖的组整体确认，必须显示原值、新值、影响、来源和未定项（v1.1 §05.6）；版本冲突只重现真实变化；按运行撤回并列出未撤回项（B17）；“我的工作”已把 `waiting_input` 的小Pai 运行列为“需查看”卡（`my-work.tsx` 第 93、133–137 行附近）。**这部分已领先。**
- **差距与建议（中）**：需查看卡现在只给“查看运行”跳转。建议在卡片上直接显示待确认候选的数量和摘要，独立组少于 3 条时允许就地确认（T1 语义不变，只是入口挪到卡片上）。

### 3.8 引用、可解释与归因，以及“说人话”

- **行业**：Linear 悬停显示建议理由；Notion 2026-10 起版本历史区分人和 agent；Linear 2026-07 推出文本归因。
- **PDOS**：过程面板、引用逐字核对、运行详情和回执（v1.1 §05.4、§06.6.3、§06.14），以及“自动 / 一次确认 / 具名决定”三词档位（B18）。在可解释性上是领先的。
- **差距与建议（高，界面层，不改业务）**：业务用户看到的内部术语太多。`pdos-next/web/src/components/my-work-attention.tsx` 的注意卡上直接显示“固定来源版本 vN”“当前办理授权有效至”，折叠区里还有“责任关系 {原始代码}”“稳定任务 {id}”。卡片唯一的动作是“查看原提案/查看原项目”跳转，没有就地主动作。v1.1 §05.2 要求“主动作只显示当前真实可执行的动作”，§05.1 要求“前台不展示内部架构”。建议：
  1. 卡片主区只回答 §05.2 的七个问题：发生了什么、哪一版、为什么与我有关、谁负责、下一步、证据、AI 做了什么。版本号和授权期限放进“来源与版本”折叠区，并改用业务语言（例如“按定义 v3 执行”）。
  2. 卡片上提供当前可执行的主动作（接收、验收、确认、补缺项），不可执行时写明原因。
  3. 键盘分诊（j/k 移动、e 办理、s 稍后），参考 Linear inbox 的习惯；v1.1 §05.11 已要求主要操作支持键盘。

### 3.9 记忆与个人图谱

- **行业**：Glean 个人图谱可看、可改、可删；Copilot 的“已保存记忆”管理页；Notion 经 MCP 同步 agent 记忆；aily 沉淀记忆、自动学习；ClickUp 宣称“无限记忆”。
- **PDOS**：五层记忆，每条记忆有来源、版本、作用域、有效期、敏感度和撤回标记；项目事实从领域查询重建；私人对话不因 Agent 读过而共享（v1.1 §06.8）。设计严谨。
- **差距与建议（中）**：v1.1 §05.3 的页面表里**没有用户可见的“小Pai 记得什么”页面**。建议在小Pai 会话管理旁加一个“我的偏好与记忆”视图：列出个人偏好（例如“周报用表格”“默认按 6 个市场比较”）和当前工作短记忆，每条显示来源、作用域、有效期，可编辑和撤回（撤回按 §06.8 传播）。项目和产品经验仍走“候选 → 适用性验证 → 发布”，不在这里编辑。这是 §06.8 在界面上的落点，可能只需在 §05.3 页面表中补一行，要不要写成 P 记录由用户决定。

### 3.10 企业检索、连接器与 MCP（双向）

- **行业**：Rovo Search 免费；Notion 企业检索覆盖 Slack/Drive/Jira/Teams 等，Agent 可连 150 多个 MCP 工具；**各家同时对外提供 MCP Server**，例如 Linear MCP（企业托管授权）、Rovo MCP Server、飞书项目 MCP（40 多个工具，OAuth）、monday MCP、Asana 的 Claude/ChatGPT/Gemini 连接器；钉钉已把核心产品做成 MCP。
- **PDOS**：消费 MCP，由管理员维护允许清单，按技能或规则逐项授权，读为 READ、写外部为 T2，返回内容按不可信内容隔离（v1.1 §06.6.2）；站内有个人检索（`pdos-next/server/pdos_next/personal_search.py`）和 ⌘K（B19）。**PDOS 本身不对外提供 MCP。**
- **差距与建议**：
  1. （高，与 3.6 同一决策）钉钉文档、听记、待办的只读 MCP。CRM（GoodJob）只读引用客户和商机编号，PDOS 不双写（v1.1 §07.9）。
  2. （低，需用户确认）**对外只读 MCP Server**：让员工在钉钉 AI 助理或其他助手里查询“我的项目状态”“某样件的测试结论”，走与界面相同的权限和领域只读查询。这不违反“只有一个 Agent”（外部助手不是 PDOS 内部 Agent），但会扩大信任边界和出站面，应在 S5 之后再评估。

### 3.11 移动端与在 IM 内办理

- **行业**：Linear iOS 支持 Triage 和文档编辑（2026-07/09）；Notion iOS Agents 应用（2026-09）；钉钉和企业微信本身就是移动入口。
- **PDOS**：移动优先覆盖交样/接收、拍照上传、现场情况、结果确认、例外和查看资料；正式动作必须在线校验，离线不宣称成功（v1.1 §05.9）；拓扑中有“授权钉钉轻入口”（v1.1 §07.1 第 1122 行）。
- **建议（中，随 3.6 的决策）**：用钉钉工作通知和互动卡片承载两件事：注意项提醒（含深链）和**低风险 T1 一次确认**（例如“确认登记：供应商承诺 10/28 到样”）。确认动作由 PDOS 服务端在线校验，卡片只是入口。具名决定（T2）不放在卡片里，只在卡片上定位到正式入口（与 B19 命令面板“不扩权”的原则一致）。不做原生 App。

### 3.12 计费与成本治理

- **行业**：额度制已成主流（Linear AI credits、Notion credits、Rovo credits、Asana AI Studio credits、monday credits、ClickUp Super Credits），配套 80%/100% 告警、按用户/agent/Loop 设限、用量浏览器。负面信号有：Atlassian 超额默认开启；Asana 额度用完后工作流停止；Notion 收费后成本难预测。
- **PDOS**：Run 和 AutomationRule 都有预算，取消时结算并释放名额（v1.1 §06.4、§06.11）；AI 工作详情显示费用（v1.1 §05.3）；过程面板不显示 token（B18）。当前模型服务商是 MiniMax（P26）。
- **差距与建议（中）**：增加管理员的“AI 用量与费用”视图：按用户、技能包、自动化规则汇总费用（以金额显示，不显示 token，与 B18 一致）；设租户、用户、规则三级上限，80%/100% 告警；**超额默认关闭**，到上限时 AutomationRule 按既有规则停止并聚合为一条注意项，不悄悄降级换模型（v1.1 §06.9 不自动转发给任意备用模型）。

### 3.13 信任、噪音与第二道检查

- **行业**：Notion “Review for me” 用第二个模型检查动作；Asana 调查显示 64% 认为不可靠；workslop 让接收者平均每次多花约 2 小时；Linear 明确标注“AI 摘要可能有错”；Rovo 社区反馈只读可靠、生成不可靠。
- **PDOS**：`verify` 节点做 schema 校验、引用逐字核对、数值交确定性引擎复算、档位与范围复核（v1.1 §06.2）；资格按“租户 × 技能包 × 模型版本”管理，T0 持续抽检（§06.12）；反馈与运行版本关联（§06.14，前端 `pdos-next/web/src/components/pai/run-feedback.tsx` 已实现）。
- **建议（低）**：不必引入第二个模型做安全审查，确定性 verify 更可靠。可以借鉴的是**按用户统计“净减负”**：每条 AI 草稿被采纳原样、改后采纳、丢弃的比例，在 AI 工作详情和资格评审中可见。§06.12 已要求记录“修改/撤回、净减负”，只缺一个面向产品负责人的汇总视图。

## 4. 用户期待信号（正面与负面）

| 信号 | 来源 | 对 PDOS 的含义 |
|---|---|---|
| 64% 员工认为 AI agent 不可靠；agent 出错时 39% 认为无人负责；只有 19% 组织跟踪错误 | Asana 2025 Global State of AI at Work（厂商调查） | 坚持人负责制和错误可追溯；把“错误与撤回统计”做成可见指标 |
| 40% 员工上月收到 workslop，平均每次处理约 2 小时 | HBR / 斯坦福社交媒体实验室 + BetterUp（2025-09） | 状态更新和周报草稿必须基于回执逐句可溯源，不写空话 |
| 超 40% 的 agentic 项目将在 2027 年底前被取消；“agent washing” | Gartner（2025-06） | 不做“万能 agent 搭建器”，聚焦 NPI 具体闭环 |
| 约 95% 的企业 GenAI 试点没有可衡量回报，原因是工具与工作流的“学习鸿沟” | MIT NANDA（2025，二手报道） | AI 必须嵌入对象和流程（PDOS 已如此），并能记住工作上下文 |
| 多轮业务任务成功率约 35%，约一半失败是因为不追问缺失信息 | Salesforce CRMArena-Pro | 支持 Grill me 式的关键追问，以及正式结论留给人 |
| 只读和归类动作很准，生成新内容容易编造（如 OKR 编造） | Atlassian 社区 | T0 只放可逆的草稿和关联；生成内容一律标“AI起草” |
| 额度是黑盒；担心花在“理解你在跟它说话”上 | Asana 论坛（AI Teammates beta） | 费用按运行可见、可设上限 |
| 成本难预测（单次 1–30 credits，有团队月花约 $1,500） | Notion 第三方评测 | 同上，另外规则要有冷却和最大运行次数 |
| Copilot 付费席位约占商业用户的 3.3%，“席位不等于使用” | 微软财报及分析 | 通用助手难以证明价值，领域内 AI 更易被用起来 |
| Slackbot 内部 80% 持续使用 | Salesforce（厂商宣称） | IM 内的个人 agent 黏性高，支持把钉钉作为触达面 |
| 接受 1–4 分钟的分诊延迟以换取质量 | Linear 文档 | 后台类建议不必追求秒级，交互命令仍按 p95 秒级（AGENTS 第 7 条） |
| 需要“Priority”标签区分要处理和可以等的 | Linear 2026-09 | 注意项按动作类型分诊之外，还要有“今天必须”的排序依据（到期、阻塞下游） |
| aily 响应不稳定，复杂任务拆解待提升 | 第三方分析（AI 生成，可信度低） | 国内大厂的 agent 也在早期，PDOS 不必追“全能”定位 |

## 5. 功能缺失与优化建议汇总（按优先级）

| # | 建议 | 优先级 | 对目标企业的价值 | 是否触碰冻结设计 |
|---|---|---|---|---|
| 1 | 钉钉定为只读 MCP 连接器：消息转交小Pai、听记纪要导入、待办和日程只读 | 高 | 让 IM 和会议中的承诺、问题、决定进入 PDOS，是四时间和承诺规则能“吃到真实数据”的前提 | **需用户确认**（确认稿第 331 行“暂缓”） |
| 2 | 注意卡“说人话” + 就地主动作 + 键盘分诊 | 高 | 降低一线工程师和品质人员的学习成本；办理不必跳页 | 否，是对 §05.1/§05.2 的实施修正 |
| 3 | 状态更新定时起草（逐句溯源）+ 个人周报草稿 | 高 | 替代每周手工整理进度表 | 否（S5 / P18 范围内） |
| 4 | OEM 客户周报版（外发 T2，复用固定包） | 中 | OEM 客户通常要求周报 | 需与 S4 外部移交对齐，建议写确认记录 |
| 5 | NPI 预置 AutomationRule 模板（齐套 T-3、承诺到期跟催草稿、测试失败建 Issue 并去重、滑期影响清单、ECR 影响待办） | 高 | 主动能力开箱即用 | 否 |
| 6 | 每日简报（代码聚合，可不用模型）经钉钉推送 | 中 | 管理层和项目负责人在手机上看到“今天必须处理的” | 依赖第 1 项 |
| 7 | 进入物分诊建议（型号/项目/负责人/重复项 + 理由，可按类型显示/自动/隐藏） | 中 | 售后和现场反馈自动合并到对应 Lot 和样件 | 可能需要确认关联动作的档位 |
| 8 | AI 风险线索 → 风险候选（来自聊天、纪要、测试趋势），人确认后才进入规则 | 中 | 提早发现“供应商口头推迟” | 否，保持 P17；风险候选进入现有 `project_risk` 领域 |
| 9 | “我的偏好与记忆”可见、可改、可撤回 | 中 | 建立信任，减少重复交代 | 可能需在 §05.3 页面表补一行 |
| 10 | AI 用量与费用视图 + 三级上限 + 超额默认关闭 | 中 | 控制 MiniMax 费用，避免规则风暴 | 否 |
| 11 | 待确认候选在卡片上就地确认（独立组少于 3 条） | 中 | 减少点击 | 否 |
| 12 | 净减负与采纳率汇总视图 | 低 | 用于资格评审和说服管理层 | 否（§06.12 已要求记录） |
| 13 | 对外只读 MCP Server | 低 | 员工可在钉钉助手里查 PDOS | **需用户确认**，S5 之后再评估 |
| 14 | 移动端语音转写候选（品质接收、现场异常） | 低 | 车间不方便打字 | 否（§05.9 已规定） |

## 6. 不建议照搬的做法

- **AI 健康分或风险分**（monday 按严重度排序、飞书风险评级）：与 P17 冲突，会让门禁评审被模型分数左右。
- **Agent 自动对外发布或发送**（Loops 自动发 Slack）：内部通知可以，状态更新的发布和对外发送必须具名（P18、§06.5）。
- **多 agent 画廊或通用 agent 搭建器**（Asana Teammates、ClickUp Super Agents、悟空 OPT）：与“只有小Pai”的拓扑冲突（AGENTS 不可协商项 6）。PDOS 的对应物是技能包和规则模板。
- **“无限记忆”**：不带来源的记忆在承认和认证场景中无法追溯。
- **超额计费默认开启**：与“预算硬上限”的治理风格冲突。
- **自建会议录音和转写**：钉钉听记已经成熟，重复建设没有收益。
- **看板拖拽换阶段**：已由 B3 禁止，竞品这种交互在 NPI 门禁中会造成“伪推进”。

## 7. 主要来源

- Linear：[Linear for Agents](https://linear.app/changelog/2025-05-20-linear-for-agents)；[Agent Interaction SDK](https://linear.app/changelog/2025-07-30-agent-interaction-guidelines-and-sdk)；[Agents in Linear 文档](https://linear.app/docs/agents-in-linear)；[AIG](https://linear.app/developers/aig)；[Triage Intelligence](https://linear.app/docs/triage-intelligence)；[Product Intelligence 预览](https://linear.app/changelog/2025-08-14-product-intelligence-technology-preview)；[Asks 文档](https://linear.app/docs/linear-asks)；[Intercom/Zendesk/Gong 代理](https://linear.app/changelog/2025-12-11-linear-agent-for-intercom-zendesk-gong)；[Pulse](https://linear.app/changelog/2025-04-16-pulse)；[Priority inbox](https://linear.app/changelog/2026-09-03-priority-inbox)；[Introducing Loops](https://linear.app/changelog/2026-07-20-introducing-loops)；[Loops for product management](https://linear.app/changelog/2026-09-14-loops-for-product-management)；[Changelog 首页](https://linear.app/changelog)；[pricingsaas 追踪（第三方）](https://pricingsaas.com/companies/linear/diffs/2026W25)
- Asana：[AI Studio 定价](https://help.asana.com/s/article/ai-studio-pricing)；[Smart status](https://help.asana.com/s/article/smart-status)；[AI Teammates 帮助](https://help.asana.com/s/article/ai-teammates)；[Computerworld 报道](https://www.computerworld.com/article/4063082/asana-puts-ai-teammate-agents-to-work.html)；[Spring 2026 Release](https://asana.com/inside-asana/spring-release-2026.md)；[Winter 2026 Release](https://asana.com/inside-asana/winter-release-2026)；[AI Teammates beta 论坛](https://forum.asana.com/t/an-early-look-at-ai-teammates-aka-what-you-might-be-wondering-already-after-the-announcement/1102527)；[State of AI at Work 报道](https://www.unleash.ai/artificial-intelligence/asana-64-of-employees-believe-ai-agents-are-unreliable-calling-for-more-training-clarity-and-guardrails)
- Notion：[3.0 发布](https://notion.com/releases/2025-09-18)；[2.51 会议纪要与企业检索](https://www.notion.com/releases/2025-05-13)；[Releases](https://www.notion.com/releases)；[Custom Agent 定价](https://www.notion.com/help/custom-agent-pricing)；[2026-10-19 博客](https://www.notion.com/blog/notion-ai-more-for-less)
- Atlassian：[Rovo 授权](https://www.atlassian.com/licensing/rovo)；[Team ’26 Teamwork Collection](https://www.atlassian.com/blog/company-news/teamwork-collection-team-26)；[Teamwork Graph 开放新闻稿](https://www.nasdaq.com/press-release/atlassian-opens-its-teamwork-graph-power-agentic-work-across-enterprise-2026-05-06)；[Loom 会议与 bug](https://www.atlassian.com/blog/loom/turn-meetings-and-bugs-into-action)；[Product Collection](https://www.atlassian.com/collections/product)；[Rovo 社区：OKR 幻觉](https://community.atlassian.com/forums/Rovo-questions/Rovo-OKR-Generator-Hallucinations/qaq-p/2917086)；[Rovo 社区经验](https://community.atlassian.com/forums/Atlassian-AI-Rovo-discussions/Exploring-Atlassian-Rovo-AI-Experiences-Tips-and-Challenges/td-p/3213192)
- monday.com：[AI Credits](https://support.monday.com/hc/en-us/articles/29544502265746-AI-Credits)；[Agent Factory](https://support.monday.com/hc/en-us/articles/29545836087570-Create-a-Digital-Workforce-with-Agent-Factory)；[风险管理营销页](https://monday.com/w/use-cases/risk-management)
- ClickUp：[Super Agents 发布](https://clickup.com/blog/super-agents-launch/)；[Super Agent 触发与知识](https://help.clickup.com/hc/en-us/articles/37092796379927-Super-Agent-instructions-triggers-tools-and-knowledge)；[ClickUp 更新汇总](https://clickup.com/learn/topic/project-management/tools/clickup/news/)
- Microsoft：[Planner Agent 更名与推广 MC1250279](https://mc.merill.net/message/MC1250279)；[RM516576](https://mc.merill.net/message/RM516576)；[Researcher/Analyst GA](https://m365admin.handsontek.net/?p=14281)；[Copilot Memory MC1158329](https://mc.merill.net/message/MC1158329)；[1,500 万付费席位分析](https://www.directionsonmicrosoft.com/blog/microsoft-claims-15-million-paid-m365-copilot-seats)；[Agent 365（第三方）](https://www.epcgroup.net/blog/microsoft-agent-365-general-availability-may-2026-registry-sync-aws-google-cloud)
- Salesforce：[Slackbot GA](https://investor.salesforce.com/news/news-details/2026/Salesforce-Announces-the-General-Availability-of-Slackbot--Your-Personal-Agent-for-Work/default.aspx)；[TechRepublic 报道](https://techrepublic.com/article/news-salesforce-ai-assistant-release)；[CRMArena-Pro 论文](https://arxiv.org/abs/2505.18878)；[SaaStr 定价分析](https://www.saastr.com/salesforce-now-has-3-pricing-models-for-agentforce-and-maybe-right-now-thats-the-way-to-do-it)
- Glean：[2026-02 Assistant 报道](https://thelettertwo.com/2026/02/17/glean-assistant-proactive-ai-coworker/)；[Glean 新闻稿](https://www.glean.com/jp/press/gleans-latest-ai-assistant-moves-every-employee-from-insight-to-execution)
- 飞书：[飞书项目开放平台焕新（量子位）](https://www.qbitai.com/2026/04/406026.html)；[新华网报道](https://www.news.cn/tech/20260424/c6ac4bb20b2a4588b83824a4c7b8dc88/c.html)；[飞书 AI 项目管理实战指南](https://www.feishu.cn/content/article/7603309198601538781)；[飞书企业级 Agent 发布（量子位）](https://www.qbitai.com/2026/03/389311.html)；[飞书 aily](https://www.feishu.cn/content/3d5z9ttt)
- 钉钉：[AI 钉钉 2.0（36氪）](https://www.36kr.com/p/3728259637607553)；[钉钉发布多款 AI 硬件（量子位）](https://www.qbitai.com/2026/03/389301.html)；[AI 表格透视表与群 Agent（量子位）](https://www.qbitai.com/2026/03/383349.html)；[dingtalk-mcp（第三方收录）](https://mcpservers.org/servers/open-dingtalk/dingtalk-mcp)；[AI 听记体验（第三方）](https://www.woshipm.com/share/6265011.html)
- 企业微信：[企业微信 5.0（新华网）](https://www.news.cn/tech/20250820/fbe9a69fd7a742629cf8275238bb7b91/c.html)；[5.0.9 报道](https://www.yzwb.net/news/kj/202606/t20260625_365880.html)
- 行业：[Gartner 40% 取消预测](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)；[workslop（Axios）](https://www.axios.com/2025/09/24/ai-workslop-workplace-efficiency-study)；[MIT NANDA（Fortune）](https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/)

## 附：本报告引用的 PDOS 位置

- 设计：`docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md` §01.6–§01.7、§02.11–§02.12、§05.1–§05.12、§06.1–§06.14、§07.9；确认稿 `docs/design/2026-10-08-pdos-next-design-confirmation.md` P17–P20、P22、P26 与第 331 行；S5 合同 `docs/design/2026-10-18-pdos-next-s5-project-work-contract.md` 第 5、17 行。
- 代码：`pdos-next/web/src/components/my-work.tsx`、`pdos-next/web/src/components/my-work-attention.tsx`、`pdos-next/web/src/components/automation-rules.tsx`、`pdos-next/web/src/components/pai/run-feedback.tsx`、`pdos-next/server/pdos_next/personal_search.py`、`pdos-next/server/pdos_next/domain/automations/`、`pdos-next/contracts/operations.json`、`pdos-next/contracts/auxiliary-operations.json`。`pdos-next` 的 server 和 web 中检索不到钉钉相关代码。
