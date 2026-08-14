# ai-native-patterns

## summary
调研覆盖 CRV、a16z、Foundation Capital、Benchmark(Sarah Tavel)、LangChain(Harrison Chase)、Karpathy、Linear(Karri Saarinen)、Granola、Lightfield、Attio 等一手来源。共识分界:AI-native 不是加功能,而是"移除 AI 后产品即失效"的架构判据;数据录入默认由系统从会议/邮件/消息中环境式采集,人从操作者变为审核者与例外处理者;商业上从卖工具转向卖工作成果(Service-as-Software)。可操作模式包括:ambient capture、事件流驱动的主动 agent+代理收件箱、notify/question/review 三态人审、autonomy slider 分级自治、citation+思路轨迹的可核查设计、schema-less 非结构化优先数据层、三类系统记忆。反方主要批评术语通胀(类比 cloud-native)与 demo-产品鸿沟。

## positioning
"AI-native"论述的真实分界不在有无 AI 功能,而在三点:(1)拆除测试——CRV 定义 AI-native 为"AI 是架构地基,移除后产品停摆",AI-enabled 只是附加功能;(2)默认劳动方向反转——Attio 联创 Alexander Christie:"AI 必须深度集成进平台架构,而非事后栓上去;传统 CRM 的地基没有为 AI 所需的规模、自治与可扩展性设计",Lightfield 直接宣称传统系统"无法改变'由人做数据录入'这一根本假设";(3)商业单位反转——Sarah Tavel"Sell work, not software",Foundation Capital 把它命名为 Service-as-Software($4.6T 市场,按结果而非坐席计价)。copilot/chatbot 被多位作者定性为"在坏系统里帮人跑快一点的局部优化",不构成范式转移。

## data_model
三个反转:(1)非结构化优先——Lightfield schema-less from Day One,先完整存会议/邮件/消息原始记录('记忆层'),结构化字段(pipeline 阶段、任务状态)是 AI 派生的视图,业务流程变化时不重建 schema;(2)事件流为一等公民——ambient agents 的触发源是事件流而非人的点击,要求系统把'发生了什么'建为 append-only 事件日志;(3)数据架构先于产品设计——CRV 要求第一天具备向量检索层、反馈回路(人审纠错回流)、失败恢复。对 PM 系统的含义:项目=记忆层(一手事件与文档)+派生层(任务/阶段门/交付物状态,AI 维护、人纠错)+规则层(procedural 记忆,即 NPD 流程本身,可在人审下演进);人工纠错记录本身是高价值训练/评估资产,应作为独立数据类建模。

### idea: 拆除测试:AI-native 的硬判据
CRV《What Is AI-Native? The Founder's Guide》给出三级分类:AI-native(创立即以智能系统为基础,移除 AI 则产品 cease to function)、AI-first(后置为中心)、AI-enabled(附加功能)。并强调 data architecture comes before product design:第一天就要有向量检索层、内嵌反馈回路、失败恢复机制;仅包一层 API 调用不算数,智能必须 persistent and contextual。
- transfer: 设计评审时反问:关掉 AI 后系统是否退化成普通任务看板?AI-native 的 PM 系统里,项目健康度、风险标注、交付物完整性检查应是 AI 持续生成的原生产物,而非人肉维护字段上的点缀。
- src: https://www.crv.com/content/what-is-ai-native

### idea: 非结构化优先、schema-less 的数据层(Lightfield)
Lightfield(创始团队砍掉有 2500 万用户的 Tome 转型而来)公开的架构赌注:从非结构化会话数据出发再派生结构,而不是反过来。系统 schema-less from Day One,吞入邮件、会议转写、通话、Slack,存储'客户实际说了什么做了什么'的完整原始记录,形成 living model;pipeline 阶段由会话信号批量推断更新,业务问题用自然语言提问、答案带 citation。产品哲学是 customer memory first, pipeline second。
- transfer: 为 NPD 项目建'项目记忆层':评审会议、邮件往来、测试报告原文全部入库为一手事件,任务状态、阶段门就绪度、交付物清单是从记忆层派生的视图;换模板/换流程时不需要重建数据结构。
- src: https://www.saastr.com/saastr-ai-app-of-the-week-lightfield-the-ai-native-crm-that-killed-tomes-25-million-users-to-build-something-better/

### idea: Ambient agents + Agent Inbox(LangChain/Harrison Chase)
Chase 定义 ambient agents:监听事件流并自主行动、可多实例并行,而非等人在聊天框发起。配套 human-in-the-loop 三态:Notify(发现重要事项只提醒不动手)、Question(缺信息时提问而非瞎猜)、Review(高风险动作提交人审,人可 approve/edit/反馈)。交互载体是 Agent Inbox——聚合所有'代理与你之间未关闭的沟通项',类似邮箱+工单的混合体。
- transfer: PM 系统的事件流(提交、到期、邮件、会议结束)触发 agent 巡检;项目经理每天面对的不是任务列表而是一个'待裁决收件箱':某供应商样品延期→agent 已起草阶段门风险项与顺延方案,等人批准或改写。
- src: https://www.langchain.com/blog/introducing-ambient-agents

