# linear-agents

## summary
Linear 以「opinionated 软件」赢过 Jira:把最佳实践编码为默认工作流(triage 收件箱、cycles、标准状态),拒绝无限可配置;用自研 sync engine 换极致速度,键盘优先,为一线创作者而非管理报表设计。2025 年起它把同一套克制哲学搬到 AI:「Linear for Agents」让 Cursor/Devin/Codegen 等 agent 成为可指派、可 @ 的一等公民,但用 assignee(人)/delegate(agent)双字段守住「agent 不可担责」底线,并以 AIG 六原则 + AgentSession/AgentActivity 协议规范交互。自有 AI 从 Triage Intelligence 走到 Linear Agent 写码(Coding Sessions)、站内评审(Diffs)、循环自动化(Loops)。CEO 称 77% workspace 已用云端 agent,Linear 正转型为 agent 的「上下文基础设施」。

## positioning
经典定位:反 Jira 的高速、opinionated issue tracker,为增长期科技公司的 IC(工程师/设计师)而非采购方/管理层设计,「质量是第一原则」(First Round 访谈)。2025 起升级为「人与 agent 协作的编排层」;2026 年 Saarinen 提出「issue tracking is dead」,把 Linear 重新定位为 coding agent 的 context infrastructure——聚合 bug、反馈、目标与产品状态,供 agent 理解「做什么、为什么」;判断是:执行变便宜后,瓶颈移到「决定做什么」,决策层才是护城河(tbpndigest 2026-03-26)。差异化在于:不做聊天机器人贴皮,而是让 agent 原生栖息在既有工作流里(AIG:"an agent should inhabit the platform natively")。

## data_model
关键设计:(1) assignee 与 delegate 是任务上的两个独立字段——人担责、agent 干活,责任判定不依赖推断;(2) agent 是独立的用户类型(OAuth actor=app 的 app user),有身份、头像、token,能力由 scope 刻画(app:assignable/app:mentionable),不占计费席位,不能登录/碰管理功能;(3) AgentSession 是一等对象:挂在 issue/评论下,六状态(pending/active/error/awaitingInput/complete/stale)由活动自动推导,带 SLA(5s webhook、10s 首活动)与失联判定;(4) AgentActivity 是带语义类型的结构化事件(thought/action/elicitation/response/error + signals + ephemeral),而非纯文本评论;(5) guidance 是分层配置(team 覆盖 workspace),随委派注入上下文;(6) 建议类 AI 输出(triage 路由)是「带理由的可撤销提案」,auto-apply 是显式配置开关。

### idea: Opinionated 默认值:把最佳实践编码成产品,而不是做工作流引擎
创始团队明确说 "You can't build the optimal tool if it's very flexible or endlessly customizable"。具体做法:内置标准 issue 状态与 triage 收件箱(带自动路由、on-call 轮值、明确动作按钮),取代各公司自造的 ad-hoc 流程;用「写 task 不写 user story」「n 周 cycles 而非 sprint」「小 issue、短 spec」等 Linear Method 实践替代可配置字段海。Runtime 引 Saarinen:先弄清用户真正要做的几件事,再围绕它建功能。
- transfer: NPD 系统应把 stage-gate 阶段、交付物清单、评审规则做成强默认模板(可裁剪但不可无限自定义),而非 Jira 式自由工作流配置器;「模板瘦身分档」正是同一思路——默认值本身就是产品观点。
- src: https://linear.app/method/introduction

### idea: 速度是第一功能:sync engine + 键盘优先
两名工程师时就先造了自研 sync engine(本地数据副本、离线、事务、实时同步),前端可乐观更新、瞬时响应;创立动机就是 Jira 太慢——目标「build a tool that's never slow」。不做 A/B 测试,靠直觉与用户研究,把 issue tracking 当 craft 问题。
- transfer: 研发工程师每天报进度、勾检查项,工具慢=数据烂。制造业 PM 系统同样需要本地缓存+乐观更新+全键盘/命令面板操作;「快」不是体验加分项,是数据质量的前提。
- src: https://newsletter.pragmaticengineer.com/p/linear

### idea: 为创作者(IC)设计,不为报表设计;用实际工作物度量进度
Linear Method 首条原则 "Build for the creators":保个体生产力优先于完美报表。刻意不面向采购/IT 决策者设计,只服务日常真正用工具的人;进度验收看 diff(代码/设计文件的实际变更)而非状态字段。早期用 waitlist 每周只放 10 个匹配 ICP 的用户进来。
- transfer: NPD 系统的第一用户是结构/电子/工艺工程师,不是 PMO;报表应从任务与交付物自动派生。验收锚定交付物本体(图纸、BOM、测试报告的实际版本),而非「已完成」勾选。
- src: https://review.firstround.com/linears-path-to-product-market-fit/

