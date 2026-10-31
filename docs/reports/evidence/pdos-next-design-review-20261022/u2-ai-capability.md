# U2 · PDOS AI-native 能力地图（设计与实现对照）

范围：v1.1 §05、§06、§07.6–07.10、§09；DC-11；M2 工具面两份文档；`pdos-next/server/pdos_next/agent_kernel/`、`skill_packages/`（17 个）、`domain/automations/`、`personal_attention*.py`、前端 `components/xiaopai.tsx`、`pai-*.tsx`、`pai/`、`automation-rules.tsx`；状态来自 `tasks/ai-native-integrated-todo.md` 当前队列（L9–L88）与 evidence 链接。
口径：只读分析，未运行测试、服务或数据库。下文"已实现"是指代码与合成证据都已具备，**不等于用真实模型验证过**。凡写"未实现"的，都已对代码 grep 确认为 0 命中，或经下文所列文件核实。

---

## 0. 结论先行

1. **安全边界在前，价值面在后。** 可信写入边界做得深：服务器绑定范围、逐字引文核对、隔离子任务、回执与撤回、对账出口、预算结算。用户实际能用到的 AI 价值却很窄：只有"品类研究 → 立项提案"一段较完整，而且至今**没有一次真实模型跑通注册图的完整工作**。
2. **"AI 成功静默写入"在当前代码里不可能发生。** T0 写入要求试点资格，而任何租户都没有资格，所以 T0 一律降级为 T1 候选，T1 候选又要逐条弹窗确认。DC-11 想要的"人只处理例外"，现在实际变成了"每条 AI 产出都要人确认一次"。
3. **主动性只搭了骨架。** AutomationRule 的 schema 强制只读：不联网、不调 MCP、不写业务、不接外部事件。注意队列是纯规则投影，没有 AI 例外分类。周报、状态更新、会议纪要都没有技能。
4. **项目侧的小Pai 几乎看不见项目。** 项目运行不预载技能，项目上下文只有 id/name/revision/visibility 四个字段，也没有 Build、Issue、TestRun、计划、任务的读取工具。产品主轴已经改为项目管理（P15），工程、品质、生产、采购这些岗位从小Pai 得到的帮助最少。
5. **输入模态和检索偏弱。** 只支持 TXT、MD、PDF（文本层）、XLSX 四种文件。没有 DOCX、邮件、OCR、图片、语音、钉钉。检索只在本次运行已绑定的来源里按标题做子串匹配，已发布的经验规则小Pai 读不到，经验回流没有闭环。

---

## 1. 用户能从小Pai 得到的能力

### 1.1 四类入口：设计与实现

| 入口 | 设计依据 | 实现现状 | 判定 |
|---|---|---|---|
| 对话委派 | v1.1 §05.4、§01.7；右侧栏可放大，跨页和刷新后续接 | `components/pai-rail.tsx`：右侧常驻栏，可放大；`components/xiaopai.tsx`：品类/提案/项目三种范围；`category-create/personal-xiaopai.tsx`：无品类时的个人对话。会话管理支持改名、置顶、归档、恢复，不支持删除（P20）。"继续工作"会新建一个 Run，接在原 Run 后面（`pai/run-continuation.tsx`、`agent_kernel/conversation.py`）。另有取消、转后台、整次撤回预览 | 骨架已实现，只有合成验证 |
| 页面按钮 | v1.1 §06.1"页面按钮由小Pai 承担"；§05.3 提案页"让小Pai 起草或查漏"；§06.3.3 按页面预载技能 | 没有一键委派按钮。页面只是把范围（品类/提案/项目）带进同一个自由文本框，例如 `preproject/proposal-pai.tsx`（23 行）里内嵌的"本案助手"。预载只看范围（`agent_kernel/bootstrap.py:453-511`），技能里写的 `preload_when` 文本在代码中没有任何消费方（grep 0 命中） | 部分 |
| 事件触发 | v1.1 §06.4 domain_event；§06.5 例：测试失败自动建 Issue；gap_check 的 `preload_when` 写了"来源有新版本/撤回"时触发 | AutomationRule 的事件触发、合并窗口、去重、因果链和级联深度都已建。但：① `domain/automations/schemas.py:110-145` 把 `allow_network`、`cross_object_write`、`external_sources_enabled` 固定为 `Literal[False]`，`mcp_tools` 的 `max_length=0`，并写明 "This read-only slice does not enable this capability"；② `agent_kernel/execution.py:68-69` 对自动化 Run 的任何业务写入一律报"当前只读规则没有业务写入权限"；③ `domain/automations/service_runtime.py:234-287` 把测试结果导入、原件上传、研究快照登记、外部回执这类事件抑制为 `EXTERNAL_TRIGGER_DISABLED` | 骨架。规则只能读和总结，产生不了业务结果 |
| 定时 | v1.1 §06.4 schedule、relative_milestone；设计稿里的"竞品价格周跟踪 · 每周一 · 仅变动时提醒" | Schedule、RelativeTrigger 加 Temporal `workflows/automation.py`（AutomationRuleWork）都已实现。限制同上：不联网就做不了"竞品价格周跟踪" | 骨架 |

运行主线 `意图 → 范围/授权 → 上下文 → 模型 → 工具 → verify → 领域命令 → 回执` 由唯一一张注册图实现（`agent_kernel/graph.py`：prepare → model → route/interrupt → tools → verify → finalize）。全局预算 12 轮、40 次工具调用（`graph.py:136-140`）。技能 frontmatter 里的 `budget` 是"建议值"，代码没有逐技能执行。

