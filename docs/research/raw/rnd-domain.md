# rnd-domain

## summary
制造业研发 PM 的痛点有扎实证据:技术人员约 20% 时间耗在非生产性数据管理(Tech-Clarity),PM 每周 3-4 小时手工拼状态报告,且状态汇报存在系统性失真——PM 乐观偏差叠加汇报偏差(MIT Sloan/Keil);stage-gate 被 Cooper 本人承认常退化为官僚文档流程;变更成本按 rule of ten 逐阶段十倍放大,倒逼 AI 价值向早期左移。厂商侧:Siemens/PTC/Dassault/Autodesk 已把 copilot 嵌入 PLM(2025-2026 陆续 GA),但被批评为"旧系统加助手";初创(CoLab、Duro、Flow、Valispace、Instrumental、nPlan)从评审、需求、build 数据、进度风险等单点切入且有量化客户成果。而 AI-native 的 NPD 项目管理层(自动 gate 材料装配、状态自动生成、跨职能风险预警)尚无明确赢家,是清晰的空窗。

## positioning
该域呈三层格局:(1) PLM 巨头(Siemens/PTC/Dassault/Autodesk)把生成式 AI 作为现有系统的自然语言入口,强在数据存量、弱在架构——被 Beyond PLM 等批评为"在 25 年前设计的数据库上加 assistant";(2) 硬件研发初创各占一个单点工作流:CoLab(设计评审)、Flow/Valispace(需求)、Duro(AI-native PLM)、Instrumental(NPI build 数据)、nPlan(进度风险),共同特征是把某类工程原语(评审意见、需求参数、缺陷影像、历史排期)结构化后喂 AI;(3) 通用 PM 工具(Asana/MS Copilot)验证了会议→行动项、AI 状态草稿等用例但不懂 NPD/gate 语义。真正把 stage-gate 流程本身做成 AI-native(gate 交付物自动装配、状态从工程信号自动生成、基于组织历史的风险预警)的产品还不存在——Cooper 的"第五代 Stage-Gate/AI-assisted gates"仍停留在框架论文层面,这正是新产品的差异化空间。

## data_model
所有可信来源指向同一结论:AI 的上限由数据底座决定。(1) 工程原语必须结构化成对象而非文档:需求/参数(Flow 的『活需求』)、评审意见(CoLab 的可召回历史反馈)、缺陷与根因(Instrumental)、排期与实际(nPlan 的 75 万份 schedule)——每家成功初创本质上都是先把一类原语变成干净数据资产。(2) 对象间要有显式关系图(digital thread):任务-交付物-需求-变更-供应商-认证测试的依赖关系是影响分析与风险传播的前提;rule of ten 意味着这张图的价值在早期最大。(3) Shilovitsky 的两层架构值得借鉴:跨系统『产品记忆』知识图谱 + 带权限/审计/预算控制的 agent 编排层;agent 写操作走与人相同的权限通道。(4) 对 PM 系统的具体启示:gate 交付物建模为『对结构化数据的视图』而非上传的 PPT;评审意见、gate 决议(Go/Kill/Hold/Recycle + 条件项)、延误原因都要落库为可检索对象,它们是未来组织记忆型 AI 的训练语料。

### idea: 状态汇报从『人填』改为『系统起草+人确认』
证据链:PM 平均每周 3-4 小时写状态报告、45% 的 PM 每周花超一天手工收集状态(PPM Express 汇总);更根本的是 Snow & Keil 的研究证明状态汇报存在两级失真——PM 感知的乐观偏差 + 向上汇报时的粉饰偏差(project status distortion),项目风险越高失真越大,高管『不能按面值相信绿灯报告』。McKinsey 2023 调研称自动化状态报告每 PM 每月省 13.5 小时。Gartner 2019 即预测 2030 年 AI 将接管 80% 的 PMO 数据收集/跟踪/报告类任务。
- transfer: 状态不再是一个人工填写字段,而是从任务完成、交付物提交、变更单、测试结果等工程信号自动汇编的草稿,负责人只修改结论与解释。关键洞察:失真是激励问题,所以 AI 必须直接读原始信号而非让人再填一遍表;把『AI 草稿 vs 人工修正』的差异留痕,本身就是治理信号。
- src: https://sloanreview.mit.edu/article/the-pitfalls-of-project-status-reporting/

