# PM 方法目录候选（pm-skills 借鉴 · 消费电子硬件化）

日期：2026-09-28。状态：**候选，待用户评审；未冻结，不改变任何现行合同效力**。

来源：2026-09-28 拷问式确认的裁决记录；pm-skills 实际清单核验（gh-proxy 镜像抓取，README 与目录交叉核对：9 插件 69 skills + 42 commands，MIT）；本机 last30days v3.23.0（MIT）核验。本文件不分配 DC 编号，评审通过后按 §25 冻结时另定（DC-12 已由小Pai使用）。

---

## 1. 结构与边界（沿用合同，不改）

- 内容进入设计合同 §16"人工发布的可信方法目录"：每条登记 key/version、适用品类、适用阶段、步骤、所需工具、输出、停止条件。
- 方法目录只喂 PMI 既有 8 项能力（research_planning / competitor_analysis / market_analysis / opportunity_mapping / experiment_design / product_strategy / product_definition / product_matrix），**不新增 capability、不改 capability 注册表**；Ask PDOS 入口、Manifest/Finding、T2 最小集一行不改。
- 逐条方法按 DC-11 §6 流程取得资格：独立评测 → T1 试运行（确认率 ≥0.9 / 撤回率 ≤0.05）→ T0 静默直写 + 抽检；本文批准不等于任何能力获得 T0。
- 许可：pm-skills MIT（保留署名）。

## 2. 适用品类与市场方向（用户裁决：宽起步；外贸出口为主）

字段值写"消费电子通用"。模板示例统一以锂电便携充气设备（D14 系）为锚点并标注"示例"：胎压精度/续航/噪音/温升/自动停机可靠性、UN38.3 / IEC 62133 / GB 31241 / CE / FCC / UL、亚马逊电池报告、RoHS/REACH。扩品类按版本新增适用范围，不改老版本。

**市场方向：外贸出口为主**——方法示例的 VOC 来源锚定英文平台（亚马逊评论、Reddit/X 社区），目标市场约束以欧美认证/法规为先（UL/CE/FCC、欧盟电池法规 (EU) 2023/1542）；国内社区（小红书/B站）作为保留选项，示例不以其为主。电商/渠道数据的采集通道**另行评审**，本目录只在"所需工具"字段注明推荐数据来源与人工导出方法。

## 3. 借入清单（26 项 + 1 项待复核，全部硬件化改写）

| 组 | pm-skills 原条目 | 目标方法（建议 key） | 硬件适配动作 | 归属能力 |
|---|---|---|---|---|
| 发现 | opportunity-solution-tree | opportunity_tree_method | Desired Outcome 挂可测参数；沿用"至少 3 方案 + 四维实验"合同 | opportunity_mapping |
| 发现 | identify-assumptions-existing / -new | assumption_inventory（两版） | 存量品/新品分别模板；假设挂证据或明示未知 | research_planning / opportunity_mapping |
| 发现 | prioritize-assumptions | assumption_prioritization | 排序依据可复算，不用 LLM 评分 | opportunity_mapping |
| 发现 | brainstorm-experiments-existing / -new | experiment_ideation（两版） | 对接四维实验（价值/可用性/商业可持续/技术可行），技术可行=台架/热测试/寿命循环 | experiment_design |
| 发现 | interview-script | channel_user_interview | 访谈对象含渠道（汽配连锁/跨境卖家）与终端用户；脚本预填品类工况 | research_planning |
| 发现 | prioritize-features | feature_tradeoff | 硬件功能取舍：BOM 成本/功耗/体积/认证影响入比较维度 | product_definition |
| 发现 | analyze-feature-requests | feature_request_triage | 输入源改为电商评论/渠道反馈/售后记录分类 | product_definition |
| 战略 | value-proposition | value_proposition_method | 与竞品同工况实测对照绑定 | product_strategy |
| 战略 | pricing-strategy | pricing_dtc | 接 design-to-cost：电芯+电机+PCB 主料 BOM 倒推价格带；汇率/关税入版本化假设 | product_strategy |
| 战略 | swot-analysis | swot_method | 通用模板，品类语境示例 | product_strategy |
| 战略 | pestle-analysis | pestle_method | E 扩认证/法规（电池法规演变）示例 | product_strategy |
| 战略 | porters-five-forces | porter_five_forces | 品类竞争格局（供应链议价=电芯供方集中度） | product_strategy |
| 战略 | ansoff-matrix | ansoff_matrix | 品类扩张决策（现有市场渗透/新品类开发） | product_matrix |
| 市场 | market-sizing | market_sizing | TAM/SAM/SOM 沿用合同 §11：公式/分母/权重版本化，数据源=电商类目+渠道走量，未知不补零、不许 LLM 评分 | market_analysis |
| 市场 | sentiment-analysis | voc_sentiment | 差评/退货 VOC 根因分类；输入=人工导出快照与后续批准的采集通道 Evidence；停止条件须含防偏差条款（样本量下限、评分分布 sanity check、激励评论/Vine 识别） | market_analysis |
| 市场 | customer-journey-map | journey_map | 购买旅程（搜索→比价→下单）+使用旅程（场景工况）两段 | market_analysis |
| 市场 | competitor-analysis | competitor_method | 同工况实测表模板（复用 D14 系列既有实测格式） | competitor_analysis |
| 执行 | pre-mortem | pre_mortem_hardware | 物理失效假设（电池热失控/过充保护/软管耐温/精度漂移）；**结构化输出自动生成 FMEA 候选（T1），首批并行实现**（见 §4） | experiment_design / living_fmea |
| 执行 | stakeholder-map | stakeholder_map | 干系人=渠道/认证机构/检测实验室/关键供方 | product_strategy |
| 执行 | prioritization-frameworks | prioritization_methods | 通用，权重可复算 | product_definition |
| 执行 | strategy-red-team | strategy_red_team | 红队评审对象=策略与定义草稿；与 AT 系列攻防负例不混 | product_strategy |
| 执行 | job-stories | jtbd_statements | 工况语句模板（当__时我想要__以便__，挂可测参数） | opportunity_mapping |
| 增长 | north-star-metric | business_north_star | **两段式**（见 §5） | product_matrix |
| GTM | competitive-battlecard | battlecard | 渠道竞争对战卡（"以本轮确认为准"口径下纳入；评审时可去掉） | competitor_analysis |