### 1.2 17 个技能包

工具数取自 `allowed_operations`。READ 列包含 read、compute、research 和 `skill.load`；T0 列包含规则计算类 T0，如 `build.readiness.compute`；"T2 准"指 T2-prepare-only。

| 技能包 | 版本 | 标题 | 典型触发（preload_when 摘要） | 合计 | READ | T0 | T1 | T2 准 | 代码默认预载 |
|---|---|---|---|---:|---:|---:|---:|---:|---|
| category_framing | 0.2.2-draft | 品类界定 | 点"新建品类"；个人对话要建品类 | 7 | 6 | 0 | 1 | 0 | 无品类时（bootstrap.py:459） |
| public_research | 0.2.2-draft | 公开研究 | 要求搜索；品类进入研究阶段；**AutomationRule 定时更新（需联网）** | 12 | 9 | 3 | 0 | 0 | 否，靠 skill.load |
| proposal_drafting | 0.2.3-draft | 立项提案起草 | 提案页；品类页"立项提案" | 16 | 11 | 2 | 3 | 0 | 有品类无提案/项目时；提案页 |
| rfq_extraction | 0.4.1-draft | 客户需求抽取 | 客户原件上传到私有提案 | 14 | 8 | 3 | 3 | 0 | 提案绑定了已解析的客户原件时 |
| competitor_comparison | 0.2.1-draft | 竞品同口径对比 | 打开对标视图；"和某某比" | 12 | 8 | 3 | 1 | 0 | 否 |
| price_band | 0.2.1-draft | 价格带 | 自主新品定位 | 11 | 8 | 3 | 0 | 0 | 否 |
| review_pain_clustering | 0.2.1-draft | 评论痛点归类 | 导入评论/退货原因文件 | 10 | 7 | 3 | 0 | 0 | 否 |
| jtbd | 0.2.1-draft | 用户要完成的工作 | 补"用户与场景" | 10 | 7 | 3 | 0 | 0 | 否 |
| option_comparison | 0.2.1-draft | 方案对比 | 方案对比视图为空 | 11 | 10 | 1 | 0 | 0 | G0 评审人运行时 |
| opportunity_scoring | 0.2.1-draft | 机会评分与市场规模 | "值不值得做"段落 | 10 | 9 | 1 | 0 | 0 | 否 |
| derivative_diff | 0.2.1-draft | 派生差异 | entry_kind=derivative | 11 | 8 | 1 | 2 | 0 | 否 |
| gap_check | 0.2.1-draft | 缺项与冲突检查 | 提交 G0 前；**来源变更事件** | 12 | 8 | 3 | 1 | 0 | 提案页；G0 评审人运行时 |
| build_execution | 0.1.0-draft | 制造轮次与试模执行 | Builds 入口已选 Build | 25 | 5 | 3 | 14 | 3 | **否（项目运行返回空，bootstrap.py:461-465）** |
| test_verification | 0.1.0-draft | 验证准备、交接与测试 | 验证/测试入口 | 21 | 6 | 3 | 10 | 2 | 否 |
| quality_issue | 0.1.0-draft | 品质问题与 CAPA | 问题入口；测试失败 | 16 | 5 | 2 | 7 | 2 | 否 |
| change_control | 0.1.0-draft | 工程变更穿透与实施 | 变更入口 | 20 | 8 | 4 | 6 | 2 | 否 |
| release_handover | 0.1.0-draft | 放行包与对外移交 | 放行/移交入口 | 12 | 5 | 2 | 0 | 5 | 否 |

共同特征：
- `owner` 全部是"待定"，`budget` 全部是"建议值（待真实模型实测后调整）"。
- 各包的 `evaluation_suite` 都写成 `evaluation-rubric.md#<key>`，这个文件不在 `skill_packages/` 目录下。实际只有 `docs/design/skills-draft/evaluation-rubric.md` 一份草稿，只覆盖 12 个产品线技能。S2–S5 新增的 5 个包没有评分条目。
- 5 个 S2–S5 包在所有租户都没有 `TenantSkillEnablement` 启用行，也没有资格（todo L31，剩余缺口③）。

### 1.3 工具注册表与可见面

- 工具由领域命令登记表自动生成（`agent_kernel/registry.py:187-225`），另加读取、计算、研究工具和 `skill.load`、MCP 入口（`agent_kernel/tools.py`）。截至 10-18 实测：137 个主循环工具、291,811 B；按技能下发后，单次可见 45–62 个工具，占全量 27.9%–45.0%，其中 22 个 T2 准备类必须一直可见（`docs/design/2026-10-17-m2-tool-surface-decision.md` 修订 §1、§3）。
- **读取工具只覆盖立项前对象。** READS 只有 category、proposal、product.baseline、platform、evidence、conversation.history（`tools.py:5-20`）。项目、计划、任务、Build、样件、Issue、TestRun、供应、知识规则都没有读取工具（todo L31，剩余缺口①）。
- **工具描述是模板字符串。** 读取工具是"读取或计算 {name}；范围由服务器运行绑定。"（`tools.py:88`）；写入工具是"办理 {operation}；结果以领域回执为准。"（`registry.py:216`）。M3 占位写工具和 T2 准备工具的 schema 只有 `{"type":"object"}`（`tools.py:120,135`）。模型选工具几乎全靠技能正文里的 note。

### 1.4 T0/T1/T2 如何落到交互