### idea: Gate 交付物 = 结构化数据的视图,AI 负责装配
Cooper 本人承认 stage-gate 常退化为『cumbersome, bureaucratic, painful to navigate and rigid』的文档官僚流程;gate 因多方审批与文档要求而拖慢节奏。Cooper & Sommer 的六公司案例研究(LEGO、Honeywell、GE 等)显示制造企业采用 Agile-Stage-Gate 混合后每项目工作量减约 25%、上市更快。Cooper 2024 年起在 Research-Technology Management 与 Stage-Gate International 系列文章中主张把 AI 嵌入 stage-gate:AI 起草 gate 文档、做初筛评估,即『AI-assisted gates』(尚属框架愿景)。
- transfer: gate 评审包不再由团队熬夜拼 PPT,而是系统对既有结构化对象(交付物状态、风险、测试结果、成本)自动生成评审视图 + AI 起草论述,gatekeeper 审例外而非审文档。这是 NPD 域最直接的『材料准备负担』解法,且现有厂商无人做成产品。
- src: https://www.sciencedirect.com/science/article/abs/pii/S0019850116301894

### idea: 组织记忆型评审:用本组织标准+历史评审意见审新交付物
CoLab AutoReview(已 GA)自动审查 2D 图纸/3D 模型:按组织自己的设计标准与检查单执行(官方表述为 review 'the way your team reviews, not just the way an LLM would'),并从几何/元数据召回历史相似件的专家评审意见。客户含 Schaeffler、Johnson Controls、Mainspring Energy,宣称 BOM 成本降最高 50%、设计周期加速。
- transfer: 交付物模板库 + 历史评审意见库是现成的『组织记忆』语料:AI 审查器按模板检查项预审交付文档,并召回同类项目/同类交付物上的历史评审意见。前提是评审意见必须落库成结构化、可检索对象,而非散在会议纪要里——这是数据模型层的硬要求。
- src: https://www.colabsoftware.com/product/autoreview

### idea: 需求/关键参数做成『活对象』,变更自动传播
Flow Engineering($23M Series A,Sequoia 领投,客户 Rivian/Joby/Astranis/VW)的核心诊断:硬件是『系统集成但工具分散』——Excel 里一个小改动会牵连 Python 代码、CAD、成本与需求。其产品把需求从静态文档变成跨机械/电气/软件共享的参数化设计标准,可每天更新并保持 live traceability。Valispace ValiAssistant(2023)用 LLM 做需求书写、需求间不一致检测、需求参数化以支持自动验证。
- transfer: PM 系统里的交付物不应只是文件附件:抽出关键参数(重量、功耗、成本目标、认证指标)做成结构化字段,任务/交付物/需求间建显式依赖,参数变更时 AI 沿依赖图生成影响提醒。这直接回应『交付物质量参差』与『跨职能协调』两个痛点。
- src: https://www.flowengineering.com/blog/flow-raises-23m-from-sequoia-to-accelerate-the-future-of-hardware-development

### idea: 少样本冷启动的异常预警 + 跨 build 记忆
Instrumental(NPI 制造 AI)宣称 5 台样机即可开始异常检测,并显式做跨阶段记忆:『如果 EVT 修掉的问题在 DVT 又出现,立即通知』;失败分析提速 90%。客户数据:Meta 每年 7 个项目省 900+ 工程周,NVIDIA 系统 build 提前 14 天,Toast 5.3x ROI。这证明在硬件小样本语境下 AI 预警可行且有付费验证。
- transfer: 问题/风险库要跨项目复用:新项目出现同类症状(同类零件、同类测试失败、同一供应商)时自动关联历史根因与解法。硬件迭代少而贵,单项目内数据永远不够,『跨项目组织记忆』是 AI 预警在 NPD 域成立的唯一路径。
- src: https://instrumental.com/

