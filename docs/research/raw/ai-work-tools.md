# ai-work-tools

## summary
六个样本呈现清晰分化。押注"全自主 AI 项目经理"的 Height 2.0(2024-10 发布,AI 自动做 bug triage、backlog 去重、追状态等 chores)在发布仅 5 个月后宣布关停(2025-09-24 停服),是最重要的反面案例;HN 用户称"并不意外"。而活下来并增长的都把 AI 收敛为可验证的辅助角色:Motion 靠约束求解式自动排程站稳,2025 年转向具名 AI Employees 后 3 个月做出八位数 ARR(总 ARR 约 $50M,估值 $550M);ClickUp 靠 AI StandUp/工作区问答做到 $300M ARR、AI 销售同比 +400%;Notion 3.0 agents 发布时 ARR 破 $500M;Asana AI Studio 走 no-code 工作流 agent 路线,有 Indeed 等真实案例但 FY2026 财年末 AI Studio ARR 仅 $6M+(对比主营约 $8 亿),证明 AI 附加收费变现远慢于宣传。已验证用例:活动数据自动生成状态汇报/standup、工作区检索问答、结构化字段自动填写与查重、约束排程、高频 intake 分诊。反复失败:全自主定位、AI 补不了核心产品的竞争劣势、强推且计费混乱的 AI 上层建筑。

## positioning
该赛道的真实分层:(1) 平台型(Asana/ClickUp/Notion)把 AI 作为已有工作图谱之上的增值层,靠存量数据和分发赢,变现慢但留存强;(2) AI-native 新秀(Dart/Motion)以"省掉 PM 杂务"切入,Motion 靠排程这一确定性引擎+后来的具名 agent 套件跑通 SMB 市场,Dart 走 chat-as-UI + agent 一体化但仍是小众($500K 种子、约 10 人);(3) 全自主愿景型(Height 2.0)已被市场证伪。对制造业 NPD 项目管理系统的启示:差异化不在"更多 AI 功能"(HN 对 Dart 的质疑:这些功能 Linear/Jira 都会做),而在结构化领域数据模型(阶段门、交付物、跨职能依赖)之上做可验证、可追溯的 AI 角色——这恰是通用工具做不深的部分。

## data_model
所有成立的 AI 能力都依赖结构化工作图谱作为基底:Asana 官方明确 Smart workflows 依赖 Work Graph(任务/依赖/历史上下文);ClickUp Brain 的软肋是数据边界——知识在 Notion/Google Docs/Slack 里它就答不了(后来靠 Brain MAX 跨应用检索补);Notion agents 强是因为一切内容本来就在 pages+databases 里且有 MCP 连接器;Dart 靠嵌入全部任务语料做查重和报告。迁移到 NPD 系统:阶段门(gate)、交付物(deliverable)、任务、变更(ECR/ECN)、活动日志必须是一等公民且互相链接,AI 汇报/问答/分诊的可靠性是数据模型覆盖度的函数;每条 AI 结论应能回溯到具体 task/文档(provenance),这是对抗幻觉信任税的结构性手段。

### idea: 已验证用例 1:从真实活动数据自动生成状态汇报/standup/changelog
ClickUp AI StandUp 从任务活动自动汇编每人做了什么+受阻项,团队不再花 30 分钟手写周报,是评测公认最被用起来的功能;Dart 创始人称其 changelog/report 自动生成让他们每周省约 7 小时,HN 上被具体点名称赞;Motion 的 'Millie the Project Manager' agent 也以生成报告为核心动作。共同点:输出可被人快速核对(有底层数据链接)、错了代价低、替代的是最被痛恨的杂务。
- transfer: NPD 场景直接对应:从任务/交付物活动流自动生成周度项目状态、阶段门评审材料包(gate review packet)初稿、试产问题清单汇总;强制要求每条结论附来源链接(哪个任务/哪份交付物),评审时人签字确认。这是最低风险、最高频、最先该做的 AI 角色。
- src: https://www.eesel.ai/blog/clickup-brain

### idea: 已验证用例 2:工作区检索问答(Ask X)
Ask Notion / ClickUp Brain 搜索被多方评测列为'从噱头变刚需'的功能:跨任务、文档、评论找答案,省掉翻找时间;ClickUp Brain MAX(2025)进一步做跨应用检索+语音转指令。前提是数据在系统内——ClickUp Brain 早期只能搜 ClickUp 内部被明确列为关键局限。
- transfer: NPD 里问答价值更高因为语料是结构化的:'DVT 阶段还缺哪些交付物''这个 ECN 影响哪些在制任务''上次模具评审的遗留项'。答案应是实体链接列表而非纯文本,错误可即时发现。
- src: https://www.eesel.ai/blog/notion-ai-review