| 档位 | 设计（DC-11 §3、§5；v1.1 §05.6、§05.12.4 B17/B18） | 实现 | 差距 |
|---|---|---|---|
| T0 自动 | 静默完成，带 AI 署名角标，一键撤回；成功不产生待办 | `graph.py:387-421`：T0 要求"技能已加载且 `qualified()`"。`policy.py:71-100` 的 qualified 要求同时满足：试点租户、技能已启用、未暂停、技能/模型/工具三个 digest 都一致、至少 10 个审阅案例。不满足就走 `ports.prepare`，降为候选 | **当前没有任何租户×技能×模型具备资格，所有 T0 实际都以 T1 候选出现** |
| T1 一次确认 | 整批呈现，一次确认；只有存疑条目单独标出；有依赖的组整体确认，独立的组可分别选 | 来源事实候选逐条走"核对并预览此事实 → 确认登记此事实"（`xiaopai.tsx:218-219`）。领域候选逐条弹窗预览、确认（`pai/run-candidates.tsx`）。设计里的 `ConfirmationBatch`（v1.1 §02.11）grep 0 命中 | 没有整批确认。一次运行产出 N 条就要确认 N 次 |
| T2 具名决定 | AI 只准备材料，不取得执行身份 | T2-prepare-only 工具只产出材料。具名决定在对象页办理，例如 `builds/build-start.tsx` 写明"不能由 AI 代签" | 符合设计 |
| 撤回 | 整次撤回或单条撤回；撤回受限时逐条列出原因（B17） | 整次撤回：`ai.run.revert` 先预览再确认（`xiaopai.tsx` 底部），预览只显示"本次包含 N 条结果回执"。单条 Claim 撤回：`preproject/proposal-share.tsx`。对象页有 AI 草稿标记（proposal-document 等） | B17 要求的"按条列出未撤回项与理由"在会话层只做到计数 |
| 用词 | 只用"自动 / 一次确认 / 具名决定" | `pai-conversation.tsx` 的 PaiPolicy 已采用 | 符合设计 |

---

## 2. 输入模态

| 模态 | 设计 | 实现 | 判定与差距 |
|---|---|---|---|
| 文本 | §05.4 自然语言 | 3–8000 字 textarea，发送即建 Run；回复是最终摘要，不流式输出 | 已实现。没有逐字流式，没有跨 Run 的连续气泡线程 |
| 文件 | §07.6：文本、MD、PDF、XLSX、DOCX、PPTX、邮件；确有需要时 OCR | 只收 `.txt/.md/.pdf/.xlsx`，≤8 MiB（`agent_kernel/upload_views.py:69`、`originals.py:31-36`、`evidence_processing/parsers.py:13`）。PDF 只取文本层，没有文字的页标记 `needs_ocr`，不做 OCR（`parsers.py:243-248`）。上传不启动工作，要再到"已登记来源"里手动选上才会随新工作发送。在提案页上传，文件落到型号或品类资料根下，"提案客户输入需另行挂接"（`pai/file-upload.tsx`） | 部分。客户 RFQ 常见的 Word、邮件、扫描 PDF 都用不了；拖入后还要三步才进入工作 |
| 图片/照片 | §05.9 移动端拍照上传、现场情况；§07.6 视觉识别保留区域和不确定性 | 前端 `accept` 只有上述四种；后端没有图片 MIME | 未实现 |
| 语音 | §05.9 音频转写作为候选；设计稿输入区有"语音"按钮 | 无 | 未实现 |
| 会议 | §09.6 S5"会议/周报"；DC-11 §8 第 1 项"纪要/行动/决策草稿 T0" | pdos-next 没有会议对象或技能。原工程的 `server/app/ai/meeting_capability_golden.py` 已归档 | 未实现 |
| 邮件 | §01.4 客户需求输入含邮件；§07.6 邮件原件 | 没有 `.eml` 解析，也没有邮箱连接器 | 未实现 |
| 钉钉 | §07.1"授权钉钉轻入口"；§07.9 钉钉身份通知 | 代码中 DingTalk/钉钉 0 命中 | 未实现 |
| CRM（GoodJob） | §01.4、§08.8 读取 CRM 来源 | 无 | 未实现 |
| CAD/EDA | §07.6 授权版本引用、受控预览 | 工程配置可以登记外部引用（`domain/configurations/service.py:296`）。没有解析、预览，AI 也读不到 | 只能引用 |
| 网页 | §06.6.3 只读本轮搜索结果或用户消息里的 URL | 研究子图隔离，用 SearXNG 适配器（`research/search.py`）；公开 PDF 隔离解析（`research/pdf.py`） | 已实现，只有合成验证 |
| 测试数据 | DC-11 §8 第 5 项：测试报告高置信行 T1 整批确认 | `test.results.import` 是 T1 表单命令。抽取行结构只注册了 `rfq_requirement` 和 `user_voice`（`agent_kernel/extract_schemas.py:190-194`） | 部分。不能从报告原件抽读数 |
| MCP | §06.6.2 | 准入、逐项授权、只读隔离子图都已实现（`mcp_*.py`），但用的是进程内 ASGI、合成模型和合成 KMS（M3 行 mcp-graph 证据） | 骨架。没接任何真实服务 |

补充：**抽取能力实际上只对 RFQ 生效。** `extract_service.py:80-93` 要求行结构由当前已加载的技能声明，否则拒绝（`row_schema_not_declared`）。17 个包里只有 `rfq_extraction.md:5-6` 声明了 `row_schemas`。`review_pain_clustering` 的工具 note 写"row_schema 为用户声音行"，却没有声明；`test_verification` 列了 `evidence.extract`，但根本没有测试读数这种行结构。所以"导入评论文件 → 痛点归类"和"测试报告 → 读数"在现有代码下都会被拒绝。