### idea: 用组织历史排期数据做逐活动风险预测
nPlan 用 75 万份历史工程进度计划(约 $2T 项目额)训练图神经网络,对计划中每个活动输出工期不确定性、识别亚关键路径,Network Rail 在 Great Western Main Line 项目实际使用。学术侧也有 XGBoost 类模型在施工延误预测上达 92% 精度的报告。这是『风险发现滞后』痛点的已验证解法,但目前只在基建域落地,NPD 域是空白。
- transfer: 从第一天就把项目计划/实际工期/延误原因作为训练资产沉淀;早期可用规则+检索(同类任务历史工期分布)替代深度模型,给新计划的每个任务标注『按你司历史,此类任务超期概率高』。注意与用户已确认的任务状态语义铁律兼容:预警是提示层,不改变状态机。
- src: https://www.nplan.io/

### idea: 会议纪要直接挂接任务系统
M365 Copilot 在制造场景的官方用例:设计评审、产线会议、供应商电话自动转成行动项并与工程/质量对齐;企业报告员工每周省 2.5-5 小时,有组织称 100 用户年省 2 万小时(厂商口径,需打折)。Asana smart status 验证了 AI 起草状态更新的产品形态。
- transfer: 评审会/供应商会的纪要不落在文档里,而是生成任务/阻碍/决策三类结构化对象进入系统,并回链到会议来源。gate 会议尤其适合:决议(Go/Kill/Hold/Recycle)+ 条件项自动生成下阶段任务。
- src: https://adoption.microsoft.com/en-us/scenario-library/manufacturing/

### idea: 先修数据底座,再放开 agent;写操作要有权限与审计层
Beyond PLM(Oleg Shilovitsky)的系统性批评:四大 PLM 厂商都在『旧系统里嵌助手』而非为智能化重新设计;copilot 完全依赖上下文,在碎片化脏数据上『放大噪声和放大信号一样高效』,用户被迫追问『AI 对错误数据的判断是否正确』。他主张两层架构:跨系统的产品记忆层(知识图谱:设计/成本/工艺/供应链)+ 多智能体编排层(管权限、工具访问、预算、审计)。
- transfer: AI-native 不等于到处放聊天框:先保证任务/交付物/gate/变更是干净的结构化对象和显式关系图,AI 读得到可靠上下文;agent 的写操作(改状态、建任务)必须走与人相同的权限与审计通道,并保留人工确认闸门——这与制造业客户的信任门槛一致。
- src: https://beyondplm.com/2025/11/22/building-plm-agents-why-everyone-is-announcing-ai-and-why-almost-everyone-is-missing-the-point/

### idea: AI 价值左移:变更影响分析在创建时即时给出
变更成本的 rule of ten:每晚一个生命周期阶段,实施变更的成本增加约 10 倍;70-80% 的制造成本在概念设计结束时已被锁定。Duro Design(2025-06 发布,自称首个 AI-native PLM)把 impact analysis、validations 作为内建 AI 能力放在统一 digital thread 上。
- transfer: 变更单创建瞬间,AI 沿依赖图列出受影响的交付物/任务/供应商/认证测试及成本量级,把『变更的真实代价』前置到决策时刻。对硬件研发,这比任何后期自动化都值钱,因为物理迭代不可逆。
- src: https://www.cenit.com/en_EN/newsroom/article/cost-risks-in-engineering-change-management.html

