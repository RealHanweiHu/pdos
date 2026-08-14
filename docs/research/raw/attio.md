# attio

## summary
Attio 的核心赌注是"数据模型灵活性本身就是产品":Objects(标准+自定义)承载身份,Records 是行,强类型 Attributes 是列,Lists/Entries 把"流程状态"从"实体本体"中剥离——同一 record 可进多个 list、携带各自的流程属性而不污染本体。AI 不是聊天框贴皮,而是挂在结构化模型上:AI attributes 让字段"由 agent 填充",Call Intelligence 把通话实时转成结构化字段,2026 年 6 月 Workflows 重建为"AI agent 编排引擎"(自然语言生成流程、agent 继承执行人权限、按 token 计费)。底层是 Rust 查询引擎+实时同步(峰值 25 万事件/分钟)和 Universal Context(graph-relational+语义索引+外部一致性,为上万并行 agent 服务,经 MCP 对外开放)。工程上自建 Thread Agent 框架(多模型抽象、Jest 式 evals、周处理 10 亿 token)。对项目管理系统的启示:用"对象=项目/任务/交付物,列表=阶段门管线"复刻身份/流程分离,让 AI 以结构化属性和权限受限 agent 的形式进入系统。

## positioning
定位为"AI-native CRM",对抗 Salesforce/HubSpot 的僵化 schema 与后贴式 AI。差异化三支柱:(1) Notion/Airtable 式灵活数据模型——创始人 Nicolas Sharp:"数据模型应该迁就用户,而不是反过来",源于前身 Fundstack 的教训"同一行业内也没有 one-size-fits-all";(2) 实时数据引擎——CTO Alexander Christie 称"数据新鲜度是杀手特性",先花三年 stealth 磨同步引擎再发布;(3) AI 作为一等公民——从 AI attributes(2024.8)→ Call Intelligence(2025.4)→ Ask Attio(2026.2)→ agent 编排 Workflows(2026.6),路径是"先把数据做成 AI 可消费的结构,再让 agent 进来",而非先做聊天机器人。7 年只靠 product engineer 不设 PM、$23.5M Series A、数千付费客户,是"工程驱动+设计驱动"打法的代表。

## data_model
五层分层:Objects(表)→ Records(行)→ Attributes(强类型列:text/number/select/currency/关系等)→ Lists(对 records 的引用集合)→ Entries(record 在某个 list 里的实例)+ Views(table/kanban/record page)。关键设计决策:(1) 标准对象只有 People/Companies 默认开启,Deals/Users/Workspaces 按需启用,其余交给自定义对象+关系属性——"少量精品预置+无限自定义兜底";(2) 身份与流程分离:object attributes 存在 record 上(如名称、负责人),list attributes 存在 entry 上(如阶段、评审结论)——同一 record 可进多个 list,甚至在同一 list 出现多次(如一个候选人申请两个岗位),各 entry 互不干扰;(3) attribute 是 AI 的挂载点:任何字段可开 AI autofill,AI 输出被 schema 约束;(4) 底层 Particle 框架:graph-relational 格式统一结构化数据+enriched 数据+非结构化内容(邮件/笔记/录音),语义嵌入与事务数据保持 External Consistency(最高级事务一致性),这就是 Universal Context——agent 无论来自站内还是经 MCP 的 Claude/ChatGPT,读到的都是同一份一致的图。迁移到 PM 域:项目/任务/交付物/人员做标准对象;"阶段门评审管线"做 list,交付物 record 进入管线产生 entry,评审状态/结论/gate 决议是 entry 属性——交付物本体保持唯一事实,同一交付物可同时挂在多个项目或多轮评审里。