---

## 3. 主动性

| 能力 | 设计 | 实现 | 判定 |
|---|---|---|---|
| AutomationRule | §06.4：trigger、scope、技能、MCP、预算、冷却、max_runs、版本化、运行历史，权限逐项开关 | 草稿、启用、暂停、版本，四种触发，冷却和次数上限（`domain/automations/rules.py`），服务授权，因果链，Temporal 监督都已建。能力开关被 schema 固定关闭（见 §1.1）。前端 `automation-rules.tsx:18-20,129` 要手填型号/项目/任务 UUID、带时区的 ISO 时点、间隔秒数、token 上限 | 骨架。业务价值为零，配置门槛高 |
| 自然语言建规则 | 设计未写；DC-11 §8 的周报和事件建单都隐含这个需求 | `ai.automation.draft.save` 在 auxiliary-operations 里登记为 T0，但 executor 是 `named_human`，没有任何技能包含它，小Pai 无起草入口 | 未实现 |
| 注意队列 | §02.11：只读聚合，不产生第二份待办 | `personal_attention*.py`：要我决定、要我接收、要我验证、等外部回复，加"我作出的承诺"，纯规则投影（S5 注意项合同）。"我的工作"会显示暂停的运行（`my-work.tsx:93`） | 已实现，但没有 AI 维度 |
| AI 例外队列 | DC-11 §5 第 2–3 条："AI 需要你"例外，"我的工作"计数改为"AI 例外" | 等待确认的 T1 候选只活在运行线程里，不进"我的工作"；没有"置信不足/来源冲突/连续失败"这类例外分类 | 未实现 |
| 事件 → 自动建 Issue | §06.5 T0 例子；DC-11 §8 第 2 项 | `quality.issue.create` 在 quality_issue 技能里是 T0，但自动化 Run 被禁写，导入类事件又被抑制 | 未实现 |
| 周报 / 状态更新草稿 | §05.3"写状态更新"；附录 A `work.status_update.create` T1，注明"AI 可起草"；DC-11 §8 第 4 项周报初稿 T0 | 这个命令不在任何技能里。项目上下文只有 4 个字段（`context-schemas.json` 的 `$defs.project`） | 未实现 |
| "说情况"登记外部承诺 | §05.5"供应商说周五才能到样"会建立外部承诺候选 | `work.external_wait.record`、`supply.commitment.record` 是 T0，但都不在任何技能里 | 未实现 |
| 来源变化触发查漏 | gap_check 的 `preload_when` | 预载不消费事件；自动化只读 | 未实现 |
| 效果复查 | §06.13：按 outcome_spec 跟进，直到真实结果 | 只有 `WorkRequest.outcome_spec` 字段（`models.py:347`），没有复查逻辑。建 Run 的 API 只收 goal 和 sources | 未实现 |

DC-11 §8 首批切换清单列了 5 项：会议纪要草稿、事件自动建单、摘要/状态字段维护、周报初稿、测试报告整批确认。**在 pdos-next 里 5 项都不可用。** DC-11 §10 的北极星看板"本周 AI 替你完成 X 项，你只处理了 Y 项例外"也不存在。

---

## 4. Memory 与学习

| 层（v1.1 §06.8） | 实现 | 判定 |
|---|---|---|
| 当前工作短记忆 | `agent_kernel/conversation.py` 从已链接的 Run 重建私有任务记忆（目标、未完成项、可核对的历史摘要）；同一会话内复用研究来源池（M3 run-continuation 证据）；同一会话共用一个 LangGraph 线程（session-thread 证据） | 已实现，只有合成验证 |
| 个人偏好 | 无表、无代码 | 未实现 |
| 项目事实摘要 | 项目上下文只投影 id/name/revision/visibility | 未实现 |
| 产品/平台经验 | `domain/knowledge/` 已有"经验候选 → 适用性评估 → T2 发布规则"（S5 knowledge 证据），但小Pai 没有读取规则的工具（`tools.py` 的 READS 里没有），也没有技能引用 `knowledge.candidate.create` 或规则 | 人工链有，没回流到 AI |
| 企业正式规则 | 同上 | 未接入 AI |
| golden-case / 评测 | pdos-next 没有 golden runner，也没有案例包。评分规则草稿在 `docs/design/skills-draft/evaluation-rubric.md`（12 个技能、案例格式和最少数量）。资格审阅的后端（`agent_kernel/skill_qualification.py`）和前端（`model_configuration/skill-qualification.tsx`）都齐了，但没有真实运行可以审 | 链路空转 |
| 运行反馈 | `run_feedback.py` 六类：wrong_object、wrong_value、missing_source、not_useful、too_many_actions、should_not_automate，绑定技能和模型版本；明确"不进入模型上下文"。评分规则 §7 要求反馈进入调试集候选，但没有对应管道 | 有采集，无学习闭环 |

---

## 5. 检索与知识

