# mfg-data-backbone

## summary
结论:ambient capture 的数据底座在制造业「分层成立」。云原生层已就绪——Arena 公开 OpenAPI 文档、Duro GraphQL API+MCP 已上线、Onshape API 自助且官方 FeatureScript MCP 进入 early access;CoLab 与 Instrumental 证明「从评审交互/产线影像自动生成结构化研发记录」商业可行(CoLab 拿下 Bombardier 数百万美元合同)。但存量主战场相反:Teamcenter 2606 的 AI BOM Agent、Windchill AI Assistant(均 2026 年随版本 GA)是内嵌自家产品的 agent,对外均无官方 MCP,社区 MCP 全部玩具级(一个已 archived 且标注 not functional);全球 on-prem 装机存量仍占约半数以上,中国 2024 年 SaaS PLM 仅占 PLM 软件市场 5.25%,军工/涉密企业物理隔离、数据不出网。因此第三方 PM 层不能复制 Lightfield 只接云 API 的路径:应以 IM(飞书/钉钉/Teams)+邮件+会议+共享盘 Excel 为主采集面,PLM 走低频只读同步,并准备 on-prem LLM 部署选项(Siemens 已用 Llama 4.0 Scout on-prem 印证);冷启动回填的先例是 Excel 导入+AI 摄取旧评审文档/lessons-learned 表格(CoLab ingestion engine),邮件回填在制造业尚无成规模先例,是空白点。

## positioning
本轮验证的判据:「原始交互是 source of truth、字段是派生视图」在制造业不能靠单一数据源实现。制造业研发的原始痕迹分裂为三层:(a) 治理层(PLM/ECO/BOM)——厂商正把 agent 内嵌到自己产品里而非开放给第三方,是竞争者而非数据源;(b) 协作层(IM/邮件/会议/评审)——API 最开放、最接近 Lightfield 的邮件/日历/会议底座,且现有 PLM 完全没占住;(c) 物理层(产线 build/试验数据)——已被 Instrumental 类专用硬件+视觉方案占据。第三方 AI-native PM 层的差异化空位在 (b):做「PLM 之外的过程记录系统」,以协作痕迹派生任务/阻碍/评审状态,与 PLM 保持只读引用关系而非竞争写入权。

## data_model
关键现实:每家 PLM 的 schema 都被深度客制(Teamcenter 用 BMIDE 扩展 item type/属性,Windchill 用软类型,Aras 用 AML 自定义 schema),第三方不能假设统一字段模型;主流机器可读出口是 OData(Windchill/Aras/Teamcenter PCM)与 GraphQL(Duro)。对 PM 层的推论:1) 以「原始交互事件」为 source of truth 的存储(消息/评审评论/审批/文档版本各带来源、时间、锚点),PLM 对象只作低频只读快照+外键引用,不做双向主数据同步;2) 字段映射做成每客户的配置层(mapping DSL/模板),而非写死代码;3) 学 Instrumental 用贯穿主键(serial number ↔ 项目/样机批次/图号)把跨系统痕迹串成 thread;4) 学 Duro 让 UI 与 agent 共用同一套带权限审计的 API。

### idea: Siemens Teamcenter 2606:agentic 是内嵌垂直 agent,不是开放接口
Teamcenter 2606(2026-06-12 发布)推出 AI BOM Agent:理解 BOM 结构、分析影响、提议变更并在受治理的工作流内执行多步操作,强调 human oversight;Copilot 扩展到 MBSE(检查需求、推荐参数、跟踪测试覆盖)、质量管理(AI 建议在插入前须用户审核)、变更管理(推荐工作流模板与任务分配)。集成策略是接 Microsoft 365 Copilot/Power BI/SAP/Salesforce,口号是 information stays where it lives。全文未提 MCP,也没有面向第三方 agent 的开放接口。
- transfer: 两点可迁移:1) agent 动作必须落在受治理工作流内+人审确认,这与「人从操作者变审核者」判据完全一致,已是行业共识;2) 大厂不会为第三方开门,PM 层接 Teamcenter 要走它的 SOA/REST API 自建连接器,且应按「联邦查询、数据留在原地」设计而非搬库。
- src: https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/