### idea: Autonomy slider + 生成-验证闭环(Karpathy, Software 3.0)
Karpathy 主张 partial autonomy apps 而非全自动:产品要带自治滑块(Cursor 的 Tab→Cmd+K→Cmd+L→agent 模式;Perplexity 的 search→research→deep research),让用户按场景调节放权程度。核心是 generation-verification loop:GUI 的职责是让人类验证比 AI 生成更快;并警告 demo 与产品的鸿沟——'Demo is works.any(), product is works.all()',以自动驾驶十年未收敛为例。
- transfer: 每类自动化单独配自治级:会议纪要抽行动项=全自动;更新任务状态=自动但可一键回滚;改基线/关闭阶段门=必须人批。审核界面按'验证快于生成'设计:改动以 diff 呈现,附证据引用,一屏内完成裁决。
- src: https://www.latent.space/p/s3

### idea: Workbench 而非 chatbot(Linear/Karri Saarinen)
Saarinen 在《Design for the AI age》里判定 chat 是'非常弱和通用的形式';AI 应被置入'木匠工作台'式的功能性应用中,agent 在工作台上被部署、管理、以明确准则运作,输出被审核批准。他在 Every 的文章给出六条 human-agent 交互原则:身份披露(agent 不得伪装人类)、原生集成(与人类同一套操作/视觉语言)、即时反馈、状态透明(展示思考过程与工具调用)、尊重解除(叫停即停)、人类责任(不搞逐步审批,委托者对结果负责)。Linear 以 Agent Sessions+活动日志落地。
- transfer: agent 以'团队成员'身份出现在任务系统:可被 assign 任务、有头像标识为 AI、有自己的会话页和活动日志;它直接在任务/交付物对象上操作,而不是在旁边挂一个聊天窗。红线之外不逐步弹窗审批——把责任锚定在委托它的人身上。
- src: https://linear.app/now/design-for-the-ai-age

### idea: Invisible AI:增强思考而非替代思考(Granola/Chris Pedregal)
Pedregal(前 Google PM)的哲学:'AI should help you think better. It should not be thinking for you'——LLM 是引擎,产品要造方向盘。Granola 嵌入用户既有行为(开会记笔记)而非新开工具,对会议其他参与者不可见。他的五条规则中最可迁移的:别修模型即将自己解决的问题(如长上下文);窄而深,把一个场景做到 10x(常靠非 AI 工程如回声消除);Context is King——把模型当'第一天上班的实习生',喂给它参会人角色、关注点等上下文而非规定输出。
- transfer: 行动项/风险抽取要寄生在已有仪式(评审会、站会)里零额外操作;给模型注入项目阶段、NPD 模板、参会人职能等结构化上下文,比调 prompt 模板更能决定输出质量;不为当前模型的上下文长度限制设计复杂分片功能。
- src: https://creatoreconomy.so/p/the-hidden-rules-behind-successful-ai-products-chris-pedregal

### idea: 可核查性设计:citation + 思路轨迹(Shape of AI)
Emily Campbell 的 shapeof.ai 模式库把 AI UX 归为 identifiers、wayfinders、prompts、tuners、trust indicators 等类。信任类的两个关键模式:Citations——AI 输出内联链接回源文档/网页/转写/数据库供核验;Stream of Thought——外显 AI 的计划、调用的工具、跑的代码与自检过程。另收录 inline action 等非聊天式介入模式。
- transfer: AI 写入的每个状态变更、风险项、评审结论都必须可点开溯源到具体会议片段/邮件/文档段落;阶段门就绪度评估附'它检查了什么'的轨迹。无出处的 AI 断言不允许落库为事实。
- src: https://www.shapeof.ai/

### idea: 三类系统记忆(LangChain CoALA 框架)
LangChain《Memory for agents》按 CoALA 论文分三类:semantic(关于世界的事实,用于个性化)、episodic(过往行动序列,用于少样本复现成功路径)、procedural(执行任务的规则,agent 可自我更新 system prompt)。配套开源 LangMem 工具包做记忆抽取与管理。
- transfer: semantic=组织事实库(供应商特性、产线约束、客户偏好);episodic=历史项目的阶段门通过/返工案例,供 agent 引用'上次类似项目卡在哪';procedural=公司 NPD 流程规则,且允许在人审下随复盘迭代。
- src: https://www.langchain.com/blog/memory-for-agents

