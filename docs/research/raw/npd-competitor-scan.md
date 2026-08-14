# npd-competitor-scan

## summary
空窗结论需分市场修正。欧美:2025-26 新入场者(Flow Engineering/Rollup/Nominal/Stell)全部聚集在需求管理、MBSE、测试数据等相邻层,无人正面做 AI-native 的 NPD 执行层项目管理;老牌 stage-gate 软件(Sopheon Accolade)与 ITONICS 的 AI 停在组合优化层;Teamcenter 2606、Windchill AI、3DEXPERIENCE 的 agentic AI 集中于 BOM/需求/数据域,尚未覆盖项目协作——全球执行层空窗仍在,但相邻包围圈已成形。中国:原结论基本不成立——飞书项目 2024-07 发布 IPD 专版后已占据该品类(厂商宣称 100+ IPD 客户、赛迪口径 IPD 流程数字化 SaaS 市占率 68.6%),并以 MCP/CLI/AI 节点/原生 AI 助手完成平台级 AI 布局;但 gate 材料装配、状态自动生成、风险预警等 NPD 特定 AI 仍靠客户与 ISV 自建。剩余空间:NPD AI 原生产品化、去飞书套件依赖的独立部署、与 BOM/试产工程数据的深度连接。

## positioning
修正后的差异化定位:全球市场,执行层 NPD 项目管理(单项目 gate 运转:材料自动装配、状态自动生成、跨职能风险预警)仍无正面竞争者,新钱都投向相邻层——Flow(需求,Sequoia 领投 $23M,客户 Rivian/Joby/Astranis)、Rollup(MBSE+program management,a16z $5.6M,航天国防)、Nominal(测试数据,10 个月融 $155M、估值 $1B,客户 Anduril/Shield AI)、Stell(AI-native 需求管理,美国太空军项目在用);它们的共同模式是「先占工程数据层,再扩平台」,因此 NPD 项目层创业者的护城河必须建立在流程+协同+AI 装配能力上,并预留与这些数据层产品的连接器。中国市场,「IPD 数字化工具」品类已被飞书项目实质占领(蔚来/小鹏/理想/比亚迪/小米/雅迪等灯塔客户,ISV 生态聚集),正面做同品类无胜算;可行缝隙有三:(1)把客户目前自建的 AI PMO 能力(雅迪「IPD 智能项目助手」式的自动汇总/预警/周报)做成原生产品;(2)服务不用/不能用飞书体系的客户(信创、数据主权、已有 IM 栈;飞书项目 2025-09 才宣布未来出脱离飞书套件的单品);(3)制造业深水区——项目层与 BOM/交付物内容/试产测试数据的结构化连接,这恰是飞书项目最弱、华为 IPDCenter 最强但无协同与 AI 的地带。

## data_model
两条建模路线的分野即竞争地图:华为 CraftArts IPDCenter 从工程数据侧建模——统一产品生命周期数据模型(需求/架构/项目/任务/结构/BOM/仿真/工艺同源)+角色工程流,目标是成为产品主数据源头,评审与生命周期状态强制绑定;飞书项目从协同侧建模——工作项+低代码流程引擎+插件点位,BOM 等工程数据能力弱。对自研系统可迁移的关键设计:(1)阶段-DCP-TR 双轨状态机,评审实体间有前置依赖约束(PDCP←系统设计准出、ADCP←PVT 准出);(2)PCR 变更单作为能触发状态机回退到指定 DCP 的一等对象;(3)评审-遗留问题-任务三级闭环关联;(4)节点/模板/checklist 资产库(支持行业包分发与 AI 选配);(5)CBB 公共构建模块作为跨项目复用实体(技术开发与产品开发分离的载体);(6)交付物内容结构化+外部工程系统(BOM/测试)连接器,否则项目层 AI 无燃料;(7)Agent 访问层:工具面(MCP)、权限面(授权范围)、异步任务协议。