- **品类知识**：有 `category.knowledge.list`、`category.competitors.list`、`category.parameters.list` 三个读取工具；`category.knowledge.add` 是 T0，promote 和 withdraw 是 T1。这部分完整。
- **evidence.search**：只在本次 Run 显式绑定的来源里，按**标题子串**做大小写无关的匹配，只返回元数据（`agent_kernel/domain_reads.py:315-329`）。
- **跨项目检索**：没有。v1.1 §07.7 的混合检索（精确 ID → 全文/向量 → 重排 → 引用验证）没有实现，tsvector 和 embedding 都是 0 命中。"以前类似失效怎么处理的""同平台别的型号认证过哪些项"都答不了。
- **企业搜索**：⌘K 对象查找（`personal_search.py`）给人用，按名称或 ID 查项目、型号、提案、品类；小Pai 调不了。
- **公开研究**：fanout 并行子任务、逐字台账、由代码生成的覆盖与失败说明、快照 T0 登记都已实现，合成验证通过（M3 行 research-host、research-projection、research-restart）。只有 SearXNG 一个后端，§07.7 写的"Tavily → Firecrawl → SearXNG 按序回退"没实现。**真实网络没有验收过**（M3 行："未做研究中途进程重启或真实网络验收"）。京东、天猫、1688、Amazon 评论页能不能抓到，也未验证。
- **不可信内容隔离**：extract、research、mcp 三个子图都只把核对过的行交回主循环，做得扎实。有一处遗留：技能正文和服务器上下文是以 `role: "user"` 注入的（`graph.py:209-211`），操作者指令和用户输入走同一通道。工具面决策稿 §3 B 已经指出这一点，计划在 B 路线迁到 system 通道。

---

## 6. 可观测与信任

| 项 | 实现 | 差距 |
|---|---|---|
| 运行与行动回执 | Run、ActionReceipt、Audit、Outbox 同一事务；回执记录技能、模型、工具版本组合；出站回执记录服务商和类别（P26） | 无 |
| 过程面板 | `agent_kernel/process_view.py` 加 `pai/run-process.tsx`：实际步骤、绑定依据、提交回执、历时；不显示模型原文和推理 | 符合 §05.4、§06.14 |
| 引用 | verify 节点逐字核对；研究计数从工具结果复制，不用模型报的数（`research_result.py`、`verification.py`） | 无 |
| 成本 | 价格卡 `pricing.py`、预算钱包 T1 `budget_management.py`、逐次结算；设置页显示用量 | 运行详情不显示本次费用，process_view 只有 `elapsed_seconds`（`process_view.py:141`）。§05.3 写的是"AI 工作详情：…行动回执和费用"；B18 只禁止显示 token |
| 时延 | 只有历时 | 前端每 3 秒轮询一次（`xiaopai.tsx:132`）。后端已有 SSE 过程流（`agent_kernel/api.py:481`），前端没用；没有逐字输出 |
| 失败可见 | 模型不可用会发 `model_unavailable` 事件；结果未知记 `EXTERNAL_OUTCOME_UNKNOWN`，有对账出口（`run_reconciliation.py`）；`partial` 状态保留已完成的部分；界面显示"原调用结果待核对" | 无 |
| 结果呈现 | 先给摘要，再在"查看实际结果与回执"里直接展开原始 JSON（`xiaopai.tsx:217`）；直接显示"运行 {run_id}" UUID（`xiaopai.tsx:207`）；上传详情显示 SHA256 和请求摘要 | 与 §05.1"前台不展示内部架构"相冲突，业务用户的认知负担很高 |
| 反馈 | 六类可定位反馈 | 不进评测 |

---

## 7. 真实状态

| 事实 | 依据 |
|---|---|
| **真实模型调用只有 2 次**，都是 2026-10-19 的手工网关探针：1 次没有引导提示，结果未知，按估算结算；1 次成功（456 输入 / 71 输出 / 128 缓存命中，4.8 秒，结构化结果 `{"ok": true}`，201 微美元）。没有走注册 LangGraph 图，没有多轮工具调用，没有真实业务内容 | todo L86；`docs/runbooks/minimax-cn-m3-validation-draft.md` 的"2026-10-19 首次真实调用结果"（"未覆盖：设置页 T1 启用链、真实业务资料、多轮工具调用链…"） |
| MiniMax M3 行为边界：探针必须在系统提示里指示调用 `pdos_agent_output` 收尾，否则纯文本作答会被判无效。注册图的冻结提示词自带这条约束，但没有用真实模型验证过 | 同上；`providers/agent_wire.py:17` |
| **状态源已经漂移**：M2 行仍写"106 个注册工具、12 个技能包…真实模型调用 0 次"，M3 行写"真实模型调用0次"；L31 记录的是 137 个工具、17 个技能包，L86 记录了首次真实调用 | todo L17、L18、L31、L86 |
| 资格为 0：没有任何租户×技能×模型的 T0 资格；5 个新包没有启用行；验收环境的试点准入行注明 "Local acceptance environment only; no pilot qualification" | todo L31 ③、L67 |
| 只有合成验证的部分：注册图端到端、Worker 重启续接、研究宿主（7 次合成模型调用，840 微美元）、MCP（进程内 ASGI）、MiniMax 协议（合成 HTTP/SSE）、提案内委派（"模型调用 0"）、项目运行（"真实模型调用为 0"） | M3 行 tenant-host、research-host、research-restart、mcp-graph、minimax-wire、proposal-pai；`docs/reports/evidence/pdos-next-s5-20261018/project-run-context/result.md` |
| 未做：真实网络研究、真实 MCP、真实外发、评测集与 rubric 条目、性能验收（P13 暂缓） | todo L31 ④、M3 行 |
| **建设顺序偏离**：v1.1 §09.6 把"真实模型接入"列为 S1 交付，并要求"不按…再接AI"。S1 至今未验收，S2–S5 的领域与 UI 已经推进很多 | v1.1 §09.6 表；todo M3、M6–M9 行 |