### idea: Assignment 与 Delegation 分离:agent 不可担责
AIG 核心信条 "An agent cannot be held accountable"。issue 只能 assign 给人,agent 是单独的 delegate 字段;文档明言「委派给 agent 后,人类 assignee 仍对 issue 负责」。此设计源于真实教训:早期 agent 以普通用户身份接入,出现「某 agent 名下挂几十个 issue,不知道背后该找谁」的问责真空。
- transfer: 任务模型加 delegate 字段而非让 AI 抢占 assignee;责任人、签核、追溯链永远落在人身上。对制造业尤其关键:阶段门签核、ECN 批准、质量责任都不能指向 AI。
- src: https://linear.app/now/our-approach-to-building-the-agent-interaction-sdk

### idea: Agent 是一等公民但有独立身份类型与权限刻度
新 OAuth actor 模式(actor=app)为 agent 创建专属 app user:有自己的头像、用户页、token 与 scope;可选 scope app:assignable / app:mentionable 控制其能否出现在指派菜单、能否被 @;界面上带徽标与人区分;重名自动加后缀;不占计费席位;不能登录、不能碰管理功能。
- transfer: 用户模型增加 agent 用户类型:独立身份+徽标+细粒度能力开关(可被指派?可被提及?可写哪些对象?),不计费席位。权限按「能力」而非「角色」授予,与一人多岗/冲突矩阵设计可以并存。
- src: https://linear.app/docs/agents-in-linear

### idea: AIG 六原则:一份值得直接抄的 agent 交互规范
1) 身份可辨——agent 绝不能被误认为人(界面徽标);2) 原生融入——通过平台既有 UI 模式与标准动作干活,不另起炉灶;3) 即时反馈——被唤起后立刻给出不打扰的确认(如 Thinking 状态),"Silence leads to uncertainty";4) 内部状态透明——一眼看懂 thinking/waiting/executing/complete,可下钻查看推理、工具调用与决策逻辑;5) 尊重退出——被叫停必须立刻停,收到明确信号才能再介入;6) 人负最终责任。
- transfer: 直接为自己的系统写一份 AIG:agent 评论/操作必须带身份标识、必须走与人相同的任务操作(改状态、传附件、发评论),被项目负责人叫停立即冻结,所有自动动作可追溯到发起人与依据。
- src: https://linear.app/developers/aig

### idea: AgentSession/AgentActivity:给 agent 执行建结构化契约,而非塞评论流
agent 被委派或 @ 时自动创建 Agent Session,六种状态(pending/active/error/awaitingInput/complete/stale)对用户可见,状态由活动自动推导;活动分五种语义类型:thought(推理)、action(工具调用)、elicitation(向人要澄清/确认)、response(完成交付)、error(失败+补救链接);支持 ephemeral 临时态、Agent Plan 任务清单、外链到 agent 自己的面板。硬性 SLA:webhook 5 秒内应答,created 后 10 秒内必须发出首个活动,否则标记为无响应。
- transfer: AI 执行任务时建独立「执行会话」对象挂在任务下,而不是把输出混进评论:状态机可见、要澄清时显式进入 awaitingInput 并 @ 责任人、超时自动判失联回落给人。这是「AI 接活」最可抄的工程契约。
- src: https://linear.app/developers/agent-interaction

### idea: Guidance:给 agent 的分层书面指引(系统内的 AGENTS.md)
管理员可在 workspace 级与 team 级用 markdown 写「Additional guidance」:指定仓库、提交规范、评审流程等;team 级覆盖 workspace 级;委派时该指引连同 issue 详情、评论一起打包进 promptContext 发给 agent。
- transfer: 在项目/产品线/阶段层级维护给 agent 的指引文档(交付物命名规范、本项目评审规则、禁区),委派任务时自动注入 agent 上下文;层级覆盖语义(项目>组织)照抄。
- src: https://linear.app/docs/agents-in-linear

### idea: Triage 收件箱 + AI 建议:入口统一、建议可解释、可渐进自动化
Triage Intelligence(2025-08 以 Product Intelligence 名义发布,后改名)检查进入 Triage 的所有 issue,自动建议路由到哪个 team/项目/负责人,并识别相关 issue 与疑似重复;悬停可看建议理由;可接受/驳回;2025-09 起支持 workspace/team 级配置 auto-apply,从「建议」渐进到「自动执行」。
- transfer: NPD 的问题/变更/客诉统一进 triage 队列;AI 建议路由+查重且必须可解释(悬停看依据);自动化程度做成配置项,让团队自己决定从人审到自动的推进节奏。
- src: https://linear.app/changelog/2025-08-14-product-intelligence-technology-preview