### idea: 双轨评审建模:DCP 商业决策与 TR 技术评审必须是两类一等实体
IPD 与 Cooper stage-gate 的关键差异:Cooper 是单一 gate 序列(商业+技术合一,gatekeeper 轻量);IPD 拆成 5 个 DCP(Charter/CDCP/PDCP/ADCP/LDCP,由 IPMT/IRB 高管团队做投资决策)+ 7 个 TR(TR1-TR6+TR4A,质量导向技术评审),再叠加 4 个准出(系统设计/EVT/DVT/PVT)。评审间有硬性前置依赖:PDCP 的前提是系统设计准出完成,ADCP 的前提是 PVT 准出完成;EVT 准出后原则上不接受 PCR(计划变更请求),重大规格变更必须回到 PDCP 重新决策。智能硬件落地形态为 7 阶段:Charter→设计&计划→T0→EVT→DVT→PVT→MP。
- transfer: gate 模板引擎要支持两类评审对象各自的 checklist、决策结论枚举(GO/KILL/HOLD/REDIRECT vs 通过/有条件通过/不通过)、评审主体角色(IPMT vs 技术专家),以及评审之间的前置依赖约束;PCR 变更单应是能把项目状态机回退到指定 DCP 的一等对象,而非普通任务。
- src: https://www.woshipm.com/it/4384157.html

### idea: 评审遗留问题→任务闭环是已被验证的第一刚需
飞书项目 IPD 的核心卖点之一:评审中发现的问题一键转为缺陷或任务并指派到人,评审过程/意见/结论完整记录并与项目节点关联,替代『会议纪要+人工追问』。进阶版是轻舟智航案例:现场语音记录路测问题→系统自动分类打标→结合规则和历史数据推送给责任人→闭环,实现问题 100% 自动创建(厂商活动宣称)。
- transfer: 评审对象-遗留问题(Action Item)-任务的三级闭环加 AI 自动分诊派发,是 NPD 系统投入产出比最高的 AI 切入点,应做成原生能力而非自动化规则拼装。
- src: https://news.mydrivers.com/1/1118/1118081.htm

### idea: 流程资产仓库:节点与模板资产化,而非硬编码行业模板
爪印工作室在飞书项目上自研 FlowStack『流程资产仓库』,沉淀 200+ 标准节点、50+ 流程模板,结合轻应用与 AI coding,2 天把管理思路变成可用系统;华为 CraftArts IPDCenter 同样以『统一生命周期角色工程流模板+编排框架』为核心,拖拉拽组装企业自己的工程流。飞书 IPD 专版按行业分发方案包(消费电子/整车/化妆品新品上市)。
- transfer: 把阶段/节点/checklist/交付物定义做成可组合、可版本化的资产库,行业模板=资产的打包发行;这与 NPD 模板瘦身分档(核心+附加包)的思路一致,且是 AI 生成流程的前提(AI 从资产库选配,而非凭空生成)。
- src: https://support.huaweicloud.com/productdesc-craftartsipdcenter/ipdcenter_01_0001.html

### idea: AI Friendly 架构:把 Agent 当作系统的新使用者来设计开放层
飞书项目 2026-04 生态日的完整打法:MCP 服务覆盖 40+ 工具并支持 OAuth 授权;开源 CLI 以『渐进式披露』机制对抗大项目场景的幻觉/上下文限制并省 token;AI 节点把 Agent 封装为可配置流程节点在关键环节执行并沉淀 SOP;AI 字段从自定义 prompt 列升级为带应用市场的开放能力;AAMP 开源协议做平台与 Agent、Agent 与 Agent 的标准化异步任务分发(支持 NAT/防火墙内本地 Agent 双向通信)。日均接口调用量从 500 万增至 2300 万次(厂商宣称)。
- transfer: 自研系统应把『Agent 可安全读写业务对象』列为架构需求:工具面(MCP/CLI)、权限面(授权范围内读数据)、执行面(AI 作为流程节点而非聊天窗)、异步任务协议。这比抢先做单点 AI 功能更具结构性价值。
- src: https://www.qbitai.com/2026/04/406026.html