### idea: Teamcenter Copilot 的三种 LLM 部署形态是 on-prem 客户的真实需求画像
2606 起 Teamcenter Copilot 支持:纯 on-prem(Llama 4.0 Scout)、客户自有云(Azure AI 的 GPT-4.1/5.1、AWS Bedrock 的 Claude Sonnet 4.5)、Teamcenter X SaaS 三种部署。厂商专门为 on-prem 做了本地开源 LLM 选项,说明大量客户不允许研发数据出网调用云端模型。
- transfer: AI-native PM 系统若要进制造业存量市场,架构上必须把「LLM 可替换为本地模型/客户自有云端点」作为一等公民,而不是事后补丁;这也印证此前 ERP Agent Gateway 的「结构出门、数据留库」方向。
- src: https://blogs.sw.siemens.com/teamcenter/teamcenter-plm-ai-copilot/

### idea: 社区 Teamcenter MCP 全部失败或玩具级——不能指望生态白嫖连接器
srgio-es/teamcenter-mcp-server:TypeScript,基于 REST API,3 stars,2026-03-24 已 archived,README 标注 UNDER DEVELOPMENT - NOT FUNCTIONAL YET。goenninger-b-t/tc-mcp:面向 TC 2412+,宣称 30+ 工具覆盖搜索/BOM/变更/工作流,包装 JsonRestServices/SOA 端点,但仅 1 star、单次 commit,主体用小众语言 Unison 编写,明显是早期 WIP。两个项目共同说明:Teamcenter 的 API 文档需登录、数据模型经 BMIDE 深度客制,个人开发者做不出可用连接器。
- transfer: PM 层的 Teamcenter/Windchill 连接器必须自研并按客户逐个实施字段映射(每家的 item type/属性都被客制过),这是服务成本而非纯产品成本;报价与交付模型要预留连接器实施人天。
- src: https://github.com/goenninger-b-t/tc-mcp

### idea: Windchill:API 出口成熟且免费捆绑,AI 从最窄的文档场景起步
Windchill REST Services 提供 OData v4 端点(/Windchill/servlet/odata/v5,Basic auth),自 Windchill 11.0 M030 CPS06 起随 CPS 捆绑、无额外许可。Windchill AI Assistant 2026-04-28 GA,on-prem 和 Windchill+ SaaS 都能装(经 Plugin Manager),但发布说明明确:目前只回答文档 vault 内容的问答与摘要,不覆盖 metadata、其他业务对象;「agentic digital thread」仍是 Windchill AI 页面的愿景叙事。社区有 srinivasmd/windchill-plm:Python agentic skill,28 个领域客户端覆盖 OData v4 全 CRUD+BOM 多级查询+签入/签出/修订等 OData action,v1.3.0(2026-04-23),10 stars——个人项目但证明 OData 出口足以支撑 agent 全量读写。
- transfer: 1) Windchill 是存量 PLM 里技术门槛最低的采集源(OData 免费捆绑、schema 可自省),连接器优先做它;2) PTC 自己都从「非结构化文档问答」这个最窄场景切入 AI,佐证 PM 层从会议纪要/评审文档等非结构化层切入、暂不碰 BOM 写操作是稳妥路线。
- src: https://support.ptc.com/help/windchill/ai_plugin/en/Windchill_Help_Center/document_vault/WCAIAssistAIPluginReleaseNotes.html

### idea: Aras InnovatorEdge:把「暴露 API 给 agent」本身做成了产品
2026-02-26 Aras 宣布 InnovatorEdge 三件套:Edge API(云交付低代码服务,选择要暴露的数据与逻辑,生成 OData 兼容 API 供下游集成/应用/AI 工具用)、Edge Builder(SaaS 应用开发环境)、Edge AI(构建/部署/治理 agentic workflow 的服务套件,宣称可配置于任何 Innovator 环境)。核心叙事:产品数据与流程留在核心平台内治理,Edge 服务让它们在外部可消费。
- transfer: Aras 用一个独立产品线解决「安全地把 PLM 数据暴露给 agent」——反证这件事在企业里默认是难的。PM 层设计对接层时,应把「客户 IT 可自选暴露范围+审计」做成配置能力,以过 IT/安全评审;也可把 Aras 客户列为较易接入的目标画像。
- src: https://aras.com/en/news/press-releases/2026/02/aras-expands-innovatoredge-with-new-services-for-api-management-app-development-and-agentic-ai