### idea: Object/Record 与 List/Entry 的身份-流程分离(最大护城河)
record 是唯一实体事实,entry 是它在某条流程里的投影,携带该流程专属的 list attributes(如 Status、Hiring Manager)。官方帮助文档明确:'向 list 添加数据不改动原始 record';一个 record 可在同一 list 出现多次并持有不同值。这让'多个团队围绕同一份数据跑不同流程互不干扰'成为架构属性而非功能补丁,也是它被认为比 HubSpot 式固定 pipeline 更根本的原因。
- transfer: 交付物/任务作为 object,'NPD 阶段门管线''设计评审排期''供应商认证流程'各自作为 list。同一份 DFMEA 交付物可同时进入 Gate 2 评审 list(entry 属性:评审结论/遗留项)和文档受控发布 list(entry 属性:受控编号/发放范围),互不污染。解决制造业 PM 的经典痛点:同一交付物在不同流程语境下状态不同。
- src: https://attio.com/help/reference/attio-101/attios-data-model/understanding-lists

### idea: 标准对象精品化+自定义对象兜底+关系属性连接
只默认开 People/Companies 两个对象,Deals/Users/Workspaces 是'可启用'的标准对象(按销售型 vs PLG 型公司分场景),其余全部自定义。标准对象自带打磨过的系统属性与 enrichment;自定义对象与标准对象通过 relationship attributes 双向连接,'custom objects all the way down'被 Aakash Gupta 的深度分析认定为对僵化竞品的根本性架构优势。
- transfer: 默认对象=项目/任务/人员;可启用标准对象=交付物/评审/风险/变更(NPD 场景开,轻量场景不开——正好对应 NPD 模板分档思路);自定义对象留给模具、认证、样机批次等行业特有实体。避免'为最重场景设计导致轻场景臃肿'。
- src: https://attio.com/help/reference/attio-101/attios-data-model/understanding-attio-data-model

### idea: 强类型 attribute 作为 AI 的挂载点(AI autofill 是字段的一种填充方式)
AI attributes 的创建流程是:先选常规类型(text/select/multi-select/currency/number)→ 打开'AI autofill'→ 选任务(Research/Classify/Summarize/Prompt)→ 写指导语。AI 输出被字段 schema 约束(select 只能落在选项内),可对单 record 悬停重算或对整列批量重算。AI 不是旁挂的聊天,而是数据模型的原生填充机制。
- transfer: 交付物对象加'完成度评估''与模板差距摘要'AI 属性;任务加'阻碍原因分类'(受限 select,AI 只能归入预定义类);评审对象加'遗留风险摘要'。关键迁移点:让 AI 写进受 schema 约束的字段而非自由文本,评审员可整列批量重算,审核成本低。
- src: https://attio.com/blog/introducing-ai-attributes

### idea: Workflows = 可视化画布 + 六类 block 库 + agent 作为 block
块分六类:Triggers(record command 按钮/记录增改/属性变化/webhook/定时)、AI & Agent(Custom Agent 可选择性授予数据+MCP 工具+web 访问、Web Agent、Classify、Summarize)、Logic(Filter/If/Switch)、Actions(增删改记录/任务/序列)、Calculation(Execute Code 跑 JS、SQL 查询-企业版、公式/聚合)、Utility(Loop/Parse JSON/HTTP/Round Robin/Delay)。画布支持 Miro/FigJam 式多人实时协作。2026.6 重建后:用一句话让 Ask Attio 生成整条 workflow;Custom Agent 支持结构化输出(定义 schema,agent 只返回这些字段,精确对接下游 block)。
- transfer: 阶段门自动化天然适配:trigger='交付物状态变为已提交'→ AI block 预检查完整性(结构化输出:缺项清单)→ If 分支 → 创建评审任务+Round Robin 分配评审人 → gate 决议后批量推进。'record command'模式尤其值得抄:在交付物页面放一个按钮触发'预审 agent',人主动召唤而非 AI 乱动。
- src: https://attio.com/help/reference/automations/workflows/workflows-block-library

### idea: Human-in-the-loop 三原则:透明、权限继承、可控
2026.6 agent 化重建时明确三条安全设计:(1) Transparency——完整 run history 展示 agent 每步决策;(2) Permissions——agent 继承其 assignee(执行人)的访问边界,不能越权读写;(3) Control——用户可随时通过 AI chat 或画布编辑 prompt、替换 block。口号是'Your reps own the deal. Agents do the work to help them win'(代表拥有交易,agent 只是干活)。
- transfer: 对制造业 PM 更关键:gate 决议、金样本确认这类红线动作,agent 必须以'某个人的身份+该人的权限'运行且留完整审计轨迹。与四眼原则/红线设计直接兼容——agent 永远不能是决议的签署主体,只能是准备材料的执行者。
- src: https://attio.com/blog/orchestrate-revenue-agents

