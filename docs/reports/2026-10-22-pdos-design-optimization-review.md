# PDOS 设计优化空间综合审查（修订版）

2026-10-22 · 只读审查：只新增本报告和证据目录，没有改动其他文件，也没有运行任何服务或测试。

**快照**：代码以 HEAD `f341d1fe`（10-22 09:19）加当时工作树为准。第一阶段报告是 03:2x 的快照，此后的变化已并入：`0efed69f`（05:01，项目工作区与持久会话，web/src 新增约 1.5 万行，已提交）；S1 最小切片关闭（P27）；五个项目结构读取工具（08:08）和 `work_management` 技能包（08:49）。后两项未提交、未启用，也没有真实模型运行。“在途”栏据此标注。

**口径**：6 个视角共提出 80 条发现，合并为 F01–F45。每条都经两名核查员反驳：一名查设计或代码里是否已经覆盖，一名查业务价值、与已定决策是否冲突。核查结果为部分覆盖 30 条、设计有但未实现 13 条、设计缺失 2 条；没有整条被淘汰，被砍掉的子方案见 §9。两人的结论逐条记在 [verified-all.json](evidence/pdos-next-design-review-20261022/verified-all.json)，第一阶段的 8 份调研报告在同一目录。F46–F53 是复审阶段补入的，已对照原文或代码。主会话又抽查了 P27、S1 起草证据、认证/客户专业变更死锁、`preload_when` 无消费方、`model_available` 写死、只有本机合成登录这几条，均属实。竞品数字只作方向参考。

**卡片抬头**依次为：级别｜类型｜决策｜改 v1.1｜在途。类型：缺失＝v1.1 未设计；未实现＝有设计、无代码；部分＝部分覆盖。需DR＝需要你新写决策记录。附A/附B/正文＝要补改 v1.1 的附录 A 操作、附录 B 场景或正文。

**编号**：P/K/C＝确认稿决策（K2 立项前只交提案；K3 三个入口；K7 单一小Pai；C8 本人审阅取得资格；P17 健康度纯规则；P18 状态更新须确认；P19 我的工作分五组；P21 S3–S5 自动续工；P26 协议可选；P27 试点可由本人做 G0 评审，取代 P24）。I＝v1.1 不变量（I08 四时间分开；I23 AI 署名、可撤回）。AT＝附录 B 场景。B14/B17/B18＝10-17 界面补遗（告知携带内容；撤回时列出未撤回项；不显示 token）。B3a/D6＝10-07 执行计划的待定项（生产 Temporal 形态、研究时延）。M2 稿＝`docs/design/2026-10-17-m2-tool-surface-decision.md`。`srv/`＝`pdos-next/server/pdos_next/`，`web/`＝`pdos-next/web/src/`。

---

## 1. 总判断

**一句话：v1.1 的方向和边界成立，但操作层不完整。53 条中有 13 条要补改 v1.1 正文或附录 A/B。与冻结设计有张力的 6 处建议，2 处已改回设计口径（F15①、F14④），4 处交你定（§10 #1、#2、#16、#17）。优化空间集中在四处：实现加严了录入门槛；项目主干缺 NPI 骨架和冻结点；派生和品质两条主线断在最后一段；AI 和真人都还没真正接进来。**

1. 分类：缺失 4 条（F19、F21、F48、F51），未实现 16 条，部分覆盖 33 条；待你拍板 18 项。
2. 录入门槛：三处实现比 v1.1 更严，即日常动作强制引用原件（F15）、交样逐项写原因并手填时区（F29）、测试只收 JSONL（F28）。
3. 项目主干：阶段模板、门禁、冻结点和 G1 都没有命令（F14），预测刷新也没实现（F51③）。健康度、下一门禁和组合视图（F52）因此都缺输入。
4. 两条主线断尾：派生迭代拿不到已发布的父版（F46）；“失败→问题→CAPA→有效性→关闭”缺有效性决定（F47）。
5. AI-native 只做到“能起草一段”：S1 切片第一次经注册图真实起草成功（3 次调用，约 43 秒）。项目侧读取和 work_management 在途；项目运行不预载技能（F49）；公开研究从未用真实网络验收（F53）；评测集为零；非管理员调不动模型（F07）。
6. 多人试点的硬前置：登录、成员页和常驻环境（F38/F39），另外要核对 3 人能否满足独立性约束（F50）。

---

## 2. 立即修复的缺陷（工作量 S）

| 缺陷 | 位置 | 影响 | 修法 |
|---|---|---|---|
| 带认证或客户专业的变更永远批不了（**阻塞**） | `srv/change_selection_service.py:221-226`；`srv/domain/professional_authority/schemas.py:40` 角色只有 engineering/quality/manufacturing/knowledge | S3 这类变更死锁 | 先返回明确的“暂不支持”；角色口径见 §10 #6 |
| change.close、effectivity.record、verification.record 无技能声明 | `tests/agent_kernel/test_m3_skill_contracts.py:158`（10-22 内核回归唯一真实失败） | 小Pai 办不了变更收尾 | change_control 补声明 |
| 前端文案与 P26 相反 | `web/components/model_configuration/provider-agreements.tsx:139`、`mcp-management.tsx:134`；v1.1 L30、L1416、L1481、L1519、L1535、L1606 的旧措辞 | 误以为未签约就不能出站 | 改文案，同步 v1.1 |
| 契约标记失真 | `operations.json` 把 provider.agreement.register、my_work.query 标为未实现；`srv/api.py:453` 的 model_available 写死 False | 状态看板失真 | 改标记，健康端点读真实配置 |
| 本人自评的 G0 不进“要我决定”（一致性，不阻塞） | `srv/personal_attention_decisions.py:106` | 只影响显示，提案页已能办理（回执 325a1235） | 试点租户按 P27 放行 |

---

## 3. 最先要做的事（P0）

按价值兑现排序。前四项不需要决策；第五项本期只写决策记录，实施放在 1–2 个月内。

