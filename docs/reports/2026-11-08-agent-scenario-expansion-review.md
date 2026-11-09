# 小Pai 业务场景拓展与创新机会评估（竞品对照增补）

日期：2026-11-08。性质：**分析稿，不构成合同，不修改 v1.1 冻结条款，也不改变 W3b 已拍板条目。** 任何条目进入建设，须按 v1.1 §00.4 写决策记录并由用户确认；切片合同不得据此自行扩大范围。

依据：
- 设计侧：[10-22 缺口稿](../design/2026-10-22-pdos-v1.1-gap-analysis-and-competitive-review.md)（G-01–G-44）、[唯一清单](../../tasks/ai-native-integrated-todo.md#debt-board) W3b 候选池与拍板结果（P77–P83）、[不采用清单](evidence/debt-consolidation-20261101/rejected-and-unverified.md)。
- 调研侧：2026-11-08 十路 WebSearch（DPP/电池护照、CRA/RED 合规、专利情报、采购 agent、关税与 HS 归类、退货与 NFF、A2A 协议、CAE agent、PLM 厂商复核、VoC 挖掘）。可信度标注沿用缺口稿口径：**[一手]** 官方页面、**[公告]** 官方宣布未交付、**[二手]** 媒体或第三方转述；厂商自报的效果数字一律视为营销口径。

## 0. 结论

1. 10-22 缺口稿加 W3b 候选池已覆盖常见的 agent 场景（IM 入口、MCP server、移动审批、测试数据管道、认证台账、供应链情报、会议/邮件摄取、个人技能等），且绝大多数已拍板。本稿**只列那一轮没覆盖、或 10-22 之后出现新依据的场景**，共 5 个拓展场景（J-01–J-05）和 3 个创新机会（J-06–J-08）。
2. 最值得优先的两个方向都有硬日期且是竞品空档：**合规雷达与数字产品护照**（CRA 报告义务 2026-09-11 已生效、电池护照 2027-02-18 强制）和**立项期 IP/FTO 初筛**（智慧芽 Eureka 已开放 MCP/API，PLM 厂商无人做立项 IP 环节）。
3. 大厂 PLM 基线复核：10-22 之后无新的实质发布（Teamcenter AI BOM Agent 仍是 2606/6 月版，Windchill AI Assistant 为 4 月版，Arena/Propel 无新动作），10-22 稿的竞品基线不需要更新。
4. 查过但不建议做的：自主谈判成交、自建 CAE/仿真 agent、A2A 自动下单，均与 T2 红线或业务边界冲突，见 §4。

## 1. 方法与边界

- 排重口径：凡已拍板（P35–P90）、已在 W3b 候选池（含延后项）或已入不采用清单的，不重复提案；本稿条目若与既有 D 条目相邻，写明关系与差集。
- 调研信息以 2026-11-08 之前公开资料为限；合规类日期多数来自厂商博客，关键日期在采纳前须对欧盟官方文本（Official Journal / Commission 页面）核对，待核对项集中列在 §6。
- 编号 J-01 起，避免与既有 G/D/B/C/F/P/AT 系列冲突。

## 2. 可拓展场景

### J-01 合规雷达 + 数字产品护照（DPP）——优先级：高

**外部变化**：欧盟合规在 2026–2027 密集生效，均直接落在消费电子 ODM 头上：

| 法规 | 关键日期 | 来源 |
|---|---|---|
| 电池法规 2023/1542：电池护照 | 2027-02-18 强制；全护照范围为 LMT/工业 >2kWh/动力电池，便携电池为标签与二维码信息义务（准确范围待核对官方文本） | [欧盟委员会 DPP-batteries](https://single-market-economy.ec.europa.eu/single-market/digital-product-passport/batteries_en) [一手]；[护照测试环境 2026-06 上线](https://www.electrive.com/2026/06/25/digital-battery-passport-test-environment-goes-online/) [二手] |
| ESPR（DPP 伞形法） | 按品类授权法案逐步生效；六项横向 DPP 标准 2026-05 发布、登记册 2026-07 上线（日期口径不一，见 §6） | [Circulor](https://circulor.com/articles/eus-digital-product-passport-standards) [二手] |
| CRA | 2024-12 生效；Article 14 漏洞/事件报告义务 2026-09-11 **已生效**；2027-12-11 全面适用 | [euverify](https://euverify.com/resource/cyber-resilience-act-reporting-deadline/)、[advisori](https://www.advisori.de/en/blog/cyber-resilience-act-overview-businesses-2026) [二手] |
| RED 网络安全条款 | 2025-08 起适用于联网消费电子（耳机、音箱等） | [UL Solutions](https://www.ul.com/insights/red-compliance-achieved-lets-prepare-whats-next) [一手] |
| Right to Repair | 2026-07 生效口径（待核实原文） | [Claimlane](https://www.claimlane.com/resources/blog/electronics-returns-warranty-claims) [二手] |

**竞品格局**：合规侧只有独立 SaaS（Circularise、osapiens、[TracexTech 的"Agentic AI for EUDR"](https://tracextech.com/digital-product-passport/) [一手官网]）；TÜV SÜD 明确提示买软件不转移法律责任 [[一手](https://www.tuvsud.com/en-gb/resource-centre/blogs/uk/testing-and-certification-blog/eu-digital-battery-passport-compliance)]。**没有任何 PLM AI 把"研发数据→合规数据包"做成闭环**；Arena SCI 只做法规更新周检（10-22 稿已录）。而 DPP 需要的恰好是 PDOS 的一等对象：BOM、材料、证书、供应商、放行包。

**我方现状**：D93/D188 认证台账已采纳（排 S3/S4），管台账不管"法规变化→设计需求→重认证判定→数据包导出"的持续链路；G-37 AI 生成内容标识已定为细化导出。

**建议落法**（两段）：
- (a) **合规雷达**：品类知识的"法规认证按地区"从静态清单升为持续监测场景。研究类技能包 + 法规源作 MCP 研究工具（官方数据库/订阅源），变化产出带引用的 Claim 与 SpecItem/重认证候选（T1 确认），接 D93 台账与 ImpactAssessment 的重认证判定。
- (b) **DPP/合规数据包导出**：放行包增加面向 ESPR/电池法规的导出格式，字段映射由确定性引擎完成，AI 只起草缺项说明；与 D185 已延后的外审取证包同构，可合并设计（见 J-07）。

**需要的决策**：(a) 新来源类型，同 G-18 口径须决策记录；(b) 细化 §07.6 导出与放行包出口，新增导出模板须记录。

### J-02 立项期 IP/FTO 初筛——优先级：高

**外部变化**：智慧芽 Patsnap 的 Eureka [2026-03-18 大改版](https://eureka.patsnap.com/blog/patsnap-eureka-major-updates-2026) [一手]，agent 覆盖 Find Solutions、可行性分析、新颖性检索、交底书起草，建在 TRIZ/FMEA 方法论上 [[一手](https://eureka.patsnap.com/blog/eureka-ai-agent)]；并已开放**自助试用、API、MCP 接入与 agent 编排** [[一手新闻稿](https://www.patsnap.com/resources/blog/press_release/patsnap-expands-access-to-one-of-the-worlds-largest-innovation-intelligence-datasets/)]。其准确率对比为厂商自报，不作依据。

**竞品空档**：海外与国内 PLM 的 AI 均无立项 IP 环节；10-22 稿 A–G 组完全未涉及专利维度。消费电子出口美欧，FTO 是真实的立项红线。

**我方现状**：路径 A（品类研究→G0）无 IP 风险一环；三个研究类技能包（D180 已补外贸市场方向）无专利源。D101 供应链情报源延后条件是"有可接入的数据源时"——Patsnap 这类 MCP 源的出现是该条件可能成立的同类信号。

**建议落法**：研究类技能包"立项 IP 初筛"：按品类/方案关键词做新颖性与 FTO 粗筛，产出带引用的 Claim 进证据库，G0 材料加"IP 风险"一节。结论性的侵权判断不由 AI 下，候选一律标注"须专业代理复核"。专利查询词可能携带方案信息，属出站内容，须按 P26 口径把专利数据服务商登记进"服务商 × 数据类别"回执。

**需要的决策**：新 MCP 连接器与数据类别登记；技能包新增前按 G-36/M2 工具面决策核对。

### J-03 关税与 HS 编码口径——优先级：中

**外部变化**：HS 2028 修订将于 2028-01 生效，[Thomson Reuters](https://www.thomsonreuters.com/en-us/help/onesource-global-trade/regulatory-insights/2026/july-30th/understanding-harmonized-system-hs-2028) 与 [Descartes](https://www.descartes.com/resources/knowledge-center/hs2028-coming-what-next-global-tariff-reset-means-your-business) 都把 2026–2027 列为归类治理窗口 [一手]。关税工程（改产品本身换税目）有明确合法边界（*United States v. Citroen*），[Flexport](https://www.flexport.com/blog/can-you-engineer-lower-duties-yes-if-you-can-find-the-customs-codes/index.md) 有完整论述 [一手]。AI 归类工具自报 90%+ 准确率，但行业共识是不可单独依赖 [二手]。

**我方现状**：D105 目标成本对照、G-19 ECO 成本 delta 均无关税维度；确定性引擎拥有成本事实。

**建议落法**：CostEstimate 与 ImpactAssessment 增加关税口径（HS 候选码、目的市场、税率），税率表作为规则数据由确定性引擎计算差额；AI 只起草归类理由和"改设计换税目"的候选（T1），最终归类以报关行/BTI 裁定为准，系统只存依据与候选。不新建贸易合规模块。

**需要的决策**：字段与规则来源细化；若接外部税率数据源，须按来源类型登记。

### J-04 询价—比价—跟催循环（收敛版）——优先级：中（前置 D47）

**外部变化**：采购 agent 是 2026 最热品类：Levelpath 的 Merlin 层（intake + 自主寻源 + 尾部支出谈判，[IDC MarketScape 2026-07 Leader](https://resources.rework.com/tools/ai-agents/best-ai-agents-for-procurement-2026) [二手]）、Pactum 自主谈判、Keelvar/Fairmarkit 自主寻源、[Arkestro 走"预测 + 人保留决定权"路线并已接 MCP](https://procurement-ai-agents.pages.dev/compare/pactum-vs-arkestro-negotiation-ai) [二手]。同时 Gartner 口径是到 2028 年也只有 40% 采购团队用上至少一个 agent [二手]——自主谈判远未被验证。

**我方现状**：`rfq_extraction`、CostEstimate、SupplierReference、AvailabilitySnapshot 已有；D241 供应异常恢复延后（前置 D47 供应承诺命令）；D199 供方画像延后；D106 外部协作者延后。

**建议落法**：只补中段：多供应商报价单抽取（已有）→ **结构化比价表**（确定性引擎算价差、交期差与缺项）→ 跟催/澄清函草稿（T1 预填）。实际外发维持 T2/明确授权，**不做自主谈判**（学 Arkestro，不学 Pactum）——这正是分级写入制度的展示场景。可与 D241 同批实施。

**需要的决策**：多为既有对象细化；比价表若成一等对象须决策记录。

### J-05 退货与 NFF 回流——优先级：中低（排期不变，随 D48/路径 F）

**外部变化**：消费电子退货率 15–20% [厂商口径]；"无故障发现"（NFF）是行业公认痛点，[Claimlane 指出全行业连"退货件复测结果"的结构化字段都没有](https://www.claimlane.com/resources/blog/no-fault-found-warranty-claims) [二手]；Bruviti 自报 NFF 降 40–60%（厂商数字，不作依据）。竞品分工：Instrumental 管产线内构建数据、Claimlane/Bruviti 管客服与理赔流程，**没有人把退货件当工程对象管**。10-22 稿已判"国产 NPI 测试数据 AI SaaS 空档"，退货侧是同一空档的另一半。

**我方现状**：D104 售后差评回流延后（随 D48 的 S5 爬坡反馈，路径 F）；SampleUnit/TestRun/Measurement 与五种事实性质现成；D186 的 Living FMEA 延后。

**建议落法**：不提前排期，只给 D104 一个具体承接物写进恢复条件：**现场退货单元（FieldReturnUnit）一等对象**——序列号、退货原因口径、复测 TestRun、处置结论；AI 做失效聚类→Issue/FailureMode 候选（T1），喂 Living FMEA。领域模型先行即可在空档里领先。

**需要的决策**：新对象须决策记录，可在 D48/D104 启动时一并定。

## 3. 创新机会（竞品没有、我方架构天然适合）

### J-06 "G0 风险雷达"

把 J-01(a)、J-02、J-03 与已采纳的 D101（PCN 子流程）合成一页纸：G0 评审材料固定加"风险雷达"节——**IP、法规认证、关税、供应（长交期/生命周期）**四维候选，各带引用与未知项责任人（接 D100 的未知项机制）。竞品无人占位：Flow Engineering 只做航天国防的需求—测试追溯 [一手，10-22 已录]。架构匹配度高：全部是只读研究 + 候选产出，在 T0/T1 内完成，正好用单 Agent + 渐进技能包承载，不碰任何不可协商项。

### J-07 放行包 → DPP / 外审数据包出口

J-01(b) 与 D185（外审取证包，延后）、D139（领先点做成可见特性，延后）、G-44（ROI 叙事）合并为一个出口设计：放行包本来就是证据链，导出格式对准电池护照/ESPR 标准与 ISO 9001/IATF 外审口径，把运行回执、引用逐字核对、资格记录做成**客户看得见的审计叙事**。这是把已有的信任层设计变现为销售特性，不新增运行时能力。

### J-08 被外部 Agent 调用的恢复信号（趋势项，不动结论）

Google A2A 协议已入 Linux Foundation、150+ 组织支持 [[二手](https://logisticsviewpoints.com/?p=34342)]，买卖双方 agent 直接交换询报价的模式正在成型。这不改变 D112（PDOS 作 MCP server，延后）与 D106（外部协作者，延后）的结论，只建议把两条的恢复条件措辞补上"客户或供应商提出 agent 对接时"。届时"供应商 agent 提交报价/PCN，经我方受众与档位核对入库"是 G-20 外部主体的下一形态。

## 4. 查过但不建议做的

- **自主谈判成交**（Pactum 路线）：违反不可协商项 1 的 T2 保留（具名签核/外发），且无独立验证的效果数据。
- **自建 CAE/仿真 agent**：Ansys SimAI 的 Mesh Agent 自标"探索性"、Discovery Validation Agent 仅早期客户评估 [[二手](https://www.automotivetestingtechnologyinternational.com/news/cae-simulation-modeling/ansys-launches-ai-tech-for-virtual-testing.html)]；SimScale Engineering AI 为厂商自述。在"不替代 ERP/MES/PLM"的同一边界外，将来按证据类型接入仿真结果即可。
- **A2A 自动下单/自动承诺**：同 T2 红线，只接收候选、不自动成交。
- **大厂 PLM 基线更新**：复核结果无新实质发布——[Teamcenter AI BOM Agent 仍是 2606（2026-06）](https://blogs.sw.siemens.com/teamcenter/ai-bom-agent-plm-engineering-change/) [一手]、Windchill AI Assistant 为 2026-04 [二手]、Arena/Propel 无新动作；PTC 2026-11-02 德文博客出现"ProductAscentAI"字样但无可用细节（§6）。

## 5. 优先级与进入路径

| 条目 | 优先级 | 建议时机 | 需决策记录 |
|---|---|---|---|
| J-01(a) 合规雷达 | 高 | S3 认证台账（D93）动工前拍板 | 是（新来源类型） |
| J-02 IP 初筛 | 高 | 研究类技能包批次（可与 D180 同组） | 是（连接器与数据类别） |
| J-01(b)+J-07 DPP/外审包出口 | 中高 | 随 D93/D185，S4 放行闭环 | 是（导出模板） |
| J-03 关税口径 | 中 | 随 D105 目标成本 | 细化为主 |
| J-04 比价与跟催 | 中 | 前置 D47，与 D241 同批 | 视比价表对象化而定 |
| J-05 FieldReturnUnit | 中低 | 排期不变，写进 D104 恢复条件 | 是（新对象，随 D48 定） |
| J-06 G0 风险雷达 | 合成项 | 随 J-01–J-03 落地后拼装 | 否（材料模板细化） |
| J-08 A2A 恢复信号 | 措辞项 | 下次整理 W3b 延后条目时顺手改 | 否 |

进入路径：已于 2026-11-08 登记为 [W3b 候选](../../tasks/ai-native-integrated-todo.md#debt-board) D321–D328（J-01a=D321、J-01b+J-07=D322、J-02=D323、J-03=D324、J-04=D325、J-05=D326、J-06=D327、J-08=D328），逐条经用户拍板→写 P 编号决策记录→挂对应 W 组；本稿不自带任何施工授权。

## 6. 未证实事项（采纳前须核对）

1. 电池法规中便携电池的二维码/标签义务准确范围与全护照门槛，须对官方文本核对。
2. ESPR 登记册上线日期（2026-07-19/20 两个口径）与六项横向标准发布时间，来自第三方转述。
3. CRA Article 14 报告义务细节与罚则数字均来自合规厂商博客。
4. Right to Repair 指令 2026-07 生效口径未对原文核实。
5. A2A 的 Maersk/DHL/Flexport 联盟案例与"v2.1 版本"均无一手来源，不作依据。
6. Bruviti、Pactum、Levelpath、Patsnap 的效果数字全部为厂商自报。
7. PTC "ProductAscentAI"（2026-11-02 德文博客）内容无可用细节。
