# 原工程 34 个 SHADOW 能力逐项对照（2026-11-02）

回应[欠债总表](../../../../tasks/ai-native-integrated-todo.md#debt-board) D174 第 3 项，依据[设计确认稿 P73](../../../design/2026-10-08-pdos-next-design-confirmation.md#p73) 第 3 项。本表只做对照，不恢复任何原工程能力；“未承接”的条目由主会话加入 W3b 候选池，由用户逐条定。

## 来源与口径

- **名单**：标签 `original-final-2026-10-08` 的 `server/app/ai/capability_contract.py`（`CAPABILITY_CONTRACTS`，共 45 项）。读取用 `git show 'original-final-2026-10-08^{}:<路径>'`。
  - 32 项在登记里直接写 `rollout=SHADOW`；
  - 另 2 项（`supplier_intelligence.supplier_delay_risk`、`executive_intelligence.executive_portfolio_brief`）经 `_finding_capability` 登记，因所属 Agent 在 `PHASE_THREE_AGENT_KEYS`（同标签 `server/app/ai/runtime_contract.py`）而为 SHADOW；
  - 合计 34 项 SHADOW、11 项 LIVE，与 10-07 单 Agent 方案（标签 `archive/pre-restructure-2026-11-01` 的 `docs/design/2026-10-07-xiaopai-single-agent-runtime-plan.md` §1.1）一致。`rollout_guard.py` 没有覆盖这些常量。
- **原用途**：取自同一标签 `server/app/ai/prompts/` 中各能力的提示词（版本按登记里的 `prompt_version`）。原能力全部只产出待人审的 Finding。
- **分组**：10-07 方案只给了各组数量（产品 9、会议/知识 8、工程讨论 10、管理 3、供应 2、品质 2），没有逐项名单。本表按原 Agent 归属和用途分组，数量与之吻合。
- **现承接位置**：
  - [18 个技能包](../../../../server/pdos_next/agent/skill_packages/)（不含 `evaluation-rubric.md`）；
  - `contracts/operations.json` 与 `contracts/auxiliary-operations.json` 中的命令；
  - [v1.1](../../../design/2026-10-08-pdos-complete-target-architecture-v1.1.md)；[确认稿](../../../design/2026-10-08-pdos-next-design-confirmation.md)的 C3、P17、P18、P33–P36、P65；[DC-11](../../../design/2026-09-20-ai-direct-write-tier-policy.md) §8；
  - W3b 候选池 D70–D139、D180–D204。
- **处置分类**：
  - 已承接：现有技能包或命令能完成原用途；
  - 部分承接：写明已覆盖什么、缺什么；
  - 未承接：有价值，但现在没有承接，建议进候选池；能并入已有 W3b 条目的写明条目号；
  - 放弃：现行设计下不需要，写明理由。
- 承接后的档位按 DC-11 与 v1.1 附录 A 办理，不继承原工程的 SHADOW/LIVE 状态或资格（AGENTS.md 不可协商项 6）。

## 逐项对照

能力 ID 省略前缀：产品组为 `product_management_intelligence.`，会议/知识组为 `knowledge_lite.`，工程讨论组为 `engineering_intelligence.`，管理组为 `executive_intelligence.`，供应组为 `supplier_intelligence.`，品质组为 `quality_intelligence.`。

| # | 原能力（id 与名称） | 分组 | 原用途 | 处置 | 现承接位置或理由 |
|---|---|---|---|---|---|
| 1 | `research_planning` 研究规划 | 产品 | 按受控资料提出一个有界研究任务候选：研究问题、用户/地区/时间范围、方法、支持哪个决定、停止条件 | 部分承接 | `public_research` 把问题拆成可独立回答的研究问题并执行公开研究；`jtbd` 的假设带验证方式（访谈、问卷、小样测试）和证伪条件。缺：一手研究任务的规划。研究对象已按确认稿 C3 删除，不建议单补 |
| 2 | `competitor_analysis` 竞品分析 | 产品 | 同口径（型号、地区、时间、单位、工况）比较竞品，给出最多 6 项可登记观察 | 已承接 | `competitor_comparison`：数值比较交 `calc.spec_compare`，口径不同时分组标注 |
| 3 | `market_analysis` 市场细分 | 产品 | 给出最多 6 项有依据的市场细分；规模只解释确定性引擎的结果 | 已承接 | `jtbd` 写细分（`category.knowledge.add`，kind=segment）；`opportunity_scoring` 用 `calc.market_size` 算规模；`price_band` 补价格结构 |
| 4 | `opportunity_mapping` 机会映射 | 产品 | 按细分列机会，每个机会至少 3 个候选方案，保留依据、约束与未知 | 已承接 | 痛点和用户工作由 `review_pain_clustering`、`jtbd` 给出；评分用 `opportunity_scoring`（`calc.opportunity_score`）；方案用 `option_comparison`。机会不再是对象（C3）。方案下限从 3 个降到 2–3 个，这一口径变化已列在 D202 |
| 5 | `experiment_design` 实验设计 | 产品 | 为方案设计验证实验：价值、可用性、可行性、商业四个维度，假设、方法、样本依据、成功与证伪判据 | 部分承接 | `jtbd` 正文写明原工程的实验设计并入其假设清单，每条带验证方式与证伪条件（最多 5 条）。缺：按方案逐个设计、四维划分、样本依据。C3 写明要有实验设计技能包，现在没有 → 并入 D187 |
| 6 | `product_strategy` 产品策略 | 产品 | 绑定机会比较至少 3 个方案，填九区 Canvas、模块目标成本、DQE/SQE/PIE 约束 | 部分承接 | 方案比较由 `option_comparison` 承担（定位、关键规格差、`calc.cost_subtotal` 粗成本、周期、取舍），写进提案靠 `proposal_drafting`。缺：九区 Canvas（可随 D187 方法技能定）、模块目标成本（D105 目标成本对照）、专业早期约束（D201）。策略对象已删（C3） |
| 7 | `product_definition` 产品定义 | 产品 | 绑定已发布策略起草型号定义：规格条目带目标、单位、工况、方法、判据，修订时保留条目标识 | 部分承接 | 立项版定义（10–20 条关键规格）由 `proposal_drafting` 起草，派生型号由 `derivative_diff` 起草，`gap_check` 查缺项；G0 批准时固定为型号定义 v1。缺：G0 后在项目内补全完整规格、提示专业协审缺项的技能包。命令 `product.definition.draft`、`product.definition.item.patch` 已有，目前只有 `change_control` 使用。可与 D184（PRD 装配）一起定 |
| 8 | `rfq_requirements` RFQ 需求抽取 | 产品 | 逐条抽取客户要求，保留数值、单位、工况、否定和例外，不补造 | 已承接 | `rfq_extraction`：经 `evidence.extract` 隔离子任务抽取，映射规格字典，列冲突和待问问题 |
| 9 | `product_matrix` 产品矩阵解释 | 产品 | 解释已保存的“市场—型号”覆盖比较和所选路线图；状态和计数只由确定性覆盖引擎给出 | 未承接 | v1.1 §01.6 的“品类矩阵视图”只有界面描述，没有覆盖引擎，也没有解释技能；路线图全文缺失 → 并入 D189（矩阵与路线图补成视图或确认放弃） |
| 10 | `meeting_planning` 临时会议起草 | 会议/知识 | 按用户要求和具名候选人起草临时会议（目的、议程、参会理由），不预约、不通知 | 未承接 | 现在没有会议对象，也没有对应技能包；P34 的项目讨论与 @提及承担了一部分异步协调 → 并入 D202（会议闭环的会前装配） |
| 11 | `intake_organization` 历史资料导入整理 | 会议/知识 | 整理明确选入的历史资料片段，保留原值与来源冲突；历史日期不当基线 | 未承接 | 原件登记和 `evidence.extract` 已有，但没有把历史项目资料整理成记录候选的技能包。试点导入在途项目需要它 → 并入 D85（在途项目纳管），与 D200（CEHub 在途项目迁入）一起定 |
| 12 | `process_template_configuration` 流程模板配置 | 会议/知识 | 为组织流程模板提出可配置项修改（任务、阶段名称、签核、提醒），不能削弱硬门禁 | 未承接 | P33 规定框架由用户或项目管理部门维护，小Pai 不改框架（`work.framework.publish` 由人办理） → 并入 D198（小Pai 能否起草框架差异） |
| 13 | `meeting_business` 会议业务事项 | 会议/知识 | 从会议转写中提取问题、风险、变更申请候选，每项逐字引用 | 未承接 | 没有会议转写来源。按现行规则，问题须有 run/测量/事件来源（`quality.issue.create`），变更须有正式来源（`change_control` 写明聊天里的意向不足以建立变更），会议原话只能形成待核候选 → 并入 D114（纪要摄取） |
| 14 | `meeting_decisions` 会议决策候选 | 会议/知识 | 整理有证据的待决事项：背景、备选、权衡、结论、理由、后果 | 未承接 | 没有“决定草稿”命令。P34 设计稿 §6.2 提到可从讨论起草决定草稿，但没有落成命令 → 并入 D114；决定的执行跟踪见 D182 |
| 15 | `meeting_actions` 会议行动 | 会议/知识 | 提取行动建议，责任人与日期只逐字摘录原文 | 部分承接 | 行动转任务可走 `work_management` 的 `work.task.create`，以及 P34 讨论里的“转为任务”；NPI 设计稿把“会议决定”列为调整任务的触发。缺：从会议转写逐条提取 → 并入 D114 |
| 16 | `meeting_minutes` 会议纪要 | 会议/知识 | 按转写和纪要底稿生成纪要草稿 | 未承接 | 没有纪要对象和命令。DC-11 §8 首批第 1 项定为 T0 草稿，P34 设计稿 §6.2 写“小Pai 可以从讨论起草纪要”，v1.1 §09 的 S5 列有“会议/周报”，都还没有落实 → 并入 D114 |
| 17 | `meeting_reading` 会议阅读 | 会议/知识 | 归纳转写内容，每条带片段编号和逐字引用，不形成业务对象 | 部分承接 | 已登记的原件进入企业检索（`server/pdos_next/agent/enterprise_search/`），小Pai 可以带引用回答。缺：转写分段，以及逐段逐字引用的结构化阅读 → 随 D114 |
| 18 | `discussion_followup` 讨论后的变更工作包 | 工程讨论 | 多专业讨论结束后，按讨论摘要和影响资料准备变更工作包 | 已承接 | `change_control`：`change.impact.compute` 算显式影响，AI 待核线索分栏列出，`change.order.prepare` 准备实施计划，复验加载 `build_execution`、`test_verification`。讨论来源改为 P34 项目讨论里 @小Pai；讨论结论不作正式来源 |
| 19 | `discussion_convene` 判定是否召集多专业讨论 | 工程讨论 | 判断是否需要多席位 AI 讨论，并选择席位 | 放弃 | v1.1 §06 只有小Pai 一个 Agent，不默认构造 Agent 群聊，不靠投票形成结论（AGENTS.md 不可协商项 6）。多专业意见改由 P34 项目讨论中 @角色 找真人 |
| 20 | `discussion_research` 讨论席位内的公开研究 | 工程讨论 | 讨论席位内选择公开搜索或读取，出站查询不带内部信息 | 部分承接 | 公开研究与出站查询脱敏由 `public_research`（`research.fanout` 隔离子任务）承担，但它的上下文是品类或个人会话；项目内的 `change_control`、`quality_issue` 没有研究工具。讨论席位语境放弃。缺口暂不建议单列 |
| 21 | `change_discussion` 变更讨论中的专业席位 | 工程讨论 | 模型扮演一个专业席位，给出有引用的立场并回应其他席位 | 放弃 | 同第 19 项：不设领域 Agent，不做角色扮演式的多席位讨论 |
| 22 | `discussion_initiation` 用户发起讨论时的判定 | 工程讨论 | 用户发起讨论时判断是否召集、给出席位 | 放弃 | 同第 19 项 |
| 23 | `notice_discussion` 供方变更通知讨论 | 工程讨论 | 针对供方变更通知，召集硬件、SQE、DQE、项目经理席位讨论 | 放弃 | 多席位部分同第 19 项；供方变更本身见第 24 项 |
| 24 | `notice_work_package` 供方变更通知工作包 | 工程讨论 | 按已授权的供方变更通知（PCN）证据，准备变更影响与复验工作包 | 部分承接 | `change_control` 接受“供应变化”作为变更来源，评测案例含“供应替代”。缺：PCN 的登记、评审和适用范围 → 并入 D101（PCN 子流程，推荐采纳） |
| 25 | `change_work_package` 变更工作包 | 工程讨论 | 逐对象给出影响判断，以及调查、复验、复审、复认证建议和完成判据 | 已承接 | `change_control`，同第 18 项 |
| 26 | `cost_discussion_followup` 讨论后的降本方案 | 工程讨论 | 讨论结束后，按讨论摘要准备降本方案 | 未承接 | 讨论部分同第 19 项，放弃；降本本身同第 27 项 → 并入 D105 |
| 27 | `cost_reduction` 降本方案 | 工程讨论 | 针对选定的成本差距给出最多 6 个降本选项，单价与 NRE 分开，写明质量、进度、供方影响和所需验证 | 未承接 | 已有 `cost.inputs.record`、`cost.estimate.compute`（在 `build_execution` 中）和 `option_comparison` 的粗成本，但没有降本技能包。v1.1 §04.10 写明“AI 解释敏感项与降本路径”，§01.1 也把降本列为项目类型 → 并入 D105（目标成本对照与 ECO 成本差） |
| 28 | `executive_brief` 管理简报 | 管理 | 对选定项目的冻结管理快照做带引用的说明：异常、缺失证据、待决事项 | 部分承接 | 管理者驾驶舱按规则汇总滑期节点、待决阶段评审、资源冲突、状态更新缺失（P34 第 6 项，读模型在 D37 ⑦）；各项目的叙述由小Pai 起草状态更新、负责人确认后发布（P18、P65，`work_management`）；本人摘要见 P36。缺：跨项目的 AI 叙述简报，驾驶舱上线后再评 |
| 29 | `portfolio_explanation` 组合比较解释 | 管理 | 解释已保存的确定性组合比较：逐方案讲资格、时间、成本、质量、产能，以及加班、替代设备、外包、范围取舍、延期 | 部分承接 | 计划候选的资源冲突和前后比较已有确定性代码（`server/pdos_next/domain/projects/resources.py`），`work_management` 起草计划候选（`work.plan.propose`）；P35 规定跨项目冲突进入比较与取舍。缺：跨项目取舍方案的并列比较与解释 → 并入 D84（优先级取舍记录） |
| 30 | `executive_portfolio_brief` 组合异常简报（事件触发） | 管理 | 项目阶段变化或门禁批准时，提出需要管理层关注的组合异常 | 放弃 | 管理者驾驶舱已按规则呈现同类异常（P34 第 6 项）；健康度是纯规则投影，AI 不参与（P17）。事件触发的 AI 简报与之重复 |
| 31 | `supplier_recovery` 供应恢复方案 | 供应 | 针对物料异常或模具轮次，给出催交、替代、借料、模具恢复选项，写明验证步骤和完成判据 | 未承接 | `build_execution` 只登记供应快照、计算齐套（`supply.snapshot.record`、`supply.kit.compute`）；替代须有 AlternateQualification，`supply.alternate.approve` 为 T2、小Pai 只准备材料。没有起草恢复选项的技能包。v1.1 §01.5 的采购/供应职责包含“齐套、替代与异常”。W3b 没有对应条目 → 建议新增 |
| 32 | `supplier_delay_risk` 供方延期风险（事件触发） | 供应 | 供方报告延期时，提出项目风险候选，附缓解和应急方案 | 部分承接 | 供方承诺 `supply.commitment.record`、外部等待 `work.external_wait.record`、预测刷新 `work.forecast.refresh` 和健康度规则能反映延期。缺：延期事件自动形成风险跟进 → 并入 D75（自动化规则模板中的“外部等待升级”） |
| 33 | `event_issue` 事件建单建议 | 品质 | 测试失败或物料短缺时，建议新建或复用问题，必须逐字引用原始失败或短缺事实 | 部分承接 | 测试失败建单与去重由 `quality_issue` 承担（`quality.issue.create` 为 T0，来源须为 run/测量/事件），对应 DC-11 §8 首批第 2 项。缺：物料短缺进入问题或异常的路径 → 与第 31 项的新增条目一起定 |
| 34 | `capa_work_package` CAPA 工作包 | 品质 | 按不合格记录分阶段准备：调查任务和所需证据、根因假设、纠正预防措施、有效性计划 | 已承接 | `quality_issue`：`quality.capa.draft`（T0）起草假设与措施；有效性复核 `quality.capa.verification.review` 只准备材料，结论由专业具名作出 |

## 汇总

| 分组 | 已承接 | 部分承接 | 未承接 | 放弃 | 合计 |
|---|---|---|---|---|---|
| 产品 | 4 | 4 | 1 | 0 | 9 |
| 会议/知识 | 0 | 2 | 6 | 0 | 8 |
| 工程讨论 | 2 | 2 | 2 | 4 | 10 |
| 管理 | 0 | 2 | 0 | 1 | 3 |
| 供应 | 0 | 1 | 1 | 0 | 2 |
| 品质 | 1 | 1 | 0 | 0 | 2 |
| 合计 | 7 | 12 | 10 | 5 | 34 |

**未承接、建议进候选池**（10 项，合成 7 条；由主会话加入 W3b）：

- 产品矩阵解释（#9）→ 并入 D189。
- 临时会议起草（#10）→ 并入 D202 的会前装配。
- 会议纪要、决策候选、业务事项（#13、#14、#16），连同 #15、#17 的缺口 → 并入 D114。建议把 D114 的范围写成“会议技能包”，并注明 DC-11 §8 首批第 1 项和 v1.1 S5 已经列入。
- 历史资料导入整理（#11）→ 并入 D85，与 D200 一起定。
- 流程模板配置（#12）→ 并入 D198。
- 降本方案（#26、#27）→ 并入 D105。
- 供应恢复方案（#31），连同 #33 的物料短缺缺口 → 新增一条（W3b · NPI 业务域），现有条目都不对应。

**部分承接中可挂到已有条目的缺口**：#5 → D187；#6 → D187、D105、D201；#7 → D184；#24 → D101；#29 → D84；#32 → D75。#1、#20、#28 的缺口暂不建议单列。

**放弃**（5 项）：#19、#21、#22、#23 是多席位 AI 讨论，与单 Agent 拓扑冲突，多专业意见改由 P34 讨论找真人；#30 由管理者驾驶舱的规则汇总承担。

## 存疑

- 分组是按原 Agent 归属和用途推定的，10-07 方案只给了数量。
- 10-07 方案 §5.2 写“研究规划、市场、机会、实验、策略、定义、矩阵解释”是“现有 8 项 SHADOW 能力”，但只列了 7 个名称。第 8 项应是竞品分析（RFQ 另由 `rfq_extraction` 承接）。
- 10-07 方案把 34 项都称为“按钮触发”，但 #30、#32 是事件触发的 Finding 能力，只因第三期 Agent 未开放才是 SHADOW。
- 同一标签的 `durable_registry.py` 列的是 31 个模型调用入口，口径不同，本表未使用。