### idea: Generative UI:界面按意图现场生成(a16z)
Jennifer Li 与 Yoko Li 的《How Generative AI Is Remaking UI/UX Design》提出自适应 UI:在 CRM 场景中根据用户意图自动预选和隐藏字段。Builder.io/CopilotKit 进一步区分三种 GenUI:Static(从预置组件中选)、Declarative(agent 输出结构化描述由 app 渲染)、Open-Ended(完全生成)。业界主流落点是 Declarative——agent 不直接对用户说话,通过 API 与应用通信,由应用渲染原生组件。
- transfer: 阶段门检查单按项目类型/风险等级动态生成而非 55 项全量铺开;填报表单按上下文预填并隐藏无关字段;agent 汇报用系统原生卡片(风险卡、甘特片段)而非纯文本,保持视觉语言一致。
- src: https://a16z.com/how-generative-ai-is-remaking-ui-ux-design/

### idea: 审批路径的工程化设计(而非一个确认按钮)
《Human-in-the-Loop Is Not a Button》提出审批决策树应位于 agent 拟定动作与工具执行层之间:动作分类→政策核对→证据校验→超时处理→异常路由,之后才触达目标系统。经验:agent 像队友一样解释决策时人批得更快;人审记录应回流为 prompt/路由/评估集的训练数据。EU AI Act 第 14 条与 NIST AI RMF 都要求'可证明的人类监督'。
- transfer: 把审批建成策略引擎:低风险动作(补标签)直通+可回滚,中风险(改排期)批量待审,红线(关闭阶段门、改基线)强制四眼;每次人工改写 AI 提案都记录为纠错样本反哺后续提案质量——这同时满足制造业质量体系的审计要求。
- src: https://digitalthoughtdisruption.com/2026/07/12/human-in-the-loop-ai-agent-approval-paths/

### pattern: Ambient capture(环境式数据采集) [已上线(Granola、Lightfield、Attio 均为在售产品)]
系统接入邮件、日历、会议音频/转写、Slack 等信源,自动生成并维护结构化记录;人不再录入数据,只纠错。Granola 在本地静默转写会议增强人写的笔记;Lightfield 吞入全渠道会话派生 pipeline 状态;Attio 宣称 eliminates manual data entry。

### pattern: Proactive/ambient agents(事件流驱动的主动代理) [已上线(垂直产品内);通用框架层 beta]
agent 订阅事件流(而非等待人发消息),发现机会或异常时主动产出提案:Lightfield 识别 stale deals 并生成复活外联(有用户单次 2 小时复活 40+ 停滞商机);LangChain 提供开源 agent-inbox 参考实现。

### pattern: Human-in-the-loop 三态(Notify / Question / Review) [已上线(LangChain 生产实践,被广泛复制)]
按风险与信息完备度路由:只提醒、向人提问补信息、或提交完整提案供 approve/edit/feedback。Review 的编辑与反馈同时是对 agent 的在线指导。

### pattern: Agent Inbox(代理收件箱) [已上线(LangChain 开源实现);作为主界面范式仍在验证]
所有 agent 发起的未关闭沟通项聚合为一个收件箱(邮箱+工单混合体),人按队列裁决;取代'打开 N 个聊天窗'的交互。

### pattern: Autonomy slider(分级自治) [已上线(编码/搜索工具);业务软件采纳中]
同一产品内提供从补全→局部改写→全 agent 的连续档位(Cursor: Tab→Cmd+K→Cmd+L→agent;Perplexity: search→research→deep research),用户按任务风险选档。

### pattern: Generation-Verification loop + diff 式审核 [已上线(代码评审场景);结构化业务数据的 diff 审核为 beta]
AI 生成、人快速验证的紧循环;UI 目标是让验证比生成快:改动以差异视图呈现、附证据、一键接受/拒绝。Karpathy 称之为 keep AI on a leash 的具体形态。

### pattern: Citation + Stream of Thought(可核查层) [已上线]
AI 每条结论内联引用源材料;复杂任务外显计划、工具调用与自检轨迹。Perplexity、Lightfield(带引用回答业务问题)已实装;shapeof.ai 收录为标准模式。

### pattern: 系统记忆(semantic / episodic / procedural) [beta(框架可用,产品化案例早期)]
分别存事实、过往行动序列、任务规则;agent 检索记忆做个性化与少样本复现,procedural 记忆可在人审下自我更新(LangMem 工具包)。

### pattern: Generative/Declarative UI [beta(协议层 A2UI/AG-UI/MCP Apps 竞争中)]
agent 输出结构化 UI 描述,应用渲染为原生组件;界面按用户意图动态预选/隐藏字段。三档:Static/Declarative/Open-Ended,主流落点为 Declarative。

### pattern: Agent 作为原生团队成员 [已上线(Linear closed beta 转公开)]
agent 有身份标识、可被分配任务、有会话页与活动日志,用与人相同的对象模型操作系统(Linear for Agents / Agent Sessions);人类责任原则:委托者负责,不逐步审批。