**① F15 日常录入松绑**　P0｜部分（S5 合同比 v1.1 严）｜—｜—｜work_management 受同一约束
- 现状：任务、承诺、状态更新和外部等待都只接受原件引用（`kind=artifact`），已固化进触发器和 CHECK。前端只给 JSON 框，每个动作必填理由。v1.1 §03.4–03.6、附录 A、P18 均无此要求。
- 先做：①人工发起的 task.create/assign/accept/start、commitment.accept、status_update.create、external_wait.record，允许以“本人陈述、本轮消息、运行回执”作为来源（`SourceRef` 已有 domain、command 两种 kind），标 `time_basis=human_recorded`，界面显示“对方声称（本人记录）”。**来源要求不取消**：§05.5 L833 要求先建有来源的外部承诺候选，§03.3 L522 要求状态迁移受来源有效性约束。②小Pai 的写入以该轮消息或回执为来源，保留署名和撤回（I23）。③理由只在退回、拒绝、转交、撤回、替代时必填。④JSON 框改为“从项目资料选择”。⑤S5 合同第 5 行改回 v1.1 口径。
- 位置：`srv/domain/work_management/schemas.py:42-67,113,178`、`g0_storage.py:26-30`；`srv/schemas/verification/contracts.py:38`；`web/components/projects/project-work.tsx:127`；`docs/design/2026-10-18-pdos-next-s5-project-work-contract.md:5`。

**② F07 让非管理员用上小Pai**　P0｜部分｜—｜—｜—
- 现状：预算只能由管理员给自己建；配了价格卡后，非管理员会被报“未绑定可用的本人预算”。运行详情不显示费用，价格卡只收 USD。钱包每人一份，所以不存在“几条规则耗光全员额度”。
- 先做：管理员可为指定成员办理预算，一次确认，回执记录分配人，不建租户总池；运行详情显示“本次约 ¥x · 模型 · 用时”，不显示 token。后做：人民币价格卡、用量视图和 80%/100% 注意项。
- 位置：`srv/agent_kernel/budget_management.py:54-58`、`persistence.py:375-381`、`pricing.py:27,43`。

**③ F29 交样接收做轻＋F28 测试结果可导入**　P0｜未实现（F29 比 §04.7 严）｜—｜—｜—
- F29 现状：每个交接动作、每个“样件×测试项”都要写原因、附原文依据，每个事件手填时间和 IANA 时区。§04.7 只要求退回和部分接收时写原因。
- F29 先做：时点默认“现在”，时区取租户设置，原文依据可选；整批接收一次 T1，只有例外行要填原因；服务器比对交样清单与验证请求的数量、Lot、模穴、配置，列出不符项。后做：照片作原件、移动 Web、按样件号定位。
- F28 现状：只收规范 JSONL，页面不能录读数。失败测量自动建 Issue 并去重已实现。
- F28 先做：一个品类、一个模板的 XLSX/CSV 确定性导入。保存列映射，由服务器从原件派生 JSONL，每行回链到单元格；方法和设备默认取 TestPlan；高置信行整批 T1，不符行单列。可从标签 `original-final-2026-10-08` 取回 `test_report_workbook.py`（307 行）改写，取回前先补进确认稿 §5 的复用清单。实验室 PDF 只挂原件。
- 位置：`srv/domain/verification_handoff/schemas.py:17-35`、`web/components/builds/build-handoff.tsx:29,153-155`、`srv/domain/measurement_evidence/verifier.py:33-44`、`srv/agent_kernel/extract_service.py:59-62`。

**④ F01＋F08 真实基线与最小资格集**　P0｜未实现｜—（⑥需DR）｜—｜—
- 为什么：S2–S5 的 94 条工具授权建在没被真实模型检验过的工具面上（单技能可见 45–62 个、81–131 KB）；要返工的是技能和工具描述，不是领域后端。
- 现状：10-22 切片走通了 HTTP→Temporal→注册 LangGraph→MiniMax-M3，7 次调用合计 $0.139。公开研究、gap_check 多轮、取消与重启都还没跑过。`acceptance.json` 的 63 条全是 definition_only，其中 32 条标 s1_first_loop；AT-57 还是 P26 之前的文本。
- 先做：①汽车充气泵品类经注册图真实运行 ≥10 次，覆盖公开研究（含 F53 可达率）、起草、gap_check，取消和重启各 1 次；由代码记录轮数、时延、费用、误选工具、schema 首次通过率，以及未知是否保持未知。②rfq_extraction 资格集 10 例，两个品类各 ≥4 例，含缺单位、否定与例外、原件注入；参考要点由你签名，作为可信根只读保存。③跑批器做成 CLI，技能包或模型变化时才跑。④占位工具补 schema，未实现命令移出注册表。⑤从 v1.1 重新派生 acceptance.json，32 个场景逐条标状态。⑥**（需DR，属加严）**是否要求技能包“先跑基线再启用”：v1.1 §06.12 只对 T0 要求资格，P27 也已经为演示租户启用了两个技能，所以推荐只作建议、不设闸门。冻结前缀加上 F10 那句护栏。
- 位置：`v1.1` §06.12、§09.4；`docs/design/skills-draft/evaluation-rubric.md` §5.4；`docs/reports/evidence/pdos-next-s1-20261022/result.md`。

**⑤ F14 NPI 骨架：阶段模板、门禁、冻结点、G1**　P0（本期写决策记录）｜部分｜需DR｜附A、附B｜—
- 现状：v1.1 有 StageInstance、模板、FreezePoint 的概念，G1 有 `work.baseline.approve`（未实现）。但这些对象不在 §02.1 对象表里，附录 A 没有门禁和冻结点命令，附录 B 没有场景，代码里也没有。项目列表的阶段列全是“待提供”。CEHub 清单（14 个 scenario、325 类交付、687 条 checkItems）也没接入。
- 先做：①默认“消费电子精简 NPI”模板：概念与计划（出口 G1）→EVT→DVT→PVT→MP。OEM/ODM 按 CEHub 的 jdm/obt 改写前段，并加“客户签样”关口。每阶段 3–6 条硬出口规则（规则 id 带版本），其余 checkItems 进技能包，由小Pai 提示可能缺的交付，不作硬阻塞。②G0 建项目时挂模板，只显示阶段位置。③新增一条 T2 `stage.gate.decide`（通过/有条件通过/退回），评审包由小Pai 准备；同时实现 G1。④冻结点按 §03.9 L578-580 写明批准主体，且“任务完成不等于投入授权”。规格冻结（F46）、结构冻结、开模授权在 PDOS 内由具名人决定；**资金审批留在钉钉/ERP**，PDOS 只引用单号。⑤**（偏离 §03.13 L614，须写进同一份决策记录）**暂缓模板更新差异和多版本模板。
- 位置：`v1.1` §03.2 L495-499、§03.9 L574-580、§03.13 L610-614、附录 A L1618-1710；`assets/cehub/deliverable-guide-manifest.json`；`web/components/projects/project-workspace.tsx:56-64`。