### idea: Duro:AI-native PLM 的 API-first 样板——同一 API 驱动应用与 agent,MCP 已上线
Duro 2025 年重建为 API-first:「Every core object and workflow in Duro is exposed through the same API that powers the application itself」,GraphQL 覆盖 BOM/版本/变更单及其关系,内置 Apollo Explorer 自助探索;官方 blog 以现在时确认「Duro supports MCP」,场景包括 agent 修改组件、创建变更单、通知用户;API 限 PLM Enterprise 账户。其对传统 PLM 集成的批评:「Integrations were an afterthought, often bolted on years later through limited or proprietary interfaces… heavily dependent on 3rd party consultants」。Duro Design(2025-06 发布)主打航天/防务/医疗硬件客户(AstroForge、Rapid Robotics)。
- transfer: 「dogfood 自己的 API:UI 和 agent 走同一接口」是 AI-native 系统的架构铁律,直接适用于我们的 PM 系统——agent 的每个动作等价于一次有权限、有审计的 API 调用,不做第二套旁路。
- src: https://durolabs.co/blog/api-first/

### idea: Onshape:API 自助化程度最高,官方 MCP 在 early access
Onshape 有完整 REST API+公开 OpenAPI spec,API key/OAuth2 自助申请;因此社区 MCP 最繁荣(altendky/onshape-mcp 内嵌完整 OpenAPI spec 让 AI 动态发现端点,另有 hedless/onshape-mcp 及 Rust 实现)。PTC 官方 Onshape Labs early-access 计划中列出:AI agents 与自动化、AI Drawing Checker、FeatureScript MCP Server(text-to-code-to-CAD)——官方 MCP 处于「已宣布/early access」而非 GA。
- transfer: API 自助开放度与社区连接器繁荣度强相关。PM 系统若想让客户/伙伴自建采集器,要学 Onshape:公开 OpenAPI/GraphQL schema+自助 API key,而不是 Teamcenter 式登录墙。
- src: https://www.engineering.com/ptc-adds-early-access-ai-program-to-onshape/

### idea: CoLab:设计评审的 ambient capture + AI 历史回填的最佳先例
机制:浏览器内看 CAD,每条评论自动锚定 2D/3D 几何与所指版本,自动入结构化数据库(把「原本活在 PPT 和邮件里的反馈」变成结构化知识);直连 Windchill/Teamcenter/3DEXPERIENCE/Creo/NX/SolidWorks 同步版本历史与元数据,连 Jira/Teams;ML 引擎自动识别相似设计、重复问题、复用机会,构建 engineering knowledge graph。关键是 ingestion engine:可摄取旧设计评审、lessons-learned 电子表格、标准指南并自动分类,宣称无需人工重新排版或打标——这就是制造业版「回填历史」。商业验证:Bombardier 签数百万美元 AI 合同;AutoReview 用客户自己的设计标准自动审图并标注不合规处。
- transfer: 可整体迁移:1) 评论/决策必须自动携带上下文锚点(哪个交付物、哪个版本、哪次评审),入库即结构化;2) 冷启动=「AI 摄取客户旧评审 PPT/Excel/纪要自动建档」,把回填做成售前可演示的能力;3) 知识图谱按「问题-设计-决策」组织而非按文件夹。
- src: https://www.colabsoftware.com/product/ai-knowledge-graph

### idea: Instrumental:产线 build 数据的 ambient capture 样板
在装配线关键工位部署成像站(自有或客户相机),每个工位设置校准不到 1 小时;量产时操作员放件按钮,4-5 秒出绿/红灯判定;每台产品的图像+测试数据按 serial number 串成可追溯 digital thread,AI 自动发现缺陷异常,工程师的复核标注反哺模型多轮学习。已上架 Siemens Xcelerator marketplace 与 SAP 工业云。
- transfer: 证明制造业 ambient capture 的成立条件:在「工作必经的物理/流程卡点」放置零摩擦采集点,而不是让人事后填表。PM 层的等价物是把采集点放在评审会、ECO 审批、试产 build 报告提交这些必经节点;serial number 式的「贯穿主键」思路可对应到按项目/样机批次串起全部痕迹。
- src: https://instrumental.com/product/