### idea: Universal Context:一个为上万并行 agent 设计的一致性数据底座
工程博客提出'agent-centric model of the universe':人类用户并发有限,agent 可上万并行,因此语义嵌入必须与事务数据保持 External Consistency(否则 agent 读到过期向量做错决策)。Particle 框架用 graph-relational 格式统一结构化字段、enriched 数据和非结构化内容(邮件/录音/笔记),全文+语义检索同库;经 MCP server,Claude Code/ChatGPT 上的外部 agent 获得与站内 agent 相同的一致性保证。
- transfer: PM 域的对应物:把任务/交付物/评审纪要/会议记录/图纸变更说明统一进一个 agent 可查询的上下文层,而不是'结构化数据在库里、文档在网盘里'。这与 ERP Agent Gateway 的'结构出门数据留库'思路互补:先建统一上下文层,再控制出门粒度。MCP 对外开放意味着客户可用自己的 Claude 查项目状态——平台边界变成协议边界。
- src: https://attio.com/engineering/blog/introducing-universal-context

### idea: Thread Agent 框架:AI 作为一等架构概念而非散落的 prompt 调用
工程博客《You can't just prompt your way to great AI features》:拒绝'到处散落 OpenAI 调用',自建框架使'生成 workflow 名字和总结通话用同一套方式构建'。要点:agent 定义是含 variants(模型/指令/工具/输出 schema)的 POJO;多 provider 抽象支持按用例动态选模型、A/B、降级;全链路按 workspace/feature 归因(单周约 60 万 completions、4 万 tool runs、10 亿+ token);Jest 式 eval 框架:每用例多次运行、自定义 scorer、variant 对比矩阵含成本/延迟;workspace 间 round-robin 防资源霸占,实时请求(通话洞察)优先于批量任务。
- transfer: 给 PM 系统加 AI 前先定框架纪律:统一的 agent 定义格式+eval 集(如'阻碍分类准确率''评审预检漏检率')+按项目/功能的 token 归因+实时交互优先于夜间批量。否则每个 AI 功能都是一次性 prompt 工程,无法回归测试。
- src: https://attio.com/engineering/blog/you-cant-just-prompt-your-way-to-great-ai-features

### idea: Ask Attio 的上下文推断:agent '看见'用户屏幕上的东西
技术博客披露六个机制,最有迁移价值的是 interests:前端持续声明'当前屏幕可见什么'(某通话/某公司页),后端将其水合成富结构上下文随消息注入,用户无需手动圈选。另有:树状会话(消息引用父节点,可编辑分支不丢历史)、运行时按用户权限+feature flag 构建 capability registry、多 provider 请求级 failover、流式感知 parser 抑制未闭合语法、Zod schema 定义的结构化 UI 组件(record card/音频播放器)在聊天流中渐进渲染。
- transfer: 项目助手应自动知道'用户正开着 Gate 3 评审页/某任务详情',回答'这个交付物还缺什么'时无需用户粘贴上下文。回复中直接渲染可点击的任务卡/交付物卡而非纯文本。capability registry 按角色收敛工具集:评审员的助手没有'改状态'工具。
- src: https://attio.com/engineering/blog/ask-attio-a-technical-look-at-our-new-agent

### idea: 先磨引擎后发布:实时性是产品定位而非优化项
《Where's the technical challenge in CRM anyway?》披露:Rust 查询引擎每秒数千查询、PB 级数据、峰值 25 万事件/分钟的多渠道交互流实时入库做语义 enrichment;50+ 集成应用每分钟 2 万次 API 调用。CTO:'数据新鲜度是杀手特性——用户连上邮箱日历的那一刻就要立即看到洞察'。前端配套自研 React Data List 虚拟化列表库保证大表滚动性能。公司 stealth 三年先建同步引擎。
- transfer: PM 域同理:甘特图/看板的实时协作与'连上 ERP/PLM 后立即出画像'的首体验决定'AI-native'可信度。大项目任务表必须虚拟化。教训反面:Attio 无 SLA 导致宕机丢数据的投诉,说明实时系统必须配可用性承诺。
- src: https://attio.com/engineering/blog/where-s-the-technical-challenge-in-cr m-anyway-