不借（已覆盖）：startup-canvas（=九区 Canvas）、market-segments（=细分/JTBD 区）、create-prd（产品定义规格条目更严）、summarize-meeting（会议链已有）、test-scenarios（N3-08 已有）、outcome-roadmap（矩阵/路线图已有）。

丢弃：pm-data-analytics 全部 3 项、pm-go-to-market 其余 5 项、pm-marketing-growth 其余 4 项、pm-toolkit 全部 4 项、pm-ai-shipping 全部 3 项、execution 中 brainstorm-okrs / sprint-plan / retro / release-notes / user-stories / wwas / dummy-dataset。

## 4. pre-mortem → FMEA 自动候选（用户裁决：首批并行实现，T1）

- 定义失效假设→FMEA 字段映射 schema（severity/occurrence/detection 初值由模型建议、人工可改）；输出走 T1 预填一次确认，原值不由模型补造。
- 独立评测（真实模型、固定合同、golden 候选）+ T1 试运行达标后按 DC-11 §6 申请 T0；失败人工替代路径=纯文档模板手动建候选。
- 与 N4-02/N4-05 living FMEA 验收语衔接，不替代其人工签核。

## 5. 北极星指标两段式（用户裁决）

量产前：先行指标=渠道意向/预订/样机测试通过率；量产后：真实指标=评分/退货率/复购/NPS。两段不混算；先行指标不能替代量产后效果验收；与 N7-03 员工效率测量分列。

## 6. PRD 与规格书双文档 · 贯穿项目目标（用户裁决：必须有实际文档）

- **Spec 文档（已有，保持）**：导出中心"内部产品规格书"——从指定真实定义版本生成 docx/xlsx/pptx/pdf，含规格正文、依据与假设、协审、发布/撤回历史、原引用；预览→确认→保存回执（digest/模板版本）；明确不作客户批准/审厂/认证证明。
- **PRD 文档（新增，装配导出）**：导出中心新增"PRD 文档"装配类型，从同一市场空间的真实对象装配成稿：市场背景与研究结论、目标用户与 JTBD、机会与方案取舍（含证伪/不确定）、竞争与差异、功能范围、成功指标（§5 两段式）、约束（认证/目标成本/上市窗口）、**需求与规格映射表（需求编号 ↔ item_key）**、版本与变更记录。固定章节模板版本化；AI 装配初稿按 DC-11 首批 #4"导出初稿"档位（T0 初稿、人工定稿后发布/下载）。
- **贯穿性不变量**：两份文档均版本化，被 Case/项目/ECR/结项引用时固定快照+digest（沿用 SourceRef 引用模式）；定义修订→PRD 新版可装配（旧版保留）；工程变更影响规格时受影响版本进入对照；结项反馈对照原 PRD 假设逐项裁决（支持/证伪/未知），不覆盖历史。
- **不改变**：PRD/Spec 均为内部文档，正式发布、客户外发仍走 T2 与既有授权；文档是版本化投影交付物，不成为新业务真值。

---

## 附 · 相关裁决记录（2026-09-28 拷问确认）

| 决策点 | 用户裁决 |
|---|---|
| 对照范围 | 以当轮确认为准，不另产出 69 项全量表文档 |
| 品类口径 | 宽起步：消费电子通用；示例锚点 D14 系 |
| 市场方向 | 产品设计以外贸出口为主 |
| pre-mortem→FMEA | 自动生成候选（T1），首批并行实现 |
| 战略四件套 | SWOT/PESTLE/波特五力/安索夫四项全借 |
| 北极星 | 两段式 |
| PRD/Spec 双文档 | 必须有实际 PRD 与规格书文档，贯穿整个项目 |

待用户后续提供（涉及采集通道时另行处理）：卖家精灵凭据；社区采集账号。AI 动作模型维持 DC-11 T0/T1/T2。
