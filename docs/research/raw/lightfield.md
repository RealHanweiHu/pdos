# lightfield

## summary
Lightfield 是 Tome(2500 万用户的 AI 演示工具)创始人 Keith Peiris 与 Henri Liriani(均 ex-Meta)于 2025 年 8 月 pivot 出的 AI-native CRM,2025 年 11 月出 stealth,2026 年 3 月上 Product Hunt(865 赞、当日第 2),数月内约 2,000-4,000 家公司注册,累计融资 $81M(Lightspeed/Greylock/Coatue 等)。其对 AI-native 的定义不是"CRM 会自动更新",而是"为公司建 world model":原始客户交互(邮件/日历/会议录音/Slack/工单)是 source of truth,字段、看板、摘要全是派生视图;数据由 agent 自动进入系统(可回填 2 年历史),改 schema 时 AI 重新分析全部历史数据回填新字段;自动化被视为"理解的结果而非起点"。人的角色变为提供意图、提问和在 "For review" 队列里审批。UI 是"传统表格/管线视图 + agent 对话层 + 审批队列"的混合,并非纯生成式 UI。与 Attio 的分野:Attio 是 data-model-first 的可组合系统(人管理系统),Lightfield 是 automation-first(schema 只是给 AI 的索引)。已知争议:AI 自动创建错误记录/不存在的公司、企业级功能不全、定价偏高且多次调整。

## positioning
定位:面向 founder-led sales 到前 50 人阶段创业公司的"完整替代型" AI-native CRM——一个产品替掉 CRM+Gong/录音工具+笔记工具,而非在旧 CRM 上加 AI 层。差异化路线:(1) 与 Salesforce/HubSpot("在几十年老架构上补 AI")相反,从非结构化会话数据出发反推结构;(2) 与 Attio(control & customization,人主动配置和管理数据模型)相反,主打"CRM 自己填自己",Peiris 明言 Lightfield 的 schema "exists primarily as an indexing mechanism to make AI more effective";(3) 与 Day.ai(叠加在现有工具上的 memory layer)相反,做整体替换。商业上用 flat 全包定价($79/user/月含全部 AI)对打 Attio 的 $29+AI credits 消耗制。明确放弃企业市场:"If you're an enterprise with 500 reps and deeply customized Salesforce instance, this isn't for you… yet"(SaaStr)。