---

## 8. AI-native 体验短板候选

按影响排序。P0 直接决定"像不像 AI-native"，P1 是主要功能缺口，P2 是体验和长期风险。

### P0

**G1 真实模型从未完整跑通一次小Pai 工作**
- 位置：todo L86、L17–18；v1.1 §09.6；技能的 `model_capability_requirements`（如 `proposal_drafting.md:153` 要求原生工具调用、JSON schema 输出、只读并行调用、≥64k 上下文）。
- 为何怀疑：所有 AI 能力的证据都来自合成模型。MiniMax M3 面对 45–62 个可见工具、模板化描述、逐字引文和单位/工况约束时，能否正确选工具、遵守 schema，完全未知。一旦不达标，就要回头重做技能和工具面。
- 方向：先用路径 A 的合成案例走一次"真实 M3 + 注册图 + 一次确认"闭环，记录选错工具、参数错误、轮次和费用，作为后续所有 AI 设计的基线。

**G2 T0 实际永远降为 T1，T1 又要逐条确认，与"静默成功、人只处理例外"正好相反**
- 位置：`graph.py:387-421`；`policy.py:71-100`；`xiaopai.tsx:218-219`；`pai/run-candidates.tsx`；DC-11 §1、§5；v1.1 §05.11"不把AI成功转成人工审批负担"；§02.11 的 ConfirmationBatch（未实现）。
- 为何怀疑：资格依赖真实运行的审阅案例，而真实运行是 0，所以 T0 没有进入的路径。一次 RFQ 抽取会产出几十条 Claim 和条目补丁，用户要逐条"预览 → 确认"，比手工录入还累。
- 方向：一是补 ConfirmationBatch 整批确认（独立组可勾选，存疑条目单列）；二是让试点资格审阅尽早能跑起来（依赖 G1）。

**G3 主动执行只有骨架：规则只读、不联网、不写、不接 MCP 和外部事件**
- 位置：`domain/automations/schemas.py:110-145`；`execution.py:68-69`；`service_runtime.py:234-287`；v1.1 §01.7"主动执行"、§06.4；`public_research.md` 的 `preload_when`（"AutomationRule 定时更新，需规则授权联网"）；设计稿里的"竞品价格周跟踪"。
- 为何怀疑：v1.1 的三种体验之一实际不可用，规则最多读一读、写个总结。设计稿承诺的后台委托做不出来。
- 方向：按 §06.4 的"逐项开关"放开"只写触发对象"的 T0 草稿写入，以及联网研究；外部来源触发继续默认关闭。

**G4 项目侧小Pai 近乎失明**
- 位置：`tools.py:5-20`（READS 没有项目/Build/Issue/TestRun/计划/任务）；`context-schemas.json` 的 `$defs.project`（只有 4 个字段）；`bootstrap.py:461-465`（项目运行预载为空）；todo L31 剩余缺口①（"id 与 expected_*_revision 只能由页面、触发对象或用户消息给出"）。
- 为何怀疑：P15 已把主干改为项目管理，大部分岗位从项目入口打开小Pai。5 个 S2–S5 技能合计 94 条工具授权（含读取），但读不到对象，模型只能等用户粘贴 UUID 和版本号。
- 方向：补项目、Build、Issue、TestRun、计划、任务的只读端口，扩展项目上下文投影（阶段、下一门禁、阻塞、承诺），并按页面对象预载对应技能。

**G5 日常工作命令没有技能，"说情况""写状态更新""建任务"都不能交给小Pai**
- 位置：`contracts/operations.json` 中 T0 的 `work.task.create`、`work.plan.propose`、`work.forecast.refresh`、`work.external_wait.record`、`supply.commitment.record`、`knowledge.candidate.create`、`evidence.artifact.register`，T1 的 `work.status_update.create`，以及 auxiliary 里 T0 的 `field.feedback.create`（executor 为 qualified_authorized_actor）、`ai.automation.draft.save`（executor 为 named_human）——全部不在任何技能里；todo L31 ②；v1.1 §05.5、附录 A `work.status_update.create`。
- 为何怀疑：对工程师和 PM 来说，最高频的 AI-native 期待正是"一句话登记""帮我写周报"，这一层恰好是空的。
- 方向：新增 `project_followup`（或 `daily_work`）技能，覆盖外部等待、承诺、任务、状态更新草稿、现场反馈登记。

**G6 DC-11 首批切换清单 5/5 不可用，北极星看板缺失**
- 位置：DC-11 §8、§10。
- 为何怀疑：DC-11 是用户当初对"AI 帮我减负"最具体的表述，pdos-next 没有承接（会议纪要、事件建单、状态字段、周报、测试报告整批确认）。v1.1 附录 B 的验收场景也没有逐项对照这 5 项。
- 方向：把这 5 项映射到 S2–S5 的验收场景，并确认要不要保留。

### P1

**G7 输入模态窄，上传路径长**
- 位置：`upload_views.py:69`；`originals.py:31-36`；`parsers.py:13, 243-248`；`pai/file-upload.tsx`（"上传不启动工作…发送只使用已登记来源中手选的资料"）；v1.1 §07.6、§05.5"拖文件：先显示上传/解析状态…再以可操作候选呈现"、§05.9。
- 为何怀疑：OEM/ODM 客户的 RFQ 多是 Word、邮件或扫描件；现场品质靠照片。拖入文件后还要"本人确认上传 → 刷新来源 → 手选 → 发送"。在提案页上传还要另行挂接。
- 方向：补 DOCX、EML、OCR、图片；拖入即绑定当前 Run 来源，提案页直接挂到提案。