---

## 4. AI-native 体验

**F05 项目侧小Pai 看不见也办不了**　P1｜未实现｜—｜—｜读取工具、work_management 在途
- 现状：工作树里读取工具已从 13 个增到 18 个（新增 build、lot、sample、issue、test.run 的结构读取，三个技能升为 0.1.1-draft）。`work_management` 0.1.0-draft 授权了 work.task.*、commitment.accept/review、status_update.create、plan.propose/apply、external_wait.record。仍然缺的有三样：项目运行不预载技能，`preload_when` 没有消费方，任务和承诺没有读取工具。
- 先做：**在 work_management 上补齐，不另建技能**。①代码预聚合项目上下文，追加在末尾（阶段、未结任务、14 天内的承诺与外部等待，算不出写“未知”）；②项目运行默认预载 work_management（F49）；③提交在途工作，启用前跑 F01 基线。验收：说一句“电机厂说电流偏大，下周三重送”，生成一条外部等待候选和一条复测任务，不改承诺（I08）。
- 位置：`srv/agent_kernel/bootstrap.py:453-466`、`tools.py:6-27`、`project_object_reads.py`、`skill_packages/work_management.md`；`docs/reports/evidence/pdos-next-domain-reads-20261022/result.md`。

**F49 “所有岗位自动带技能”只兑现了产品经理**　P1｜部分｜—｜—｜—
- 现状：18 个技能包的 `preload_when` 都只是文字，代码中没有消费方（grep 结果为 0）。`default_preload` 只按品类和提案判断，项目运行返回空 `()`。

| 岗位 | 页面/对象 | 应预载 | 现状 |
|---|---|---|---|
| 产品经理、G0 评审人 | 品类、提案 | proposal_drafting、gap_check、rfq_extraction 等 | 已预载 |
| 项目负责人 | 项目工作区、我的工作 | work_management | 包在途，不预载 |
| 结构/硬件/固件 | 配置、变更 | change_control | 有包，不预载 |
| 品质/测试 | 接收、测试 Run、Issue | test_verification、quality_issue | 有包，不预载 |
| 生产/NPI | Build、试产、放行 | build_execution、release_handover | 有包，不预载 |
| 采购、模具、认证、售后、管理层 | 供应、试模、法规、现场反馈、组合 | 无 | 缺包（F25、F30、F22、F36、F52） |

- 先做：把 `preload_when` 改成服务器能判定的条件（页面、对象类型、事件），按 v1.1 §06.3.3 在第一轮附上技能。判定依据是页面和对象，不是岗位名称，因为岗位不是权限事实（v1.1 L213）。位置：`srv/agent_kernel/bootstrap.py:453-511`。

**F53 公开研究的数据可达性**　P1｜部分｜—｜—｜—
- 现状：只有 SearXNG 一个后端（`srv/research/search.py`、`runtime.py:56-81`），v1.1 L1202 规定的“Tavily→Firecrawl→SearXNG”回退链没实现；从未在真实网络上验收，京东、天猫、1688、Amazon 能否抓到也没验证。这决定了 F01 里“公开研究 8–12 款竞品”有没有意义。
- 先做：①F01 基线中两个品类各跑一次真实研究，按站点记录结果（成功/登录墙/反爬/无结果）；②接一家商用搜索或读取服务，出站记回执；③卖家精灵、Helium 10 导出文件做导入模板，带抽样元数据（样本上限、星级配额、时间窗、导出时点），与 F36 共用行结构；④抓不到的写“未获取”，不补造。

**F04 整批确认与资格**　P1｜未实现｜—｜—｜—
现状：候选逐条预览、逐条弹窗；本人审阅一次都没做，T0 资格为 0。建议：同一 Run 的候选一次预览、整包提交，默认全选、可取消单条；三个草稿技能各用 10–20 个案例走本人审阅。位置：`web/components/pai/run-candidates.tsx:134-178`。

**F06 会话与失败说明**　P1｜未实现｜—｜—｜持久会话已提交
现状：每 3 秒轮询；露出 run_id、原始 JSON 和错误码；模型不可用时不能手动建提案（AT-45）；撤回全有或全无（违反 B17）。先做：手动新建提案；UUID、JSON 收进“技术详情”；错误码译成“已完成/未发生/你可以”。同一会话的 Run 连续显示（持久会话已提交，需复核）。后做：SSE、逐条列出撤回跳过的理由。位置：`web/components/xiaopai.tsx:130-136,207-219`。

**F12 捕捉入口窄**　P1｜未实现｜—｜—｜—
只收 TXT/MD/PDF/XLSX；上传后要刷新再手选。建议：复用 office_documents.py 支持 DOCX；拖入即加入本次携带清单（B14）；提案页上传直接挂到私有提案；图片先登记为原件。位置：`srv/originals.py:31-36`、`web/components/pai/file-upload.tsx:130-133`。

**F48 会话模式与操作者通道**　P2｜缺失｜需DR｜正文｜—
现状：你 10-18 提出的“会话权限”维度（与角色权限并列，例如只问不写）在代码里完全缺失（M2 稿 L179）。完整实现要在会话中增减工具（B 路线），而 M2 待决②（开 Anthropic 原生路线并换型号）、③（A 是否作 OpenAI 兼容退路）都没定。技能正文和服务器上下文以 `role:"user"` 注入（`srv/agent_kernel/graph.py:209-211`），操作者指令和用户输入同走一个通道。建议：最小版不依赖 B，把“只问不写”做成服务器事实，运行开始时只披露读取、计算、研究工具，切换模式即新开运行；注入通道随 M2 ②一起定，此前先补“原件内含指令”的负向案例。