### idea: 中国市场:95% 非 SaaS,ambient capture 采集面应转向飞书/钉钉生态
IDC《中国PLM市场厂商份额,2024:反内卷》:2024 中国 PLM 软件市场 35.1 亿元(+21.6%),其中 SaaS PLM 子市场仅 1.81 亿元、占 5.25%;国际三大家增速放缓甚至负增长,国产厂商(数码大方、华天 InforCenter、鼎捷、用友、金蝶等)份额上升,行业前三为高科技电子、装备制造、汽车零部件。军工/涉密场景:四级密级文档管控、内外网物理隔离、等保三级+GJB9001C 是选型硬门槛。同时飞书官方案例显示制造企业用飞书低代码/多维表格补 PLM 协同短板(变更评审周期 8 天降到 4 天),协作痕迹大量沉淀在 IM+低代码表格。
- transfer: 中国版 ambient capture 的现实路径:PLM 端不指望 API(国产 PLM 开放度参差、部署在内网),主采集面是飞书/钉钉/企业微信的开放平台(消息、审批、文档、事件订阅)+共享盘 Excel;产品需可私有化部署并支持国产化适配才能进装备/军工客户。
- src: https://my.idc.com/getdoc.jsp?containerId=prCHC53752325

### idea: 冷启动回填:Excel 导入是行业默认通道,PLM 到 PLM 迁移是重服务
传统 PLM 迁移(PROSTEP OpenPDM、PROLIM、Migravion)是重咨询项目,涉及 BOM、CAD 文档、变更数据、配置与有效性,策略分 big bang/incremental,共识是「迁移=数据治理项目」且旧数据普遍缺属性、重复、不一致。轻量派 OpenBOM 把 Excel 电子表格导入作为第一迁移通道。AI 回填唯一成型先例是 CoLab ingestion engine(见上)。可回填的历史形态排序:共享盘 Excel/BOM 表(最普遍、最易)>旧评审 PPT/纪要(AI 可摄取)>PLM 记录(API 可导但 schema 客制)>供应商邮件(制造业尚无规模化回填先例——差异化空白)。
- transfer: 冷启动设计:第一优先做「Excel/共享盘扫描导入+AI 清洗建档」,第二做「评审文档/纪要摄取」,PLM 同步放最后;把 Lightfield「回填 2 年邮件」翻译成「回填 2 年共享盘+IM 群聊」更贴合制造业现实。
- src: https://www.openbom.com/blog/how-to-approach-legacy-data-import-to-openbom

### idea: 第三方接入门槛清单(按系统)
Onshape:公开 OpenAPI+自助 API key,门槛最低。Windchill:OData 免费捆绑(11.0 M030 CPS06 起)、Basic auth,技术门槛低但需进客户内网。Arena:Swagger/OAS 3.0 文档公开(ptc-arena.github.io),OAuth2,复用 Arena 角色权限,需含 API 的订阅;第三方定价站口径约 $1,200-2,500/用户/年,企业级 25 用户约 $50-75k(非官方,仅供量级参考)。Duro:GraphQL+MCP,但限 Enterprise 账户。Aras:核心 REST/OData 开放,agent 级暴露走 InnovatorEdge(云交付)。Teamcenter:API 文档要登录,技术伙伴计划「Fees may be involved」,数据模型 BMIDE 客制最重,单客户字段映射工作量最大。
- transfer: 连接器路线图应按门槛排序:Onshape/Arena/Duro(云,天级接入)→ Windchill(OData,周级+现场)→ Aras(视 Edge 采纳度)→ Teamcenter(月级、按客户实施)→ 国产 PLM(逐家谈)。商业上把重连接器做成实施服务收费项。
- src: https://ptc-arena.github.io/arena-dev-help/

### pattern: 内嵌垂直 agent(厂商自营,不对外) [已上线(随 Teamcenter 2606,2026-06-12)]
Teamcenter 2606 AI BOM Agent:BOM-aware agent 嵌在 PLM 内,理解 BOM 结构→分析变更影响→提议并在受治理工作流中执行多步操作,人工监督兜底;变更管理 AI 推荐工作流模板与任务分配。不提供对外 agent 接口。