### idea: 客户自建 AI PMO 的实证与产品化空白
雅迪科技集团用飞书项目落地 IPD+IPMS 双流程,并基于开放接口自建『IPD 智能项目助手』:自动汇总进展与预警、生成周报月报,宣称减少 20% 资源浪费、30% 重复工时、缩短 2 个月新车开发周期;暗物智能自建『PMO 小助手』降低 50% 人工提问率;唱吧一线 PMO 用 AI 能力组合实现会议/任务/需求 AI 评审/数据分析。共同点:这些都是客户在平台上自建,不是飞书项目原生产品能力——『AI PMO』目前是实践叙事,不是产品模块。
- transfer: 状态自动生成、进展汇总、风险预警值得直接做成原生产品能力——这是目前中外所有玩家共同留给客户自建的空白,也是原立项假设中仍然成立的部分。
- src: https://news.mydrivers.com/1/1118/1118081.htm

### idea: 相邻层的启示:工程数据是项目层 AI 的燃料
欧美新钱全部流向数据层:Nominal(测试遥测/HITL 数据)、Flow Engineering(需求作为动态系统,连接 CAD/PLM/仿真)、Stell(需求合规,NIST 800-171/ITAR)、Instrumental(产线影像)。PLM 大厂的 agentic AI 也从 BOM 数据起步(Teamcenter AI BOM agent 能理解 BOM 上下文、提议并在人类监督下执行多步变更工作流)。
- transfer: NPD 项目层 AI 若接不到工程数据(交付物内容、测试结果、BOM 状态),就只能做日程与文本类浅 AI。系统设计上要求:交付物内容结构化(不是附件堆)+外部工程系统连接器,才能支撑 gate 材料自动装配与真实风险预警。
- src: https://techcrunch.com/2026/03/05/hardware-testing-startup-nominal-hits-1b-valuation-raises-155m-in-10-months/

### idea: 组合层 AI 与执行层 AI 是两个市场:老牌 stage-gate 软件的 20 年教训
Cooper 官方认证的 Sopheon Accolade(2024-02 被 Wellspring 收购)内置 Kalypso Optimizer:在资源/技能约束下求解项目组合优先级、做 what-if 情景;ITONICS Prism 检测 15-20% 停滞项目、重复投入、战略偏离。两者都停在组合治理层,从未做进执行层(单项目 gate 运转、交付物装配、跨职能任务)。
- transfer: 不要把有限资源投向组合优化 AI(已有成熟玩家且是 CFO 采购),执行层的 gate 运转自动化才是空窗;但系统数据模型应为将来向组合层扩展预留项目集/组合实体(与 CEHub 项目集工作线呼应)。
- src: https://www.sopheon.com/products/accolade

### pattern: AI 字段(prompt 列) [已上线(飞书项目 2025-04 起)]
用户在工作项上自定义 prompt,LLM 基于项目内信息生成总结/分析,可定时更新;2026-04 升级为带应用市场、视图内人人可配。这是『贴皮』层级的 AI,但因可嵌入流程被大量复用。

### pattern: 原生项目分析智能体(AI 助手) [已上线(2026-04 发布)]
飞书项目开箱即用智能体:项目分析、图表生成、进展追踪、风险洞察、人力分析、个人周报,强调全程基于授权范围与可读数据生成。

### pattern: Agent 即流程节点(AI 节点) [已上线/beta(2026-04 发布,案例为 ISV 共创)]
把 Agent 封装为可配置的流程节点嵌入业务流,在关键节点自动执行(如词元无限把方案生成/智能编码/测试封装进流程,宣称 7-10 人天压缩到 1-2 人天),支持沉淀为 SOP、调试与重复运行。

### pattern: MCP/CLI Agent 接入层 + AAMP 异步协议 [已上线(MCP/CLI),AAMP 刚开源]
MCP 覆盖工作项/视图/度量/待办等 40+ 工具并支持 OAuth;CLI 开源、用渐进式披露提升模型稳定性并省 token;AAMP 基于邮件机制做平台-Agent、Agent-Agent 的标准化异步任务分发确认。