### idea: API-first 五件套:REST+webhooks+App SDK+SQL+MCP
开发者平台五层:REST API(读写全量数据模型,attributes/objects/lists 皆可 API 创建)、webhooks 实时事件订阅、App SDK(TypeScript React 应用直接嵌入 Attio 界面,server functions 回调 REST)、SQL 直查 workspace 数据(企业版,也做成 workflow block)、MCP server 接入 AI 生态。CTO 把 App SDK 定位为'AI 代码生成的编译目标'——让 agent 用 npm 生态为客户现场生成自定义能力,而非发明专有语言。
- transfer: PM 系统的 schema(对象/属性/管线定义)本身要可经 API 操作,这是'AI 帮你搭工作区'的前提。SQL 直查解决'报表弱'的逃生舱。'SDK 作为 AI 编译目标'是激进但可借鉴的方向:客户说'我要一个模具寿命看板',agent 生成嵌入式小应用。
- src: https://docs.attio.com/docs/overview

### idea: AI 计费从 flat credits 转向按 token 实际用量
2026.6 重建时宣布'9 /10 的 block run 免费,AI 按实际模型用量计费',替代原先的固定 credit 制。第三方评测中'Plus 档 automation credit 上限'曾是最集中抱怨之一,这次转向等于承认 credit 制在 agent 高频场景下失败。
- transfer: 若 PM 系统内置 AI(如 ERP Agent Gateway),定价直接学结论:确定性自动化(状态推进/通知)免费不限量,AI 步骤按 token 透传+预算上限,避免用户为省 credit 而不敢用自动化。
- src: https://attio.com/blog/orchestrate-revenue-agents

### pattern: AI attributes(字段级 agent 填充:Research/Classify/Summarize/Prompt 四任务) [已上线(2024.8 GA,需 Plus 及以上;是最成熟的 AI 能力,后演化为 workflow 中的 agent blocks)]
在任意对象/list 上建常规类型字段→开启 AI autofill→选任务并写指导语。Research Agent 结合 web 检索与已有 CRM 上下文(公司详情、交互历史、自定义属性)找融资/人事等信息;Classify 在预定义选项内归类;Summarize 把几十个属性压成摘要;Prompt Completion 以已有属性值为上下文回答自定义问题。单条悬停重算或列头整列重算,结果直接写入字段。

### pattern: Call Intelligence(实时通话理解→结构化 CRM 数据) [已上线(2025.4 发布,Pro/Enterprise 档;实时洞察部分较新,字段映射细节官方披露少)]
bot 自动加入 Google Meet/Zoom/Teams,录音同时生成带说话人标签和时间戳的实时转写;按角色可自定义 insight 模板(销售追异议、CS 追满意度、产品收需求),并有 MEDDPICC/BANT/CHAMP 模板把资格化数据直接抽进记录字段;通话结束生成摘要,模板可回放套用到任意历史录音;通话作为原生数据类型进入 workspace,可触发下游 workflow。

### pattern: Ask Attio(嵌入式对话 agent,可检索可执行) [beta 走向成熟(2026.2 GA 后快速迭代:3 月进 Slack、4 月可执行操作、5 月自定义上下文)]
自然语言查询记录/通话/邮件并可直接执行操作(建记录、生成 workflow)。技术上:interests 机制自动注入'用户当前屏幕可见内容'的结构化上下文;树状会话支持编辑分支;运行时按权限/feature flag 组装工具集;多 provider(Anthropic/Vertex/OpenAI)请求级 failover,用户可选默认模型(2026.4 加入 Claude Opus 4.7);回复流式渲染结构化 UI 组件。已进 Slack。