## data_model
Narrative-first 数据层:Peiris 专文《LLMs also prefer stories to graphs and databases》主张放弃知识图谱(图 \"treat the relationships too rigidly\"、模型 \"lacked understanding of why concepts were connected\"),改为维护 \"live-updating chronological stories about people and your relationship with them\",与结构化+非结构化数据一起喂给强模型(文中点名 Claude Opus),让模型自行动态调整细节权重;并用代码执行保证不失真(\"make sure it's not lossy\")。记忆架构四要素:Chronology(何事何序)、Attribution(谁在何时说了什么、回应什么)、Causality(什么行动导致什么结果)、State(trust/risk/momentum/intent 及其变化)。结构化 schema 依然存在但降级为\"让 AI 更高效的索引机制\"(Peiris 语),支持 schema-less 灵活变更+历史全量回填。隐私在对象级:LLM 只能看到当前用户可见的对象。对 PM 系统的启示:项目/任务除结构化字段外应维护一条机器可读的编年叙事流(含归因与因果),这是 AI 回答 why 类问题的基础。

### idea: Reality first:原始交互是 source of truth,字段/看板是派生视图
创始 manifesto 明确:"Summaries, fields, and dashboards are derived views—not the source of truth. Reality comes first." 系统先无损保存每封邮件、每次通话、每场会议的原始痕迹,再从中派生结构。这解决传统 CRM 的致命伤——"it only knows what people remembered to type in"(只知道人们记得录入的东西),CRM 成为 "a tax on learning"。
- transfer: NPD 项目系统里,评审会议录音、邮件、设计变更讨论应作为原始层保存;任务状态、交付物完成度、阶段门检查表都从原始层派生并可溯源。当有人质疑'这个交付物为什么标记完成'时,系统能引用到具体会议/邮件出处。
- src: https://lightfield.app/blog/why-we-built-lightfield

### idea: Schema 变更全量回填:改字段时 AI 重新分析全部历史非结构化数据
Contrary Research 记载:"when users modify or add new fields, the system re-analyzes all historical unstructured data to backfill the new schema",而传统 CRM 改 schema 只影响新记录。配合最多回填 2 年的历史邮件/日历数据,新用户 5 分钟内 CRM 自动建成。
- transfer: NPD 模板演进(如新增'模具风险等级'或'合规检查项'字段)时,AI 可对存量项目的会议纪要/邮件重新抽取回填,老项目不再是空白字段。这直接缓解'模板瘦身/加字段导致历史数据断层'的问题。
- src: https://research.contrary.com/company/lightfield

### idea: For review 审批队列:AI 建议写入,人批准落库
每次客户交互后系统 "suggests CRM record updates for human approval" 而非直接写入;官网有专门的 "For review" surface。Peiris:"We want the human attached to the record update so that you can trust it." 人的角色 = 提供意图 + 提问 + 审批,AI 负责组装数据、分析模式、起草内容、执行代码。
- transfer: PM 系统中 AI 从会议/邮件抽取的'任务完成'、'阻碍出现'、'交付物就绪'应进入待审队列而非直接改状态——与你们'blocked 由人显式设置、不由依赖图派生'的铁律同构。审批留痕即金样本,可持续校准抽取模型。
- src: https://research.contrary.com/company/lightfield

### idea: 自然语言 automation,后台编译为代码执行
SaaStr 现场 demo:Peiris 用一句话 "run this process every time a deal reaches the POC stage without an IT contact" 生成自动化;机制是 "You write and iterate on these in plain language, and they run in Python in the background"。agent 在 sandbox 中执行代码,直接访问 object model,可做批量更新、CSV 处理、自定义报表。
- transfer: 阶段门规则可用自然语言定义:'每当项目进入 EVT 且缺少 DFM 报告时,提醒结构负责人并起草跟催'。规则以可读文本存储、编译为确定性代码执行,规避 LLM 每次实时判断的不稳定性。
- src: https://www.saastr.com/watching-an-ai-native-crm-run-the-full-gtm-loop-live-lightfield-ceo-keith-peiris-demos-a-stalled-deal-an-automation-and-ten-new-prospects/

### idea: 单一 API + agent 继承人的权限,无独立 agent 安全模型
"the agent, the UI, and external systems all share one API";"The agent inherits the human's permissions, so there is no separate agent security model to manage";并且 per-object privacy:"The LLM can only see what each user can see within the CRM"。
- transfer: AI 助手在 PM 系统中应以'代表某个用户'执行,权限完全继承该用户(与一人多岗/四眼红线兼容):agent 不能看到用户看不到的项目,也不能替用户签阶段门。避免为 AI 单独建一套权限模型的复杂度和漏洞面。
- src: https://www.saastr.com/lightfield-just-assembled-a-working-crm-live-on-stage-then-unstuck-a-stalled-deal-in-3-minutes/

### idea: 因果归因式诊断:对比赢单/输单找 pattern,再反向生成流程规则
现场 demo 三步闭环:问 "why is this deal stalled?" → 系统对比全部 closed-won/closed-lost 发现规律(赢单都有 IT 领导早期介入)→ 推荐加 CIO 并起草邮件 → 一句话把该洞察固化为自动化 → 再按赢单画像生成 10 个新 prospect。约 3 分钟解卡一个停滞 deal。
- transfer: '这个项目为什么延期'可用同一机制:对比历史按期/延期项目的原始记录找共性(如打样前未锁 BOM),把结论固化为阶段门检查规则。项目复盘从人工回忆变成可引用证据的归因分析。
- src: https://www.saastr.com/watching-an-ai-native-crm-run-the-full-gtm-loop-live-lightfield-ceo-keith-peiris-demos-a-stalled-deal-an-automation-and-ten-new-prospects/

### idea: AI-CRM 评估五测试 + 三类分级(反 AI-washing 框架)
Lightfield 提出判别真伪 AI-native 的框架——三类:Type 1 "AI bolted onto legacy architecture"、Type 2 "AI autocomplete without a world model"(有转写自动填但无推理)、Type 3 "AI as the foundation—A world model for your business";五测试:Capture(系统知道多少真实发生的事)/ Synthesis(能否跨全库找模式)/ Why(能否解释原因)/ Query(能否自然语言问任何问题)/ Action(理解之后能否行动)。
- transfer: 可直接改造成 AI-native PM 系统的验收标准:系统捕获了多少真实项目活动?能否回答'哪些项目卡在同一个供应商'?能否解释'为什么 DVT 延了三周'?能否自然语言查询?发现风险后能否自动起草跟催/变更单?
- src: https://lightfield.app/blog/the-founders-guide-to-evaluating-an-ai-crm

### idea: MCP-first 集成策略与 agentic 迁移(一小时替换旧系统)
不建成百上千点对点集成,而让 agent 消费各 SaaS 的 MCP server(已接 Notion、Linear、Granola,REST API beta):"Nearly every one of these companies has an MCP server because their customers expect it"。迁移用 agent "build a Python program and run a deterministic migration without hallucination",宣称 1 小时内替换 HubSpot。创始人论断:"when the cost of migrations and integrations approach zero, mediocre products lose their ability to lock customers"。
- transfer: 制造业研发场景对接 PLM/ERP/邮件时,优先做 MCP client + 让 agent 写确定性迁移脚本(生成代码后确定性执行,而非 LLM 逐条实时搬数据),可大幅降低从 Excel/旧系统迁入的门槛——迁移成本本身就是采用率的最大障碍。
- src: https://lightfield.app/blog/the-dissolution-of-integrations-and-data-moats-in-saas

### idea: 默认干净数据库:outbound 联系人有回复才入库
"Outbound contacts only sync when someone replies. The database stays clean by default, not by quarterly cleanup projects"——用入库门槛而非事后清理保证数据质量。
- transfer: PM 系统同理:AI 侦测到的'疑似新任务/新风险'不应直接建实体,应设置确认门槛(有人认领/有后续活动才转正),防止 AI 把系统灌满噪音实体——Lightfield 自己踩过的坑(自动创建不存在的公司)反证了这一点。
- src: https://www.saastr.com/watching-an-ai-native-crm-run-the-full-gtm-loop-live-lightfield-ceo-keith-peiris-demos-a-stalled-deal-an-automation-and-ten-new-prospects/

### pattern: Ambient capture(环境捕获,数据自动进入系统) [已上线]
连接 email、calendar、Slack、原生会议录音器、支持工单后,系统自动创建 account/contact/opportunity 并回填最多 2 年历史;号称 "95% recall accuracy at scale";Product Hunt 描述 "Connect your inbox, upload a spreadsheet…everything is recreated in less than five minutes"。人不再做数据录入。

### pattern: Lossless customer memory / 版本化客户记忆 [已上线]
Peiris:"You need lossless customer memory so that you're prepared for every meeting, you don't drop the balls." 每次交互作为连续上下文存储("stores every interaction as continuous context, not disconnected records"),账户画像随新信息持续更新(客户在会上提到预算变化会自动并入画像)。

### pattern: 带引用的自然语言 BI 查询 [已上线]
可对全库提问,如 "Which of my active opportunities would have moved faster if we had our Slack integration?" 或 "What objections came up in lost deals?",回答附带到具体对话的 citation,以对抗幻觉并可验证。

### pattern: 建议-审批式记录更新(human-in-the-loop) [已上线]
交互结束后 AI 生成记录更新建议进入 "For review" 队列,人批准后落库;批量操作(改 stage、重分配账户、打标签)通过向 agent 下自然语言指令完成。

### pattern: 自然语言工作流 + sandbox 代码执行 [beta(第三方评测称 workflow builder 仍 beta、触发器有限;代码执行 2026 年 2 月上线)]
用户用一句话定义自动化,系统 "wrote a natural language automation on the spot",以 Python 在后台沙箱运行,agent 可调用 20+ enrichment 供应商、web search、object model API。

### pattern: Meeting prep / pre-caps 与自动跟进 [已上线]
会前自动生成简报(Chris Messina 评价 "Offered value on Day 1 with meeting pre-caps and client dossiers");会后自动转写、摘要、起草引用具体会议细节和承诺的 follow-up。替代 Gong/Chorus 订阅。

### pattern: 停滞交易复活与归因诊断 [已上线]
自动识别 stale deals、起草复活邮件;有用户 "revived 40+ stalled opportunities in a single two-hour session";诊断机制是把单个 deal 与全部 closed-won/closed-lost 对比找缺失模式。

### pattern: Agentic 迁移与导入 [已上线]
迁移 agent 自动生成 Python 程序做确定性迁移("deterministic migration without hallucination"),宣称 1 小时内从 HubSpot 迁完;CSV/agentic import 2026 年 3 月上线。

### pattern: Slack agent / MCP 生态接入 [已上线(2026 年 6 月 changelog)]
在 Slack 内以 agent 形式提供查询与操作;通过 MCP connectors 接 Notion、Linear、Granola 等外部系统,由 agent 自主决定摄取哪些数据入库。

## ui_patterns
- 混合形态而非纯对话式:保留 table 视图(带关系过滤)、pipeline 视图、record 页、timeline,叠加 agent chat 面板作为主要操作入口——经典视图在其架构中是'派生视图'
- "For review" 审批队列:AI 生成的记录更新/草稿集中在一个待审 surface,人逐条批准,而非散落在各记录里
- 自然语言即批量操作界面:重分配账户、批量改阶段、打标签等不点表单,直接对 agent 下指令
- 单屏闭环:SaaStr demo 显示从诊断→自动化→新 prospect 全流程在一个界面完成,"The CRM is not a form to fill out. It is a customer context engine"
- 会前/会后自动物料:meeting pre-caps、client dossiers、会后摘要作为系统主动推送的内容单元
- 第三方评测对 UI 的评价是 "polished"、"clean interface from experienced product team"——未采用激进的生成式 UI,创新在数据流向(AI 写入、人审批)而非视图形态

## lessons
- AI 污染数据是真实发生的第一大投诉:多个来源记载用户 "flagged AI-created bad records or nonexistent companies",社区建议的缓解措施是 limited imports、approval-based workflows、bulk 更新前人工审查——印证'AI 直写库'必须有确认门槛(https://www.linkstartai.com/en/agents/lightfield)
- 创始人自己承认幻觉风险存在,但公开的防护细节薄弱(SourceForge 播客中只说 "we obviously put in a lot of controls" 而未展开)——引用机制(citations)是其最实的抗幻觉手段
- '完整替代'策略的代价:企业级功能(forecasting、territory management、深度定制)缺位,明确不适合大销售组织;Contrary 指出其面临与 Salesforce Agentforce(已 1,000 单)的功能完备性竞赛,且市场可能走向专用 agents 而非统一平台
- 定价混乱/多变:不同时点来源分别记载 $36/$99、$59/$149、$79 flat、以及 Peiris 早期设想的 consumption 计费——AI-native 产品的推理成本定价仍在摸索,做 PM 系统时需预留计费模型弹性
- pivot 成本巨大:放弃 25M 用户的 Tome、团队 70→28 人;换来的判断是'横向产品无法为每个 ICP 构建完美上下文'——纵向深耕(销售场景)才能定义数据源与上下文构造,这对'做通用 PM 还是做制造业 NPD 专用 PM'是明确背书
- 产品仍 "promising but still early"(2026 年中):无大规模客户评价,MakerStack 评 7.6/10;其 "自动更新真的能用" 被验证,但可靠性尚未经企业级检验
- Attio 的反面数据也值得尊重:走 control & customization 路线的 Attio 2025 年 ARR 增长 4 倍、5,000 客户——'人管理系统'路线目前商业验证反而更充分,AI-native 激进路线尚未在营收上胜出

## sources
- https://lightfield.app/
- https://lightfield.app/blog/why-we-built-lightfield
- https://lightfield.app/blog/llms-also-prefer-stories-to-graphs-and-databases
- https://lightfield.app/blog/the-dissolution-of-integrations-and-data-moats-in-saas
- https://lightfield.app/blog/the-founders-guide-to-evaluating-an-ai-crm
- https://lightfield.app/blog/building-the-crm-that-works-for-you
- https://lightfield.app/blog/attio-vs-lightfield
- https://lightfield.app/blog/day-ai-vs-lightfield
- https://research.contrary.com/company/lightfield
- https://www.saastr.com/watching-an-ai-native-crm-run-the-full-gtm-loop-live-lightfield-ceo-keith-peiris-demos-a-stalled-deal-an-automation-and-ten-new-prospects/
- https://www.saastr.com/lightfield-just-assembled-a-working-crm-live-on-stage-then-unstuck-a-stalled-deal-in-3-minutes/
- https://www.saastr.com/saastr-ai-app-of-the-week-lightfield-the-ai-native-crm-that-killed-tomes-25-million-users-to-build-something-better/
- https://www.producthunt.com/products/lightfield
- https://sourceforge.net/articles/lightfield-an-ai-native-crm-for-startups-creating-momentum-in-the-category/
- https://sourceforge.net/articles/the-ai-native-crm-lightfield-sourceforge-podcast-episode-124/
- https://makerstack.co/reviews/lightfield-review/
- https://www.linkstartai.com/en/agents/lightfield
- https://www.folk.app/articles/lightfield-crm-review
- https://venturebeat.com/technology/tomes-founders-ditch-viral-presentation-app-with-20m-users-to-build-ai
- https://finance.yahoo.com/sectors/technology/articles/lightfield-launches-one-hour-crm-172700342.html

## verification

- [confirmed] 1. Reality first:原始交互是 source of truth,字段/看板是派生视图;manifesto 原文含 "Summaries, fields, and dashboards are derived views—not | 一手来源(创始 blog)逐句核实:"Summaries, fields, and dashboards are derived views—not the source of truth. Reality comes first."、"Lightfield captures and preserves the raw traces of customer interactions—every e | https://lightfield.app/blog/why-we-built-lightfield
- [confirmed] 2. Schema 变更全量回填:改字段时 AI 重新分析全部历史非结构化数据;最多回填 2 年历史;新用户 5 分钟内 CRM 自动建成 | 三个子点各有来源:(a) Contrary Research 原文 "when users modify or add new fields, the system re-analyzes all historical unstructured data to backfill the new schema";且官网产品页(https://lightfield.app/product/crm-da | https://research.contrary.com/company/lightfield
- [confirmed] 3. For review 审批队列:AI 建议写入、人批准落库;官网有专门 "For review" surface;Peiris "We want the human attached to the record update so t | 核心全部核实:官网产品页 "You review AI-suggested CRM updates before they're applied. Nothing changes in your CRM without your approval.";官网 changelog(lightfield.app 首页,2026-06-12)"Released 'For review' - a compa | https://lightfield.app/product/crm-data-capture
- [confirmed] 4. 自然语言 automation,后台编译为 Python 执行;SaaStr demo 一句话 "run this process every time a deal reaches the POC stage without an  | SaaStr 现场报道两句引文逐字核实(demo 人是 CEO Keith Peiris)。sandbox 执行代码有旁证:同文提到 "code sandbox" 中按需生成自定义报表;SourceForge 文章称 "The AI agent can write and run Python scripts in a sandboxed environment"(https://sourcefo | https://www.saastr.com/watching-an-ai-native-crm-run-the-full-gtm-loop-live-lightfield-ceo-keith-peiris-demos-a-stalled-deal-an-automation-and-ten-new-prospects/
- [confirmed] 5. Ambient capture:连接 email/calendar/Slack/会议录音器/支持工单后自动建 account/contact/opportunity 并回填 2 年历史;"95% recall accuracy at  | 核心一手可证:官网产品页确认 Gmail/Outlook、日历、内置会议录音器,"Schedule a meeting with a new prospect and Lightfield creates the contact and account before you join the call",及 2 年邮件/日历回填;Product Hunt 官方页逐字确认 "Connect your | https://lightfield.app/product/crm-data-capture
- [confirmed] 6. Lossless customer memory:Peiris "You need lossless customer memory so that you're prepared for every meeting, you don | Peiris 引语在 Contrary 报告逐字核实,完整版为:"We're not selling you CRM bookkeeping. You need lossless customer memory so that you're prepared for every meeting, you don't drop the balls after meetings, and afterw | https://research.contrary.com/company/lightfield
- [confirmed] 7. 带引用的自然语言 BI 查询:可问 "Which of my active opportunities would have moved faster if we had our Slack integration?" 或 "What | Contrary 报告逐字核实第一个问句及 "receive detailed, cited responses that reference specific accounts and interactions";第二个问句 "What objections came up in lost deals?" 逐字见于 SourceForge 文章(https://sourceforge.net/a | https://research.contrary.com/company/lightfield