### pattern: 多 Agent 需求评审与测试生成(TAPD) [已上线(软件研发域)]
腾讯 TAPD 按角色提供 AI:产品经理需求 AI 辅助撰写+多 Agent 自动评审,测试人员 AI 生成与评审测试用例,运维 AI 生成 release notes;信通院联合报告称需求管理与测试用例生成应用率各 49%。面向软件敏捷研发,非硬件 NPD。

### pattern: Agentic BOM agent(Teamcenter 2606) [已上线(2026-06 发布)]
理解 BOM 上下文,提议变更并在人类监督下执行多步工作流,替代人工装配影响分析与变更执行;Copilot 支持 Azure(GPT 4.1/5.1)与 AWS Bedrock(Claude Sonnet 4.5)本地化部署。AI 未触及项目/计划管理域(program plans 仅出现在 Power BI 报表集成)。

### pattern: 需求质量 AI(Teamcenter MBSE/Codebeamer AI/Stell/Flow) [已上线]
按 INCOSE 类规则检查需求、并排给出修改建议、提取参数并关联仿真、推荐测试用例并跟踪覆盖率;Stell 面向国防合规场景(NIST 800-171/ITAR)。

### pattern: 组合层 AI 优化器(Accolade Optimizer/ITONICS Prism) [已上线(组合治理层,非执行层)]
在资源与技能约束下求解开发项目组合的最优优先级、生成 what-if 情景;Prism 融合外部信号(趋势/专利/竞品)与内部组合数据,标记停滞项目与重复投入。

### pattern: Virtual Companions(Dassault 3DEXPERIENCE) [Aura 已上线,整体接近仅愿景]
Aura/Leo/Marie 三类 AI 专家宣称跨产品全生命周期协调人与数千 Agent 的异步协作;当前 Aura 是问答助手,Leo/Marie 2026 年内上线。叙事覆盖面最广、落地最少。

### pattern: 客户自建 AI PMO(雅迪/暗物智能/唱吧) [已落地但非产品原生——这正是产品化空白]
基于飞书项目开放接口与底层数据,自建自动汇总进展、预警、生成周报月报的嵌入式助手;效果数字均为厂商活动口径。

### pattern: Gate 评审材料自动装配 [空白(仅存在于本项目的立项假设中,仍成立)]
从交付物、测试数据、任务状态自动装配 DCP/TR 评审包并预判准出风险——本轮全网扫描未发现任何厂商(中外)实现或宣称此能力。

## ui_patterns
- 泳道图呈现跨部门职能与阶段并行(飞书 IPD『泳道可视化,计划管理更透明』)
- 管理驾驶舱:自定义报表+公式字段+各阶段预设管控指标,实时督办与项目盈利分析(翰博高新案例)
- 评审集成视图:评审过程/意见/结论/遗留问题/转出任务在同一上下文内可追溯
- 文档即交付物:交付物与协同文档原生打通,而非附件上传
- 流程可视化编排:拖拉拽组装工程流(IPDCenter 编排框架、飞书轻应用『搭乐高』式无代码)
- Gate 五问式阶段框架:Gate1 为什么做/Gate2 做什么/Gate3 怎么做/Gate4 怎么卖/LR 用户体验(飞书智能硬件方案)
- 阶段准出 checklist 门禁与缺陷收敛趋势(DI 值)监控