### pattern: Agent 编排型 Workflows(自然语言生成流程+Custom/Web Agent block) [已上线但很新(2026.6.9 整体重建发布,6 月底仍在密集补功能,如 loop 遍历对象数组)]
向 Ask Attio 描述目标即可生成整条 workflow;Custom Agent block 按指令执行任务,可选择性授予 Attio 数据、MCP 工具(Notion/Linear/Fin 等)和 web 访问,支持结构化输出(定义 schema 后只返回这些字段,精确衔接下游 block);Web Agent 做实时网络调研;中途可执行任意 JavaScript;agent 继承 assignee 权限,run history 全程可审计;AI 按 token 计费。

### pattern: Universal Context + MCP(为大规模并行 agent 提供一致性上下文) [基础设施已上线(MCP server 2026.2 发布,Universal Context 为工程博客描述的底层架构),'agent 用 App SDK 生成自定义应用'部分仍偏愿景]
基于 Particle 框架的 graph-relational 存储统一结构化/enriched/非结构化数据,语义嵌入与事务数据保持 External Consistency;站内 agent 与经 MCP server 接入的外部 agent(Claude Code、ChatGPT、Notion agents)读写同一份一致的图,支持跨平台实时协作工作流。

### pattern: Thread Agent 内部框架(所有 AI 功能的统一底座) [内部已成熟运行(单周约 60 万 completions、10 亿+ token),是对外功能质量的幕后保障]
agent 定义为含 variants(模型/指令/工具/输出 schema)的类型化 POJO;provider 抽象支持动态选模型、A/B、降级、限流;每次 LLM/工具调用按 workspace+feature+request 归因;Jest 式 eval(多次运行、自定义 scorer、含成本延迟的 variant 矩阵);生产 trace 逐步展示模型调用/工具调用/子 agent 级联;workspace 间 round-robin 公平调度,实时请求优先于批量。

## ui_patterns
- Cmd+K 打开 30+ 上下文相关 quick actions(随所在页面变化);'/' 全局搜索整个 CRM;单键快捷键:n 新建笔记、t 新建任务、? 查看全部快捷键表——高频动作单键化而非藏在菜单里
- 高信息密度表格 + 自研 React Data List 虚拟化列表库(React/React Native 通用),保证大数据集滚动流畅;被用户形容为'Notion 式美学、Figma 式编辑'
- Record page 三区结构:属性面板 + 关联 lists + 活动时间线;2026.5 整页重建提速,2026.6 时间线降噪(减少无效活动条目)——时间线是 AI 上下文的可视化对应物
- List 的多视图:同一数据 table/kanban 自由切换;kanban 卡片显示 time-in-stage(在此阶段停留时长)暴露瓶颈,支持拖拽批量改阶段——直接可抄到阶段门看板
- Record 页 toolbar 可自定义快捷 action 按钮(record command 触发 workflow),把自动化入口放进实体详情页而非独立的自动化中心
- Workflow 画布支持 Miro/FigJam 式多人实时协作编辑,流程设计本身是协作物
- AI 回复不是纯文本:Zod schema 定义的结构化组件(record card、音频播放器、指示器)在流式输出中渐进渲染,AI 输出可点击可操作
- AI 重算入口极轻:单元格悬停出现重算图标,列头菜单整列批量重算——AI 操作嵌在数据网格的原地交互里