### idea: 闭环留在系统内:执行、评审与上下文同处一地
Coding Sessions 让 Linear Agent(驱动 Claude Code/Codex)从 triage 的 bug 一路做到「已评审的修复」,工作不离开 Linear;Diffs 把代码评审搬进 Linear,理由是「评审应与全部产品上下文在一起」,并为 agent 产码的量身设计;Cursor 集成中 agent 开 PR、进度回流 issue。
- transfer: 交付物的产生—评审—定稿闭环应在 PM 系统内完成并与任务/阶段门绑定,而非散落邮件与网盘;当 agent 开始产出交付物草稿,「产出物+评审+上下文同址」变成硬需求。
- src: https://linear.app/changelog/2026-06-11-coding-sessions

### idea: Loops:例行工作交给 agent,配置全团队可见可审
2026-07-20 发布:用自然语言描述一项重复工作,选择按计划(schedule)或按事件触发;agent 利用 workspace 上下文与集成工具决定后续动作。官方示例:检查新 issue、查根因并路由给 coding agent;从会议纪要/事故报告生成并管理后续任务;维护发布计划与项目 spec 的时效性。强调 shared visibility and control:团队可查看指令、检查配置、审查每次运行结果。Business/Enterprise,消耗 AI credits。
- transfer: NPD 例行事务(阶段门材料齐套检查、每周风险扫描、会议纪要转任务、交付物逾期催办)是 loop 型 agent 的天然场景;关键抄点是配置与运行日志对全团队透明,不做黑箱自动化。
- src: https://linear.app/changelog/2026-07-20-introducing-loops

### idea: Design for the AI age:workbench 而非 chatbot
Saarinen 主张跳出通用聊天框:"Prompting is essentially like writing a spec",措辞不同结果迥异,失控方差是设计问题;应把 AI 分层叠进结构化应用(workbench 隐喻),由应用提供上下文、结构与护栏;未来 agent 需要在明确 guideline 内运行、保留人工 review/approval 回路的工作台。
- transfer: AI-native PM 不等于「加个聊天侧栏」:让 AI 出现在结构化对象(任务、交付物、评审)的原生动作里,用系统结构约束方差;聊天只是入口之一。
- src: https://linear.app/now/design-for-the-ai-age

### pattern: 把 issue 指派(delegate)给第三方 coding agent [已上线(2025-05-20 GA;Saarinen 称 77% workspace 已采用云端 agent)]
Cursor/Devin/Codegen/ChatPRD/Charlie 等作为 app user 进入 workspace,可在指派菜单选择或在评论 @ 唤起;委派后 agent 云端起会话,读取 issue 详情+评论+guidance(promptContext),干活并把 thoughts/actions/PR 链接回写 issue;可配 triage 规则自动把某类任务委派给 agent。人类 assignee 保持负责。

### pattern: Agent Interaction SDK / AgentSession 协议 [已上线(2025-07-30 developer preview 起步,现为第三方 agent 接入标准)]
AgentSessionEvent webhook(created/prompted)下发指令;agent 通过五类 AgentActivity(thought/action/elicitation/response/error)回报,session 状态自动流转并对用户可见;5 秒应答、10 秒首活动的 SLA;支持 ephemeral 活动、Agent Plans 清单、repository suggestions(LLM 排序建议目标仓库)。

### pattern: Triage Intelligence(AI 分诊) [已上线(2025-08 Technology Preview,Business/Enterprise;2025-09 加 auto-apply)]
AI 检查进入 Triage 的 issue,基于历史 issue 研究后建议 team/项目/负责人,标记相关与重复 issue;悬停看理由,可接受/驳回,或按 workspace/team 配置 auto-apply 自动应用。

### pattern: Linear Agent 自研 agent + Coding Sessions [已上线(2026-06-11,Business/Enterprise,耗 AI credits)]
Linear 自己的 agent 包装 Claude Code/Codex,云端运行;指派 issue 或在 chat/评论/Slack 里请求即可开码,从 triage bug 到 reviewed fix 全程不出 Linear;也能读代码库答问(code intelligence)。

### pattern: Diffs(站内代码评审) [已上线(2026-05-27)]
PR 评审直接在 Linear 内进行,与产品上下文(issue、项目、讨论)同址;为承接 agent 产码量而设计,含 auto-merge 状态可视化。

### pattern: Loops(循环 agent 自动化) [已上线(2026-07-20,Business/Enterprise)]
自然语言描述重复工作+选择 schedule 或事件触发;agent 用 workspace 上下文与集成工具执行;团队可审查指令、配置与每次运行结果。