### idea: 已验证用例 3:结构化字段自动填写、查重、拆子任务(建议式,人确认)
Dart 的 duplicate detection 被创始人称为'最受欢迎功能之一',HN 用户 (bestlauren) 说这能省下 backlog refinement 的大量痛苦;自动填 task properties、AI 拆 subtask 同样被用起来,但 Dart 的 accept/reject 交互曾被用户吐槽要重做——说明'建议+确认'的交互质量决定采用率。Height 2.0 的 bug 自动分诊本质是同一用例的全自动版,产品死了;建议式版本活着。
- transfer: 跨职能 intake(市场/销售/产线反馈)自动归类到项目与类别、自动填元数据、识别重复问题单;交付物上传后自动对照模板检查项预填。全部走建议+人确认,不做静默写入。
- src: https://news.ycombinator.com/item?id=39442368

### idea: 已验证用例 4:约束求解式自动排程(引擎确定性,AI 只做解释和输入)
Motion 是唯一以排程为核心活下来并规模化的:任务+优先级+截止期自动排进日历,没做完自动顺延,评测共识是'如果你的日历一团糟,它真的有用';10,000+ SMB 付费客户、ARR 约 $50M。注意其核心是确定性优化引擎而非 LLM,LLM 幻觉风险为零;用户抱怨集中在'临时变更时太死板'和计费手法,不在排程本身。
- transfer: NPD 的资源负载与排期重算(gate 延期后下游任务自动重排、跨项目资源冲突提示)应该用确定性调度算法实现,AI 负责解释'为什么这样排'和把自然语言约束翻译成参数。不要用 LLM 直接排任务。
- src: https://sacra.com/c/motion/

### idea: 已验证用例 5:高频、可模板化的 intake/分诊工作流 agent(带人工检查点)
Asana AI Studio 的真实落地场景是 campaign 上线、product intake、service ticketing 这类高量重复流:Indeed 用它减少 42% 人工工单处理;有 8 家客户仅 AI Studio 年花费超 $10 万。Asana 为 AI Teammates 建了逐次执行反馈机制(每次执行可提交文字反馈,团队全量阅读)+自建 LLM 评估框架——说明生产级 agent 必须配评估与反馈闭环。但总收入仅 $6M+ ARR,证明这是慢生意。
- transfer: ECR/ECN 受理与路由、供应商问题单分诊、测试失败报告归类是制造业 NPD 里同构的高频流。设计要点:agent 只推进到检查点,人放行;每次执行留痕可反馈;不按 credit 卖(见教训)。
- src: https://investors.asana.com/news-releases/news-release-details/asana-announces-ai-studio-no-code-builder-designing-and

### idea: 交互设计:具名角色 agent 划定预期边界
Motion 把 agent 拟人化为 'Alfred the Executive Assistant / Millie the Project Manager / Chip the Sales Rep',每个角色能做的多步工作流(起草邮件、更新 CRM、生成报告)边界清晰,这一产品化让 AI Employees 3 个月从 0 做到八位数 ARR。对比之下 Height 的无形'reasoning engine in every project'让用户不知道 AI 什么时候会动他们的数据。
- transfer: 与其做泛用 copilot,不如做 2-3 个职责明确的角色:'汇报员'(只读,生成状态与 gate 材料)、'分诊员'(intake 归类,建议式)、'检查员'(交付物完整性核对)。角色即权限边界,用户一眼知道谁在做什么、能不能改数据。
- src: https://www.businesswire.com/news/home/20250905188051/en/Motion-Raises-$60M-at-$550M-Valuation-to-Build-the-Agentic-Work-Suite-for-Businesses

### pattern: 全自主项目管理 / autonomous chores(Height 2.0) [已证伪:发布约 5 个月后(2025-03-22)宣布关停,2025-09-24 停服。公司 2018 年创立、融资 $18.3M。HN 用户称'我们团队并不意外,鉴于近期的产品决策';Creativerly 分析认为 v2.0 投入过重且核心产品竞争不过 Linear。]
每个项目内置'AI reasoning engine',自动执行 chores:分诊新 bug、清理与去重 backlog、随进展更新 spec、追问状态、上浮 blocker——定位为'第一个自主项目协作工具'(2024-10-08 发布)。此前已有 Height Copilot(2023-04)。

### pattern: AI 自动排程(Motion 核心) [已上线且验证:10,000+ SMB 付费客户,B2B 收入 3x YoY。用户口碑'排程真的好用',抱怨集中在死板、移动端弱、试用期自动转年费的计费手法(Trustpilot 反复出现)。]
任务(优先级、时长、截止期)+ 会议约束自动排入个人/团队日历;有变动秒级重算;没做完的任务自动前滚直到完成。本质是约束优化引擎,AI 包装输入输出。