## lessons
- 灵活性的代价是上手成本:多个第三方评测汇总的用户反馈称需数周试错才能搭出稳定的数据模型,'很多人喜欢灵活模型却困在实施'——PM 系统若采用同类架构,必须配行业模板(如 NPD 预置对象+管线)把冷启动做没(delveant.com/blog/attio-reviews, coffee.ai 评测)
- 报表弱是最持久的抱怨:基础报表长期被 gating 在 Enterprise 档,灵活数据模型反而加大了通用报表引擎的难度;Attio 的补救是 SQL 直查+SQL workflow block——启示:灵活 schema 系统要早做分析层,不能只做录入层
- 无 SLA 曾导致用户宕机丢线索且无追索,是'操作后果最重的投诉'——实时协作系统必须配可用性承诺
- 权限粒度不足的具体案例:邮件分享无白名单,'队友对分享敏感'——多团队共用一个数据底座时,分享控制要做到字段/来源级
- 缺统一 inbox、缺表单、缺自动查重:说明'灵活模型'不能替代高频刚需的专用界面;PM 域对应物是'我的待办/待我评审'这类聚合视图必须专门做
- AI 重度 gating 抑制采用:AI attributes 要 Plus+、Call Intelligence 要 Pro+、automation credits 曾限档,2026.6 被迫改为'9/10 block 免费+AI 按 token 计费'——flat credit 定价在 agent 高频场景下被自己否定
- 组织侧:7 年不设 PM、纯 product engineer 文化+stealth 三年先磨同步引擎,证明'基础设施先行'路线可行但极慢;其间三次接近死亡(june.so 的 Attio 史记),资本耐心是前提
- 工程博客直言'不能靠 prompt 堆出好 AI 功能':没有 eval、归因和统一框架的 AI 功能无法回归测试、成本失控——先建框架纪律再铺 AI 功能面

## sources
- https://attio.com/help/reference/attio-101/attios-data-model/understanding-attio-data-model
- https://attio.com/help/reference/attio-101/attios-data-model/understanding-lists
- https://docs.attio.com/docs/objects-and-lists
- https://docs.attio.com/docs/overview
- https://attio.com/blog/introducing-ai-attributes
- https://attio.com/blog/introducing-attio-ai-research-agent
- https://attio.com/blog/introducing-call-intelligence
- https://attio.com/blog/introducing-attio-automations
- https://attio.com/blog/orchestrate-revenue-agents
- https://attio.com/help/reference/automations/workflows/workflows-block-library
- https://attio.com/changelog/2026
- https://attio.com/changelog/2026/what-s-new-in-workflows
- https://attio.com/engineering/blog/you-cant-just-prompt-your-way-to-great-ai-features
- https://attio.com/engineering/blog/where-s-the-technical-challenge-in-crm-anyway-
- https://attio.com/engineering/blog/introducing-universal-context
- https://attio.com/engineering/blog/ask-attio-a-technical-look-at-our-new-agent
- https://attio.com/engineering/blog/react-data-list-building-virtualized-uis-declaratively
- https://attio.com/help/reference/tips-and-tricks/quick-actions
- https://www.news.aakashg.com/p/the-attio-deep-dive-how-it-builds
- https://www.gv.com/news/reinventing-crm-attio-nicolas-sharp
- https://www.june.so/blog/the-epic-story-of-attio
- https://delveant.com/blog/attio-reviews/
- https://www.coffee.ai/articles/attio-crm-reviews-alternatives-2026
- https://www.automationjinn.com/blog/attio-workflows-guide
- https://x.com/attio/status/1907459077266960598

## verification