- **F09 研发记忆**（P2｜未实现）：同品类 Issue 标题检索（先过 RLS），⌘K 加样件标签与 Issue 标题，Issue 关闭时可起草经验候选。位置：`srv/personal_search.py:24-28`。
- **F10 护栏**（P2｜部分）：冻结前缀加一句“不自拟健康度、风险分或百分比；对方日期记为声称”，加两个负向案例，不做关键词拦截。位置：`srv/agent_kernel/graph.py:25-33`。
- **F11 后台委托**（P2｜部分｜④需DR）：先做不经模型的确定性注意项（齐套未满足、承诺临期）；有资格后只开“测试结果事件建 Issue”一条写路径；表单改业务语言；“个人技能”定义为保存的指令模板。位置：`srv/agent_kernel/execution.py:68-69`。

---

## 5. 业务功能缺口（按生命周期）

### 5.1 立项与定义

**F46 规格冻结与派生入口**　P1｜未实现｜—｜—｜—
- 现状：`product.definition.publish`（规格冻结，T2）和 `update`（T1）都是 not_implemented，`protect_fixed_definition` 也不允许把定义改为 published。确认稿 P23 因此写明，派生提案在真实命令链上拿不到可引用的发布父版，K3 的“派生迭代”入口走不通。S1 证据中，G0 生成的定义 v1 仍是 `status=draft`。v1.1 L627 规定规格冻结在项目内的概念与计划阶段完成。
- 先做：①实现 publish（具名 T2），作为 F14 的第一个冻结点，排在 G1 之前；②update 以 T1 承接项目内迭代；③派生提案引用已发布父版，真实走一次派生→G0。
- 位置：确认稿 L599-603；`v1.1` L507、L627、L1646；`docs/reports/evidence/pdos-next-s1-20261022/result.md:21`。

**F19 在途项目进不来**　P1｜缺失｜需DR（小）｜附A｜—
项目只能随 G0 原子建立；附录 A L1648 还写着“保留过渡入口”，与代码不符。建议：经 G0 纳管，带“在途纳管”标记并附原立项单，统计时排除；定义 v1 标“未复核”；先纳管 3–5 个。位置：`srv/domain/projects/service.py:161-180`。

- **F20 客户改版差异**（P2｜部分）：由人指定“v2 替代 v1”，在隔离子任务里做差异，主循环只拿定位不拿原文；S3 之后每个修订建一个变更请求。位置：`srv/skill_packages/rfq_extraction.md:105,114`。
- **F21 专利与外观**（P3｜缺失）：不让 AI 评专利风险；有新外观、走美欧渠道时建议建待决问题，并放进 F14 模板作为可豁免检查项。

### 5.2 项目执行与管理

**F03 项目工作区**　P1｜部分｜—｜—｜前端已提交（0efed69f）
Builds、准备、评审三个标签已经是真实面板；写操作仍跳回品类工作台，阶段、门禁、健康度是占位。建议：三个写入口在项目内打开。验收：不离开工作区，完成“记录失败→建问题→写状态更新”。位置：`web/components/projects/project-workspace.tsx:55-70`。

**F51 原工程已批准、v1.1 未明确承接的行为**　P1｜缺失｜需DR｜正文｜—
要你定保留还是放弃：①项目共享会话（DC-12）。v1.1 §05.4 规定个人对话默认私人，推荐放弃，改为发布确认内容为项目记录。②主动询问与未回复升级。推荐保留，做成确定性规则：等待或承诺过检查点 1 个工作日无回复，给负责人生成注意项。③延期自动重算。`work.forecast.refresh`（T0）未实现，“预测”没有数据来源，而它是 P17 健康度和 F16 的输入；推荐 P1 用确定性引擎实现，不改承诺和基线。④Triage 待分拣。推荐不建对象，在“要我接收”下加“待分拣”来源标签（现场反馈、客户输入、问题候选），由小Pai 给分诊和去重建议，不新增分组（守 P19）。每日简报暂缓。

- **F16 老板看什么**（P1｜部分）：健康度列按 P17 的输入映射，可下钻到规则 id，依赖 F51③。位置：`web/components/projects/project-list.tsx:80`。
- **F17 我的工作分诊**（P1｜部分｜③需确认）：卡片深链并预选版本；补上已实现的变更、放行、测试处置 T2；未确认候选按运行聚合。位置：`srv/personal_attention_decisions.py:59-60,106`。
- **F18 周报**（P1｜部分｜status_update.create 已获授权，在途）：排在 F05/F15 之后；按本周回执预填事实清单（不调模型，满足 AT-45），小Pai 压成 3–5 句，可复制为钉钉日志。位置：`srv/domain/work_management/schemas.py:180-183`。

**F52 组合与资源**　P2｜未实现｜需DR｜附A｜—
这是 P15 定的四个主干之一，整页仍是“尚未接入”（`web/components/app-shell.tsx:236`，`web/lib/global-navigation.ts:10` 标 planned），附录 A 也没有管理层命令。台架、模具厂、认证预算、工程师的冲突无处可见。建议：只读组合视图（阶段位置、健康度档位、下一门禁、阻塞等待）；共享资源只做占用登记和冲突提示；管理层只加一条具名的优先级取舍记录。排在 F14/F16 之后。

### 5.3 认证合规

- **F22 认证落点**（P2｜部分｜台账进 PDOS 需确认｜正文）：certification 块固定返回 unknown。认证测试走 VerificationRequest，报告作原件，覆盖由具名人员判定。位置：`srv/domain/preproject/baseline_blocks.py:27`。
- **F23 上市交付物**（P2｜部分｜附A）：§03.11 在概念上定义了四种放行，附录 A 缺“市场/认证适用性”命令（`srv/domain/release/constants.py` 只有组包和工程、制造批准），属操作层缺口。宣称值与实测同条件比对，不阻断。

### 5.4 供应与成本