**G8 抽取只对 RFQ 生效**
- 位置：`extract_schemas.py:190-194`；`extract_service.py:80-93`；`review_pain_clustering.md`（有 `evidence.extract` 但没有 `row_schemas`）；`test_verification.md`。
- 为何怀疑：评论痛点、测试读数这两个高价值场景按现有代码会被拒绝。技能写了做什么，代码却不支持。
- 方向：给评论痛点归类补 `user_voice` 行声明，新增测试读数行结构。

**G9 检索与经验回流断链**
- 位置：`domain_reads.py:315-329`；v1.1 §07.7、§06.8 经验晋升；`domain/knowledge/models.py`（已发布规则）；`tools.py` 的 READS。
- 为何怀疑：PDOS 想成为"企业研发记忆"，可是 AI 既检索不到历史问题和变更，也读不到已发布的设计规则。用户最期待的"以前怎么做的"无从回答。
- 方向：先给规则和已关闭 Issue/CAPA 做全文检索（带 ACL 前置过滤）；再给小Pai 加 `knowledge.rules.search` 读取工具。

**G10 对话体验不是"对话式 agent"**
- 位置：`xiaopai.tsx:132`（3 秒轮询）、`:207`（显示 UUID）、`:217`（原始 JSON）、`:243-244`（"@ 对象"只能勾选当前型号）；设计稿 10-16 的"@ 对象、/ 技能、附件、语音与建议动作""消息级动作（复制/重跑/运行详情）"；v1.1 §05.12.4 B13（范围可改）、B14（@ 对象进入 ContextSnapshot）、B16（重跑）；§06.9 SSE。
- 为何怀疑：用户 10-16 明确要"像 claude、chatgpt 一样"。现在每条消息都是一个独立 Run，线程只显示当前 Run，没有逐字流式，没有可交互的结果卡片。
- 方向：会话线程按同会话 Run 链连续渲染，接上已有的 SSE；结果用结构化卡片呈现（写入了什么、去对象页、撤回）；补 `/技能` 和 `@对象`。

**G11 工具描述与 schema 质量**
- 位置：`tools.py:88,120,135`；`registry.py:214-216`；工具面决策稿修订 §1–§3（可见面 45–62 个工具，其中 22 个 T2 准备类）。
- 为何怀疑：工具描述只有"办理 X"，模型几乎只能看工具名；占位工具的 schema 是 `{"type":"object"}`。国内模型在工具很多、描述很弱时容易选错。
- 方向：从操作登记表生成真实的中文描述和示例；评估零技能时把 T2 准备类收进技能（决策稿修订 §4，可从 27.9% 压到 9.2%，属于设计变更，需要用户决策）。

**G12 预载规则粗、`preload_when` 只是文字**
- 位置：`bootstrap.py:453-511`；grep `preload_when` 在代码里 0 命中；v1.1 §06.3.3"服务器根据当前页面、对象、会话范围或触发事件，在第一轮附上相关技能"。
- 为何怀疑：打开 Build 页问"这批样件去哪了"，不会预载 build_execution，只能靠模型自己调 `skill.load`。
- 方向：把 `preload_when` 改成机器可判的条件（页面、对象类型、事件），由服务器判定。

**G13 评测、资格与效果复查都在空转**
- 位置：`agent_kernel/skill_qualification.py`；`docs/design/skills-draft/evaluation-rubric.md`（不含 S2–S5 的 5 个包）；各技能 `evaluation_suite` 的引用路径不存在；`run_feedback.py`；`models.py:347` 的 outcome_spec；v1.1 §06.12–06.13、§09.4。
- 为何怀疑：资格审批的界面做好了，但没有案例包和跑批器，用户本人"审 10–20 个案例"这条试点路径走不起来。T0 开不了，又回到 G2。
- 方向：建两个品类各约 20 个合成案例包（rubric §5.4 已设计），做 nightly 跑批，并把反馈接入调试集。

**G14 自动化规则配置面向工程师**
- 位置：`automation-rules.tsx:18-20,129`（手填 UUID、ISO 时点、间隔秒数、token 上限）；`ai.automation.draft.save` 的 executor 是 `named_human`，没有技能。
- 为何怀疑：AI-native 的预期是"跟小Pai 说一句，每周一提醒我"。
- 方向：由小Pai 起草规则草稿（T0），人一次确认启用（T1）。

### P2

**G15 注意队列没有 AI 维度**
- 位置：`personal_attention*.py`；`my-work.tsx:93`；DC-11 §5 第 2–3 条。
- 为何怀疑：待确认候选和 AI 例外不进"我的工作"，用户关掉侧栏就忘了。
- 方向：补"小Pai 等你确认 N 项"和 AI 例外两类，作为只读投影。

**G16 成本和首字时延不可见**
- 位置：`process_view.py:141`；v1.1 §05.3（AI 工作详情含费用）、§07.10。
- 方向：运行详情显示本次费用和所用模型；接入流式输出以缩短首字时间。

**G17 界面暴露内部标识，认知负担重**
- 位置：`xiaopai.tsx:207`；`pai/file-upload.tsx` 的"回执与固定标识"；自动化表单。
- 依据：v1.1 §05.1。
- 方向：业务视图只显示对象名称和版本，UUID 收进"技术详情"。