### pattern: 文档层 AI 助手(最窄切口先行) [已上线(2026-04-28 GA);「agentic digital thread」部分仅愿景]
Windchill AI Assistant:挂在 Navigator 面板的聊天界面,自然语言问答与摘要,仅基于文档 vault 内容,明确不回答 metadata 与其他业务对象;on-prem 与 Windchill+ SaaS 均可经 Plugin Manager 安装。

### pattern: agent 网关/API 管理层 [已宣布/初上线(2026-02-26 发布,on-prem 支持细节未明)]
Aras InnovatorEdge:Edge API 低代码定义要暴露的 PLM 数据与逻辑并生成 OData API;Edge AI 提供构建、部署、治理 agentic workflow 的服务套件;数据治理留在核心 Innovator,消费在边缘。

### pattern: 官方 MCP server [Duro 已上线;Onshape 在 Labs early access;其余缺席]
Duro:MCP 接口让 AI agent 通过与应用同源的 GraphQL API 理解件/装配/版本/变更关系并执行动作(改组件、开变更单、发通知);Onshape 的 FeatureScript MCP Server 走 text-to-code-to-CAD。Siemens/PTC(Windchill)/Arena 均无官方 MCP。

### pattern: 社区 MCP/agentic skill [Windchill skill 可用但个人项目(10 stars);Teamcenter 社区 MCP 实质不可用]
srinivasmd/windchill-plm 用 28 个领域客户端包装 Windchill OData v4 全 CRUD+OData action 供 agent/CLI/CI 使用;两个 Teamcenter MCP 分别为 archived-not-functional 和单 commit WIP。

### pattern: 联邦式 Copilot(数据不搬家) [已上线]
Teamcenter 2606 把 PLM 上下文送进 Microsoft 365 Copilot,口号 information stays where it lives——用户在 Office 侧问,数据留在 PLM 侧。

### pattern: 多形态 LLM 部署 [已上线(2606)]
Teamcenter Copilot 同一功能支持纯 on-prem(Llama 4.0 Scout)/客户云(Azure GPT-4.1/5.1、Bedrock Claude Sonnet 4.5)/SaaS(Teamcenter X)三种跑法,以适配数据不出网约束。

### pattern: 视觉式 ambient capture(产线) [已上线多年(上架 Siemens Xcelerator/SAP 工业云)]
Instrumental:工位成像站零摩擦采集每台产品影像,按 serial number 串成 digital thread,AI 异常检测+工程师标注闭环学习,root-cause 分析工具消费同一数据。

### pattern: 评审交互→知识图谱+AI 回填 [已上线(Bombardier 数百万美元合同)]
CoLab:评论自动锚定几何与版本入结构化库;ML 识别相似设计与重复问题;ingestion engine 无人工整理即摄取旧评审、lessons-learned 表格、标准文档;AutoReview 用企业自有标准自动审图。

## ui_patterns
- Chat 助手挂在 PLM 既有导航(Windchill Navigator pane 内嵌 AI Assistant),不另开应用
- Agent 提议-人批准流:BOM Agent 提议变更并在治理工作流内执行、质量 Copilot 的 AI 建议在插入前必须用户审核——「AI 起草、人盖章」是行业标准交互
- 浏览器内轻量 CAD 评审,评论直接锚定 3D 几何与版本(CoLab),非工程角色零安装参与
- 工位级两态反馈:放件→按钮→4-5 秒绿/红灯(Instrumental),采集交互压缩到秒级零学习成本
- API 自助探索台:Duro 内置 Apollo Explorer、Arena 用 Swagger UI 公开文档——把集成的第一公里做成自助
- 联邦入口:在用户已在的界面(M365 Copilot/飞书)消费 PLM 上下文,而不是把人拉进新系统