- **F25 交期没人追**（P1｜部分）：承诺已能作为快照行挂到 BOM 物料，外部等待到检查日会进“我的工作”，缺的是到期判断和按行展示。实现轻量的 `supply.commitment.record`（来源可为本人陈述），同时生成“承诺日+1 天”检查；供应面板按 BOM 行显示需求、承诺、实到。位置：`srv/domain/supply_execution/schemas.py:11-27`。
- **F37 BOM 进不来**（P1｜部分｜零件身份上移需DR）：零件跨型号不能复用，没有导入和 bom_line 行结构。Excel/CSV 导入，小Pai 只建议列映射，转换交给代码，整版 T1 并与前版做差异，ERP 料号精确匹配时复用。位置：`srv/domain/configurations/models.py:41-47`。
- **F24 PCN/替代料**（P2）：change_control 加“供方变更通知”子流程，接受仍是 T2。位置：`srv/schemas/change_control/contracts.py:12-51`。
- **F26 成本链**（P2）：G0 物化只带了目标售价。只读对照 G0 目标成本与最新估算，差额按行分解。位置：`srv/domain/preproject/materialize.py:95-110`。

### 5.5 制造与品质

**F47 CAPA 有效性与关闭**　P1｜未实现｜—｜—｜—
- 现状：`quality.capa.effectiveness.decide`（T2，S3）是 not_implemented。capa_effectiveness 领域已有约 1.38 万行代码，但观察期、评效、独立复核和关闭都没完成，Issue 停在 awaiting_verification。这是品质工程师的主循环。
- 先做：①有效性决定（有效/无效/延长观察），具名 T2，决定人不能是实施人；②观察期取模板默认值，到期生成注意项；③判为无效时回到根因和措施；④Issue 关闭以有效性决定为前置；⑤小Pai 只准备评效包。验收：失败→Issue→CAPA→复测→观察期满→判定有效→Issue 关闭。
- 位置：`pdos-next/contracts/operations.json`；`srv/domain/capa_effectiveness/`；清单 M7 行。

- **F27 验证计划不连规格**（P1｜部分｜“定义转需求”需DR｜正文）：TestItem 生成时丢了参数版本，覆盖矩阵和 AT-10 未实现。加可空 parameter_ref，做确定性覆盖视图，支持复制上一型号测试计划；可靠性项导入企业自己的 DVP，不让 AI 补造。位置：`srv/schemas/verification/contracts.py:122-135`。
- **F30 模具与试模**（P1｜未实现｜模具验收需确认）：合同和准备度规则已就绪，但没有表、命令未注册。轻量模具记录，实现 `npi.tooltrial.create`，模具状态进 Build 准备度；寿命和保养留在 ERP/MES。位置：`srv/schemas/manufacturing_trials/contracts.py:149-185`。
- **F31 客户送样与承认**（P1｜未实现）：放行已从结构上禁止冒充客户承认。上传签样单，按外观、尺寸、性能、包装标识、认证资料五个范围逐项承认。位置：`v1.1` L727-731。
- **F33/F34/F35**（P2）：safety_ctq 贯通规格→测试→控制；制造基线加可空 line_programs；BOM 页加 3–5 条确定性规则卡。位置：`srv/domain/manufacturing_baseline/schemas.py:107-117`、`srv/domain/configurations/schemas.py:21-35`、`srv/domain/change_control/rules.py:41-58`。

### 5.6 上市与售后

- **F32 量产 ECN**（P2｜日期断点需DR｜正文）：涉及已放行产品时，要有带 ERP ECN 单号的生效计划项才能关闭；断点类型（批次/序列号/旧料用完）作字段，日期断点与现行规则冲突。位置：`srv/domain/change_control/handlers.py:745-753`。
- **F36 差评退货回流**（第 0 步 P1｜补场景需DR｜附B）：review_pain_clustering 没声明行结构，导入会被拒。先声明 user_voice@1，不带个人信息，注明“频次不等于故障率”；S5 再加售后渠道和 3 条路径 F 场景。位置：`srv/skill_packages/review_pain_clustering.md:10,55,75`。

---

## 6. 落地、集成与试点

**F38 真人进不来**　P1｜部分｜⑤需DR｜正文｜—
只能本机合成登录；成员授权没有界面；没有停用命令；资格只能后台导入，且绑定到项目（`srv/domain/professional_authority/schemas.py:36` 的 project_id 必填）。建议：①成员页具名授权；②一次性邀请链接；③一键停用并列出未结事项；④修 §2 的死锁；⑤资格改为管理员页具名 T2 登记，范围可到品类。位置：`web/app/api/local-session/route.ts:5-10`。

**F50 小团队兼岗与独立性**　P1｜部分｜视核对结果｜—｜—
- 现状：v1.1 L213 允许一人兼多职，L443 写明兼岗不豁免独立验证，L590 要求保留真实人员的独立性；P27 只放开了 G0 自评。代码里，变更要双专业批准，且“提出/批准/实施/测试执行者不能自证”（`srv/domain/change_control/handlers.py:334`）；放行要工程、制造两个独立具名 T2（`srv/domain/release/storage_schema.py:253`）；CAPA 要独立复核。原计划的“3 人试点”没有核对这些。
- 先做：①试点前列“步骤×人”编组表逐步核对，推荐选 S2 交样→测试→问题，避开 S4 放行；②资格范围上移到品类（同 F38⑤），否则每个新项目都要重登；③凑不齐人再写“小团队兼岗”决策记录，只允许明示的兼岗组合，不豁免独立验证。“兼任工作模块”和“中小企业精简模式”不另做配置，精简靠 F14 模板来实现。