### pattern: 嵌入式 PLM Copilot(自然语言查询/摘要产品数据) [已上线]
在 PLM 内嵌聊天入口,对 Teamcenter/Windchill 管理的数据做 RAG:自然语言问答、单文档摘要、自然语言 BOM 交互、以图搜件(Azure Vision)。Siemens Teamcenter 2506 Copilot 支持 AWS/Azure/Llama 部署;PTC Windchill AI Assistant 2026-04 GA,定位『找到并理解产品数据』。

### pattern: 跨对象上下文编排的 Virtual Companion [Aura 已上线,Leo/Marie beta/预告]
Dassault 3DEXPERIENCE 的 Aura 横跨 requirements/projects/changes 编排知识与上下文,帮团队『保持对齐』;Leo(工程求解)与 Marie(科学发现)2026 年内推出。区别于单纯问答:强调理解工业项目上下文。

### pattern: 按组织标准+历史评审记忆的自动设计/文档审查 [已上线(Schaeffler、Johnson Controls 等付费客户)]
CoLab AutoReview 分析图纸几何、元数据与制造细节,按客户自己的标准与检查单跑检查,并召回历史相似件上的专家评审意见,和人工批注同流呈现。

### pattern: AI 需求工程(书写/一致性检测/参数化) [已上线(细分领域,航天/eVTOL 客户)]
Valispace ValiAssistant 用 LLM 起草需求、找需求间矛盾、把文本需求参数化以便 V&V 阶段自动验证;Flow 把需求做成跨学科 live 参数对象并保持追溯。

### pattern: 历史排期数据训练的进度风险预测 [已上线(基建域验证;NPD 域无对应产品)]
nPlan 以 75 万份历史进度计划训练 GNN,对每个计划活动输出工期不确定性分布,识别亚关键路径并做风险处置情景模拟;Network Rail 实际使用。

### pattern: 制造 build 数据少样本异常检测与跨阶段记忆 [已上线(Meta/NVIDIA/Toast 有量化成果)]
Instrumental 从 5 台样机开始做影像+测试数据异常检测,EVT 修复的问题在 DVT 复发即告警,AI 关联失败-数据-影像做根因分析(称省 90% 分析时间)。

### pattern: 会议→行动项→任务系统 [已上线(通用工具,不懂 NPD 语义)]
M365 Copilot 把设计评审/产线会/供应商会转写并蒸馏成摘要、决策、行动项,回填 Teams/Planner;制造场景是微软官方 scenario library 的一类。

### pattern: AI 状态草稿(suggest status + draft update) [已上线]
Asana 智能状态:AI 根据项目近期活动建议健康度并起草状态更新、自动生成进度图表,人工编辑后发布。

### pattern: 变更影响分析 AI [已上线/beta(2025-06 发布,验证深度待观察)]
Duro Design 在统一 digital thread 上内建 validations、impact analysis、metadata 生成与 sourcing 建议,主打变更牵连的自动评估。

### pattern: Agentic AI 贯穿 digital thread(厂商战略层) [仅愿景/beta(单点 assistant 已 GA,跨环节 agent 未见实证)]
PTC 表述为『advancing agentic AI use cases across the product digital thread』:Windchill AI + Codebeamer AI(需求)+ ServiceMax AI(现场服务)分别在各环节做 agent,再靠 digital thread 串联。

### pattern: AI-assisted gates / 第五代 Stage-Gate [仅愿景(框架与研究,无成型产品)]
Cooper 主张把 AI 嵌入 stage-gate 信息流:AI 起草 gate 交付物、做项目初筛与监控;其与 Brem 的多公司研究显示 NPD 中 AI 采用率从 2023 初 13% 升至 2024 初 24%,早期采用者开发时间缩短约 50%(40+ 类应用、400+ 供应商)。

### pattern: 产品记忆层 + 多 agent 编排层(架构主张) [仅愿景(行业评论,方向正确性被广泛引用)]
Shilovitsky:真正的 PLM agent 需要跨系统知识图谱(product memory:设计/成本/工艺/供应链)作为上下文,其上是管理权限、工具访问、预算、审计的编排层;反对在单一旧系统里困住 agent。