## lessons
- 取样偏差直接导致误判:原调研覆盖欧美工具与 PLM 大厂,漏掉了中国已出现的品类赢家。飞书项目 IPD 客户从『超 20 家深度使用』(2024-07)到『IPD 100 目标达成』(2025-04 洪涛口述)再到『超过 100 家客户』(2025-09 发布会),两年走完从 0 到品类占领。
- 数字口径需谨慎:『赛迪研究院 2025 年 IPD 流程数字化 SaaS 市占率 68.6%』出自飞书项目自己的活动稿,该品类定义疑似为其定制;所有客户效果数字(雅迪 -30% 重复工时、轻舟 100% 自动创建等)均为厂商活动口径,未见独立验证。
- 飞书系内容农场干扰调研:cnblogs『IPD_Master』、CSDN『Feishu_project』等账号批量发布伪装成第三方评测的软文(对比结论一边倒向飞书项目),中文竞品调研必须做来源甄别。
- 『AI PMO』是实践叙事不是产品:飞书项目原生 AI 是平台件(AI 字段/节点/助手/MCP),NPD 特定智能(自动汇总/预警/gate 装配)全部由客户或 ISV 自建——说明需求真实存在,也说明平台厂商选择了做底座而非做场景,这是后来者的机会与警示并存。
- PLM 大厂不会永远停在数据域:Teamcenter BOM agent 已能在人类监督下执行多步变更工作流,PTC 沿 requirements(Codebeamer AI)推进,Dassault 直接讲『协调全生命周期活动』的 companion 叙事。执行层空窗的窗口期估计 12-24 个月,不是永久空地。
- 老牌 stage-gate 软件(Sopheon 2024 被 Wellspring 收购)20 年未能下沉到执行层,提示该层的胜负手是协同产品基因与工程数据接入,而非流程审批引擎;单纯把 Cooper/IPD 模板软件化的路线已被证伪。
- 中国客户会拿华为术语逐项对表:模板与文档需原生使用 TR/DCP/准出/PCR/CBB/IPMT/PDT 词汇,并支持 EVT/DVT/PVT 与 TR 点的映射——这与 NPD 模板瘦身工作线直接相关。

## sources
- https://project.feishu.cn/home/ipd
- https://project.feishu.cn/home/blogs/solution-ihm
- https://blog.csdn.net/TMT_XQ/article/details/140571848
- https://www.53ai.com/news/zhinengyingjian/2025042506784.html
- https://www.qbitai.com/2026/04/406026.html
- https://news.mydrivers.com/1/1118/1118081.htm
- https://m.tech.china.com/articles/20250910/202509101729457.html
- https://www.cnblogs.com/feishu-project/p/19796268/feishu-project-ipd-center
- https://news.qq.com/rain/a/20240722A080IW00
- https://www.huaweicloud.com/product/ipdcenter.html
- https://support.huaweicloud.com/productdesc-craftartsipdcenter/ipdcenter_01_0001.html
- https://blog.pingcode.com/v5-0-0-release/
- https://cloud.tencent.com.cn/developer/article/2679704
- https://www.tapd.cn/
- https://blog.csdn.net/Teambition/article/details/145780968
- https://cloud.tencent.com/developer/article/2650314
- http://www.powerproject.cn/
- https://www.woshipm.com/it/4384157.html
- https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/
- https://blogs.sw.siemens.com/teamcenter/teamcenter-plm-ai-copilot/
- https://www.ptc.com/en/news/2025/ptc-brings-ai-powered-plm-to-hannover-messe
- https://www.ptc.com/en/news/2026/ptc-launches-windchill-ai-assistant
- https://www.3ds.com/newsroom/press-releases/dassault-systemes-unveils-new-way-working-industry-ai-powered-virtual-companions
- https://www.flowengineering.com/blog/flow-raises-23m-from-sequoia-to-accelerate-the-future-of-hardware-development
- https://finance.yahoo.com/news/exclusive-flow-engineering-raises-23-094816163.html
- https://techcrunch.com/2024/05/20/rollup-wants-to-be-the-hardware-engineers-workhorse
- https://rollup.ai/program-management
- https://techcrunch.com/2026/03/05/hardware-testing-startup-nominal-hits-1b-valuation-raises-155m-in-10-months/
- https://www.prnewswire.com/news-releases/nominal-raises-75-million-led-by-sequoia-capital-to-modernize-hardware-testing-302479991.html
- https://stell-engineering.com/
- https://www.sopheon.com/products/accolade
- https://www.stage-gate.com/wp-content/uploads/2024/05/SGI-Article-Building-AI-into-your-Stage-Gate-NP-Process-Part-1-Cooper-2024.docx.pdf
- https://www.itonics-innovation.com/ai
- https://www.forbes.com/sites/dariashunina/2025/11/13/the-top-startups-to-watch-from-y-combinators-fall-2025-batch/
- https://www.betauniversity.org/post/inside-y-combinator-s-ai-revolution-key-startup-trends-from-the-2025-demo-day