- **F39 常驻环境**（P1｜B3a 需拍板）：单机 compose 放在内网常开机器上，镜像做离线包；每天备份，试点前按 AT-47 演练一次恢复；检查点按天清理。位置：`pdos-next/containers/`。
- **F13 钉钉触达**（P1｜排期需定）：只推要我决定、被指派、承诺临期或过期、被退回四类，只带深链，不经模型；首次发送前取得你的授权。位置：`srv/domain/external_wait/rules.py:204-268`。
- **F02 试点与度量**（P1｜第二步需DR）：先用只读脚本从回执算 5 个数，你用旧方法计时作基线；F38/F39/F03/F50 就绪后再做 3 人试点。
- **F41 导出**（P1）：项目、我的工作、BOM 差异、测试汇总导出 Excel，按读者权限过滤，保留“AI 起草”标记并记审计。位置：`srv/api.py:1484-1526`。
- **F42 ERP/CRM**（P2）：提案上加 GoodJob 客户编号和商机编号。
- **F40 多服务商**（P2｜正文：同步 §2 所列旧措辞）：一个协议只能配一把钥；出站事件有记录但不显示。运行详情加出站去向；接第二家服务商时再做路由。位置：`srv/model_configuration/host.py:104-108`。

---

## 7. 架构与建设方式

**F43 交付状态不可信**（P1｜部分）：没有 CI，整仓从未全绿。10-22 内核纯回归 1570 项通过，435 项因依赖数据库或检查点被排除；4 项失败中 3 项是沙箱环境问题，有权限复核后通过，剩 1 项就是 §2 的技能声明缺口。清单里 10-18 记的 181 项失败，其中旧出站断言已全部改写。另外，清单单格有 3.1 万字，多个会话在同一个工作树里施工。建议：①邀请同事前在已提交哈希上跑一次整仓回归，失败项进隔离清单；②无数据库的 `make check`；③当前队列每个里程碑一行；④每个会话一个 worktree。

**F44 守卫双写**（P2｜需确认）：同一守卫在 plpgsql 和 Python 各写一遍，s0_0728（10-10）之后又新增 84 个迁移。建议一页放置约定：RLS、约束、只追加、AI 身份边界、审批双重检查留在数据库，其余放领域服务。**冲突提示**：“只管新代码、存量不回收”相当于确认稿 C5 选项 1，这个选项你 10-08 否决过，当时选了整体重构。本条只涉及守卫放置，范围比 C5 窄，但仍需你确认。

**F45 性能预算**（P1｜D6 需拍板｜正文）：AI 时延没有目标；worker 固定 4 线程（`srv/worker.py:161`）；未知调用按上限占账，约为实际的 3.4 倍（49,012 对 14,511 微美元）；幂等重放还会重走校验。建议：定 D6，线程数做成配置项，幂等重放直接返回原回执。

| 指标 | 现状 | 目标 |
|---|---|---|
| 真实注册图运行 | 1 次（起草） | ≥10 次，含取消、重启 |
| S1 第一闭环场景 | 32 个未执行 | 逐条标状态，安全与权限类全过 |
| rfq_extraction 资格集 | 0 | 10 例，你签名 |
| 契约标记不一致 | ≥2 处 | 0 |
| 研究站点可达率 | 未测 | 两品类各测一次 |
| 起草时延 | 约 43 秒（单样本） | 按 D6（建议 p95 ≤90 秒） |
| 已提交哈希整仓回归 | 从未全绿 | 失败数＝隔离清单条数 |
| 运行费用可见 | 无 | 每次 Run 显示人民币金额 |
| 项目工作区占位标签 | ≥4 个 | 0 |

---

## 8. 竞品对照与参照来源

### 8.1 竞品能力 → PDOS 现状 → 建议

“成熟度”取自调研时的公开资料：GA＝已正式发布；预览＝beta、早期访问或路线图。效果数字一律视为厂商宣称。

| 能力 | 代表产品（成熟度） | PDOS 现状 | 建议 |
|---|---|---|---|
| 外部声音转成带原文摘录的候选（IM、邮件、通话、会议） | Linear Asks 与 Gong/Intercom 代理（GA）；钉钉 AI 听记→待办；企业微信“记录面聊” | 钉钉零代码；会议只到“已登记原件”；“说一句”被原件引用要求挡住 | 先做 F15 松绑和“说情况”技能（F05）；F13 排在登录之后，只推四类注意项、只带深链、不经模型。卡片内确认、转给小Pai、听记拉取暂缓 |
| 每日摘要、优先收件箱 | Linear Pulse、Priority inbox（2026-09）；Glean 每日关注 | “我的工作”11 个只读区块，没有排序和推送 | F17 就地分诊与排序；每日简报暂缓（F51） |
| 状态更新、周报：AI 起草→人改→发布 | Asana Smart status（GA）；飞书、Teambition AI 周报 | P18 已定，`status_update.create` 在 work_management 中在途 | F18：按回执预填事实，小Pai 压缩成几句，一次确认 |
| 文件、修订差异摘要 | Arena AI File Comparison 与 Item Redline（GA）；Bild Delta | rfq_extraction 只做单份抽取，客户 v1→v2 要人工对读 | F20：人指定替代关系，隔离子任务出差异，转成变更请求候选 |
| BOM 导入清洗、确定性检查卡加 AI 检查卡 | OpenBOM BOM Review（2026-07 GA）；Aras BOM Assistant；Cofactr 清洗 | BOM 只能逐行手录，没有导入和版本差异 | F37 导入与差异；F35 先做 3–5 条确定性规则卡 |
| 零件去重、where-used、AML | Windchill Parts Rationalization（2026-01）；Propel AML；Duro | 零件按型号隔离，无法反查 | F37：ERP 料号精确匹配时复用；AML 主数据留在 ERP（§9） |
| 替代料、供方变更→影响分析→变更单 | Oracle Component Replacement Assistant；Teamcenter 2606 BOM Agent（每步人确认）；Cofactr 逐行接受 | 没有 PCN 入口，供方变更不会让已签核的测试和认证失效 | F24：change_control 加供方变更子流程，接受为具名决定（安克召回案例说明风险，单一来源报道） |
| 规则驱动的提交前预审、准备度简报 | Oracle Change Order Auditor、Product Readiness Workspace（26B）；阿维塔×飞书交付件预审（客户宣称） | gap_check 只覆盖提案；门禁规则不存在 | F14 门禁规则＋F35 规则卡；保持“规则给结论、AI 只解释” |
| 测试数据检查清单、跨 Run 关联 | Nominal checklists；Instrumental 根因排序 | 只收 JSONL，处置只能整个 Run 一次做 | F28：XLSX/CSV 模板导入，导出时带 Lot、模穴列；失效分布视图和 AI 关联假设放到 P2 |
| 设计与 DFM 第一遍检查、带出相似件历史教训 | CoLab AutoReview 2.0（2026-07）；Fictiv 注塑 DFM；Leo AI | 无 | 先做 F09（同品类 Issue 检索）；DFM 技能等有历史数据后再做（§9） |
| 供应商报价抽取与口径归一 | LightSource；Paperless Parts Wingman | 无报价对象，目标成本不随项目流转 | F26：先做目标成本与估算的只读对照；报价由小Pai 抽成成本输入候选，一次确认，不做授标 |
| VOC、评论导入，证据可回查 | 卖家精灵 2.0 证据抽屉；Amazon Customer Review Insights；Helium 10 MCP（2026-07） | 实测/宣称/推断/未知的区分领先，但 review_pain_clustering 没声明行结构、没有导入模板 | F36 第 0 步与 F53 导入模板，带抽样元数据 |
| 变更影响覆盖 ERP 在途、在制、在库 | 金蝶 AI PLM（厂商宣称） | 变更采用明确不覆盖库存和在制 | F32：关闭前要求带 ERP ECN 单号的生效计划；F42：只读 ERP 事实 |
| 对外 MCP Server，让外部 Agent 调用本系统 | Propel 生产级 MCP（2026-06）；ONES MCP 63 个工具；飞书项目 MCP＋CLI；Rovo MCP（beta） | 只有入站 MCP | 规模化前再评估（暴露面变大，§9）；先满足钉钉内触达 |
| AI 用量计费与额度治理 | Notion credits 与 80%/100% 告警；Rovo；Asana AI Studio | 费用不可见；非管理员调不动模型 | F07：先做到每次运行显示人民币金额，再做用量视图和阈值告警 |
| 可看可改的记忆 | Glean 个人图谱；M365 Copilot Memory | 五层记忆只实现了当前工作短记忆 | F09；个人偏好层暂缓（§9，需决策记录） |
| AI 嵌进既有流程和审签 | 飞书项目 AI 节点；阿维塔嵌入 IPD 审签后累计 6 万多次调用（客户宣称） | 设计方向一致，但项目页不预载技能 | F49：按页面和对象预载技能 |
| 零代码沉淀“我的做法” | PingCode 智能引擎；用友 Skills 构建器；Asana AI Studio | 技能随代码发布，“个人技能”没有落地 | F11：先把“个人技能”做成保存的指令模板 |