**G18 协同通道空白：钉钉、CRM、邮件**
- 位置：v1.1 §07.1、§07.9；grep 0 命中。
- 为何怀疑：用户每天在钉钉里协同，PDOS 只有 Web 入口，AI 的结果和提醒到不了用户手边。
- 方向：先做钉钉的通知和待办深链（只读、回到原对象），再考虑在钉钉里直接收发小Pai 消息。

**G19 公开研究后端单一，未用真实网络验收**
- 位置：`research/search.py`（只有 SearXNG）；v1.1 §07.7 的回退链；M3 行 research-host。
- 为何怀疑：竞品价格、评论来自京东、天猫、Amazon 等站点，反爬和登录墙会让台账大面积变成 `unavailable`。
- 方向：用真实网络对两个品类各跑一次研究，测覆盖率；评估商用搜索和读取服务，接入要按 P26 记录出站回执。

**G20 工具面随领域增长；MiniMax 缓存未测**
- 位置：工具面决策稿 §1、修订 §2、§5（9 天 +36%，10 天 +74%；执行类技能组 43–66 KB；OpenAI 兼容分支没有缓存断点）。
- 方向：用真实 M3 测量 `count_tokens`、缓存命中率和误选率之后，再决定 B、C 路线。

**G21 会话模式缺失**
- 位置：工具面决策稿修订 §5（用户 10-18 提出"角色权限 vs 会话模式，后者在代码中完全缺失"）。
- 为何怀疑：用户想有"只问不写"之类的安全模式，好放心地探索。
- 方向：增加会话级"只读/可起草"模式，作为服务器事实收窄工具披露。

**G22 建设顺序与 §09.6 冲突**
- 位置：v1.1 §09.6；todo M3、M6–M9 行。
- 为何怀疑：领域和界面已经铺到 S5，AI 的真实能力还停在 S1 之前。G1–G5 每补一项，都可能连带要改已建的领域读取端口和界面。
- 方向：下一个闭环把"真实模型 + 一个项目侧技能"一起作为出口条件。

---

## 9. 竞品参照（仅供方向参考，待竞品组核实）

以下基于截至 2026 年中的公开资料的一般认知，本组未逐条核实。

| 能力 | 常见竞品做法 | PDOS 现状 |
|---|---|---|
| 自然语言建自动化 | Asana AI Studio、Notion Agents 一类：用一句话定义触发、动作和 AI 步骤 | 规则表单要手填 UUID，规则只读（G3、G14） |
| 智能分诊 | Linear Triage 一类：重复检测，建议负责人和标签 | 注意队列纯规则，没有 AI 建议（G15） |
| 状态更新/周报 | Asana、Jira、Linear 一类：基于项目活动生成更新草稿 | 无技能（G5） |
| 会议纪要 → 行动项 | 飞书妙记、钉钉听记、Notion AI Meeting Notes | 未实现（§2 会议行） |
| 企业搜索/跨工具问答 | Atlassian Rovo、Notion 企业搜索、Glean 一类 | 只有标题子串匹配（G9） |
| IM 内入口 | Slack/钉钉机器人、Linear Asks 一类：在 IM 里收集需求、推送待办 | 无（G18） |
| PLM/QMS AI | 主流 PLM/QMS 厂商集中在变更影响分析、相似问题检索、文档问答和合规条款抽取 | 变更影响是确定性计算（强项）；相似问题检索和文档问答缺失 |

**PDOS 相对竞品的差异化强项**（应保留）：服务器绑定范围、逐字可核对的引用、署名 AI 加整次撤回、隔离读取不可信内容、回执与对账、"未知不补造"的数据语义、确定性引擎独占准备度和覆盖率等结论。差距不在安全面，而在**价值面的覆盖与交互成本**。

---

## 附：主要证据位置

- 设计：`docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md`（§05 L762–919；§06 L926–1108；§07.6–07.10 L1184–1226；§09.4–09.6 L1455–1486）；`docs/design/2026-09-20-ai-direct-write-tier-policy.md`（§3 L26、§5 L43、§6 L50、§8 L62、§10 L78）；`docs/design/2026-10-17-m2-tool-surface-decision.md`（含 10-18 修订）；`docs/design/2026-10-08-m2-skill-tool-delivery-proposal.md`；`docs/design/skills-draft/evaluation-rubric.md`。
- 状态：`tasks/ai-native-integrated-todo.md` L17（M2）、L18（M3）、L22（M9）、L31（S2–S5 技能包）、L67（试点准入）、L84（P26）、L86（MiniMax 首次真实调用）；`docs/runbooks/minimax-cn-m3-validation-draft.md`。
- 代码：`pdos-next/server/pdos_next/agent_kernel/{graph.py, tools.py, registry.py, policy.py, bootstrap.py, execution.py, domain_reads.py, extract_service.py, extract_schemas.py, conversation.py, process_view.py, run_feedback.py, upload_views.py, api.py}`；`pdos-next/server/pdos_next/domain/automations/{schemas.py, service_runtime.py, rules.py}`；`pdos-next/server/pdos_next/workflows/automation.py`；`pdos-next/server/pdos_next/evidence_processing/parsers.py`；`pdos-next/server/pdos_next/originals.py`；`pdos-next/server/pdos_next/research/search.py`；`pdos-next/server/pdos_next/skill_packages/*.md`、`context-schemas.json`；`pdos-next/contracts/operations.json`、`auxiliary-operations.json`；前端 `pdos-next/web/src/components/{xiaopai.tsx, pai-rail.tsx, pai-conversation.tsx, automation-rules.tsx, my-work.tsx, pai/*.tsx, preproject/proposal-pai.tsx}`。