### pattern: 具名 AI Employees 套件(Motion 2025 转型) [已上线,商业验证强:2025-05 发布后 3 个月 $0→八位数 ARR,带动总 ARR 至约 $50M,2025-09 以 $550M 估值再融 $60M。]
在既有工作管理平台内推出自主 agent:Alfred(行政助理)、Millie(项目经理)、Chip(销售),执行多步工作流(起草邮件、更新 CRM、生成报告),按固定席位打包卖给 SMB。

### pattern: AI PM 助理:字段填写/查重/拆任务/报告(Dart) [已上线,小而存活:约 10 人团队、种子轮约 $500K。Product Hunt/Trustpilot 好评集中在速度与 AI 减负(自称省 7h/周);HN 质疑切换成本与被 Linear/Jira 复制的风险。属于'功能被验证、生意未被验证'。]
YC W22,2022 年创立。AI 自动填 task properties、检测重复任务、生成 subtasks、写周报/changelog、AI 排 roadmap;2025 后转向 chat-as-UI + 可定制 agents 作为一等协作者。

### pattern: No-code 工作流 agent + credit 计费(Asana AI Studio) [已上线但变现慢:FY2026 财年末 ARR 仅 $6M+(公司总收入约 $8 亿),Q4 环比增 50%+,8 家客户年花超 $10 万。真实案例:Indeed 人工工单处理 -42%。用户抱怨 credit 模型'真心令人困惑',重度用法折算每人每月可达 $300 附加费。]
2024-10-22 发布。无代码把 AI 步骤嵌入既有工作流(intake→计划→执行→汇报),依托 Work Graph 提供上下文;按 credit 消耗计费(Plus 档 $150/月 100K credits)。

### pattern: AI Teammates 协作代理(Asana) [beta(GA 预期 FY27 Q1)。方向上是'AI 参与协作而非替代 PM',效果待验证。]
2025-09-25 发布 beta:理解全组织工作上下文的协作 agent,一个 agent 服务多个团队,靠人类反馈持续改进;每次执行可提交反馈,配自建 LLM 评估框架。

### pattern: 嵌入式全域助手 + AI StandUp(ClickUp Brain / Brain MAX) [已上线,商业强劲:2025-09 披露冲向 $300M ARR、AI 销售 +400% YoY、AI 用量 +800%、20M 用户。但用户端有强推反弹:官方反馈区高票请求'关掉 Brain 弹窗/横幅'(遮挡 20% 屏幕、无法局部禁用)。]
AI 遍布产品各处:写作、工作区问答、AI StandUp 自动汇编每日更新、项目摘要、自动拆 subtask;Brain MAX(桌面伴侣)跨应用检索+语音转指令;Autopilot Agents 按触发器在 Space/List 级执行;Super Agents(2026-02)自然语言建 agent。

### pattern: 自主工作区 agents(Notion 3.0 / Custom Agents) [已上线:发布当天 CNBC 报道 ARR 破 $500M,年底约 $600M,估值 $10B+。评测共识'从噱头变有用',但 agent 输出普遍需要人工复查、不建议无检查点用于对客流程;2025-05 取消 $8 AI 附加包、把 AI 锁进 $20 Business 档引发涨价强烈反弹。]
2025-09-18 发布 3.0:agent 可做'你在 Notion 里能做的任何事',20+ 分钟多步工作,跨 pages/databases,配 MCP 连接器;2026 年 Custom Agents 支持定时/触发运行,按 credit 计费。

## ui_patterns
- 建议+确认(accept/reject)而非静默写入:Dart 的 subtask 接受/拒绝交互;Notion agent 输出默认需要 review pass——AI 改结构化数据前必须给人过目
- 具名 persona agent 划定能力与权限边界(Motion 的 Alfred/Millie/Chip),避免'看不见的 AI 在动我的项目'(Height 的反面)
- agent 执行留痕 + 逐次反馈入口:Asana AI Teammates 每次执行附文字反馈框,团队全量阅读并用 AI 归类反馈主题
- 触发器式 agent 配置面(ClickUp Autopilot Agents 挂在 Space/Folder/List/Chat 上),把 agent 当自动化规则来管理而非聊天窗
- credit/用量可视化仪表:Asana 与 Notion 都因 credit 模型不透明挨骂——若按量计费必须给实时消耗面板
- 机器主导的日历 + 顺手的人工覆盖(Motion):自动排程可接受的前提是覆盖/锁定操作足够轻
- 反面模式:不可局部关闭的 AI 弹窗/横幅(ClickUp 官方反馈区高票投诉)——AI 入口必须可按模块静默
- chat-as-UI 作为补充入口而非唯一入口(Dart):HN 反馈显示用户仍要传统列表/看板做主视图