**不跟随**：Dassault 虚拟伙伴宣称“会做决定”，与 AI 不取得具名决定权相反；monday.com 的 AI 风险排序与 P17 冲突；ClickUp 的“无限记忆”与多 Agent 搭建，与带来源的记忆、单一小Pai 相反；text-to-CAD、AI PCB 布局仍属早期或演示，产物的权威应留在 CAD/EDA。

### 8.2 参照来源

| 来源 | 用于 |
|---|---|
| 华为云 CodeArts IPD 模板，只借阶段形态（https://support.huaweicloud.com/productdesc-projectman/projectman_07_3001.html）；Oracle Readiness 26B，借呈现方式，不学按文件名判合规（https://docs.oracle.com/en/cloud/saas/readiness/scm/26b/plm26b/26B-plm-wn-f44464.htm） | F14 |
| Linear Asks（https://linear.app/docs/linear-asks）、Triage Intelligence（https://linear.app/docs/triage-intelligence）、Priority inbox（https://linear.app/changelog/2026-09-03-priority-inbox）、Pulse（https://linear.app/changelog/2025-04-16-pulse）、Loops（https://linear.app/changelog/2026-07-20-introducing-loops）、AIG（https://linear.app/developers/aig） | F15、F51、F04、F17、F16、F11、F06 |
| Notion 按 credits 计费（https://www.notion.com/help/custom-agent-pricing）；Asana Smart status（https://help.asana.com/s/article/smart-status）；ONES Assistant（https://ones.cn/blog/features-updates/ones-assistant-end-to-end-rd-management-ai） | F07、F18、F05 |
| Nominal（https://docs.nominal.io/python/checklists/data-review）；RAG-MCP 预印本，非 MiniMax 实测（https://arxiv.org/abs/2505.03275）；Aras，厂商资料（https://aras.com/en/blog/introducing-the-first-generation-of-agents-built-on-aras-innovator-edge-ai）；华天（https://www.hoteamsoft.com/news-2050） | F28、F01、F12、F09 |
| 飞书 AI 风险评级，作反例（https://www.feishu.cn/content/article/7603309198601538781）；上海宇昔（https://www.yx-win.com/h-nd-321.html?m871pageno=3）；PTC Arena（https://www.digitalengineering247.com/article/ai-engine-for-arena-plm-and-quality-management-boosts-automation/plm） | F10、F19、F20 |
| Teamcenter 2606（https://blogs.sw.siemens.com/teamcenter/teamcenter-2606/、https://blogs.sw.siemens.com/teamcenter/whats-new-teamcenter-quality-2606/）；亚马逊锂电要求（https://gs.amazon.cn/zhishi/article-260205-3） | F22、F27、F33 |
| Windchill（https://www.digitalengineering247.com/article/ptc-launches-windchill-ai-parts-rationalization-capabilities）；Oracle 替代料（https://docs.oracle.com/en/cloud/saas/fusion-ai/aiafl/ai-scm.html）；LightSource（https://lightsource.ai/llm-info）；OpenBOM（https://www.openbom.com/blog/plm-and-bom-management/ai-bom-health-check-card-bom-review）；金蝶，厂商宣称（https://www.kingdee.com/products/galaxy_plm.html） | F37、F24、F26、F35、F32 |
| Amazon Review Insights（https://sell.amazon.com/blog/customer-review-insights）；钉钉登录（https://developer.aliyun.com/article/792876）、听记（https://www.36kr.com/p/3728259637607553）；Temporal（https://temporal.io/blog/auto-setup） | F36、F38、F18、F39 |
| 阿维塔×飞书，客户宣称（https://inabr.com/news/22580）；CIMdata（https://www.engineering.com/ai-in-plm-near-term-expectations-and-challenges/）；V2EX 单帖（https://www.v2ex.com/t/1226030） | F13、F02、F41 |