## ui_patterns
- Agent Inbox:待裁决提案队列取代任务列表作为高频入口(LangChain)
- 审批三键:Approve / Edit / Give feedback,编辑即在线教学(LangChain Review 模式)
- Diff-style review:AI 拟改动以差异视图+证据呈现,验证快于生成(Karpathy)
- 内联 Citation:每条 AI 结论可点开跳到源会议片段/邮件/文档(shapeof.ai、Lightfield)
- Stream of Thought:外显计划、工具调用、自检轨迹(shapeof.ai)
- Autonomy slider:按任务风险选择自治档位(Cursor/Perplexity)
- Agent 身份披露+活动日志+会话页:AI 是可追责的'队员'而非聊天窗(Linear 六原则)
- Inline action:AI 介入发生在对象/字段就地,而非侧边 chatbot(shapeof.ai;Wattenberger 反 chatbox 论)
- 自适应表单:按意图动态预填、预选、隐藏字段(a16z Generative UI)
- 尊重解除:一键叫停 agent 且保持停止(Linear)

## lessons
- 术语通胀风险:SECO 指出 'AI-native' 正复制 cloud-native 的通胀周期(从容器微服务被稀释到'托管在别人机房的旧软件');厂商说 AI-native 时应追问到底哪一层 native——人、流程、架构还是单个功能。多数所谓 AI-native SOC 实为人主导流程+AI 辅助,即 AI-enhanced。
- Hacker News 社区共识:活跃批评者多数每天用 LLM,但拒绝无运营实证的叙事;'AI washing'(公司扎堆改叙事)被视为负信号,hype-to-utility 比例失衡是核心不满。
- Karpathy 的内部批评:'Demo is works.any(), product is works.all()'——自动驾驶 2014 年 demo 看似已解决,十余年仍未收敛;这是反对'全自动 agent 一步到位'叙事、主张 partial autonomy 的最强论据。
- Chat 不等于 AI-native:Wattenberger(2023)论证 chatbot 界面 affordance 不清、打断心流、把学习成本推给每个用户;Saarinen 称 chat 是'非常弱和通用的形式'。把 AI-native 做成'加个聊天框'是最常见的伪 AI-native。
- 别为即将消失的模型局限造功能(Pedregal):长上下文、多语言等问题会被下一代模型自然解决,围绕它们建的复杂工程会变成负资产。
- 逐步审批会毁掉体验:Saarinen 第六原则反对每步弹窗确认,主张委托者担责+红线例外;但 EU AI Act 第 14 条要求可证明的人类监督——审批流设计要同时过 UX 和合规两关,分级策略引擎是折中解。
- 商业模式警示(Foundation Capital):Service-as-Software 公司可能被模型供应商吃掉——差异化必须建立在私有工作流数据与领域深度上,不在模型调用层。

## sources
- https://www.crv.com/content/what-is-ai-native
- https://www.langchain.com/blog/introducing-ambient-agents
- https://sequoiacap.com/podcast/training-data-harrison-chase-2/
- https://www.latent.space/p/s3
- https://www.saastr.com/saastr-ai-app-of-the-week-lightfield-the-ai-native-crm-that-killed-tomes-25-million-users-to-build-something-better/
- https://lightfield.app/
- https://www.gv.com/news/reinventing-crm-attio-nicolas-sharp
- https://www.prnewswire.com/news-releases/attio-raises-52m-series-b-to-scale-the-first-ai-native-crm-for-go-to-market-builders-302538357.html
- https://linear.app/now/design-for-the-ai-age
- https://every.to/thesis/how-to-design-for-human-agent-interaction
- https://creatoreconomy.so/p/the-hidden-rules-behind-successful-ai-products-chris-pedregal
- https://www.shapeof.ai/
- https://wattenberger.com/thoughts/boo-chatbots/
- https://a16z.com/how-generative-ai-is-remaking-ui-ux-design/
- https://www.builder.io/blog/designing-generative-ui-in-an-agent-native-world
- https://www.copilotkit.ai/generative-ui
- https://www.langchain.com/blog/memory-for-agents
- https://www.forbes.com/sites/joannechen/2024/04/29/ai-leads-a-service-as-software-paradigm-shift/
- https://foundationcapital.com/ideas/when-model-providers-eat-everything-a-survival-guide-for-service-as-software-startups
- https://20vc.substack.com/p/20vc-newsletter-may-12th-2024
- https://www.seco.com/blog/details/the-ai-buzzword-trap-why-branding-everything-as-ai-is-dangerous
- https://news.ycombinator.com/item?id=48257980
- https://digitalthoughtdisruption.com/2026/07/12/human-in-the-loop-ai-agent-approval-paths/