## lessons
- 陷阱 1 — '全自主 AI 项目经理'定位反复失败:Height 2.0 以'首个 autonomous 项目协作工具'为卖点,5 个月后宣布关停;HN 评论'谁想执行一份 AI 生成的任务清单?'点出本质——自动化任务分配剥夺执行者的 ownership,且静默自动修改(改 spec、动 backlog)摧毁对系统记录的信任。自主性只能给可验证、低代价、可回滚的杂务,且要可见可撤销。
- 陷阱 2 — AI 作为强推的付费上层建筑:三大平台全部踩坑——Notion 2025-05 取消 $8 AI 附加包变相涨价 100% 引发迁移潮讨论;Asana credit 计费被用户算出重度使用每人每月 $300 附加费、'genuinely confusing';ClickUp 不可关闭的 AI 弹窗成官方反馈区高票投诉。且变现远慢于宣传:Asana AI Studio 一年半只做到 $6M ARR(主营 $8 亿)。AI 收费要么并入席位价、要么给透明用量面板,不要按次数刁难。
- 陷阱 3 — AI 补不了核心产品的竞争劣势:Height 的教训是它输给 Linear 不是因为 AI 不够多,而是核心工具与生态弱;Dart 在 HN 被一针见血质疑'这些 AI 功能 Linear/Asana/Jira 都会跟进,切换成本凭什么值得?'。AI 功能本身不构成护城河,护城河是系统内沉淀的结构化工作数据与流程绑定。
- 陷阱 4(通用信任税)— 幻觉让'AI 状态汇报'有归零风险:调查中 51% 受访者把幻觉列为最大采用障碍;错误的状态报告比没有报告更糟(误导 gate 决策)。所有成立的用例共同点是输出可被数据回溯验证——不带 provenance 的 AI 汇总在 PM 域不可用。

## sources
- https://www.businesswire.com/news/home/20241008197812/en/Height.app-Unveils-First-Ever-Autonomous-Project-Collaboration-Tool-for-Product-Builders
- https://x.com/height_app/status/1903820182557999555
- https://www.creativerly.com/height-app-is-shutting-down/
- https://alternativeto.net/news/2025/3/height-project-management-tool-to-shut-down-by-september-2025/
- https://news.ycombinator.com/item?id=43454034
- https://techround.co.uk/interviews/meet-michael-villar-ceo-at-ai-project-tool-for-builders-height/
- https://sacra.com/c/motion/
- https://www.businesswire.com/news/home/20250905188051/en/Motion-Raises-$60M-at-$550M-Valuation-to-Build-the-Agentic-Work-Suite-for-Businesses
- https://www.saner.ai/blogs/motion-reviews
- https://www.trustpilot.com/review/www.usemotion.com
- https://www.capterra.com/p/214264/Motion/reviews/
- https://news.ycombinator.com/item?id=39442368
- https://www.ycombinator.com/companies/dart
- https://www.producthunt.com/products/itsdart/reviews
- https://tracxn.com/d/companies/dart/__rJDxgecLJ62FLnbGQZ9m92I9B36Ga--HbwFpp0EXxzU
- https://www.dartai.com/
- https://investors.asana.com/news-releases/news-release-details/asana-announces-ai-studio-no-code-builder-designing-and
- https://siliconangle.com/2024/10/22/asanas-ai-studio-promises-transform-work-management-smart-workflows-task-automation/
- https://investors.asana.com/news-releases/news-release-details/asana-announces-new-ai-teammates-collaborative-agents-deliver
- https://asana.com/inside-asana/custom-llm-evaluation-ai-teammates
- https://finance.yahoo.com/news/asana-inc-asan-q4-2026-050123369.html
- https://www.fool.com/earnings/call-transcripts/2026/05/28/asana-asan-q1-2027-earnings-transcript/
- https://stackcut.net/saas-costs/asana
- https://www.spendhound.com/marketplace/asana-pricing
- https://finance.yahoo.com/news/clickup-accelerating-300-million-annual-130000796.html
- https://getlatka.com/companies/clickup
- https://clickup.com/blog/contextual-ai-super-app/
- https://feedback.clickup.com/feature-requests/p/disable-brain-ai-pop-up
- https://feedback.clickup.com/feature-requests/p/disable-clickup-brain-banners-in-task-view
- https://feedback.clickup.com/feature-requests/p/turn-off-ai
- https://www.eesel.ai/blog/clickup-brain
- https://www.zenpilot.com/clickup-ai/
- https://www.notion.com/releases/2025-09-18
- https://www.cnbc.com/2025/09/18/notion-launches-ai-agent-as-it-crosses-500-million-in-annual-revenue.html
- https://news.ycombinator.com/item?id=45304816
- https://www.eesel.ai/blog/notion-ai-review
- https://sacra.com/c/notion/
- https://thedigitalprojectmanager.com/project-management/ai-in-project-status-reporting/