### pattern: 自动修 bug 流水线(Linear 内部 dogfood) [内部实践(公开分享于 2026,方法论可复用)]
Datadog 监控发现问题→自动进 Triage→automation 委派 Linear Agent 调查并尝试修复;设置 confidence gate(先证明理解再动手)压低低质 PR;全过程(调查、失败、PR)留在 issue 内供团队审查,人工 review+merge。

### pattern: Agent guidance 注入 [已上线]
workspace/team 两级 markdown 指引(仓库、提交规范、评审流程),team 级优先;随委派打包进 promptContext。

## ui_patterns
- 指派菜单中 agent 带徽标,与人类用户明确区分(身份可辨原则的落地)
- assignee(人)与 delegate(agent)在 issue 上是两个可见字段,委派不转移责任
- 被唤起后立即显示 'Thinking' 等不打扰的确认反馈;ephemeral 中间态活动展示后自动消失
- session 状态(工作中/等输入/出错/完成/失联)在 issue 内一眼可见,可下钻看推理与工具调用
- AI 建议(triage 路由、重复检测)悬停可看 reasoning,接受/驳回二键操作
- Agent Plan:agent 的任务清单(pending/in-progress/completed/canceled)在会话内展示
- agent 有自己的用户页;'My Issues' 与自定义视图可按 delegate 过滤;Insights 可按 agent 参与度切分
- 会话可挂外部 URL,跳转到 agent 自己的执行面板(如 Cursor 云端)
- Triage 收件箱队列:统一入口+明确动作按钮,替代各处散落的报障
- 经典层:全键盘操作+命令面板、乐观更新零等待、克制的标准状态集

## lessons
- 「让 agent 一把过所有进来的 bug」失败了:上下文不足以 one-shot,必须收窄到高置信任务类型——dead feature flag 清理成功率约 100%,失败后台任务排查仅约 33%。启示:按任务类型分级授权 agent,而非一刀切放权(linear.app/now/linear-agent-bug-fix)
- 早期 agent 以普通用户身份接入,出现「agent 名下挂几十个 issue、不知道背后找谁」的问责真空——这是 delegation 模型(assign 人/delegate agent 分离)的直接起因(linear.app/now/our-approach-to-building-the-agent-interaction-sdk)
- agent 评论要克制频率,否则造成用户疲劳;Cursor 集成刻意限制回写频率,并把 agent 用在「积压的 P2/P3、不值得人切换上下文」的任务上——agent 的最佳切入点是长尾而非关键路径(linear.app/now/how-cursor-integrated-with-linear-for-agents)
- Saarinen 自己承认 23% workspace 未采用 agent 的原因:agent 在复杂企业环境还不成熟、公司仍在评估、安全采购流程阻塞——对制造业客户预期要更保守(tbpndigest)
- 流程倒挂是真风险:「agent 5 分钟修好 bug,但报障流程走一周」——AI 提速执行后,PM 系统自身的流程开销会成为最显眼的瓶颈,阶段门/审批设计必须按此重估
- AIG 目前更多是 Linear 的单方标准(HN 帖仅 11 分无讨论),业界尚无共识协议;抄其原则可以,绑定其具体协议需谨慎
- Igor Sechyn 的经验:「让 agent 干得好,取决于你留下的面包屑」——命名规范、书面约定、结构化上下文决定 agent 成败;这把「文档纪律」从软要求变成了硬投资

## sources
- https://linear.app/method/introduction
- https://review.firstround.com/linears-path-to-product-market-fit/
- https://newsletter.pragmaticengineer.com/p/linear
- https://www.runtime.news/how-linear-became-the-new-jira/
- https://www.figma.com/blog/the-linear-method-opinionated-software/
- https://linear.app/developers/aig
- https://linear.app/developers/agent-interaction
- https://linear.app/docs/agents-in-linear
- https://linear.app/changelog/2025-05-20-linear-for-agents
- https://linear.app/changelog/2025-07-30-agent-interaction-guidelines-and-sdk
- https://linear.app/now/our-approach-to-building-the-agent-interaction-sdk
- https://linear.app/now/how-cursor-integrated-with-linear-for-agents
- https://linear.app/changelog/2025-08-14-product-intelligence-technology-preview
- https://linear.app/changelog/2025-09-19-auto-apply-triage-suggestions
- https://linear.app/docs/triage-intelligence
- https://linear.app/now/ai
- https://linear.app/changelog/2026-06-11-coding-sessions
- https://linear.app/changelog/2026-05-27-linear-diffs
- https://linear.app/changelog/2026-07-20-introducing-loops
- https://linear.app/now/linear-agent-bug-fix
- https://linear.app/now/design-for-the-ai-age
- https://www.tbpndigest.com/story/2026-03-26/linear-ceo-karri-saarinen-declares-issue-tracking-is-dead-and-reveals-linears-ai-era-pivot