## lessons
- 不要指望社区连接器:两个 Teamcenter MCP 一个 archived 标注 NOT FUNCTIONAL、一个单 commit(1 star),重 PLM 的连接器只能自研+按客户实施。
- 大厂 AI 从最窄场景起步:Windchill AI Assistant GA 时只做文档 vault 问答,不碰业务对象——「agentic digital thread」宣传与实际交付有明显落差,评估厂商能力时要区分 GA 功能与愿景页。
- 云 PLM 顾虑二十年未变:CIMdata 调研中集成(45%)与安全(43%)是头两大顾虑;Aras 2024 调研「81% 认为 SaaS 将成标准」是态度数据,不能当现状引用。
- 市场数字互相矛盾:有报告称 2025 云占 70%,另有报告称 on-prem 收入占 56.66%、2019 年 on-prem 装机占 82.4%——统计口径(收入/装机/新增)差异巨大,引用时必须标注口径;确定性最高的是 IDC 中国口径:SaaS PLM 仅占中国 PLM 软件市场 5.25%(2024)。
- 军工/涉密是硬边界:内外网物理隔离、四级密级管控、等保三级+GJB9001C,任何依赖云端 LLM 的 ambient capture 在这类客户直接出局,必须有全离线部署形态。
- 制造业的会议纪要→结构化研发记录(ECO 草稿、DFM issue)没有专用玩家,通用 AI 笔记工具(Spinach 等)只到 action item→ticket 层——这既是空白机会,也提示该场景可能比想象难(领域词表、图纸引用、保密)。

## sources
- https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/
- https://blogs.sw.siemens.com/teamcenter/ai-bom-agent-plm-engineering-change/
- https://blogs.sw.siemens.com/teamcenter/teamcenter-plm-ai-copilot/
- https://github.com/srgio-es/teamcenter-mcp-server
- https://github.com/goenninger-b-t/tc-mcp
- https://github.com/srinivasmd/windchill-plm
- https://support.ptc.com/help/windchill_rest_services/r2.0/en/windchill_rest_services/WCCG_RESTAPIsWRS.html
- https://www.ptc.com/en/news/2026/ptc-launches-windchill-ai-assistant
- https://support.ptc.com/help/windchill/ai_plugin/en/Windchill_Help_Center/document_vault/WCAIAssistAIPluginReleaseNotes.html
- https://www.ptc.com/en/products/windchill/windchill-ai
- https://aras.com/en/news/press-releases/2026/02/aras-expands-innovatoredge-with-new-services-for-api-management-app-development-and-agentic-ai
- https://aras.com/en/capabilities/aras-innovatoredge
- https://ptc-arena.github.io/arena-dev-help/
- https://github.com/ptc-arena/arena-restapi-doc
- https://durolabs.co/blog/api-first/
- https://duro.zendesk.com/hc/en-us/articles/11814592464532-Quick-Start-Guide-to-using-Duro-s-GraphQL-API
- https://www.prnewswire.com/news-releases/duro-unveils-duro-design-the-first-ai-native-plm-for-modern-hardware-engineering-302479918.html
- https://www.onshape.com/en/blog/ai-artificial-intelligence-cloud-native-cad-pdm-platform
- https://www.engineering.com/ptc-adds-early-access-ai-program-to-onshape/
- https://github.com/altendky/onshape-mcp
- https://my.idc.com/getdoc.jsp?containerId=prCHC53752325
- https://www.cinn.cn/p/432166.html?f=pad
- https://www.cimdata.com/en/news/item/9453-cimdata-publishes-final-report-from-cloud-plm-research
- https://aras.com/en/news/press-releases/2024/09/81-of-industrial-companies-say-that-saas-will-become-the-standard-for-plm
- https://www.digitalengineering247.com/article/majority-of-companies-surveyed-view-saas-as-standard-for-plm
- https://instrumental.com/product/
- https://xcelerator.siemens.com/global/en/all-offerings/products/i/instrumental-ai-and-data-platform.html
- https://www.colabsoftware.com/product/ai-knowledge-graph
- https://www.colabsoftware.com/product/autoreview
- https://www.openbom.com/blog/how-to-approach-legacy-data-import-to-openbom
- https://prostep.us/solutions/plm-migration/
- https://www.feishu.cn/content/plm-change-manage
- https://segmentfault.com/a/1190000046302869
- https://www.vendr.com/marketplace/arena-solutions
- https://www.siemens.com/en-us/partners/software/join-partner-program/build/technology-partners/
- https://www.spinach.ai/blog/top-ai-note-takers-remote-engineering-teams