**应坚持的差异点**：写入分级与具名决定，AI 永不执行 T2；准备度和健康度用规则；数字由代码算；单一小Pai 加 MCP；四时间分开。自建部署和模型可换目前还是**目标**，现状见 F39、F40。

---

## 9. 不做与暂缓

**不做**（收窄方案时去掉的子方案，以及曾被否决的方向）：

| 不做 | 来自 | 理由 |
|---|---|---|
| 冻结 S2、S3–S5 只修缺陷 | F01（曾否决） | 与 P13/P21 冲突，会冻住项目主体 |
| 通过率作出口、契约写 last_run、每晚跑批、工具数进 CI | F01/F08 | 掩盖安全场景；持续花费无收益 |
| 境外服务商默认拦截 | F40（曾否决） | 部分恢复 C9 选项 1 |
| PDOS 内资金审批、687 条全做硬规则 | F14 | 与钉钉/ERP 双重审批；方法论变关卡 |
| 不经 G0 的存量登记 | F19 | 撞 K2/P23 |
| AI 评专利风险、ip_screening 技能 | F21 | 专业度不够，还留下不利证据 |
| 型号级合规矩阵、物质声明、listing 对象 | F22/F23 | 第二份事实，越过电商与 ERP 边界 |
| AML/MPN 主数据、比价授标、零件身份上移 | F24/F26/F37 | ERP/SRM 双写；动权限根 |
| 凭空写 FMEA、固件兼容矩阵、DFM 技能 | F33–F35 | 没有历史数据，维护压在小团队 |
| 退货率阈值、自动建 Issue | F36 | 电商退货没有批次 |
| 关键词拦截 | F10 | 误伤合法术语 |
| 钉钉卡片内办理 T1、对外 MCP Server | F13 | 可行性未核实，暴露面变大 |
| 定时起草周报、会议对象 | F18 | 撞 P18/P19；钉钉听记已覆盖 |
| 按岗位名称预载技能、T2 批量授予 | F38/F49 | 岗位不是权限事实；改按页面和对象 |
| 夜间整仓回归、迁移日期前缀、SQL 失败闸门、RTO/RPO 承诺 | F43–F45/F39 | 新的验证仪式；违反迁移单调规则；无数据不承诺 |

**暂缓**（v1.1 已设计，删除等于缩减冻结范围，须写决策记录）：FailureMode 对象（§02.1）；个人偏好记忆层（§06.8）；全文与混合检索（§07.7，C13 只是把它移出第一闭环）；模板更新差异（§03.13）。

**继续坚持**：AI 健康分或风险分（P17）；自动发布状态更新（P18）；删除会话（P20）；成员视角预览（P16）；看板拖拽、阶段百分比；显示 T0/T1/T2 和 token；多 Agent（K7）；研究类对象（C3）；立项前加关卡（K2）；tool search；CRM 销售漏斗；替代 ERP/MES/PLM/CAD/EDA；协议作为出站前置（P26）。

---

## 10. 需要你拍板

| # | 决策 | 推荐 |
|---|---|---|
| 1 | F14 门禁与冻结点写进附录 A/B | 批准最小版；冻结点由具名人在 PDOS 决定，资金只引用单号；**模板差异暂缓（偏离 §03.13）** |
| 2 | F01⑥“先跑基线再启用”是否设为闸门 | 不设闸门（设闸门属于加严，且与 P21、P27 冲突） |
| 3 | F01 是否暂停 S3–S5 | 不暂停 |
| 4 | F51 四项原工程行为 | 共享会话放弃；升级保留；预测重算实现；Triage 只做来源标签 |
| 5 | F48 会话模式，M2 待决②③ | 先做“只问不写”；②等多服务商时再评；③不保留 A，除非缓存测量证明有收益 |
| 6 | F38 资格登记与角色 | 具名 T2 登记，范围到品类；新增 regulatory，customer 改由客户承认处理 |
| 7 | F50 小团队兼岗 | 先走查，凑不齐再写记录 |
| 8 | F02 多人试点（放宽 K9） | 前置就绪后做 3 人试点，走 S2 子流程 |
| 9 | F19 在途项目 | 经 G0 纳管 3–5 个 |
| 10 | F17 待确认候选位置 | 放在“要我决定”下的独立小节，按运行聚合 |
| 11 | B3a 生产 Temporal | 自托管官方镜像，同一 PG 实例分库；检查点保留 30 天起步 |
| 12 | D6 AI 时延 | 首个进展 ≤2 秒，起草 p95 ≤90 秒，研究超过 5 分钟转后台 |
| 13 | F13 钉钉通知 | 放在 F38/F39 之后，首次发送单独授权 |
| 14 | F22/F23 认证台账、市场放行 | 台账进 PDOS；市场放行到 S4 再定 |
| 15 | F52 管理层取舍命令 | 先做只读视图，命令随 F14 补进附录 A |
| 16 | F44 守卫放置（C5 先例） | 接受“只管新代码”，因为范围只限守卫放置 |
| 17 | §9 四项暂缓 | 确认是暂缓，不是删除 |
| 18 | M2 待决①：T2 准备也要求技能包 | 等 F01 基线出来再定 |

---

## 11. 建议路线

**近 2 周**：修完 §2 的缺陷；收口在途工作（提交读取工具和 work_management）；做 P0 ①–④（F15、F07、F29、F28 第一个模板、F01/F08 含 F53 可达率）、F10 前缀、F43①②；请你先定 §10 #1–#5、#11、#12，需要的写成决策记录。

**1–2 个月**：F14 实施（含 F46）→F03→F51③→F16→F17、F18；F47；F05＋F49；F04、F06、F12；F25、F27、F30、F31、F37；F38、F50 走查、F39、F41、F45；后段做 F13。

**规模化前**：F02 试点；F52；F48；其余 P2 与 F21；上云（逐项授权）和钉钉登录。