## ui_patterns
- 聊天式 copilot 作为 PLM 主界面的侧栏/伴随窗,而非独立应用(Teamcenter Copilot、Windchill AI Assistant)
- 自然语言查询替代表单式检索与报表(『哪些零件用了这个供应商的料』直接问)
- AI 草稿 + 人工确认的两段式发布:状态更新、会议行动项、图纸批注都先出草稿(Asana smart status、CoLab)
- AI 发现的问题与人工评审批注锚定在同一图纸/3D 模型位置、同一评论流中呈现,而不是另开报告(CoLab AutoReview)
- 以图搜件/多模态检索:拍照或截图找相似零件与其历史(Teamcenter 2506 image-to-part)
- 风险用网络图与亚关键路径可视化,每个活动带不确定性区间而非单点日期(nPlan)
- 跨阶段复发告警以事件流推送(『EVT 修过的问题在 DVT 复发』即时通知,Instrumental)
- 会议纪要自动结构化为摘要/决策/行动项三段式并可一键转任务(M365 Copilot)

## lessons
- 『旧系统加助手』被点名批评:Dassault/Siemens/PTC/Aras 都采取在既有架构上嵌 assistant 的策略,Beyond PLM 认为这只是 UI 层添加,PLM 数据库是 25 年前为记录设计的,不支撑智能推理;工程工作流横跨 CAD/ERP/MES,单系统内的 agent 天然残缺(https://beyondplm.com/2025/11/22/building-plm-agents-why-everyone-is-announcing-ai-and-why-almost-everyone-is-missing-the-point/)
- 脏数据上的 copilot 放大噪声:上下文不完整时,用户被迫追问『AI 对错误数据的判断是否正确』,认知负担反而上升——数据治理先于 AI 功能(https://beyondplm.com/2025/08/10/why-just-add-ai-to-plm-wont-work/)
- 厂商叙事与客户体验脱节:CIMdata 首个 AI-in-PLM 全球研究发现两者差距『比任何人预期都大』;PLM 厂商新闻稿提 AI 的比例一年内从 7% 涨到 29%,存在明显 AI-washing(https://www.cimdata.com/en/education/educational-webinars/webinar-the-state-of-ai-in-product-development-what-cimdata-s-ai-in-plm-global-study-reveals)
- 企业 AI 项目高失败率的底色:RAND 口径约 80% AI 项目无可衡量业务价值,2025 年 42% 公司放弃了多数 AI 计划;幻觉事件显著削弱一线信任——面向制造业客户,『AI 可能自信地出错』要作为设计前提而非边角情况
- 状态汇报自动化的陷阱:失真根源是激励(报喜不报忧),若 AI 只是帮人把要填的内容写得更快,失真依旧;必须从工程信号直接生成,并保留人工修正的痕迹作为治理信号(MIT Sloan / Snow & Keil)
- stage-gate 的教训预演了 AI 的风险:一个本意是决策系统的框架,在多数组织退化成官僚文档流程(Cooper 本人承认);AI 若被用来更快地生产 gate 文档而非减少文档,只会加速官僚化——正确目标是让 gate 审例外、审数据,而不是审更厚的材料
- 硬件域的根本约束:迭代少而贵(交付首个产品前常烧 €2-5M)、12-24 个月周期、认证测试不可跳过、70-80% 成本在概念期锁定——单项目数据永远稀疏,AI 必须依赖跨项目组织记忆与少样本方法,且价值重心在早期(左移),这与软件研发 AI(高频迭代数据充裕)的打法本质不同(https://blog.bolt.io/hardware-is-not-the-new-software/)

## sources
- https://sloanreview.mit.edu/article/the-pitfalls-of-project-status-reporting/
- https://www.researchgate.net/publication/3076745_The_challenge_of_accurate_software_project_status_reporting_A_two-stage_model_incorporating_status_errors_and_reporting_bias
- https://tech-clarity.com/engineering-time-wasters-survey-results/11285
- https://www.ppm.express/blog/how-to-automate-project-status-reports-and-free-up-your-time
- https://www.in-parallel.com/insight/the-status-update-is-a-lie/
- https://siliconangle.com/2019/03/20/gartner-says-ai-will-assume-80-project-management-tasks-2030/
- https://projectproduction.org/journal/stage-gate-what-are-the-implications/
- https://diginsights.com/resources/pitfalls-stage-gate-process/
- https://www.sciencedirect.com/science/article/abs/pii/S0019850116301894
- http://www.five-is.com/wp-content/uploads/Agile-Stage-Gate-for-Manufacturers-in-RTM-Cooper-Sommer-March-2018.pdf
- https://stage-gate.com/about/ai-next-gen-stage-gate
- https://www.researchgate.net/publication/380096360_Unleashing_the_Power_of_Artificial_Intelligence_in_New_Product_Development_Building_AI_Into_Your_Stage-GateR_New-Product_Process_The_Coming_AI_Wave
- https://www.stage-gate.com/wp-content/uploads/2024/05/SGI-Articles-Transform-NPD-with-AI-by-Dr-Cooper-Part-2.pdf
- https://blogs.sw.siemens.com/teamcenter/teamcenter-2506-copilot-genai/
- https://www.siemens.com/en-us/products/teamcenter/teamcenter-ai/
- https://www.ptc.com/en/news/2025/ptc-brings-ai-powered-plm-to-hannover-messe
- https://www.ptc.com/en/news/2026/ptc-launches-windchill-ai-assistant
- https://www.3ds.com/newsroom/press-releases/dassault-systemes-unveils-new-way-working-industry-ai-powered-virtual-companions
- https://adsknews.autodesk.com/en/news/autodesk-ai-strengthens-fusion-and-alias/
- https://www.colabsoftware.com/product/autoreview
- https://www.engineering.com/colab-launches-autoreview-ai-tool-for-design-review/
- https://durolabs.co/press/duro-unveils-duro-design/
- https://www.prnewswire.com/news-releases/valispace-releases-worlds-first-ai-engineering-assistant-301842496.html
- https://www.flowengineering.com/blog/flow-raises-23m-from-sequoia-to-accelerate-the-future-of-hardware-development
- https://instrumental.com/
- https://instrumental.com/build-better-handbook/evt-dvt-pvt
- https://www.nplan.io/
- https://ascelibrary.org/doi/abs/10.1061/(ASCE)CO.1943-7862.0001736
- https://blog.bolt.io/hardware-is-not-the-new-software/
- https://resources.altium.com/p/why-hardware-development-is-different
- https://www.cenit.com/en_EN/newsroom/article/cost-risks-in-engineering-change-management.html
- https://beyondplm.com/2025/11/22/building-plm-agents-why-everyone-is-announcing-ai-and-why-almost-everyone-is-missing-the-point/
- https://beyondplm.com/2025/08/10/why-just-add-ai-to-plm-wont-work/
- https://beyondplm.com/2025/03/30/my-12-observations-from-cimdata-industry-and-market-forum-in-ann-arbor-this-week/
- https://www.cimdata.com/en/education/educational-webinars/webinar-the-state-of-ai-in-product-development-what-cimdata-s-ai-in-plm-global-study-reveals
- https://adoption.microsoft.com/en-us/scenario-library/manufacturing/
- https://2wtech.com/microsoft-365-copilot-for-manufacturing-teams-real-examples-for-engineering-operations-and-customer-service/
- https://asana.com/features/project-management/status-updates
- https://www.mckinsey.com/capabilities/operations/our-insights/operations-blog/using-ai-to-supercharge-r-and-d-takeaways-from-the-r-and-d-leaders-forum