- [confirmed] 1. Object/Record 与 List/Entry 的身份-流程分离:record 是唯一实体事实,entry 是流程投影,携带 list attributes(Status、Hiring Manager 等);向 list 添加数 | 官方帮助文档逐句可对上:"By adding records to a list, you can include additional data for each one...without altering the original records themselves";"When a record joins a list, Attio creates a list entry. A li | https://attio.com/help/reference/attio-101/attios-data-model/understanding-lists
- [confirmed] 2. 标准对象精品化+自定义对象兜底+关系属性连接:仅 People/Companies 默认开启,Deals/Users/Workspaces 可启用(销售型 vs PLG 型分场景);标准对象自带打磨过的系统属性与 enrichment | 帮助文档确认:People/Companies 默认启用,Deals/Workspaces/Users 需在 Workspace settings 激活;"Each standard object comes with a pre-defined set of attributes"。enrichment 由 https://attio.com/help/reference/managing-yo | https://attio.com/help/reference/attio-101/attios-data-model/understanding-objects
- [confirmed] 3. 强类型 attribute 作为 AI 挂载点:创建流程为选常规类型(text/select/multi-select/currency/number)→开 AI autofill→选任务→写指导语;AI 输出被字段 schema 约 | 帮助文档原句:"When adding a new text, number, currency, select, or multi-select attribute, you can enable AI autofill",五种类型完全对上;流程(开 toggle→选 autofill 类型→写 guidance)一致;重算方式三种:悬停单格点 Run AI autofill、拖选右键批量、列头 | https://attio.com/help/reference/attio-ai/ai-attributes
- [confirmed] 4. Workflows 主体:可视化画布+block 库+agent 作为 block;2026 年 6 月重建;Ask Attio 一句话生成整条 workflow;Custom Agent 支持结构化输出(定义 schema 只返回这 | 块级事实几乎全部核实:triggers 含 Record command/Record created/Record updated/Attribute value changed/Webhook received/Recurring schedule;Custom agent("optional access to Attio data, MCP tools, and the web")、Web | https://attio.com/help/reference/automations/workflows/workflows-block-library
- [wrong] 4b. 块分六类:Triggers / AI & Agent / Logic / Actions / Calculation / Utility | 官方 block library 文档的分组与'六类'说法不符:实际为 Triggers(按 Record/List/Data/Task/Utilities 细分)+ 步骤组 Agent、AI、Record、List、Sequence、Task、Calculation、Condition、Delay、Workspace、Utilities、Third-party,约 13 组。且具体归属矛盾:Ro | https://attio.com/help/reference/automations/workflows/workflows-block-library
- [unverified] 4c. 画布支持 Miro/FigJam 式多人实时协作 | 遍查 2026-06-09 与 06-29 两条 changelog、发布博文(https://attio.com/blog/orchestrate-revenue-agents)、help 的 getting-started-with-workflows 与 create-a-workflow,均无 workflow 画布多人实时协作/协作光标的任何表述。'multiplayer' 一词只在 2 | https://attio.com/changelog/2026/the-new-workflows
- [confirmed] 5. AI attributes 四任务(Research/Classify/Summarize/Prompt)细节:Research 实时检索外部 web;Classify 在预定义选项内归类;Summarize 基于已有属性值生成摘要; | 帮助文档四任务对应为 Summarize record / Web agent / Prompt completion / Classify record;官方发布博文(https://attio.com/blog/introducing-ai-attributes)中叫 Research Agent / Classify Record / Summarize Record / Prompt Co | https://attio.com/help/reference/attio-ai/ai-attributes
- [confirmed] 6. Call Intelligence:bot 自动加入 Meet/Zoom/Teams;实时转写带说话人标签和时间戳;按角色自定义 insight 模板;有 MEDDPICC/BANT/CHAMP 模板;通话结束生成摘要;模板可回放套用 | 帮助文档原句:"Attio generates a real-time transcript with speaker labels and timestamps";会议进行中可实时查看转写与 insights;通话后自动生成 AI Summary。bot 加入三平台由 recording-calls-with-attio 文档确认(Zoom 主持人批准、Meet 需 Admit、Teams 在  | https://attio.com/help/reference/productivity-collaborating/call-intelligence/view-and-manage-call-recordings
- [unverified] 6b. 通话作为原生数据类型进入 workspace,可触发下游 workflow | 前半句成立:通话自动关联参会人 record、可手动关联 deal 等,出现在 Activity/Calls 标签,且 API 有 call transcript 端点(docs.attio.com)。后半句找不到一手来源:官方 workflow block library 的 trigger 列表(Record/List/Data/Task/Webhook/Schedule)没有任何通话类 tr | https://attio.com/help/reference/automations/workflows/workflows-block-library
- [confirmed] 7. Ask Attio:interests 机制注入当前屏幕上下文;树状会话可编辑分支;运行时按权限/feature flag 组装工具集;多 provider(Anthropic/Vertex/OpenAI)请求级 failover;用 | 工程博客逐条对上:interests——"the UI registers an interest. This is a structured declaration of what's currently on screen",后端 hydrate 成关联记录/参与人/时间戳等结构化上下文随消息注入;树状会话——"We modeled Ask Attio conversations as a t | https://attio.com/engineering/blog/ask-attio-a-technical-look-at-our-new-agent