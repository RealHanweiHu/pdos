# PDOS AI-native 整合执行清单 v1.7

历史实现摘要只说明当时已登记的部分覆盖；当前队列优先，摘要中的旧待批/下一步不作为现行指令，完整判据与状态见原条目。

本文件是唯一活动勾选清单；执行计划（已归档：标签 `archive/pre-restructure-2026-11-01` 的 `docs/design/2026-09-09-ai-native-integrated-execution-plan.md#execution-cadence`）规定闭环顺序与验证层级。65项编号、状态、依赖、交付/验收及映射保持；未完成工作按下方功能闭环推进，原条目作为验收底账。历史流水已转入只读归档（标签 `archive/pre-restructure-2026-11-01` 的 `tasks/ai-native-integrated-todo.history-2026-09-27.md`），原条目保留定向链接；不默认全文读取归档。

<a id="current-queue"></a>

## 当前队列（2026-10-08 起：pdos-next 主线）

<a id="debt-board"></a>

### 欠债总表与完成顺序（2026-11-01 汇总，后续会话从这里接）

**来源**：10-15 至 11-01 的 Claude Code 会话、Codex 6 个主线程（含子线程）、本清单当前队列、设计稿、确认稿 P14–P34、[10-22 拍板表](../docs/reports/2026-10-22-pdos-decision-sheet.md)和 [10-26 UI 对照报告](../docs/reports/evidence/pdos-next-ui-comparison-20261026/result.md)（这两份此前清单都没有链接），以及两份 10-22 评估：[缺口与竞品对照](../docs/design/2026-10-22-pdos-v1.1-gap-analysis-and-competitive-review.md)、[设计优化评估](../docs/reports/2026-10-22-pdos-design-optimization-review.md)。已明确不采用的方案和未证实的竞品口径另见[不采用清单](../docs/reports/evidence/debt-consolidation-20261101/rejected-and-unverified.md)。11-01 第三轮又扫了四块：10-08 之前的设计稿和你最初的原件（从归档标签读取）、原工程义务的承接情况、当前设计之间的冲突、所有材料都没考虑到的方面。由此新增 W3c、W11，以及 W3b 的早期想法部分。会话索引和归档去向见[汇总证据](../docs/reports/evidence/debt-consolidation-20261101/README.md)。

**用法**：
- 每组（W0–W11）开一个会话，开头说“接欠债总表 Wn”；W6 按 ①–⑧ 可拆成 2–3 个会话。
- 做完一项就在原位改成 ✅ 并附证据链接，不另起段落。新发现的问题追加到对应组，不要只留在会话里。
- 本节下方的旧段落保留为历史，其中写的“下一步”不再作为指令，以本节为准。
- 〔你〕表示需要你决定、提供材料或亲自操作。

**推荐顺序**：
1. W0 ✅ → W1 ✅（11-03 由 Claude 主会话收口并本地提交，未推送）。
2. D60 迁出 iCloud ✅（11-05，旧文件夹待删）→ W2（整仓重组放在 W2 最后做）。
3. W3 拍板与 W4 小缺陷并行：一个是问答，一个是代码。拍板按 W3 → W3c 设计冲突（先定 D140–D144 五条）→ W3b 候选池分拣的顺序做，内容多，可以分两三次。采纳的条目移入对应组。
4. W5 在 W1 出结果后由你随时做。
5. W6 先做 P34，再做 P33；W7 中与 P34 无关的页面可以并行。D140、D141、D144 不定，W6 的 ③⑥ 不能动工。
6. W8、W9 按闭环推进。W11 试点上线准备与它们并行，真人试点前必须完成；其中 D214 登录是任何真人使用的前提。
7. W10 最后集中做检查点。

外部动作（D60–D68）随时可做。整仓重组原定排在 W1 提交和迁出 iCloud 之后，实际已提前开始，现状见 D02。

**W0 立即处理**
- D01 ✅ 11-01 晚只读核对完毕，[核对记录](../docs/reports/evidence/debt-consolidation-20261101/d01-preview-eval-isolation-check.md)。原来担心的“预览重启后续派积压运行、产生 MiniMax 调用”不成立：派发只在 Worker 里做，而且只处理预览租户；预览没有配 Worker，API 启动时不派发；预览租户排队中的运行和没派发的出站记录都是 0。库里有 10-11 到 10-22 克隆来的约 5000 个运行中/排队中的运行，分属 4394 个测试租户，预览碰不到。已改两处本机配置：`.claude/launch.json` 去掉了 `--watch tools`，下次启动预览时生效（当前 API 由重组会话 22:15 启动，仍按旧参数跑，没有重启）；`.local/agent-runtime/environment.json` 的 Temporal 程序路径改到 `.local/tools/temporal`（原路径在整仓重组中失效，Temporal 一旦重启就会找不到程序）。余项：评测和预览仍然共用库、租户和命名空间，评测的 37 个运行出现在预览历史里，隔离归 D59；还开着的评测工作流归 D08。原记录：Codex 真实评测和本地预览共用同一个库（64387 `pdos-comprehensive-c351c0ca`）和同一个 Temporal 命名空间（`pdos-next-comprehensive-20261023`），预览的 `dev_reload.py` 又监视 `tools`。
- D02 ✅ 「项目代码结构优化」会话已完成整仓重组（没有等 D60），全部为本地提交、未推送：
  - 392341ee：删除原工程、旧设计和本清单的历史段，全部留在标签 `archive/pre-restructure-2026-11-01`；
  - f733edc9：前端按产品区重组；
  - 539c1419；
  - d167f9ea：重写设计索引；
  - 002bf63c：下线手册说明原部署脚本从标签 `original-final-2026-10-08` 检出；
  - 09a3184c：删除历次 wave/m2/m3/s0 检查点脚本；
  - d90bab91：后端 `pdos_next` 按 core、agent、features、originals、integrations、bootstrap 分组；
  - ee5e4a76：`packages/`、`assets/cehub`、`agent_runtime_environment.py` 移入 pdos-next，根目录只剩 docs、pdos-next、tasks；
  - 3f331769：新增 `README.md` 目录地图，更新根 README、AGENTS.md 与设计文档里的代码路径；
  - 218ee392：D240 收尾；
  - 3da5167b：v1.1 设计稿恢复为冻结原文（契约固定了它的 SHA-256，218ee392 改链接导致 validate_contracts 失败）；
  - 9bcc7d54：后端 `domain/` 48 个目录与 `features/` 合并为 10 个产品区（categories、projects、builds、verification、quality、change、manufacturing、knowledge、automations、my_work），测试按同样的产品区分组；
  - e341e5e5：`pdos-next/` 下的代码提到仓库根目录，`pdos-next/.local` 并入根目录 `.local/`；随后的文档提交更新 README 目录地图、AGENTS.md 和文档里的路径。
  验证：后端无库全量 10413 通过，与重组前逐项一致；828 个模块全部可导入；前端 207 个测试文件 2637 例全过，typecheck、lint 无错误；tools 63 通过，4 个失败是原有的。

  遗留的断链和误删见 D240。
- D03 ✅ P33 设计会话临时目录里的 NPI 模板瘦身审阅稿和 CEHub v3 `npd.json` 已复制到[汇总证据](../docs/reports/evidence/debt-consolidation-20261101/npi-framework-scratch-a28e836c/)。

**W1 收口在途工作（验证欠账；11-02 起改由 Claude 主会话接手，11-03 收口，[W1 评测结果](../docs/reports/evidence/pdos-next-real-eval-20261101/result.md)）**

语义质量没有审阅（归 D30）；结果不授予 golden-case、T0、模型白名单或生产资格。57 个失败运行全部归因，没有一个是模型答错：超时并发 33 个（D243）、完整响应被记成未知 20 个（其中 15 个归 D244）、参数校验崩溃 4 个（D245）。
- D04 ✅ 52 题真实回放（MiniMax-M3）：46 题有真实运行；6 题没跑：3 题评测运行时缺端口、2 题父题没形成必需引用（D249），1 题被受众守卫正确拒绝。上下文 12 题 × F=64000/48000 都跑完，CTX-01、CTX-12 另在拆分拓扑下复跑（c64）。RAG 机械检查与首搜召回见报告 §2。
- D05 ✅ ENG-07 的“Kernel run binding immutable”是评测环境造成的：当时评测另起的 Temporal 与预览 Worker 重复派发同一个 Run，产品的绑定保护按设计生效。11-02 起评测改用共享命名空间加独立队列，评测内不再重复派发。
- D06 ✅ 缓存：输入 token 的 73% 是缓存读取，价卡费用少约 47%。时延：单次模型调用 p50 10.5 秒、p95 55 秒；单题 p50 4.1 分钟、p95 11.8 分钟。成本：价卡实计 7.35 美元（1523 次调用），另有 51 次未知调用按上限占账 35 美元（D57）。三点口径限制已在报告 §4.4 标注。D118 按工具的失败率、D124 子任务成本占比也在报告 §4.3、§4.5。
- D07 ✅ 30 轮长会话：两档 F 下服务商实际输入都没超过 F（最大 62,165 / 46,123），准入口径超 F 时清理触发、如实标为上下文不完整，历史 10 轮封顶；但 F=48000 下 61 轮里 43 轮回答不完整（D247）。注入与隔离：ENG-06、QUA-06 零写入、零候选，没有请求 `skill.load`。
- D08 收尾：
  - ✅ 11-03 分组本地提交（未推送）：评测报告与汇总、对账缺陷修复与回归测试（D242）、评测运行器与运行时（`--role`/`--queue`、原始原因观测）。11-02 之后新增的逐运行原始抓取（约 84 MB）和中途导出只留本地；
  - ✅ 写入本清单；
  - ✅ 11-03 恢复原模型配置（修订 7，逐字段核对一致）；4 个遗留的等待中运行以发起人身份取消（含 11-01 18:35 那个），预览租户里已没有未结束的运行；100 个评测人员的登录吊销、租户管理员身份停用；评测运行时全部停止，预览的 Temporal 和服务没动；
  - ✅ 陈旧状态已改为“已实施，余项见 W1”：设计索引、x1 handoff 文件头、本清单原 10-28/10-30 段里的“切片 B…仍待”和“90≠86”。
- D242 ✅ W1 中发现并修复：自动对账后，运行的回答对发起人本人也返回 403，从这种运行续接也被拦下。11-02 经你同意修复（`deterministic_proofs.reconciled_epoch`、`archived_citation_read`、`assistant_ledger.carried`），回归测试 `test_interrupted_citations_pg.py` 的 `[reconciled]` 用例去掉修复时失败、加上修复后通过；11-03 已本地提交（D08）。受影响范围另有 48 个既有失败，见 D27。

**W2 仓库整理（工程卫生；一个会话，删除类逐项经你同意；前置 D60）**
- D09 ✅ 清理 iCloud 编号副本（11-01 整仓重组已清；`.local/` 内的旧副本未动）：源码和测试树 14 个、`web/src` 7 个（不加过滤时 lint 会失败），以及 `docs/design/README 2/3.md` 等。`tests/.../test_run_continuation 2.py` 可能被 pytest 收集。
- D10 `~/Documents/pdos-ui-linear` 工作树断链：`.git` 指向已不存在的旧路径。它只含原工程 `web/` 在 09-29 的 4 个提交，09-30 已整合。建议移除工作树，分支留作历史。
- D11 `pdos-searxng-1` 已退出 3 周，仍挂旧路径，settings 挂载是空目录，需要从现仓库重建，并更新下方“环境”段；另外 33 个容器中 19 个已退出，`~/Documents/ai-native-R` 是空目录。
- D12 历史 `codex/*` 分支（s0-*、sprint-*、p1、vnext、m3-after-b8）建议清理。sprint-4/5、unify 有本地独有的提交，删除前要确认。
- D13 预览遗留：
  - `.claude/launch.json` 和 `tools/dev_reload.py`：提交还是忽略〔你〕；
  - `web/next-env.d.ts` 是生成副作用，提交前还原；
  - 预览库已升到 s0_0854（备份 `.local/comprehensive-preview-64387-before-0825.dump`），端口 57358→64387，22 个演示身份延期到 11-08；
  - 下方“本地预览导览”段仍链接已停的 59650。
- D14 ✅ 设计索引缺 8 份切片合同（d167f9ea 已补）：m3-implementation、s2×2、s3、s4、s5×3。
- D15 〔你〕11-01 的 6 个提交不在 10-31 快照里，是否追加一次快照推送。
- D16 ✅ 整仓目录重组（D02 那个会话），见 D02。
- D59 整仓重组时定一条规则：每个会话用独立的 worktree，不再让多个会话共用一个工作树和一个预览库。D01 和 D09 都是这个根源（审查 F43④）。
- D240 ✅ 整仓重组遗留的断链和误删，已由 218ee392 收尾：评测规则恢复到 `pdos_next/agent/skill_packages/evaluation-rubric.md`（技能加载器跳过它）；31 处断链改为写明归档标签里的路径，本清单文件头 2 处同改；wave 旧工具已随 09a3184c 删除。余项：build_execution、change_control、quality_issue、release_handover、test_verification、work_management 六个技能包在评测规则 §4 没有专属小节，重组前就缺，影响 D30、D31。原记录：
  - 高：`docs/design/skills-draft/evaluation-rubric.md` 已删，但 18 个技能包的 `evaluation_suite.rubric` 仍引用它，其中 §6“与资格的对应”没有替代件，会影响 D30、D31。建议恢复到技能包旁边。
  - 中：DC-11 第 3 行引用的 `docs/contracts/pdos-runtime-v1/freeze-record.md`（不可协商项 1 的依据）；AGENTS.md 的入口历史链接；UI 基线 4 处、v1.1 1 处、确认稿 3 处、本清单文件头 2 处的依据链也断了。建议改为指向归档标签。
  - 低：wave17/15 的旧工具引用了已删目录，可以一起删。
  - 设计索引已由 d167f9ea 修好，没有死链。

**W3 拍板（设计待拍板；一个问答会话，只出决定和记录，新记录从 P35 起编号；11-04 已用到 P83）**
- D17 ✅ 11-02 全部按推荐，见[确认稿 P41](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p41)。要点：
  - ≥95% 作新品框架 v1 缺省值，只用于阶段评审材料判定，不自动推进或阻断；首批框架为新品和派生；
  - 轻量路径看四个字段（电池、新模、新认证、首用关键部件），任一未知按“是”，G0 评审人只能升不能降；
  - 群聊 @小Pai、钉钉推送都放第二批；评论只锚定到对象版本；讨论随对象保留，导出并入 D56；
  - 降级阈值：撤回率 >5%、人工修改率 >30%、框架检查失败率 >10%，关键错误 1 次暂停；合并窗口 10 分钟、冷却期 1 个工作日、负载 4 周 160 小时；
  - 日历接通前按周一至周五估算并标注；登记 AT-64–AT-66。
  待同步：v1.1 §05.12.6 通知段、附录 B 与 `contracts/acceptance.json` 补 AT-64–AT-66（W6 开工时做）。11-09 AT-64–AT-66 已写入附录 B 与 `acceptance.json`（D37 ⑧）；§05.12.6 通知段仍待同步。
- D18 ✅ 11-02 定：以 10-25 定稿和代码为准，见[确认稿 P35](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p35)。全局为我的工作、收件箱、小Pai、项目、项目集、知识，加产品管理分组；取消“组合与资源”；我的工作三页，P19 改为判据保留。v1.1 待同步：§01.6、§05.3 的“我的工作”“组合与资源”两行、P19 加注。实施缺口（待我处理按四类分组、承诺页覆盖全部承诺）交 W7 D38。原记录：信息架构合同和代码不一致：v1.1 §01.6/§05.3 仍是“我的工作｜项目｜组合与资源｜知识”，代码和 10-25 UI 稿已经是收件箱、小Pai、项目集、取消资源协调入口；我的工作已改成三页，而 P19 写的是四分诊加承诺分区。
- D19 ✅ 11-02 定：状态只经正式命令变化；本人自建、无需他人验收的任务可一键完成（回执标“本人自验”）；“我的摘要”留在收件箱，并入每日摘要。见[确认稿 P36](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p36)。v1.1 无需同步；实施随 W7 D39。原记录：通用任务能否直接改状态（UI 稿的做法），还是走分派→承接→提交→验收（正式流程），边界在哪里；收件箱「我的摘要」页放在哪里。
- D20 ✅ 11-02 拍板表 A 组全部按推荐：
  - A1 ✅ [P43](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p43)：`work.stage.review.submit`、`work.stage.decide` 登记进附录 A；阶段决定只有批准、退回；规格冻结排在 G1 前（D36）；CEHub 687 条进 `work_management` 参考资料，只作缺项提示（同时答复 W11 D223，该条未改）；模板更新差异并入 D152。待同步：附录 A 两行，合同目录对齐后消除 90≠86；
  - A2 ✅ [P47](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p47)：不设基线闸门；授权技能包真实基线 ≥10 次，排在 W1 之后；rfq 资格集 10 例由你签名（W5 D31）；
  - A3 ✅ P47：接 Tavily + Firecrawl，SearXNG 回退，凭据见 D62；境外出站限制随 D216；
  - A4 ✅ [P44](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p44)：`proposal.g0.submit` 对齐一次确认，`proposal.share` 为“小Pai 仅准备”（同时定了 D166 后半）。11-04 已同步（已本地提交，未推送，随 D247）：附录 A `proposal.share` 行、registry、两个技能包、评测细则 G-S3；
  - A5 ✅ P47：管理员为成员办预算，运行详情显示 ¥，不做三级上限（D135）；
  - A6 ✅ [P45](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p45)：取回原工作簿解析按 B 类复用，确认稿 §5.1 已补一行；
  - A7 ✅ [P46](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p46)：首个进展 ≤2 秒（按服务器事件计）、日常问答 p95 ≤8 秒、企业问答 ≤25 秒、起草 ≤90 秒、研究 >5 分钟转后台，均为观察目标，W1 后与 D23 一起复核；
  - A8 ✅ 不单独拍板：底座已由 P37 定，余项在 W3b 的 D119–D121 定。
- D21 ✅ 11-04 拍板表 B、C 两组已随 W3b 候选池全部定完（P77–P83）。原记录：拍板表 B、C 两组已逐条拆进下方 W3b 候选池，在那里一起定。B1①、B9、B17③、C2、C4 的前提已被 P28–P34 改变，候选池里按新前提改写了，已失效的部分记在不采用清单。
- D22 ✅ 补决策记录（11-02 五项全部定完）：
  - ✅ M2 方案 C 追认，见[P37](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p37)。取代 v1.1 §06.3.3 末段“工具列表保持稳定、引入检索工具”。待同步：v1.1 §06.3.3 末段；`contracts/acceptance.json` 的 AT-58 补“下发集合按已加载技能推导并记入运行”；
  - ✅ 不采用程序化工具调用，理由见[P38](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p38)，不采用清单已改；
  - ✅ T0 抽检 20%、每周至少 2 次，关键错误五类、1 次即暂停，见[P42](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p42)。待同步：v1.1 §06.12 末段加注（11-09 已加注，D37 ⑧）；
  - ✅ 会话模式延后，恢复条件是首个 T0 资格生效或你提出需要，见[P39](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p39)。D119 不因此触发；
  - ✅ P14 A 类 24 条按你 10-17 原话整体认可，P14、P22 已加状态更正，见[P40](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p40)。
- D23 ✅ 11-04 按 W1 数据全部按推荐，见[P76](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p76)：§16 配置试点期由你本人负责、缺省沿用代码值；CTX-09 修订稿采纳为替换候选进 D30；QUA-04 接受为已知项；工具下发三处收缩（范围过滤、T2 准备也须先加载技能即 D120、预载按页面判定，关联 D29），交 W8；token 流式只在日常问答快档开；P46 目标不变并登记 W1 基线。原记录：小Pai 启用前的选项（等 W1 数据）：
  - RAG §16 配置项：停用词和编号维护人、摘要模板与频率、品类知识负责人、补查阈值等；
  - CTX-09 修订稿是否采纳；QUA-04 没进前 5 是否接受；
  - 主循环固定前缀（61 项工具，约 3 万 token）是否收缩；是否做 token 级流式。
- D253 ✅ 11-07 记忆层设计全部按推荐确认：Q1–Q15，加上你 11-07 提出的语言习惯（Q16）、并入你的《节点衔接设计与评测方案》（Q17–Q18，其中 12 处按已定规则调整）、验收场景 AT-71–AT-74（Q19）。决定见 [P84](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p84)–[P90](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p90)，P72 由 P86 修订，P32 第 4 项由 P85 补充；设计稿改为 [v0.4 已确认](../docs/design/2026-11-05-xiaopai-memory-layer-design.md)，结果汇总在其 §12；实施按其 §13 交 W8 D45。v1.1、RAG 设计 D11 与不采用清单的待同步处见各条记录。 原记录：11-05 记忆层优化：按你提的“Memory 层 + RAG 层”和四类记忆，对照主流 agent 的做法与 LangGraph + Temporal 的现有链路，写成[设计草案 v0.3](../docs/design/2026-11-05-xiaopai-memory-layer-design.md)，同日按你的要求补入业务场景记忆（§7）和具体架构与机制（§14：组件、数据表、读写流程、检索算法、事件沉淀、撤权传播）。§12 列了 Q1–Q15，均附推荐，确认后写为 P84 起的记录，实施交 W8 D45。要点：
  - 五类记忆（四类加程序性，感知归入 RAG 层），分个人和业务范围两种归属；
  - 第 1 期做跨会话情景回忆；P72 修订为“小Pai 提议、本人确认”的自由文本记忆；
  - 业务场景：新增范围备忘（挂品类、产品、提案、项目，T1 确认，90 天复核）、按技能包声明的场景记忆配方；G0 结束、问题关闭、项目复盘时起草沉淀候选；不建客户实体；
  - 不引入 Qdrant、Neo4j、SQLite，也不用 LangGraph 自带的 Store。

**W3b 候选池：未确认的优化方案与竞品功能缺口（需要你逐条定采纳、延后或不做；同意推荐可以直接说“按推荐”）**

每条前的〔推荐〕只是建议，不是决定。定下来以后：采纳的移入箭头所指的组；延后的留在这里，写明恢复条件；不做的移到不采用清单。

W3b · 协作、通知与项目管理
- D70 ✅ 11-02 随 D150 定掉：承接时默认一并承诺，后台分开记录，见[P58](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p58)。实施归 W6。 原记录：〔采纳→W6〕承接即承诺：受派人一键“承接并承诺这个日期”，或者提出另一个日期。后台仍分开记录，只是合并展示（a28e836c T2；v1.1 §03.3）。
- D71 ✅ 11-09 已实现（[见 W9 末](#automation-templates-20261109)）。采纳→W9，并入 D190：未回复和未推进分别计时（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）未回复自动升级：1 个工作日没有回复，就给负责人一条注意项。用确定性规则，不经模型（拍板表 B1②；对标 Linear Asks）。
- D72 〔延后：D114 上线后〕（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）待分拣来源标签（B1④；对标 Linear Triage）。
- D73 ✅ 采纳→W6⑤（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）收件箱加“稍后提醒”。目前只有已读、归档、关注（驾驶舱稿 §3.1；对标 Linear）。
- D74 ✅ 采纳→W6⑤，定为 SSE，断线回退 30 秒轮询（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）定下聊天和通知的实时投递方式（轮询还是 SSE），要在 P34 讨论上线前定。目前收件箱前端没有推送（UI 候选 §5.1）。
- D75 ✅ 11-09 已实现最小版（[见 W9 末](#automation-templates-20261109)）。采纳→W6，负责人与范围按 P57，状态更新起草按 P65（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）自动化规则模板的最小版：承诺到期提醒、外部等待升级、状态更新起草（G-28、C8；对标 Linear Loops、Notion Custom Agents）。
- D76 ✅ 采纳→W6⑦（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）；11-09 随 D37 ⑦ 实施：管理者驾驶舱按当前阶段出口条件逐项比较（每项一个规则结果，不按任务、任务数或比例），框架出口成果待阶段节点建成后接入（D406），[证据](../docs/reports/evidence/w6-cockpit-20261109/README.md)。原记录：跨项目对比改按出口成果计算。P33 之后各项目的任务不同，按任务比没有意义（NPI 稿 §12）。
- D77 ✅ 采纳→W7、W8（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）同一运行产生的候选整包确认，减轻审批疲劳（B7；对标 Asana、Linear）。 **W7 实施 ✅ 11-09**（[证据](../docs/reports/evidence/pdos-next-w7-my-work-20261109/README.md)）：“要我决定”的运行卡片上默认全选、可取消单条，“核对整包”逐条生成服务器预览（可展开原值、新值、来源与未定项），确认后经新接口 `POST /v1/categories/{c}/agent-runs/{run}/candidates/confirm` 逐条执行各自的原命令、各自事务，回执逐条记录；T2、多步候选、改动过的命令、未预览的条目一律拒收，部分失败逐条列出，不放宽档位。W8 部分（小Pai 侧）未在本次范围。
- D78 ✅ 采纳→W7，放在“要我决定”内按运行聚合（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）定下待确认候选和待答问题放在哪里，深链时预选版本（B8、G-10）。 **实施 ✅ 11-09**（[证据](../docs/reports/evidence/pdos-next-w7-my-work-20261109/README.md)）：新只读接口 `GET /v1/personal/run-decisions` 按运行列出本人待确认候选与待答问题（每个品类在各自只读快照里复用候选状态投影，不预览、不写入）；“要我决定”组内一运行一卡片；深链 `?area=work&decide=<运行>&candidate=<候选事件>` 定位该卡片并只预选该版本，失效链接提示“已没有待决定事项”。余项 D423、D424、D426。
- D79 〔延后：同一品类 3 个以上项目完成计划基线后〕（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）品类常见任务沉淀回品类资料，等多项目数据积累后，经你批准生效（NPI 稿 §9）。
- D80 ✅ 不做，已移入不采用清单（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）流程节点由小Pai 执行（驾驶舱稿 §3.1；对标飞书项目 AI 节点）。P33/P34 已覆盖大半。
- D81 〔延后：试点中多人同时编辑同一草稿成为常态时〕（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）草稿多人实时协同编辑（v1.1 §05.7；对标 Notion、飞书文档），乐观版本控制已够用。
- D82 ✅ 不做，已移入不采用清单（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）“近 7 天完成/新建与状态分布”卡片（对标 Jira Summary），与 UI 定稿“无指标卡片墙”冲突。

W3b · 资源、组合与试点准备
- D83 ✅ 采纳→W7（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）共享设备和台架预约：项目内登记占用并提示冲突。后端已有 `test_resource_reservations`（UI 候选 §5.1、C7）。
- D84 〔延后：P34 成员负载上线后〕（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）按人、设备、周的只读负载视图，以及优先级取舍记录（C7；对标飞书人力甘特、Motion）。
- D85 ✅ 采纳→W6：带“在途纳管”标记，统计排除，定义 v1 标“未复核”，首批 3–5 个；附录 A 过渡入口文字待同步（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）在途项目经 G0 纳管，否则试点时现有项目进不来。先同步附录 A L1683 的文字（B10）。（11-02 补：原工程 `intake_organization` 在途项目资料整理未承接，并入本条，与 D200 一起定。见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)。）
- D86 ✅ 11-07 已实现（随 D214，[证据](../docs/reports/evidence/pdos-next-sign-in-20261107/result.md)：链接第二次使用、过期、被新链接取代均被拒，库约束有效期不超过 72 小时；停用立即吊销全部会话和未用链接）。采纳→W11，并入 D192，与 D214 一起做：邀请链接 72 小时单次有效，停用即吊销全部会话（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）邀请链接和一键停用，这是多人试点的硬前置（B2 F38②③）。
- D87 ✅ 采纳→W11（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）试点的“步骤 × 人”编组表：先走查，凑不齐人就写兼岗记录（B3）。
- D88 ✅ 采纳→W11：Temporal 官方镜像自托管、同实例分库，检查点 30 天；部署位置随 D210（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）生产形态的 Temporal 和常驻环境，试点前置。目前是 SQLite 回退（B15）。
- D89 ✅ 采纳→W11（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）录入责任清单：列出系统依赖的约十条事实，写清谁录、何时录；找不到人录的，就不建那个页面（9a1ab768 T15）。
- D90 〔延后：第二位真人用户加入前〕（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）首周引导与角色模板（G-41）。
- D91 〔延后：D86、D88、D214 完成且 D218 定好后；届时放宽 K9 另写记录〕（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）多人试点与 ROI/减负报表，需要放宽 K9（C1、G-44）。

W3b · NPI 业务域（对照 PLM/NPI 软件）
- D92 ✅ 采纳→W9：新增 regulatory 专业角色，资格在管理员页具名登记、可到品类（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）regulatory 角色与资格上移：目前只有四个角色，且 project_id 必填。这是 D26 根治的前提（B2）。
- D93 ✅ 采纳，并入 D188：认证台账排在 S3/S4，市场放行与宣传口径核对到 S4 再定（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）认证台账与市场放行。P33 把认证报告列为红线成果，需要有实际记录可以链接；包装、说明书、标签目前不受控（B11；对标 Arena）。
- D94 ✅ 采纳→W9：G0 批准时未映射规格条目逐条处置（加严，已记录）（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）规格条目映射参数版本：G0 时逐条处置，S2 的覆盖视图依赖它（B4；对标 Teamcenter）。
- D95 ✅ 采纳：维持 T1，“草稿可 T0”限于条目级草稿；v1.1 §05.5、§08 待同步（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）`proposal.create` 档位：代码一直是 T1，v1.1 正文和附录 A 自相矛盾。以附录 A 为准改正文（B5）。
- D96 ✅ 采纳→W8（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）私有提案在运行收尾时预填 promote，不放宽 K5/I22（B6）。
- D97 ✅ 采纳→W9（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）模具记录与验收：不新增验收命令（B12）。
- D98 ✅ 采纳→W9（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）BOM 导入与版本差异，加 BOM 确定性规则卡（B13、F35；对标 OpenBOM、Aras）。11-10 已实现（worktree `hopeful-joliot-438789`，本地提交未推送，[证据](../docs/reports/evidence/w9-bom-import-20261109/README.md)）。
  - 11-09 实现：
    - 可用：XLSX/CSV 原件经既有上传、扫描与隔离解析后，`POST …/configurations/bom-import/inputs`（READ）按表头同义词确定性建议列映射并逐行转换；不能照原样导入的行（数量非正、缺单位、公式、ERP 料号与已有物料一致等）须逐条处置（跳过 / 建新物料 / 关联已有物料）。保存仍走 `engineering.bom.revise`（T1，整版一次确认），载荷带 `import_basis`，服务端确认时重做转换，行不一致即拒；原件、映射与逐行处置随版本存档。BOM 行新增位号；同内部编号复用可见物料，ERP 料号只作关联提示。规则卡四条（重复位号、位号数与用量不符、缺单位、数量非正或未知），确定性、不经模型、只提示不阻止保存。CSV 按 UTF-8 文本走同一解析路径（不改隔离容器）。
    - 迁移：占位 `s0_0900`（down `s0_0869`；11-10 第五轮集成改为 `s0_0876`，接 `s0_0875`），只给 `bom_lines` 加 `reference_designators`、`bom_revisions` 加 `import_basis`，有数据时拒绝降级。
    - 验证（11-10 终版）：无库 16 项；PG 端到端 2 项加受影响 46 项、BOM 链 131 项；迁移往返（含替代料列）；前端 tsc、eslint、相关 node 测试；合同导出与校验；浏览器亮暗、375px 走查并经页面导入保存一版。
    - 11-09 续（[P113](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p113)，用户选 A）：BOM 行可声明替代料（本型号已有物料的固定版本），声明不构成资格；规则卡第五条“替代料无资格”只读 Build 级批准，批准记录未接入时显示“暂不能判断”。导入新增替代料列，对应不上已有物料的替代料须逐行决定不导入；手工续版保留位号和替代料。
    - 余项：D430、D431、D433、D434。
- D430 小Pai 建议 BOM 列映射（P79 “小Pai 只建议列映射”）：要给小Pai 加读取解析表头的工具或技能说明，属于模型可见改动，走 Prompt A/B；转换仍由代码完成。
- D431 导入时替代料只能引用本型号已有物料，同一次导入里新建的物料不能当替代料（要先导入建立，再在下一版引用）。试点出现批量新建替代料的需要时，再定“按内部编号在同一载荷内引用新物料”的写法。
- D432 ✅ 11-10 D98 浏览器走查：亮暗两种主题、375px 宽度，并经页面导入、处置、一次确认保存一版，[证据](../docs/reports/evidence/w9-bom-import-20261109/README.md)。走查中修了差异表窄栏折行和导入确认框不居中。
- D433 规则卡“替代料无资格”接入 D47 的批准记录：D47（`supply.alternate.approve`）合入后，在 `domain/builds/configurations/bom_alternates.py` 读取固定了本 BOM 版本、读者可见的 Build 的当前有效批准，返回（行标识, 替代料物料）集合（P113 第 3、4 项）。
- D434 多处一次确认对话框没有 `m-auto`，被 Tailwind 的重置去掉了浏览器的居中，显示在左上角：`build-preparation`、`build-cost`、`build-verification`、`build-execution`、`build-supply`、`project-planning`、`original-files`、`product-variants`。D98 走查时发现，只改了导入确认框；其余各自加一个类即可，留给对应页面的负责会话或 W4 小修。
- D99 ✅ 采纳→W7（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）项目内的品类知识只读入口，不改权限（B14、G-31）。
- D100 ✅ 采纳→W6、W9：只在挡住下一个冻结点或阶段节点时推送（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）未知项要有责任人和期限，但只在它挡住下一个不可逆动作时才推到人面前（9a1ab768 T15）。
- D101 ✅ PCN 子流程采纳→W9；情报源〔延后：有可接入的数据源时〕（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）供方变更（PCN）子流程；供应链情报源（C10；对标 Arena SCI、Cofactr）。
- D102 〔延后：P45 首个导入模板跑通后〕（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）测试数据管道与 Cpk（C9；对标 Instrumental）。
- D103 〔延后：S4 放行闭环建成后，届时定日期断点〕（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）量产 ECN 单号与断点（C12；对标金蝶 AI PLM）。
- D104 〔延后：随 D48 的 S5 爬坡反馈〕（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）售后差评回流场景，附录 B 的路径 F 还没补（C13）。
- D105 ✅ 设计已覆盖，改为实施项→W9，按闭环排期（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）四项：客户改版差异与版本比对（F20；对标 Arena File Comparison）；目标成本对照与 ECO 成本差（F26；对标 Teamcenter BOM Agent）；safety_ctq 贯通（F33）；制造基线 line_programs（F34）。（11-02 补：原工程 `cost_reduction`、`cost_discussion_followup` 降本与成本讨论跟进未承接，并入本条。见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)。）
- D106 〔延后：首个客户或供应商要求直接登录时；在此之前内部具名人代为登记〕（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）外部协作者入口与协作席位。UI 稿有“收到的交付”，C11 推荐先由内部具名人代为登记（对标 Teamcenter Supplier Hub、Jiga）。
- D107 ✅ 不做，已移入不采用清单（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）培训记录作为人员资格证据（G-24）。

W3b · 入口、移动与集成
- D108 〔延后：D52 ⌘K 命令面板完成后〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）⌘K 支持自然语言（G-08）。
- D109 ✅ 采纳→W7，随交样移动 Web；样件二维码标签生成并入本条（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）扫码定位与一步录入：交样扫码、品质一键接收、拍照即上传（v1.1 §05.9；9a1ab768 T15）。
- D110 〔延后：交样移动 Web 与 D214 登录完成后〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）移动端的 T1/G0 审批与续聊（C14、G-03）。
- D111 〔延后：钉钉真实联通且有客户要求飞书或企微时〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）飞书/企微入口与卡片内办理（C2；对标飞书 aily、企微）。
- D112 〔延后：规模化前或有外部 Agent 接入需求时；只读优先〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）PDOS 作为 MCP server（C3；对标 Propel、Linear、Notion）。
- D113 〔延后：D66 试点范围定了且有具体系统要接时〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）企业系统只读连接器：钉钉文档、ERP、PLM（RAG §16-3；对标 Glean、Rovo）。
- D114 ✅ 拆开：会议技能包采纳→W8（排在 P34 讨论之后）；邮件与群聊自动摄取〔延后：试点出现稳定需求，外部触发由你单独开启〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）摄取邮件、纪要和群聊，会议纪要转任务（C17、G-04；对标 Rovo、飞书妙记）。（11-02 补：原工程会议类能力 `meeting_business`、`meeting_decisions`、`meeting_minutes` 未承接，`meeting_actions`、`meeting_reading` 部分承接，建议本条扩为“会议技能包”一并定；DC-11 §8 首批第 1 项已列此方向。见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)。）
- D115 ✅ 改为实施项→W9，只存外部编号作引用（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）对接 GoodJob 的客户和商机编号（F42）。

W3b · 小Pai 与 AI 能力
- D116 ✅ 不另建，并入 work_management 的扩展→W6、W8（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）NPI 协调线技能包。现有 18 个技能包里没有协调类（a1e2d2bf T2，当时没回答）。
- D117 ✅ 采纳→W8（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）AI 价值指标，如草稿保留率、人工修改率。P33 的自动降级本来就要用这些量（10-07 运行时方案 §9）。✅ 11-09 实施，随 D37 ⑧，见 W6 段。
- D118 ✅ 已由 W1 报告 §4.5 完成，此后作 D129 固定指标（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）✅〔采纳→D06〕按操作统计工具误选率和参数错误率，并入 W1 的评测报告（M2 §7）。11-03 已并入[报告 §4.5](../docs/reports/evidence/pdos-next-real-eval-20261101/result.md)：按工具的失败率和原始原因；“误选”只能给机械近似（项目级读取在品类范围内必然被拒）。
- D119 〔延后：开通 Anthropic 路线（D65）或会话模式恢复（P39）时〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）方案 B：原生延迟加载、会话中增删工具（M2 §5、拍板表 A8）。
- D120 ✅ 11-04 随 D23 采纳：T2 准备类工具也须先加载对应技能，页面预载照常带上，见[P76](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p76) 第 4 项。11-04 已实现（已本地提交，未推送），见 D247。原记录：〔延后，与 D23 一起定〕T2 准备类工具也要求先加载技能。零技能基线可以从 27.9% 压到 9.2%，但这是能力变更，要写决策记录（M2 修订 §4）。
- D121 ✅ 不做，W1 显示兼容路线缓存已生效，已移入不采用清单（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）A 窄入口作为兼容路线的退路（M2 §6）。
- D122 〔延后：W1 §5.4 修复后参数错误率仍高且服务商支持时〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）逐个工具开 `strict: true`。P28 接入的兼容接口不保证都支持（M2 §4）。
- D123 〔延后：有真实岗位题时〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）跨编码器或 LLM 重排。合成题的 recall@10 已经是 100%（RAG §16-4；对标 Glean、Cohere）。
- D124 ✅ 采纳→W8：子任务可单独配置较小模型，同题回归不降才启用（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）隔离子任务改用较小的模型（RAG §6.4）。D06 已出（11-03）：抽取子任务占价卡成本 27%、比较子任务 3%，抽取的调用次数和输出都比主循环多；换小模型的收益上限约为总成本的 30%，可以拍板了。
- D125 〔延后：研究长运行撞到上下文上限时〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）研究子任务内用模型压缩（上下文设计 §12）。
- D126 ✅ 不做，已移入不采用清单（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）服务端 `clear_tool_uses`，图内的确定性清理已经够用（上下文设计 §6.4）。
- D127 〔延后：试点用户提出复用指令需求时；届时只作指令模板，不取得 T0〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）用户自建、保存并共享个人技能。v1.1 §06.3.4 已写，没有实现（C8；对标 Claude Skills、GPTs、Rovo）。
- D128 〔延后：选定视觉模型且试点有需求时〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）照片与图纸问答（视觉输入）；图纸/形状相似检索（RAG §20、§18；对标 CADDi）。
- D129 〔延后：D30 题集定版且 D249 环境缺口补齐后〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）真实模型定期回归（10-07 运行时方案 §9）。
- D130 〔延后：试点排障吃力时〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）统一调用链追踪（对标 LangSmith、Langfuse、OpenTelemetry）。
- D131 〔延后：随 D42、D43〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）富 Markdown 回答展示，目前只解析表格。
- D132 〔延后：随 D37 再评〕（11-04，[P81](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p81)）AI 改动的段落高亮（G-13；对标 Linear 文本归因）。

W3b · 部署、合规与商业
- D133 ✅ 采纳，只写进 v1.1 §07.1（待同步），不建设（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）部署三档与信创核对（C15、G-38/G-39）。
- D134 ✅ 拆开：运行详情显示出站去向→W8；私有部署适配与固定出站 IP〔延后：首个私有化客户〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）DeepSeek/Qwen 私有部署适配、固定出站 IP、运行详情显示出站去向（C4、G-25）。
- D135 〔延后：成员预算上线并有 1 个月真实用量后〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）三级用量上限与触顶暂停（C5、G-09）。
- D136 ✅ 不做，已移入不采用清单（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）目标客户分层与计费（C18）。
- D137 ✅ 采纳→W8：写约定，新代码遵守，存量清点列清单，动到时收口（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）守卫放置约定。须先确认它与 10-08 否决过的 C5 选项 1 不冲突（B16）。
- D138 ✅ 逐项定：模板更新差异已由 P60 定；“我的记忆”页作为 P72 显式偏好管理页随 RAG 切片 B 做；FailureMode〔延后：S3 问题闭环上线并有 20 条以上同品类已关闭 Issue〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）三项暂缓的设计各自写明恢复条件：FailureMode；个人偏好记忆与“我的记忆”页；模板更新差异（B17）。（11-02：其中“模板更新差异”已由 [P60](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p60) 定为项目绑定框架版本、新版本只出差异，不再暂缓。）
- D139 〔延后：准备对外演示或销售材料时〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）把已经领先竞品的 9 个点做成用户看得见的特性（缺口稿 §2）。
- D241 〔延后：供应承诺与替代料命令实现后（D47），届时加进 build_execution；11-08：`supply.commitment.record` 已实现并进 `build_execution` 0.1.3-draft，替代料批准仍待 D308，恢复方案继续延后；11-09：`supply.alternate.approve` 已实现并进 `build_execution` 0.1.4-draft，替代料依赖解除，恢复方案可以排期〕（11-04，[P80](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p80)）供应异常恢复方案：物料短缺或模具轮次异常时，小Pai 给出催交、替代、借料、模具恢复等选项，写明验证步骤和完成判据。原工程 `supplier_recovery` 未承接，`event_issue` 的缺料部分也没人接；现在 `build_execution` 只登记供应快照、计算齐套（见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)）。

W3b · 早期想法（10-08 之前）：丢失或口径变窄，需要定补回还是放弃
- D180 ✅ 补回→W8，写进三个研究类技能包的使用原则（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）外贸出口的市场方向。这是你 09-28 的裁决：用户声音以英文平台为主（亚马逊评论、Reddit），认证先看 UL/CE/FCC 和欧盟电池法规，用卖家精灵作采集渠道。现在 v1.1、确认稿和技能包里都找不到（PM 方法目录 §2）。
- D181 ✅ 补回→W9，加 AT-67；v1.1 §09.5 待同步（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）两项：承诺兑现率作北极星，并用预测误差校准排期；关键路径与浮时，延期只传到受影响的后继。原固定案例：A 延 6 天，B 延 3 天，C 被浮时吸收（08-24 §8、09-10 §11）。
- D182 ✅ 补回→W6（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）需要执行的决定要关联任务和回执。“已记录”不能算“已完成”，下次要核对是否落实（09-10 §4、§10）。
- D183 ✅ 补回→W9，附录 A 补测试计划命令，加 AT-68（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）项目级测试计划：绑定模板版本；增删项要写理由；必测覆盖按版本计算；对话生成新版计划时，旧结果不被覆盖。这是你 09-08 提出的场景，现在附录 A 没有测试计划的创建或修订命令（09-08 测试模板合同）。
- D184 ✅ 补回→W9（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）三项：
  - PRD 装配文档：你当时裁决“必须有实际 PRD”，含需求↔规格映射；
  - 结项时按假设逐条判支持、证伪或未知；
  - 项目复盘入库（PM 方法目录 §6）。
- D185 ✅ 拆开：按模板导出采纳→W9；回传差异候选、外审取证包、API/Webhook〔延后〕（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）导出与审核：
  - 8D、DFMEA、Gate 包、周报按客户的 Word/PPT 模板导出；手改过的导出件传回来，变成差异候选；
  - ISO 9001/IATF 外审和客户验厂用的签核取证包；
  - 受控的 API/Webhook。

  原 N7-01 注明“此条不得从总出口遗漏”，现在只有 D56 的 Excel 导出。
- D186 ✅ 拆开：事前验尸生成 FMEA 候选采纳→W8；Living FMEA〔延后：随 D138 的 FailureMode〕（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）pre-mortem 生成 FMEA 候选；Living FMEA：新 Issue 没被 FMEA 覆盖时，提出更新提案。你当时裁决“首批并行，T1”（PM 方法目录 §4）。
- D187 ✅ 补回→W8：产品方法技能包与实验设计技能包（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）方法技能：SWOT、PESTLE、五力、安索夫（你当时说“四项全借”），以及确认稿 C3 写明的实验设计技能包。现有 18 个技能包里都没有。
- D188 ✅ 并入 D93 一起采纳（11-04，[P79](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p79)）上市准备：卖点证据与销售资料，宣传口径要与实测能力一致（PDOS 产品空间.pdf p1）。
- D189 ✅ 补成只读视图→W7：品类矩阵与路线图（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）产品家族、矩阵与路线图（产品空间.pdf p4、原 N6-04）。v1.1 §01.5 仍写产品经理负责“产品路线”，全文却没有路线图。（11-02 补：原工程 `product_matrix` 产品矩阵解释未承接，并入本条，见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)。）
- D190 ✅ 11-09 随 D71 实现（[见 W9 末](#automation-templates-20261109)）。并入 D71 一起采纳（11-04，[P77](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p77)）“未推进”也要升级：“收到”不算推进，未回复和未推进分别计时（DC-12 Q10/Q14，已批准）。
- D191 ✅ 补回：纪律进 §09.5 与 D218，原指标进试点报表，真人走查进 D218（11-04，[P82](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p82)）指标纪律与原业务指标：
  - 纪律：阈值先冻结，看到结果后不下调；分母为 0 记 N/A；主动时间要计入审核和纠错；
  - 原指标：兑现率；Issue 重开与复发；齐套与快照新鲜度；员工价值按岗位分场景；
  - 单日工作流真人走查（原 Q1）。
- D192 ✅ 11-07 已实现（随 D214，[证据](../docs/reports/evidence/pdos-next-sign-in-20261107/result.md)：只由管理员建号；不能停用自己、不能更改自己的管理员身份，数据库限制性策略同样拒绝；两位管理员同时互相停用只成功一个，至少保留一位启用的管理员；重置密码后旧口令和全部会话失效。P78 的 Owner 按“启用的人类租户管理员”实现）。并入 D86 一起采纳（11-04，[P78](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p78)）账户生命周期：只由管理员建号；不能提权，也不能停用自己；至少保留一个 Owner；重置密码后旧会话失效（08-20 账户合同）。
- D193 ✅ 补回→W11，具体年限写进 D217（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）数据保留与删除：分档保留期；删除前先做引用分析和预览；被引用的证据受保护；租户退出时提供导出包（09-10 §20）。
- D194 ✅ 拆开：重复检测→W9；合并拆分〔延后：出现第一个需要合并或拆分的真实品类〕（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）品类合并、拆分与重复检测。品类是权限根，划错了目前没有修正路径（10-07 立项前审查 §3）。
- D195 ✅ 采纳→W11，写进试点规程（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）两项：试点失败按七类归因（模型误读、映射、资料矛盾、规则缺失、职责不清、连接器、界面难用）；加功能前先回答“给谁用、用在哪、少做了什么”（V2 设计包 04 §13）。
- D196 ✅ 补回→W9（S5），加 AT-69（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）主动知识复用：立项、ECR、选型时推送已验证的经验；采用、无用、纠错都要留痕；未验证的经验不作依据；作者不能当审核人（原 N3-03）。
- D197 ✅ 补回→W6，加 AT-70（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）新人与临时接手：接手人拿到最小相关资料包；代理有期限、可撤销；无关的敏感资料不泄漏（原 N3-04）。
- D198 ✅ 采纳→W8，排在框架 v1 投入使用后：小Pai 可起草差异，不能发布（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）小Pai 能否按自然语言起草流程、规则或框架的差异，用历史项目演练后由授权人发布（原 N3-09）。P33 目前写的是“小Pai 不改框架”。（11-02 补：原工程 `process_template_configuration` 流程模板配置未承接，并入本条。见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)。）
- D199 〔延后：画像待 D47 供应承诺积累半年数据；NRE 待 D105 目标成本上线〕（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）两项：供方工程画像（交期、响应、历史失败，可重算）；NRE 预算与模具费用、归属（原 N5-04、N5-06；CEHub 有 6 条相关）。
- D200 ✅ 定：试点通过后取代 CEHub；在途项目经 G0 纳管；试点期并行，达标后转只读 3 个月再退役；试点期随时可回退。转只读与退役执行前仍须你授权（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）CEHub 去留：
  - pdos-next 是否取代 CEHub；
  - CEHub 的在途项目怎么进来；
  - 何时转只读、何时退役；回滚方案。

  CEHub 目前还在生产服务器上运行，v1.1 和确认稿都没有决定（原 P5）。
- D201 ✅ 并入 D66 的租户角色目录（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）缺失的岗位：成本、资源管理员/职能负责人、知识审核人，在 v1.1 的 9 类职责里都没有；DQE/SQE/IE 的早期介入和 ID 计划也没有场景（09-10 角色稿）。
- D202 ✅ 逐条定，见 P83 第 2 项（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）口径变窄的地方：（11-02 补：原工程 `meeting_planning` 会前装配未承接，并入“会前装配”一项，见[34 项对照](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)。）（11-03：第 3 项中的日推送上限与静默时段已由 [P75](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p75) 第 6 项补回。）
  - 依赖传播的对账案例没有 AT；资源受限排程和情景比较没有判据；
  - 健康度从六维缩成四档；会议闭环的会前装配和下次复查没有去留；收敛前的方案数从 3 降到 2；
  - 单项确认 ≤3 次点击、14 天自动归档、日推送上限、静默时段都没了；
  - 性能从真实设备首屏变成本地计时；中英界面没有提。
- D203 ✅ 逐条定，见 P83 第 3 项；草稿 TTL、编号规则可配置已移入不采用清单（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）低价值零散项：汇率、Webhook、草稿 TTL、长周期测试进排期、客户视角“还在等什么”、销售接口角色、编号规则可配置。
- D204 ✅ 补了恢复条件；M4、M5 已由现有实现及 D45、D57、D74、P46 承接（11-04，[P83](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p83)）v1.1 写了“以后再做”，但没写恢复条件：
  - 爬虫订阅（§07.7）；
  - 第二、三批立项视图：差距矩阵、热力图、成本桥、价格与评分时间线（§05.8）；
  - 10-07 执行计划的 M4/M5。

W3b · 场景拓展候选（11-08 竞品对照增补；依据、竞品来源与可信度标注见[场景拓展评估](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)，其 §6 的待核对项在采纳前核对）
- D321 〔推荐：采纳→W9，与 D93/D188 认证台账同批；新来源类型须决策记录〕（11-08，[评估 J-01a](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）合规雷达：品类知识的“法规认证按地区”升为持续监测——法规源作 MCP 研究工具，变化产出带引用的 Claim 与 SpecItem/重认证候选（T1），接认证台账与 ImpactAssessment。硬日期：CRA Article 14 报告义务 2026-09-11 已生效、电池护照 2027-02-18（对标 Arena SCI、osapiens、Circularise；PLM AI 无人做“研发数据→合规”闭环）。
- D322 〔推荐：采纳→W9（S4 放行闭环），与 D185 延后的外审取证包合并设计；导出模板须决策记录〕（11-08，[评估 J-01b/J-07](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）放行包→DPP/外审数据包出口：字段映射由确定性引擎做，AI 只起草缺项说明；把运行回执、引用逐字核对、资格记录做成客户可见的审计叙事（接 D139、G-44）。电池护照等硬日期给 D185 外审取证包的延后提供了新恢复依据。
- D323 〔推荐：采纳→W8，研究类技能包，与 D180 同组；专利服务商按 P26 登记“服务商 × 数据类别”，连接器须决策记录〕（11-08，[评估 J-02](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）立项期 IP/FTO 初筛：按品类/方案关键词做新颖性与 FTO 粗筛，产出带引用的 Claim，G0 材料加“IP 风险”节；侵权结论不由 AI 下，候选标注“须专业代理复核”（对标智慧芽 Eureka：2026-03 改版、已开放 MCP/API；海外与国内 PLM 均无立项 IP 环节）。Patsnap 类 MCP 源可作 D101 情报源“有可接入数据源时”恢复条件的信号。
- D324 〔推荐：采纳→W9，随 D105 目标成本；细化为主，接外部税率源时按来源类型登记〕（11-08，[评估 J-03](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）关税与 HS 口径：CostEstimate/ImpactAssessment 加 HS 候选码、目的市场、税率，差额由确定性引擎计算；AI 只起草归类理由与“改设计换税目”候选（T1），归类以报关行/BTI 裁定为准。HS 2028 的归类治理窗口在 2026–2027（对标 Flexport 关税工程、Thomson Reuters/Descartes）。
- D325 〔推荐：延后——D47 供应承诺命令实现后，与 D241 同批〕（11-08，[评估 J-04](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）询价—比价—跟催中段：报价单抽取（已有）→确定性比价表（价差、交期差、缺项）→跟催/澄清函 T1 草稿；外发维持 T2/授权，不做自主谈判（对标 Levelpath Merlin、Pactum、Arkestro；Gartner 口径 2028 年仅 40% 采购团队用上 agent，自主谈判未被验证）。
- D326 〔推荐：不提前排期，把“现场退货单元（FieldReturnUnit）一等对象 + NFF 复测结构化字段”写为 D104 的具体承接物，新对象的决策记录随 D48 启动时再写〕（11-08，[评估 J-05](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）退货与 NFF 回流：序列号、退货原因口径、复测 TestRun、处置结论；AI 做失效聚类→Issue/FailureMode 候选（T1），喂 D186 的 Living FMEA。行业连“退货件复测结果”字段都没有；Instrumental 管产线内、Claimlane/Bruviti 管客服理赔，退货件作工程对象是空档。
- D327 〔推荐：合成项，随 D321/D323/D324 落地后拼装；G0 材料模板细化，不需决策记录〕（11-08，[评估 J-06](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）G0 风险雷达：G0 评审材料固定加 IP、法规认证、关税、供应四维风险候选，各带引用与未知项责任人（接 D100、D101）。全部为只读研究 + T0/T1 候选，竞品无人占位。
- D328 〔推荐：只改措辞——D112、D106 的恢复条件补“客户或供应商提出 agent 对接时”〕（11-08，[评估 J-08](../docs/reports/2026-11-08-agent-scenario-expansion-review.md)）A2A 趋势登记：协议入 Linux Foundation、150+ 组织支持，买卖双方 agent 询报价模式成型中。不改变 D112、D106 的延后结论。

**W3c 设计冲突，以及“想法已变但没有记录”（需要你定口径，多数要写成 P35 起的决策记录；在 W3 之后、W3b 之前处理）**

先定这 5 条，它们直接挡住施工或违反不可协商项：
- D140 ✅ 11-02 定：加 `cancelled` 终态，合并以 `superseded_by` 记录；小Pai 只取消自建未承接的，负责人可取消未完成的（一次确认），已承接的须承接人确认、承诺记为“因取消解除”，不硬删。见[P48](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p48)。待同步：v1.1 §03.3 Task 行；迁移与命令归 W6 ③。 原记录：〔挡住 D35〕任务没有“取消”和“被合并”的终态。v1.1 §03.3 和代码里的 CHECK 只有 6 个状态，P33 却允许小Pai 取消或合并任务，取消后没有合法状态可落：只能硬删或冒充完成。建议给 §03.3 加 cancelled，合并用 superseded_by 记录，再改迁移。
- D141 ✅ 11-02 定：DC-11 §6 第 5 条加明示类别“基线前项目计划”，只限 P33 第 3–5 项的命令情形，DC-11 已加注。见[P49](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p49)。代码白名单归 W6 ③。 原记录：〔挡住 D32、D35〕试点资格口径。DC-11 §6.5 的“草稿类”只指可撤回的 AI 草稿，代码白名单里也没有任何 `work.*` 操作；而 P33 的计划是直接生效的，还会分派给他人。照现状，你审完 10–20 份计划，work_management 也拿不到 T0。建议按 P33 修订 DC-11 §6.5，把“基线前项目计划”列为明示的试点类别。
- D142 ✅ 11-02 定：撤回主提示词绑定，资格仍按“租户 × 技能包 × 模型版本”，提示词版本只留作追溯；提示词换版靠 10-31 的 A/B 与具名激活，加 P42 抽检兜底。见[P50](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p50)。代码（资格绑定与 RLS）交 W8。 原记录：〔违反不可协商项 7〕10-31 的 Prompt 版本化给 T0 资格加了一个“主提示词”维度，没有决策记录。更麻烦的是，它绑定的是包含全部 18 个技能目录的整体摘要：以后加一个技能、改 work_management、加一句护栏（D54），所有技能的 T0 资格都会清零。二选一：写 P35 采纳，并改成只绑正文或本技能条目；或者撤回这一绑定。
- D143 ✅ 11-02 定：AT-57（及 AT-52 措辞）同步附录 B，并增加附录 B 与 `acceptance.json` 的文字比对检查。见[P51](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p51)。合同与工具改动交 W4。 原记录：〔机器契约漂移〕acceptance.json 的 AT-57 还是 P26 之前的口径：“未签约服务商不接收资料，查询词按协议过滤”。v1.1 附录 B 已经改了。照它写测试，会断言出与现行出站策略相反的结果。建议同步 AT-57 和 AT-52，并让 export_contracts 比对附录 B 的文字。
- D144 ✅ 11-02 定：每位发起人在一个串里各有一个会话，串内公开内容作共同上下文，私下回复只留在本人会话，守卫不改；修订 P34 第 4 项。见[P52](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p52)。待同步：v1.1 §05.4 共享串第 4 点；实施归 W6 ⑥。 原记录：〔挡住 D37⑥〕共享串里第二位成员 @小Pai 时，会被数据库的会话属主守卫（kernel_run_guard）拒绝，与 P34“一个串一个会话、每轮按发起人权限”冲突。动工前先定：每位发起人各开一个会话，还是改守卫和会话模型。

W3c · 业务规则与权限（会返工）
- D145 ✅ 11-02 定：静默只对请求人与对象负责人，受派人的承接请求照常通知，见[P53](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p53)。待同步：v1.1 I11、DC-11 §5 第 1 条加注。 原记录：T0 分派会给受派人产生待办和通知，但 v1.1 I11 和 DC-11 §5.1 规定 T0 成功“不产生任何待办或通知”。建议补一句：静默只针对请求人和对象负责人，给受派人的承接请求属于业务事实。
- D146 ✅ 11-02 定：单列“运行投递”命令，由运行宿主在受众核对后执行，模型不能调用，不需 T0 资格，见[P54](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p54)。待同步：附录 A 表下加一行。 原记录：`ai.thread.invoke` 登记为 READ，但它要把小Pai 署名的回复持久贴进共享串，却没有合法的写入口；`discussion.message.post` 又是“仅人工”。建议单列一条 T0 回帖命令。
- D147 ✅ 11-02 定：G0 物化时同一事务把加入受众的人登记为成员，角色留空，见[P55](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p55)。 原记录：“成员即受众”与 G0 加受众：G0 决定会把处置负责人加入受众，而 P34 说成员只由负责人维护。建议 G0 物化时在同一事务里登记成员；私有项目加了成员，就转为“指定受众”。
- D148 ✅ 11-02 定：可以移除；移除后只保留本人未交接事项的可见与办理，交接完成后完全移除，账号停用一律失去访问，见[P56](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p56)。 原记录：成员离开后立即看不到项目，但交接完成前原责任不变，已承接的任务会没人能提交。二选一：交接完成前不能移除；或者给原责任人只留本人事项的最小可见。
- D149 ✅ 11-02 定：自动化范围取规则负责人当前范围与规则声明范围的交集，每次重核；G0 后建计划登记为系统规则、负责人为项目负责人，见[P57](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p57)。待同步：v1.1 §06.5 加注。 原记录：自动化运行用谁的权限，三处说法不同：v1.1 §06.5 写“服务授权”；P34 写“不超过规则负责人当前范围”；P33 的 G0 后自动建计划又要写多个非触发对象。建议统一为所有自动化都不超过规则负责人的范围，G0 后建计划登记为系统规则，owner 为项目负责人。
- D150 ✅ 11-02 定：“日期”只指承诺日期，计划日期照常重算；承接时默认一并承诺（预填计划日期，可改），后台分两条记录；可选“日期待定”只承接，见[P58](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p58)。D70 随之定掉。 原记录：两处措辞要定：P33 说已承接任务的“范围或日期”变更须承接人确认，没说是计划日期还是承诺日期；P33 说“承接时形成承诺”，S5 合同却说承接后仍未产生日期承诺。建议“日期”只指承诺日期；承接与承诺分开记录（与 D70 有关）。
- D151 ✅ 11-02 定：适用与否只按型号属性的固定规则判定；属性满足仍要去掉的由负责人具名决定，小Pai 只起草理由；红线不能去掉，见[P59](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p59)。 原记录：NPI 稿允许小Pai 在 T0 计划里“去掉”条件成果，但 DC-11 §7 规定豁免属于 T2。建议适用与否只按型号属性的固定规则判定；规则以外的去掉，一律交负责人具名决定。
- D152 ✅ 11-02 定：项目绑定框架版本，新版本只出差异，负责人一次确认升级，新增红线进下次阶段评审；被引用的角色只能停用不能删除，见[P60](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p60)。同时定掉 A1 第 7 项和 D138 的“模板更新差异”。 原记录：框架出新版本时，在途计划是自动重排，还是项目绑定版本、只出差异（与 D138 有关）。另外，角色目录以 T1 发布时，可能删掉 T2 框架引用的角色，发布前需要校验引用。
- D153 ✅ 11-02 定：健康度五档，有阻塞 > 待核对 > 有风险 > 待批准 > 正常；标签统一为“有阻塞”；出口成果只经 §03.7 规则影响健康度，见[P61](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p61)。待同步：v1.1 §05.12.6。代码已改（11-09 随 D37 ⑦）：“受阻”→“有阻塞”，“有条件”并入“有风险”并排在“待批准”前，每档带规则 id 与版本。 原记录：健康度：P17 是四档，代码输出五态（多一个“待核对”）；NPI 稿又说按出口成果计算。建议在 P17 补上“必需未知→待核对”，出口成果只经 §03.7 的规则进入（随 D36）。
- D154 ✅ 11-02 定：读过客户私有资料的只能分享链接；其他受限来源可分享正文，但须发起人确认并记回执；P31、P34 统一按全部读取来源核对，见[P62](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p62)。 原记录：发起人把小Pai 回复的正文分享出去，可能突破 I14（共享输出不能突破来源受众）；驾驶舱稿自己也承认判断不了正文依赖哪条来源。建议至少对客户私有来源禁止分享正文。另外，P31 和 P34 的受众核对口径不同（一个按引用来源、默认私发，一个按全部读取来源、默认贴回），却说共用一套实现。
- D155 ✅ 11-02 定：推给本人钉钉按出站处理，本人开启，只推标题和链接，客户私有对象只推“你有一条新通知”，见[P63](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p63)。 原记录：钉钉推送算出站还是真实外发：如果是外发，按 v1.1 §06.6.2 需要 T2 或明确授权。客户私有对象的标题算不算派生内容也要定。建议推送由本人明确开启，私有客户对象只推“你有一条新通知”。
- D156 ✅ 11-02 随 D144 关闭：每位发起人一个会话，工作状态与约束按 P32 归本人，见[P52](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p52)。 原记录：共享串的会话工作状态归谁：P32 是每个会话一份，约束取本会话用户的原话；P34 是多人共用一个会话。建议共享串只收公开轮次，约束按说话人分开，只能由原说话人删除。
- D157 ✅ 11-02 定：可为他人准备候选，确认时按确认人权限重核，来源须对确认人可见，回执记请求人与确认人，见[P64](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p64)。 原记录：确认卡写的是“只有有权的人能点”，但代码要求确认人就是发起人。建议允许为他人准备候选：确认时按确认人自己的权限重核，回执记录“请求人≠确认人”。
- D158 ✅ 11-02 定：一次确认候选，周期起草进负责人“要我决定”，DC-11 §8 已加注，见[P65](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p65)。 原记录：状态更新草稿三处说法不同：DC-11 §8 说是 T0 具名草稿；附录 A 和 P18 说是 T1 候选；P34 又让它进“要我确认”。建议定为 T1 候选，并进待办。
- D159 ✅ 11-02 定：分派档位以 P33 加注为准；值班摘要只列小Pai 自己的写入，引擎重算单列“系统重算”，见[P66](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p66)。待同步：v1.1 §06.5 正文加注。 原记录：两处文字不一：v1.1 §06.5 L1030 正文写分派按 T1/T2，紧挨着的 P33 加注写 T0；驾驶舱稿的值班摘要把引擎重算的预测记成了小Pai 可撤回的动作。

W3c · 小Pai 与 AI
- D160 ✅ 11-02 定：改代码对齐上下文设计 §4.1（技能正文 → 运行信封 → 会话历史 → 工作状态 → 当前问题），不改设计、不写记录；实施交 W8，排在 W1 评测跑完之后。 原记录：上下文的排列顺序与上下文设计 §4.1 相反：代码是“信封 → 技能正文”，设计是“技能正文 → 信封 → 当前问题”。结果是技能正文进不了缓存前缀，当前问题也不在末尾。
- D161 ✅ 11-02 定：R 按本次调用输出预算 + 4k（主循环缺省 8k），连接配置的输出上限只作钳制，窗口须为公布或实测值，构造值须注明，见[P67](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p67)。W1 报告口径由 D06 处理。 原记录：输出上限 524288 会让聚焦上限 F 归零（F = min(W − R, 64k)，R = 输出上限 + 4k）。评测里的窗口 592288 是按公式反推出来写进配置的，不是模型的实测窗口。建议 R 改用本轮的输出预算，报告里注明窗口是构造值（与 D06 有关）。
- D162 ✅ 11-02 定：等待中的确认与 G0 结果照常办理，续写改开续接运行，原运行标“已换版”；撤回不查版本，见[P68](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p68)。D27 的 8 条撤回失败随此修。 原记录：提示词或技能一换版，所有处于等待状态（等 T1 确认、等 G0 结果）的运行都会报 VERSION_CONFLICT。二选一：恢复时按运行记录的原版本执行；或者正式确认“换版即失败关闭”。
- D163 ✅ 11-02 定：“注册执行图”只指 AgentKernel 图，聊天模型调用必须经过它；摘要、钉钉等确定性图改用各自注册名，要用模型就发起子运行；embedding 按 P30 单列，见[P69](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p69)。实施交 W8。 原记录：注册执行图的守卫只校验名称 "xiaopai"，摘要图、钉钉图、embedding Activity 都以这个名义进入。目前没有违规调用，但以后给摘要加模型导语时，会绕过技能和校验而不报警。先定“注册执行图”是否只指 AgentKernel 图。
- D164 ✅ 11-02 定：作为 P26 的细化，协议内缺省改为允许缓存，登记时可明确关闭，见[P70](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p70)。实施交 W4。 原记录：服务商协议多了一个“是否允许提示缓存”的字段，缺省为关（迁移 s0_0853），而 P26 只按“服务商 × 数据类别”限制，疑似加严。二选一：作为 P26 的细化登记，或者改成缺省允许。
- D165 ✅ 11-02 定口径（不写记录）：CTX-08 只算模型行为证据，不算撤权传播验收；撤权传播用真实撤权命令放到 W10 验收。W1 报告的标注由 W1 会话处理。 原记录：真实评测直接插入登录和授权，并用删除受众行代替撤权。所以 CTX-08 的结果只能算模型行为证据，不能当作撤权传播路径的验收。
- D166 ✅ 两处登记缺失：钉钉的账号绑定和凭据管理已经有 10 条接口，但没登记进操作合同（P31 要求实施时登记）；`proposal.share` 的档位三处不一，并入 D20-A4 一起定。（11-02：`proposal.share` 档位已由 [P44](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p44) 定为“小Pai 仅准备、负责人在页面办理”；钉钉接口登记也已定：12 个接口按现有实现补登记为辅助操作，档位见[P71](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p71)，合同改动交 W4。）

W3c · 界面
- D167 ✅ 11-03 定：视觉与交互以 `ui-lab/platform`、DESIGN.md 和 10-23 候选稿为准，栈与品牌 token 不变；AGENTS.md 第 3 条已改，见[P74](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p74)。 原记录：视觉参照有三处说法：AGENTS.md 第 3 条要求遵循 08-09 的 UI 基线和原稿；设计索引把原稿标为“历史视觉”；10-25 你要求按 ui-lab/platform 复刻。建议改 AGENTS.md 第 3 条，以 ui-lab/platform 和 10-23 候选稿为准。
- D168 ✅ 11-03 定：UI 基线只保留 §1 token 与 §4 反模式，§2–§3 已标“已被取代”，见[P74](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p74)。 原记录：UI 基线 §2–§3 仍是原工程的信息架构。它规定的“接受和应用分两步”“收件箱 = AI 发现队列”，与 v1.1 的“T1 一次确认”和现在收件箱的含义冲突。建议基线只保留视觉 token，其余指向 v1.1 §05 和候选稿。
- D169 ✅ 11-03 定：以代码和 DESIGN.md 为准重写基线 §1 为一套；圆角 6px / 8px / pill，待定色回黄色 `#a16207`，补断点，见[P74](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p74)。重写与改代码交 W7。 原记录：视觉数值不一：
  - 中性色有三套；字号、留白、宽度、动效有四套；
  - 代码里有 6/4/7px 的圆角，而基线规定只有 8px 和 pill 两种；
  - 待定状态色回到了琥珀色，基线当初专门避开它；
  - 窄屏断点 P22 说归 UI 基线管，基线里却没有。

  建议以代码和 10-25 的 DESIGN.md 为准，回写基线。
- D170 ✅ 11-03 定：以候选稿为准（概览、任务、计划、文件、更多），旧链接改到新视图，旧八标签工作区下线，见[P74](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p74)。待同步：v1.1 §01.6 项目分区、§05.3“项目现在”行；实施交 W7。 原记录：项目内分区有三个版本（v1.1、候选稿、基线）。代码里还并存两套项目工作区：动态、试产、开测承诺的链接会跳进“品类”区里的旧八标签。建议以候选稿为准，旧链接改到新视图。
- D171 ✅ 11-03 定：单项目首页叫“概览”；“驾驶舱”只指管理者多项目汇总；产品管理入口按 P35；删掉界面上的 T0 字样，见[P74](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p74)。实施交 W7。 原记录：文字不一：“现在”和“概览”同物异名；产品管理分组的入口三处各不相同；界面上出现了 T0 字样，违反已确认的 B18；“项目驾驶舱”一词既指多项目总览，又指单项目。
- D172 ✅ 11-03 全部按推荐，见[P75](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p75)：负责人默认概览、其他人默认任务；管理者驾驶舱是“项目”页第四种视图，文字计数加分组项目行，不做卡片墙；“要我协调”归入“要我决定”；离线可存本地草稿、提交须在线；手机推送只推提及和要我决定，15 分钟未读才推，22:00–08:00 静默，每天最多 20 条；shadcn 按需引入，弹层用原生 dialog；项目集登记进 §02.1 和辅助操作。实施交 W7，合同交 W4。原记录：界面口径待定：
  - 导航：进入项目默认看“任务”还是“概览”；管理者驾驶舱挂在哪里；驾驶舱汇总用什么形式（不做卡片墙）；新增的“要我协调”分组是否保留；
  - 行为：离线时能否编辑本地草稿（v1.1 说能，候选稿说不能）；“推送到手机”的规则；
  - 实现口径：shadcn 是否只用 Button 和 token、弹层用原生 dialog；
  - 合同：项目集对象还没进合同。

W3c · 想法已变但没有记录
- D173 ✅ 11-02 定：只做本人显式偏好，取代 DC-12 Q4，见[P72](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p72)。 原记录：〔你〕DC-12 Q4 已批准“自动记忆，不必说‘记住’”，后来 RAG 设计 N12 改为只做显式偏好，没有任何 P 记录推翻它，需要补记录。
- D174 ✅ 11-02 定：前两项承接说明已写入[P73](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p73)；第 3 项的[逐项对照表](../docs/reports/evidence/debt-consolidation-20261101/shadow-capabilities-mapping.md)已完成：34 项中已承接 7、部分承接 12、未承接 10、放弃 5（4 项多席位 AI 讨论与单 Agent 冲突，1 项被管理者驾驶舱取代）。未承接的已挂到 W3b 的 D85、D105、D114、D189、D198、D202，供应恢复新增 D241。 原记录：补承接说明：
  - 持续委托（DC-12 §5）改由 AutomationRule + WorkRequest 承接；
  - DC-13 首批第 3 项“钉钉转发 → 状态更新”被 P31 改为只读问答；
  - 单 Agent 方案的 34 个能力合并成了 18 个技能包，但没有逐项承接清单。

**W4 小缺陷与测试债（实现缺口；一个代码会话，可与 W3 并行）**
- D24 ✅ 11-04 `operations.json` 中 `provider.agreement.register`（POST …/provider-agreements）与 `my_work.query`（GET /v1/personal/attention）改为已实现并绑定实际接口，`tools/export_contracts.py` 支持 GET；api.py 三处写死的 `model_available: False` 删除（没有任何读取方）。 原记录：契约标记失真：`provider.agreement.register`、`my_work.query` 已实现，仍标为未实现；api.py 三处 `model_available` 写死为 False。
- D25 ✅ 11-04 “要我决定”不再排除负责人本人评审（`domain/my_work/attention_decisions.py`）；试点停用后仍列出，但标为受阻（`NAMED_DECISION_REQUIRED`），与 G0 决定命令同一规则。新增 PG 用例 `test_pilot_g0.py::test_pilot_self_review_is_listed_under_decide_and_blocked_after_the_pilot_ends`。 原记录：本人自评的 G0 不进“要我决定”（`personal_attention_decisions.py:106` 只认 owner≠requester），按 P27 应放行。
- D26 ✅ 11-04 新增 `domain/change/disciplines.py`：变更政策要求的专业里有没有签核角色的（客户、认证），导入政策和准备变更单时都返回 `CHANGE_DISCIPLINE_UNSUPPORTED`（422，“暂不支持……”）；专业角色清单补上后自动放行，根治仍随 D21-B2（P79）。 原记录：认证类、客户类专业变更会死锁，先返回明确的“暂不支持”；根治随 D21-B2。
- D27 ✅ 11-07 已清（只改测试和夹具，不改产品行为；本地提交、未推送，[前后对照](../docs/reports/evidence/d27-test-debt-20261107/README.md)）：
  - 无库全量：HEAD 169 个失败 → 0（10654 通过）。原分四类的口径基本成立：① 过时替身 157 个（产品对象缺后来新增的 6 列 112、变更捕获要真实 `CoverageRead` 12、假运行缺 `project_id` 被计算证明吞成 `deterministic_proof_required` 21、其余各缺一个字段或查询分支 12）；② 即上面那 21 个，不是证明夹具缺失；③ `ScriptedProvider` 2 个（另需把工具面补回 P76 前的大小才能触发清理）；④ 缺数据库标记 5 个，照现有写法加 `skipif`。另有 5 处按现行行为改断言并注明依据：S2 分批接收（P13，10-17）3 处、品类列表 10-31 加的聚合字段、schema 冻结守卫登记 10-31 的 `model_configuration/dto.py`（钉精确摘要）。
  - PG 清单：D242、D245、P76 第 4 项、D254/D255 四份去重 89 个，加 11-04 摘要类 14 个、10-31 报告的 8 条撤回所在两个文件、`test_project_current_context_pg` 整文件，共 115 个，HEAD 103 失败 4 错误 → 修复后 分三轮复跑后只剩 4 个（见下）；连同 S1 候选摘要、整次撤回和受共享夹具影响的整文件共 184 个，180 通过、4 失败，即下面已归因的 4 个。
    - 读取绑定被拒 27 个、改收到 `VERSION_CONFLICT` 6 个、证据命令 9 个、对账 1 个和**那 8 条撤回**：夹具记录的工具定义摘要没跟上“披露按已加载技能和运行范围推导”，改用 `disclosure_digest`，追加加载技能时照网关做法记入披露链。8 条撤回的失败点在建 T0 写入的来源校验，撤回本身不查版本，**与 P68 无关**；P68（W8）仍未实施。
    - 摘要类 7 条和 `test_activity` 3 条：D243（11-04）给 `advance()` 加了活动取消保护，测试直接调用时缺替身（那次会话这些用例因缺检查点环境变量没跑到）；照 D243 已改的两处写法补上。
    - 零散：门函数比现行 head（s0_0854）定义；平台关联改用 G0 变体（P23）；开发预算夹具按 P67 输出预算和 64k 窗口；会话历史无权限时为 403（10-22）；EXPLAIN 渲染展开参数；`work_state` 冻结后回放基准改在 attach 之后；剧本宿主置空 `model_step`（10-31 起图优先走网关）；知识检索语句数为 3 条批量读取加每事务一次 `SET LOCAL jit=off`；整次撤回夹具的触发方式与运行一致。
    - 环境：以前的运行器没给检查点库地址和 Temporal 本地程序，HEAD 上 11 条因此直接报错；补齐后 4 条通过，另 7 条就是上面的 D243 替身问题。S1 的 6 条候选摘要在 HEAD 上已通过。`test_project_current_context_pg` 整文件按顺序跑全过，未复现顺序依赖。
  - 剩余 4 个，均已归因：D258 迁移缺陷 1 个、D259 企业检索缺陷 2 个（下两条）；`test_recovery_pg` 检索 p95 1.47 秒超过 1 秒 1 个，两种核对模式在 1 秒内、语句数恒定，整机负载 13–15、测试库 1.1 GB，按环境性能归因，未改阈值（性能验收按 P13 暂缓）。
  - 合并提示：主工作区未提交的改动涉及 agent kernel 与 `test_graph.py` 等 4 个测试，本次未动这 4 个；本次改了 39 个测试文件，与主工作区可能重叠的只有本清单。新编号从 D258 起，主工作区清单已有 D253，合并时核对编号。
  - 11-08 已合并进本地集成分支 `claude/frosty-villani-38f085`（未推送，见本组末尾的集成记录），D258、D259 保持原号。补记：无库全量的 ERROR 不全是缺库：`tests/agent/kernel/test_registered_snapshot_reads.py` 的 27 个用例，夹具把 `RunScope.citation_ids` 传给 `AgentRun`，以 `TypeError` 报错，`d730291d` 的干净副本上同样如此；D27 当时把它们算进了 1882 个缺库 ERROR。11-08 已修（见本组末尾的缺陷清理记录）。
  - 原记录：测试失败：HEAD 10 条回放/撤回失败（2 条 work_state 旧断言、8 条撤回 VERSION_CONFLICT）；S1 6 个摘要夹具失败；141 项测试替身层失败（capa、launch_plan、change 一带），重跑后定性。W1（D242）的受影响范围回归另有 48 个 PG 测试在不含修复的 HEAD 上同样失败，集中在 `test_computed_claim`、`test_m3_*`、`test_deterministic_proofs`（[清单](../docs/reports/evidence/pdos-next-real-eval-20261101/regression-preexisting-failures.txt)），可能与上面几类重叠，重跑定性时一起核。D245 的受影响范围回归（11-04）又多出 37 个在 HEAD 上同样失败的测试，集中在 `test_evidence_commands_pg`、`test_private_analysis_pg`、`test_baseline_watermarks_pg`、`test_private_spec_compare_pg`（[清单](../docs/reports/evidence/pdos-next-real-eval-20261101/regression-preexisting-failures-d245.txt)）；另有 `test_project_current_context_pg` 的 1 个用例单独重跑通过，疑似依赖执行顺序。（11-04 定性，W4 未修）无库全量 171 个失败在 W4 改动前后逐项相同，按原因分四类：① 测试替身过时约 120 个：`SimpleNamespace` 假会话、假对象跟不上代码接口（62 个 unhashable、51 个 `assert False`），集中在 `quality/capa_link_phases`（90）、`projects/test_launch_plan_preview`（22）、`change/test_change_capture_deadline`（12）；② 计算事实的夹具缺少确定性证明约 20 个（PG 侧另 15 个同类）；③ 假服务商 `ScriptedProvider.turn()` 不认 `prompt_identity`（2 个）；④ 需要数据库却没标记的 5 个。PG 侧（D242、D245 两份清单）另有：读取绑定被拒 27 个、6 个断言改收到 `VERSION_CONFLICT`，都是夹具早于更严的读取证明绑定；工具或技能摘要已变 9 个；零散 7 个（上下文窗口夹具过小、数据库函数文本漂移、测试库有超级用户拥有的函数等）。8 条撤回 VERSION_CONFLICT 随 P68（W8）修。修法是逐类更新夹具，建议单独做一次。
- D28 ✅ 11-04 28 个测试子目录补 `__init__.py`，14 处同目录裸导入改为相对导入；`tests/conftest.py` 忽略 iCloud 编号副本；新增 `tests/test_layout.py` 检查两者；`PENDING_LIMIT` 131→116。全量收集与改动前逐项一致，只多出新增用例。 原记录：测试卫生：28 个 tests 子目录缺 `__init__.py`，加一条 collect 检查；pytest 排除 iCloud 副本；`PENDING_LIMIT` 从 131 收到 116。
- D29 ✅ 11-04 两项（`preload_when` 归 W8，由 P76 第 4 项 (c) 落实；11-04 已改为服务器判定的条件，已本地提交、未推送，见 D247）：MCP 页文案按 P26 改为“每次调用的服务商与资料类别记入回执；已登记有效协议的按协议限制”；技能包政策漂移检查：“不授权治理操作、不执行 T2”的检查从 6 个项目技能包扩到全部 18 个（各操作档位与注册表一致的检查原已存在）。10-22 原卡片的具体内容没找到，按不可协商项 1 落实。 原记录：三件小事：`mcp-management.tsx:134` 的旧口径文案按 P26 核对；技能包与政策的漂移检查（10-22 的卡片一直没启动）；18 个技能包写了 `preload_when` 但没有任何代码读取，改成服务器可判定的条件。W1 实测：每个品类运行都由服务端预载 `proposal_drafting`（约 3.8k token），与问题内容无关。
- D53 ✅ 11-04 立项提案页的“新建提案”改为弹窗：与小Pai一起起草，或手动创建（标题、来源、简述；服务器确认预览后本人确认，人工办理 `proposal.create`），并说明小Pai不可用时可手动创建。本地开发环境实测创建成功并进入新提案页。 原记录：停用 LLM 时仍能手动建提案，并显示失败说明（拍板表 §5.3 F06、AT-45）。UI 重建后没再看到这个入口。
- D57 ✅ 11-04：Worker 活动线程数改为 `PDOS_WORKER_ACTIVITY_THREADS`（缺省 4，限 1–64），Temporal 并发活动数限为同值，避免活动排队等线程时执行超时已在计时（与 D243 有关）；幂等重放这一项已不成立：领域命令在校验前就直接返回原回执，小Pai读取重放时的复核是有意保留的（旧结果不代替当前权限）。未知调用按服务商输出上限占账一项由 D252 改为按 16k 预算占账，11-06 真实回归复核：8 次未知调用共占账 0.34 美元，每次约 0.043 美元（W1 每次约 0.69 美元），见[11-05 回归结果](../docs/reports/evidence/pdos-next-real-eval-20261105/result.md) §5.3。 原记录：运行成本口径：Worker 线程数写死为 4（`workflows/worker.py:244`）；未知调用按上限占账；幂等重放会重走校验（F45）。W1 实测（D06）：输出预留按服务商上限 524288 计，未知调用每次约 0.69 美元，约是正常调用的 140 倍（原估 3.4 倍）；51 次共占账 35 美元，是实计费用的近 5 倍，其中 33 次其实是完整响应（D244）。按 D161 改为“本次调用输出预算 + 4k”后应大幅回落，改完复核。
- D245 ✅ 11-04 已修并本地提交（未推送）：新增 `agent/kernel/tool_arguments.py`，模型给的工具参数校验失败时退回 `VALIDATION_FAILED`（422，列出字段路径和错误类型；校验说明不含提交内容时一并给出），模型可以改参数重试，不再整轮崩溃。共 21 处首次校验改用它，覆盖主循环读取、计算、比较、会话历史、企业检索和抽取、研究、比较子任务；`m3_object_reads` 原有的同类写法并入。已有校验的入口、续读恢复和对已校验参数的二次核对不改。回归：`test_tool_arguments.py` 的三个 W1 崩溃点用例在不含修复的代码上以原 `ValidationError` 失败、修复后通过；受影响的 122 个测试文件 1328 通过，失败项与 HEAD 一致（31 个在 D242 清单内、37 个在 HEAD 上同样失败，见 D27），另有 7 处原断言 `ValidationError` 的测试按新行为改为断言工具错误。11-06 真实回归：参数校验崩溃 0（W1 4 个运行），参数错误都退回模型；但有两个工具下发时没有参数定义，模型改不对，见 D255。 原记录：模型参数通过了工具定义的格式检查，但处理函数的 pydantic 校验更严时，`ValidationError` 不会退回模型，而是让整轮 `INTERNAL_ERROR`。三处直接 `model_validate`：`agent/kernel/extract_service.py:125`、`agent/kernel/platform_reads.py:26`、`agent/enterprise_search/assistant_adapter.py:216`。照 `host.read_result`（`host.py:310-313`）的做法转成 `VALIDATION_FAILED`，再查其他处理函数有没有同样的写法。W1 中 4 个运行因此失败。
- D250 ✅ 11-04 合同目录对齐（W3 交接：P43、P51、P71、P75 第 8 项）：P43 的两条阶段命令早已登记在辅助操作目录，90≠86 已不复现；AT-52、AT-57 按附录 B 同步，`tools/validate_contracts.py` 增加附录 B 与 `acceptance.json` 逐字比对；钉钉 12 个接口登记为 6 个辅助操作和 1 个入站入口，项目集两类写入登记为辅助操作；校验器检查登记的接口都存在，钉钉与项目集没有未登记的写接口（改坏任一条时检查失败，有用例）。v1.1 附录 A/B 正文待集中同步。
- D251 ✅ 11-04 P70：已登记的有效协议内提示缓存缺省允许，只有明确关闭才关（`agent/kernel/policy.py`）；登记页复选框缺省勾选，改为“允许服务商提示缓存”，取消勾选写入回执。字段可空、空即未声明，不需要迁移。
- D258 ✅ 11-08 已修（新迁移 `s0_0862_definer_owner`，占位号，集成时按真实 head 重排；本地提交、未推送，[证据](../docs/reports/evidence/w4-defects-20261108/README.md)）：函数转给 `pdos_next_owner`；升级末尾再查 public 下的定义者函数（扩展成员除外），属主只能是 `pdos_next_owner` 和两个已登记的维护角色，否则报错；降级保留属主（同 `s0_0720`）。`test_actual_owner_and_definers_are_non_superuser` 通过，并加了表属主断言（见 D284）。 原记录：`s0_0776` 新建的 SECURITY DEFINER 函数 `change_receipt_key_bound(uuid,uuid,uuid)` 没有转给 `pdos_next_owner`，属主留在执行迁移的账号上（测试库里是超级用户 `postgres`）。`s0_0720` 只把当时已有的函数一次性转给属主，之后新建的定义者函数要自己 `ALTER FUNCTION … OWNER TO pdos_next_owner`（如 `s0_0728`、`s0_0771`）或在 `SET LOCAL ROLE` 下创建。后果：该函数以迁移账号的权限执行，绕过 RLS，只靠函数体自己的谓词限范围；部署时迁移账号若是 RDS 管理员也一样。`test_review_fixes.py::test_actual_owner_and_definers_are_non_superuser` 因此失败（public 下唯一一个超级用户属主的定义者函数）。改法：新迁移 `ALTER FUNCTION public.change_receipt_key_bound(uuid,uuid,uuid) OWNER TO pdos_next_owner`，并加一条迁移检查：head 上不得有属主不在登记角色内的定义者函数。
- D259 ✅ 11-08 已修（按第一种改法，`agent/enterprise_search/indexing.py`；本地提交、未推送，[证据](../docs/reports/evidence/w4-defects-20261108/README.md)）：投影给知识条目的缓存原件补上 `retrieval_catalog` 推导的依据原件。缓存仍只扩大扫描核对范围，可读性仍由当前目录判定；读路径不加语句（批量语句数用例仍是 4 条）。两个用例通过。 原记录：以客户上传原件为依据的知识条目在检索里永远拿不到，覆盖状态停在 partial（“部分当前可读来源尚未完成索引或当前扫描复核”）。原因：`agent/enterprise_search/indexing.py` 的 `project` 用 `select_sources`→`catalog(["knowledge"])` 写投影，`SearchSource.original_ids` 只含条目自身的原件（为 `[]`），不含 `source_refs` 依据里的原件；`sources.py` 的 `dependency_originals` 只在缓存为 NULL 时才回退实时推导，于是依据原件不进入 `safe_originals` 的核对集合，`query.py` 把命中的条目判为不安全剔除。实测：同一原件用本人会话直接调 `safe_originals` 是安全的（扫描绑定一致、闸门放行），投影里却是 `[]`。影响 `test_knowledge_retrieval_authority_pg.py::test_knowledge_original_scan_proof_precedes_http_metadata` 和 `test_knowledge_dependencies_pg.py::test_updated_knowledge_dependency_still_uses_actual_original_scan_proofs`。改法二选一：投影按 `retrieval_catalog` 写入依据原件；或 `dependency_originals` 对知识条目始终补算依据原件（缓存只扩大核对范围）。
- D260 ✅ 11-08 已修，共三处（本地提交、未推送，[证据](../docs/reports/evidence/w4-defects-20261108/README.md)）：① `s0_0800` 降级用已渲染的文本重建截止期约束，PostgreSQL 把数组强转重解析成逐元素强转，`s0_0784` 的逐字核对就拒绝；改为重放 `s0_0784` 自己的原始输入（`schema_s0_0800.py`）。② 再往下到 `s0_0727`：它对 public 全部函数做指纹，而 `s0_0836` 有意保留 pgvector 扩展，降级后多出 118 个扩展函数；按你 11-08 的决定，指纹查询排除扩展成员（与 `s0_0720` 同规则）。这一版次链上 public 没有扩展，冻结的指纹值不变，PDOS 函数仍逐字核对。③ 最后一步 `s0_0001` 在单个事务里报 `out of shared memory`：`tools/local_environment.py` 建测试库时把 `max_locks_per_transaction` 调到 256，迁移的事务方式不变。`create` 的 head→base→head 往返和 seed 通过。 原记录：`tools/local_environment.py create` 在 d730291d 上失败：迁移往返降到 base 时，`s0_0784_release_exceptions.downgrade` 报“Release exception requires its exact reviewed confirmation predecessor”。降级事务整体回滚，库停在 head 可继续用，但 `seed()` 不会执行。要查是哪一步之后的降级没有把函数恢复到 0784 审核过的原文。
- D261 ✅ 11-08 已修（本地提交、未推送，[证据](../docs/reports/evidence/w4-defects-20261108/README.md)）：钉钉摘要表的租户索引由 `s0_0863` 补建（`Row.tenant_id` 声明了索引，其他 Row 表都有）；6 个 HNSW 部分索引在 `ChunkEmbedding` 里用 `postgresql_ops` 登记，表达式真正参与比对（故意改错一维会报差异）。ORM 与库比对 0 项。 原记录：`test_migration_matches_orm_and_test_guard` 在基线就失败：模型与库有 7 项漂移，`ix_dingtalk_summary_deliveries_tenant_id` 只在模型里，6 个 `ix_enterprise_embedding_hnsw_*` 只在库里。要么补迁移，要么在模型或比较规则里登记。
- D262 ✅ 11-08 已修（只改测试；本地提交、未推送，[证据](../docs/reports/evidence/w4-defects-20261108/README.md)）：`test_material_proofs_pg` 两个换技能的账本夹具按 P76 第 4 项记录所加载技能推导的披露摘要（同 D27 对 `test_evidence_commands_pg` 的改法），19 个全部通过，原先 3 个 `VERSION_CONFLICT` 也回到期望的错误码。 原记录：`test_material_proofs_pg`（19 个）和 `test_evidence_guards_pg`（4 个）共 23 个 PG 用例在基点 `d730291d` 上同样失败，错误逐条相同，D27 的清单和修复都没覆盖这两个文件（[对照记录](../docs/reports/evidence/w6-d33-project-team-20261107/result.md#受影响测试)）。其中 20 个失败在 AI 写入预备时报“实际登记工具或技能允许操作已变化”，与 D27 修好的整次撤回、证据命令同类，多半是夹具没跟上 P76 第 4 项的工具下发收窄；另 3 个断言期望 `CONFIRMATION_REQUIRED` 或 `FORBIDDEN_SCOPE`，实得 `VERSION_CONFLICT`。
  - 11-08 集成核对：这 23 个与 D27 已归因的 4 个（D258、D259 两个、检索 p95）没有重复。集成分支带上 D27 的夹具修复后，`test_evidence_guards_pg` 的 4 个通过；还剩 `test_material_proofs_pg` 19 个（16 个“实际登记工具或技能允许操作已变化”，3 个得到 `VERSION_CONFLICT`），未修。
- D284 ✅ 11-08 修 D261 时发现并修（`s0_0863`，占位号）：`s0_0852` 只把自己的函数转给了 `pdos_next_owner`，新建的 `dingtalk_summary_deliveries` 表属主留在迁移账号（测试库里是超级用户 `postgres`；`s0_0843` 的 6 张钉钉表都转过）。已转给 `pdos_next_owner`；升级末尾检查 public 业务表（框架表 `environment_guard`、`alembic_version` 除外）属主，属主测试加了表属主断言。降级保留属主。
- D285 ✅ 11-08 查 `test_category_source_consumers` 时发现并修（`s0_0864`，占位号）：`s0_0733` 的 `m3_evidence_root` 用 `SELECT … INTO STRICT`，来源不在本品类或已不存在时报 P0002（“query returned no rows”），而不是守卫统一的 23514，经 API 时会成为 500 而不是 422。拒绝本身不变，只改错误类别；升降两向逐字核对函数原文。同类 STRICT 还有 `m3_evidence_claim_guard` 读 `agent_runs` 一处，未改，也没有用例触发。
- D286 ✅ 11-10 已修（夹具过时，只改测试；本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md)）：10-11 起项目经签核的 G0 创建（`964def44`），G0 给项目另建产品，所以租户里除项目产品和测试加的对照产品外，还有共用夹具的基础产品；每个产品由触发器自带一个依赖时钟。测试写于 10-10，仍假定只有两个。改为断言时钟正好对应租户的全部产品（仍是精确断言，没有放宽）；后面原先跑不到的权限断言（`lock_change_dependency_clock` 对 `pdos_agent`、`pdos_next_auth`、PUBLIC 不可执行）也跑到并通过，单跑 13 秒。原记录：`tests/change/manufacturing_transactions/test_graph.py::test_actual_tenant_shared_asset_fence_and_rejected_roles` 断言租户里只有两个产品的变更依赖时钟，实际多出一个。多半是夹具现在多建了一个产品，测试没跟上；未核实。
- D287 ✅ 11-11 已修，两处（本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md#d287)）：产品缺陷，不是夹具过时。① 记录部分观察被拒：`ActualFactOwner._read` 收集正文来源时，`coverage_sources`（以及规则分支的 `failures`、`actions`）是模型元组，`anchor.json_value` 不序列化，`_all_source_refs` 遍历不到，覆盖来源既没进 `body.sources` 也没过 `evidence.check_source`，材料核对（`fact_write.py:453`，正文里的全部来源须在 `sources` 内）就拒绝；只在覆盖来源别处没被引用时出现。改为遍历 `_json(body_extra)`（`fact_owner.py` 一行），核对只多不少，没有放宽；`test_capa_fact_flow` 的观察加一个只出现在覆盖来源里的来源并断言读集含它，基点上报的正是 D287 的 409，修复后通过；受影响的 CAPA 事实用例 698 个通过。② 修完后链路走到独立具名复核，同一处又拒：复核正文内嵌参与者原始行（`participant_owner_material`），其中 7 个来源不在 `sources` 里（命令回执、`measurement-report` 仪器报告、整行引用），而 `read_source_closure` 对非 artifact 的领域来源一律记缺失、对 `measurement-report` 直接拒绝，所以现设计下带真实验证运行的具名复核记不下来。你 11-11 选 A（[P119](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p119)），按 D463 实施后整链通过（22.8 分钟）。原记录：`tests/change/execution/test_partial_observation_review_chain.py` 在记录部分观察时被拒，`MISSING_REQUIRED_EVIDENCE`（“缺本次真实事实owner、来源或共同写入材料”），出在 `partial_observation_chain_helpers.py:173`。还没分清是产品缺陷还是夹具过时；单次运行约 25 分钟。
- D463 ✅ 11-11 已修，集成须排在 D47 之后（你 11-10 选 A 并要求 D47 合入后做；本分支 11-11 已先实现，与 D47 分支无文件重叠，[P119](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p119)；本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md#d463)）：来源闭包补上命令回执（须是本型号该命令唯一可读的回执，版本为 1）与仪器报告（须是可读、精确版本的已上传原件，字节照常核对，原生文本不算报告）两类核对，私有的不能进入品类可见的事实，其他领域来源仍记缺失；参与者 owner 把内嵌原行的全部来源收进闭包（整行引用按实际整行换算，原件同时进读集）；具名复核并入参与者来源集。守卫不变。验证：D287 整链通过；完成整改的整链通过；CAPA 事实相关 705 个通过；新闭包用例 7 个，其中 6 个在基点失败。余项：复核页读取（`review_context`）没有端到端用例。原记录：具名复核记不下真实验证运行的参与者材料：复核正文内嵌参与者 owner 读到的原行，原行里有启动事实的命令回执（`command/receipt`）、测量导入的仪器报告（`artifact/measurement-report`）和整行引用；复核 owner 只并入各参与者自己的来源和参与者读集，没并入参与者来源集，而 `read_source_closure` 对领域来源注明“owner 接上前一律记为缺失”。三案（11-10 已发协调会话）：A（推荐）补齐命令回执与仪器报告两类来源的核对 owner，参与者 owner 收齐内嵌原行的全部来源，复核并入，规则不变、更严，工作量中等，与 D47 的 CAPA 改动同区，宜在其后；B 第 453 行的核对不再遍历已由参与者闭包封住的原行，改动小，但收窄现有守卫；C 暂不修，用例保持失败或改断言为显式拒绝。已按 P119 写入确认稿。[探测记录](../docs/reports/evidence/w4-w7-w8-debt-20261109/d287-review-missing-refs.json)
- D288 ✅ 11-10 已改（只改测试；本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md)）：加模块级 `skipif`，不设 `PDOS_EXTERNAL_HANDOFF_LINK=1` 时跳过（同 AT-47 演练的写法），用例内的开关断言保留，守卫没有放宽。不带开关 1 个跳过；带开关 1 个通过（3 分钟）。W10 D50 回归要覆盖它时仍须带开关。原记录：`tests/ui/test_project_external_handoffs_projection_pg.py` 要显式设置 `PDOS_EXTERNAL_HANDOFF_LINK=1`（只走合成的隔离两地区链路），不设时断言失败而不是跳过，所以默认的整仓回归里总是失败。带开关单独跑通过。W10 D50 回归要么带上开关，要么把它改成跳过。
- D377 ✅ 11-09 已修（你 11-09 选定修法“`s0_0001` 排除扩展成员”、落地方式“修完 D377 再落地”；本地提交、未推送）：`s0_0001` 的整体收回 `REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC,pdos_agent` 改为逐个收回 `public` 里的函数，跳过扩展成员（`pg_depend` 的 `deptype='e'`，口径同 `s0_0720`、`s0_0727`）；范围仍同 `ALL FUNCTIONS`（不含存储过程），非扩展函数照样全部收回，不放宽。只改 `schema_s0_0001.py` 这一条语句和文件说明（`s0_0001` 原样执行它），没有新增迁移，`s0_0836` 不动；空库首次升级时 `public` 里没有扩展函数，结果与原来相同。验证（`create` 新建隔离 `pdos_test`，显式 `TEST_DATABASE_URL`，用完已销毁）：head→base→head 往返和 seed 通过，第二次升级经过 `s0_0727` 的函数指纹核对（含全部非扩展函数的权限）原样通过；往返后 pgvector 118 个函数的权限都是默认值，`pdos_next_app`、`pdos_agent`、`pdos_next_auth` 都能调 `vector_norm`、`vector_dims`；`s0_0001` 建的 97 个函数对 PUBLIC 和 `pdos_agent` 都不可执行，`lock_change_dependency_clock` 对 `pdos_agent`、`pdos_next_auth`、PUBLIC 都不可执行；原来失败的 6 个向量用例全部通过；受影响的 PG 文件 24 个（向量 5 个、函数属主/定义者/执行权 11 个、迁移与基线 5 个、检索角色 3 个）共 216 个用例：212 通过、1 跳过（ANN 诊断要绑 53502）、3 失败都是已知的——D286、检索 p95（1.13 秒，单跑通过）、`test_recovery_pg[statistics_only]`（比对没有 `ORDER BY` 的查询摘要，单跑两轮通过）；无库的迁移、schema、基线测试 28 个文件 409 通过、0 失败（23 个缺库错误已在 PG 上跑过）。原问题（第四轮集成 PG 全量中发现）：W4 修好 D260 后 `create` 的往返能走完，测试库是“降到 base 再升级”后的状态；`s0_0836` 降级时有意保留 pgvector，再次升级时 `s0_0001` 的整体收回把扩展 118 个函数的执行权一起收掉，`CREATE EXTENSION IF NOT EXISTS vector` 不会补回，企业检索向量 4 个、M2a 记忆向量 2 个 PG 用例失败。生产和预览库是一次性顺序升级，不受影响。
- D470 11-10 第五轮集成无库检查中发现（`c13c3fd6` 上同样失败，未修）：`tools/tests/test_local_host_profiles.py::test_bad_explicit_list_never_falls_back_to_old_profile` 的 4 个参数都失败。测试要求报错含 “Invalid finite OPERATIONAL”，代码实际报 “Invalid nonempty OPERATIONAL host profile list of mappings”。小Pai 真实评测一段曾记为“原有的”，此前没有编号；要先确认以测试还是以代码的措辞为准。
- 集成记录 11-08（第一轮）：本地集成分支 `claude/frosty-villani-38f085`，未推送，尚未落到 `pdos-next/design-v1.1`（主工作区另有未提交改动，等你定）。
  - 基点：`pdos-next/design-v1.1` 的 `38f5a024`。M1（`claude/m1-episodic-memory-324cdf`）11-08 已快进进主线，已在基点里，无需合并，迁移保持 `s0_0855_memory_episodes`。
  - 合并：D27 `refs/heads/claude/w4-d27-test-debt-6147cc`（`7cf4351d`，只有测试，无迁移），D214 `refs/heads/claude/gracious-hofstadter-311cb9`（`b1854243`）。
  - 迁移改号：D214 的 `s0_0855_human_sign_in` 改为 `s0_0856`（down_revision `s0_0855`），快照原样移为 `schema_s0_0856.py`，只改了降级保护的报错文字；与 M1 的迁移没有共用的数据库对象。现 head `s0_0856`，链条线性。
  - D 编号：D27 的 D258、D259 保持；D214 的 D258、D259 改为 D260、D261，证据文件同步改。
  - 冲突都保留两边：生命周期目录（M1 记忆表 + D214 账户表）、`auxiliary-operations.json`（68 + `memory.search` + 8 个账户操作 = 77）、本清单。
  - 验证（独立带标记的 `pdos_test`，未用 `.env`）：
    - 合同校验通过；
    - 空库升到 `s0_0856` 通过，降到 base 在 `s0_0784` 失败（D260）；`s0_0854`↔`s0_0856` 降、升、降、升通过，也补上了 M1 末版迁移没做过的干净往返；
    - 无库全量 10656 通过、0 失败。1916 个 ERROR = D27 记的 1882 个 + M1/D214 新增 PG 用例 34 个；其中 27 个不是缺库，见 D27 补记；
    - PG（`tests/core`、`tests/agent/memory`、`tests/originals` 和两个目录类测试）637 通过、4 失败，都是原有问题：D258、D261（还是那 7 项）、`test_category_source_consumers`（`d730291d` 上同样失败）、`test_business_audience_summary`（M1 报告里基点同样失败）；
    - D27 的 PG 清单复跑 199 个，195 通过、4 失败，就是 D27 已归因的那 4 个（D258、D259 两个、检索 p95 1.07 秒）；
    - 前端 typecheck 通过，lint 0 错误（4 条警告是原有的），1899 个 `.mjs` 测试全部通过。
  - 发现：`contracts/openapi.json` 没有 M1 的 10 个记忆接口，M1 没重新导出。`tools/export_contracts.py` 能补上，但会重排上万行，没有混进合并提交。
  - 第二轮（已于 11-08 完成，见下一条）：等协调会话通知再合并 D58/D215/D248（`claude/goofy-lamarr-0cd875`）和 D33（`claude/intelligent-herschel-74d5dc`），迁移按真实 head 从 `s0_0857` 起改号；D33 里两处没写编号的既有问题改为指向 D260、D261。
- 集成记录 11-08（第二轮）：同一集成分支，未推送，`pdos-next/design-v1.1` 和主工作区都没动。
  - 合并：D58/D215/D248 `refs/heads/claude/goofy-lamarr-0cd875`（`6887053e`）、D33 `refs/heads/claude/intelligent-herschel-74d5dc`（`40d23ddd`）、D52 `refs/heads/claude/interesting-haslett-179813`（`fe3d640e`，只改前端，无迁移）。之后单独提交一次重新导出的 `openapi.json`。
  - 迁移改号：D58 `s0_0855_checkpoint_retention` 改为 `s0_0857`，D215 `s0_0856_original_rescan` 改为 `s0_0858`，D33 `s0_0855_project_team` 改为 `s0_0859`；三份快照都原样改名（内容里不带编号）。现 head `s0_0859`，链条线性。D33 会重建 `object_audiences` 上的 `m3_share_delete_only`，`s0_0736` 之后没有别的迁移动过这条策略，所以降级能恢复到正确的原文。
  - D 编号：D262（D33）、D271（D52）保持原号，没有冲突；D33 条目里两处没写编号的既有问题改为指向 D260、D261。
  - 冲突都保留两边：
    - `worker.py`：记忆索引和每租户维护两个工作流都登记，三类发现各自执行；
    - 生命周期目录：加上检查点库的条目；
    - `auxiliary-operations.json`：77 + 4 = 81 项；
    - `validate_contracts.py`：登记区加 `/v1/role-catalog`；
    - Web 总路由：M1 的 memory 与 D33 的 roleCatalog、projectTeam 一起放行；
    - 本清单：D214 取新条目，D215 取 goofy 的新条目。
  - 代码层面核对过：`context_budget.py` 和 `host.py` 两边改动不重叠，M1 的记忆背景区裁剪也经过 D248 带下限的 `measure()`；D52 的 ⌘K 面板不枚举项目标签页，不受 D33 新增“团队”页影响。
  - `openapi.json` 重新导出：只多了 M1 的 10 个记忆接口、3 个输入结构，加上 M1 的 `memory_off` 和工作状态 `text` 字段，没有删除任何接口。
  - 验证（新建独立带标记的 `pdos_test`，未用 `.env`）：
    - 合同校验通过。
    - 迁移：空库升到 `s0_0859` 通过，降到 base 仍在 `s0_0784` 失败（D260）；`s0_0854`↔`s0_0859` 降、升、降、升通过。
    - 无库全量：10707 通过、0 失败。1931 个 ERROR = 1904 个缺库 + 27 个 `citation_ids` 夹具问题（见 D27 补记）。
    - PG 第一批：D33 的受影响范围，加上 core、memory、originals、workflows，以及 goofy 和 M1 的 PG 用例，共 2420 个，2392 通过、27 失败、1 跳过。失败的都是原有问题，或已复跑通过：
      - D262 的 `test_material_proofs_pg` 19 个；
      - goofy 自报的 CTX-04 F48000/F64000 2 个（“模型调用未形成可用结果”）；
      - D258、D261（还是那 7 项）、`test_category_source_consumers`、`test_business_audience_summary` 各 1 个；
      - `test_domain_candidates_pg` 2 个：本机在第一批刚启动时休眠（02:17–11:18），这两个正跑在休眠期间，报会话失效和行级安全拒绝；单独复跑全部通过。
    - PG 第二批：D27 清单的其余部分 143 个，140 通过；3 个失败就是 D27 已归因的（D259 两个、检索 p95 1.55 秒）。
    - D33 自报的 70 个失败，在集成分支上只剩上面那 19 个：属于 D27 修复前清单的 44 个、D33 自己改好的 3 个、`test_evidence_guards_pg` 的 4 个都通过了。goofy 自报的 5 个里，`test_context_x3_full_disclosure` 2 个和 `test_development_budget_pg` 1 个已被 D27 修好，只剩 CTX-04 两个。
    - 前端：typecheck 通过，lint 0 错误（4 条警告是原有的），`.mjs` 1910 个、`.test.ts` 752 个全部通过。
  - 发现，未修：
    - `tests/core/test_current_read_profiler.py` 等三处把 `tools/` 插到 `sys.path` 最前面。如果先收集它们、后收集 `tests/builds`，`tests.conftest` 会解析成 `tools/tests/conftest.py`，导致收集报错。按默认顺序跑不会出现。
    - Web 的 54 个 `.test.ts` 用了不带扩展名的 import，`package.json` 里没有测试脚本，直接 `node --test` 加载不了。本次在草稿区用一个解析钩子跑通，仓库未改。
- 集成记录 11-08（第三轮）：同一集成分支，未推送，`pdos-next/design-v1.1` 和主工作区都没动。
  - 合并：D257/D256/D268 `refs/heads/claude/silly-easley-3b11d8`（`c2a59149`，无迁移、无合同改动）、D42/D55 `refs/heads/claude/charming-almeida-2d1941`（`254d3104`）、D56 `refs/heads/claude/xenodochial-tharp-12e9c0`（`8a5225c2`）。之后单独提交一次重新导出的 `openapi.json`，再单独提交一处合并引起的测试修正（见验证）。
  - 迁移：编号都不变，只改 down：`s0_0860_personal_run_sources` 由 `s0_0855` 改为 `s0_0859`，`s0_0861_export_audits` 由 `s0_0855` 改为 `s0_0860`。现 head `s0_0861`，链条线性。
  - 逐个核对了 s0_0856–s0_0859（`s0_0861` 还加上 `s0_0860`）：
    - `s0_0860` 改的三条函数（`kernel_read_set_visible`、`kernel_source_reference_gate`、`kernel_source_reference_clock`）没有被中间的迁移重定义；它们用到的 `direct_source_set_visible`、`scope_actor`、`scope_requester`，以及 `agent_runs`、`grants`、`artifact_versions`、`lifecycle_objects`、`categories`、`products` 的策略和授权也都没动。s0_0856 只给 `principals` 加了“不能停用自己”的更新限制策略，不影响门函数的读取。所以 `schema_s0_0860.py` 的 SQL 原样保留，只改了说明文字；往返中升级前后的 `require_functions` 核对都通过。
    - `s0_0861` 用到的 `category_access`、`kernel_append_only`、`scope_actor`、`scope_requester` 没有被重定义。s0_0856 给 `tenant_administrators` 加的是管理员读取的放行策略、插入和更新的限制策略，审计读策略里“本人管理员行”的判断不受影响。生命周期目录里 D58 的检查点库条目和 D56 的 `export_audits` 各自保留，`export_audits` 已登记为不消费来源的表。
  - 代码层面核对过：D257 的并发提取子任务记录上下文准入时照样锁运行行，D248 只在同一条记录里多写一个下限，互不影响；D257/D268 与 M1 的 kernel 改动不在同一文件。D56 的导出直接调用页面读取函数，D33 没改这些函数。
  - 冲突都保留两边：
    - 本清单：D52 取集成分支的 ✅ 新条目，D55 取 D42 分支的 ✅ 新条目，D271 和 D274–D276 都保留；
    - `auxiliary-operations.json`：81 + 1 = 82 项，入站入口 5 个不变；
    - `core/models.py`：项目团队和导出两个模型模块都导入；
    - 生命周期目录：D214、D58 的条目之后接 `export_audits`；
    - Web 总路由：两处守卫同时放行 `roleCatalog`/`projectTeam` 和 `personalExport`/`exportView`，合并后的行去掉对方新增的判断，就等于各自分支的原行。
  - D 编号：D268、D269、D274–D276、D278–D283 都保持原号，没有重复。D263–D267、D270、D272、D273、D277 不在本分支，也不在主工作区清单或任何本地 `claude/*` 分支里，可能是协调会话预留的。
  - 合同：三份合同里设计稿 v1.1 的 sha256 与文件一致（只有 D56 改过 v1.1）。`openapi.json` 重新导出后只多了 D42 的 `GET /v1/personal/agent-input-sources`；D56 的 4 个导出接口按路由注册顺序挪了位置，内容不变。
  - 验证（新建独立带标记的 `pdos_test` 和检查点库，未用 `.env`；本机全程保持唤醒）：
    - 合同校验通过（87 operations、92 events、67 acceptance）。
    - 迁移：空库升到 `s0_0861` 通过，降到 base 仍在 `s0_0784` 失败（D260）；`s0_0854`↔`s0_0861` 降、升、降、升通过。
    - 无库全量：10753 通过、1 失败（D42 的过时测试，见下）。1958 个 ERROR 都是缺库或 `citation_ids` 夹具问题。
    - PG 第一批（core、originals、projects、preproject、workflows、memory 等）2393 个：2369 通过、23 失败、1 跳过，失败都是原有的：D262 的 19 个、D258、D261（还是那 7 项，`export_audits` 与模型一致）、`test_category_source_consumers`、`test_business_audience_summary`。
    - PG 第二批（整个 kernel 和 enterprise_search、exports、my_work，加 D27 清单里的其余文件）3849 个：3741 通过、17 失败、27 错误、64 跳过。逐个归因：
      - 原有：CTX-04 两个（goofy 自报）；D259 两个和检索 p95（1.0009 秒）一个（D27 已归因）；`test_extracted_claim_pg` 8 个（“所选技能与实际模型尚无当前资格”，用基点 `38f5a024` 的代码在同一库上同样失败）；27 个 `citation_ids` 错误（D27 补记）。
      - 合并引起，已修：`test_private_analysis_pg::test_private_three_way_recovery_keeps_actual_item_versions_and_old_result`。D27 把“当前门函数”的期望改成 s0_0854 的定义，D42 的 s0_0860 又改了这条函数；两个分支各自都通过，合在一起才失败。已改为对照 `schema_s0_0860` 的定义（单独提交，只改测试），整文件 10 个通过。
      - 分支自带，未修：D42 的 `test_source_views` 一个；D33 的 `test_session_presentation_pg`、`test_project_discussion_history_pg` 各一个（见下）。
    - 指定用例全部通过、没有跳过：D42 的 11 个正反例、D56 的 6 个 PG 用例和 4 个工作簿用例、D257/D268 的 9 个 PG 用例、`test_durable_evidence` 19 个（含 DOCX 和照片上传）。
    - 前端：typecheck 通过，lint 0 错误（4 条警告是原有的），`.mjs` 1916 个、`.test.ts` 752 个全部通过。
  - 发现，未修（11-08 下面三项都已修（见本组末尾的缺陷清理记录））：
    - D42：`tests/agent/kernel/test_source_views.py::test_get_only_router_uses_current_context_and_read_snapshot` 在 D42 分支上就失败，基点通过。D42 在同一个路由里新增了 `/v1/personal/agent-input-sources`，这条旧测试仍断言该路径返回 404，又没替换个人读取函数，于是用桩会话调用了真实函数，得到 500。产品行为符合 P91，是测试过时；D42 没跑无库全量，所以没发现。改法：给个人读取打桩并断言 200，或去掉这条断言。
    - D33：`test_session_presentation_pg` 和 `test_project_discussion_history_pg` 共用的 `_revoke_peer_project_fixture` 直接删除同事的项目受众行，而同事仍是当前成员，被 D33 新加的 `require_project_team_audience` 拒绝（“Project audience differs from its current members”）。产品代码里只有 D33 的团队服务会删项目受众，所以只是夹具过时；D33 已用“由负责人经团队命令移出成员”改过另外 3 个同类用例，这两个文件不在它的回归范围里。
    - D56：证据 README 链接的 `migration-roundtrip.log` 被 `.gitignore` 的 `*.log` 排除，只在 D56 自己的 worktree 里有，提交里没有；那个 worktree 清理后这份证据就丢了。可以改名为 `.txt` 后补提交。
  - 落地准备（只读，详见交接笔记）：主工作区 19 个未提交文件里有 6 个与集成分支重叠，三方试算 5 个自动合并，`web/src/features/shell/app-shell.tsx` 有 1 处冲突，是相邻两行各改一行，按行取两边即可，不涉及取舍。把集成分支和主工作区改动合在一起的完整树在草稿区试过：前端 typecheck 通过，后端无库 3832 通过（唯一失败就是上面 D42 那条），主工作区改过的 PG 测试与相关用例 54 个全部通过。主工作区要先提交自己的改动，集成分支才能合进去。
- 落地记录 11-08：你选“我来提交再合并”。已落到本地 `pdos-next/design-v1.1`，未推送。
  - `4e04de5f`：主工作区 11-07 代码审查修复（“首版 MVP 候选预检”那批）原样提交，含证据目录 `docs/reports/evidence/pdos-next-mvp-20261107/` 和 `proposal-create-form.test.mjs`。`web/next-env.d.ts`、`.claude/`、`tools/dev_reload.py`（D13）和 11-01、11-05 的逐运行原始文件不提交。
  - `d6abcbf2`：合并集成分支 `f5379a0a`，迁移 head 为 `s0_0861`。唯一的冲突在 `app-shell.tsx`：`CategoryArea` 取主线的 `principalId`，`PlatformSettings` 取集成分支的 `administrator`。已核对两行除此以外完全相同。
  - 复验：落地的树与草稿区的组合试算是同一内容（集成分支之上只多 11-07 那 21 个文件），所以按影响只复验重叠区域，PG 沿用试算的 54 个。
    - typecheck 通过，lint 0 错误；`.mjs` 1918 个全部通过；合同校验通过（87 operations、92 events、67 acceptance）。
    - 无库 kernel、model_configuration、enterprise_search、preproject 共 3832 通过，唯一失败是 D42 的过时测试。
  - 后续：已知失败与过时测试由“W4 缺陷收尾”会话处理（D258–D262 等，迁移占位 `s0_0862`–`s0_0864`，新 D 编号 D284–D294）；并行的 M2a 占 `s0_0865`–`s0_0867`、D295–D304，D47 占 `s0_0868`–`s0_0872`、D305–D320。
- 缺陷清理记录 11-08：worktree `elated-shirley-4a1ed9`，分支 `claude/elated-shirley-4a1ed9`，基于 `d6abcbf2`，本地提交、未推送，`pdos-next/design-v1.1` 和主工作区都没动（[证据](../docs/reports/evidence/w4-defects-20261108/README.md)）。
  - 产品与迁移：D258、D259、D260、D261 已修，另新登记并修好 D284、D285，见各条。新迁移 `s0_0862`–`s0_0864` 是占位号，接在 `s0_0861` 之后，**集成时按真实 head 重排**（`s0_0865` 起由 M2a、D47 两个并行会话占用）。另改了 `s0_0727` 的函数指纹查询、`schema_s0_0800` 的降级语句和 `tools/local_environment.py` 的测试库参数（D260）。
  - 测试过时，只改测试，守卫、权限和断言都没放宽：
    - D262：`test_material_proofs_pg` 19 个；
    - `test_registered_snapshot_reads.py` 27 个 ERROR：夹具把 `RunScope.citation_ids` 传给 `AgentRun`；
    - `test_extracted_claim_pg` 8 个：派发夹具的主调用用合成提示词，资格却绑定真实提示词；夹具加 `active_prompt` 选项，只有本文件用真实提示词；
    - CTX-04 F48000/F64000：脚本化模型桩按“品类运行”断言下发工具，CTX-04 是项目运行（P76 第 4a 项多出项目读取），断言失败表现为“模型调用未形成可用结果”；
    - `test_context_x3_full_disclosure` 2 个、`test_development_budget_pg` 1 个：D27 已修，复跑通过；
    - `test_category_source_consumers`：由 D285 修好；`test_business_audience_summary`：G0 已把项目、产品、定义受众分享给具名评审，改为扣住同事从未获得的工程配置；
    - 分支自带 3 个：D42 `test_source_views`（给个人读取打桩，断言 200/422/405）；D33 共用夹具（负责人经团队命令移出同事，再做合成的可见性收窄）；
    - PG 全量新查出的 7 个，`d6abcbf2` 上同样失败（第三轮没跑这几个目录）：`builds/professional_authority/test_current_policy` 3 个（同 D33，项目受众改由团队命令收回和加回，`tests/team_fixture.py` 加 `add_member`）；`test_build_execution`、`test_builds` 各 1 个（`release.manufacturing.approve` 10-10 时还没有处理器，期望 403；放行域落地后它和另外四个操作一样先按格式拒绝，422）；`change/coverage_transactions/test_public_capture_minimal` 1 个（`rules.py` 把规格经工程配置到 BOM 的有出处路径算作已连通，测试只认直接边）；`categories/products/test_definition_parent_lineage_pg` 1 个（断言库版本等于写用例时的 head `s0_0756`，改为与执行前的版本比较）。
  - D56：证据日志改名 `migration-roundtrip.txt`，链接已改。
  - 未修：检索 p95（`test_recovery_pg` 家族检索 3.9 秒）。测试库只有 77 MB，当时整机负载 27–32，另有 4 个会话的测试库在跑；按环境归因，阈值没动（性能验收按 P13 暂缓）；同一用例在负载较低时的 PG 全量里通过。另有 D286–D288 未修，见下。
  - 验证（[结果](../docs/reports/evidence/w4-defects-20261108/results.txt)）：无库全量 10784 通过、0 失败（`d6abcbf2` 为 10755 通过、2 失败，多 27 个 `citation_ids` 错误）；PG 全量（无库时报缺库或跳过的用例所在的 353 个文件，2222 个用例，三个隔离库分段并行，全部覆盖）：分段里 11 个失败、7 个错误，按最终代码逐个复跑，只剩 D286、D287（`d6abcbf2` 上同样失败）；D288 带开关通过；其余是分段跑完后才修的过时测试，或长批次里的偶发，单独复跑都通过。`d6abcbf2` 定向对比 24 个文件：40 失败、27 错误，正是本次修掉的各项。迁移：`s0_0854`↔`s0_0864` 两轮往返通过；`tools/local_environment.py create` 在两个新库上都通过 head→base→head 并完成 seed；ORM 与库比对 0 项。
- 集成记录 11-09（第四轮）：集成分支 `claude/frosty-villani-38f085` 先快进到主线 `4ba32f97`，再合 6 个分支；未推送，`pdos-next/design-v1.1`、主工作区和预览库都没动，停在集成分支等落地确认。D47（`claude/elastic-noyce-fad368`）本轮不合。
  - 合并（按此顺序）：W4 缺陷收尾 `refs/heads/claude/elated-shirley-4a1ed9`（`bb5f624e`）、M2a `refs/heads/claude/intelligent-banach-bd90dd`（`d2dd8e9a`）、W11 运维 `refs/heads/claude/charming-robinson-414f5d`（`8d8fd4c5`）、W6 ⑤ `refs/heads/claude/eloquent-mclean-240ee2`（`1ec546b8`）、D40 `refs/heads/claude/busy-kare-1f02fd`（`e4de441b`，无迁移）、D269/D44 `refs/heads/claude/amazing-driscoll-5714b9`（`25589b1b`，无迁移）。之后单独提交一次重新导出的 `openapi.json`。
  - 迁移按真实 head 单调排号，现 head `s0_0869`，链条线性：
    - W4 `s0_0862`–`s0_0864` 本来就接 `s0_0861`，不变；它改的两份历史迁移（`schema_s0_0800.py` 降级语句、`s0_0727` 指纹查询，指纹值不变）照原样带入；
    - M2a `s0_0865`、`s0_0866` 编号不变，`s0_0865` 的 down 由 `s0_0861` 改为 `s0_0864`；
    - W11 占位 `s0_0879_ops_health_counters` 改为 `s0_0867`（down `s0_0866`）；
    - W6 ⑤ 占位 `s0_0873_handover_lane`、`s0_0874_project_discussions` 改为 `s0_0868`（down `s0_0867`）、`s0_0869`；前置核对的报错文字和降级保护的 “requires” 文字一起改；
    - 文件名、revision、down_revision、`schema_s0_xxxx` 模块名和 import 一起改，SQL 都没动。主线落地记录里给 D47 预留的 `s0_0868`–`s0_0872` 按本轮安排让给 W6 ⑤，D47 合入时再按真实 head 排号。
  - 核对：
    - `s0_0868`（原 `s0_0873`）升级前按 md5 核对 7 个对象（`projects.category_scope` 策略、`work_receipt_project_visible`、`require_project_team_audience`、`project_audience_releasable`、`guard_project_member`、`release_project_member_upstream`、`source_object_audience`）。`s0_0862`–`s0_0867` 和 W4 改的 `s0_0727`、`schema_s0_0800.py` 都没碰这 7 个对象（`s0_0727` 里的 `category_scope` 是 `quality_event_failure_links` 的），所以核对原文与 md5 原样保留，没有放宽；往返里两次升级都通过了这项核对。
    - W4 的 `s0_0862` 要求所有定义者函数归注册属主；M2a、W11 新建的定义者函数都在 `ordinary_owner()` 下创建，符合。
  - D 编号：W6 ⑤ 分支登记的 D321–D331 与主线 `4ba32f97` 竞品场景评估的 D321–D328 撞号，只把 W6 ⑤ 自己的 12 行清单和 `result.md` 1 行改为 D366–D376，共享笔记同步；主线 D321–D328 各行原样。其余分支的 D284–D294、D295–D303、D336–D341、D346–D350、D356–D358 都不重复。
  - 冲突都按各自原位保留：
    - 本清单：主线落地记录与 W4 缺陷清理记录两段都留；
    - 确认稿：M2a 的 P92–P94 之后接 W6 ⑤ 的 P98、P99；
    - `worker.py`：W11 把工作流清单挪进 `registered_workflows()` 供发布前回放检查，M2a 在旧清单里加了 `MemoryEpisodeVectors`。保留 W11 的函数并把 `MemoryEpisodeVectors` 放进去（17 个类和顺序与原清单一致），保留 M2a 的向量派发；W11 测试里写死的工作流个数 16 随之改为 17；
    - `openapi.json`：不手工拼，全部合完后用 `tools/export_contracts.py` 重新导出。
  - 代码层面核对过：D269 在 `host.py` 调整停止信号检查的位置、在 `bootstrap.py` 登记提取读取的续接，与 M2a 在同两个文件里冻结本人记忆条目、给记忆检索接向量互不重叠；D40 与 W6 ⑤ 都改了 `app-shell.tsx`，自动合并，shell 与设置页前端测试通过。
  - 合同：`openapi.json` 相对主线只增不删（266→292 个接口、136→151 个结构）：M2a 11 个记忆接口、W6 ⑤ 15 个讨论/评论/提及/通知/交接接口；`PolicyInput`（M2a）、`Preferences`（D40）各加两个字段，`AgreementRequest.data_categories` 加 `owner_session`（M2a P93）。`auxiliary-operations.json` 90 项无重复。合同校验通过（87 operations、92 events、67 acceptance）。
  - 上一轮登记的分支自带问题已由 W4 修好：D42 `test_source_views`、D33 共用夹具两个、D56 证据日志（改名 `.txt` 入库）；`citation_ids` 27 个、`test_extracted_claim_pg` 8 个、CTX-04 两个也已修好。
  - 验证（`tools/local_environment.py create` 建独立临时 `pdos_test`，显式 `TEST_DATABASE_URL`，未用 `.env`，未碰预览库；本机全程保持唤醒）：
    - 前端：typecheck 通过，lint 0 错误（4 条警告是原有的），`.mjs` 1940 个、`.test.ts` 752 个全部通过。
    - 合同校验通过。
    - 无库全量：10808 通过、0 失败、111 跳过；1980 个 ERROR 全是缺库。
    - 迁移：`create` 的 head→base→head 往返和 seed 在三个新库上都通过（本 worktree、并行副本、基点对照副本只用于下面的复核），D260 确已修好；`s0_0854`↔`s0_0869` 降、升、降、升通过，`s0_0868` 的 md5 前置核对两次升级都通过；模型与库 0 差异（D261 已修）。
    - PG 全量，按 W4 的口径取“无库时报缺库或跳过的用例所在的文件”，共 363 个，分两段在两个隔离库上并行（第二段在同一提交的草稿区副本里跑）：
      - 第一段 `tests/agent` 875 个：807 通过、61 跳过、7 失败。其中 6 个是新登记的 D377（测试库状态问题，见该条）；1 个是检索 p95（1.12 秒，负载高时偶发）。
      - 第二段其余 1391 个：1382 通过、9 跳过、0 失败。
      - D286、D287 单独跑，仍是原来那两个失败（多一个产品时钟；`MISSING_REQUIRED_EVIDENCE`），共 18 分钟。D288 带 `PDOS_EXTERNAL_HANDOFF_LINK=1` 通过。
      - 跳过的是：Temporal 相关（本机没有 Temporal，未拉镜像）、绑定 53502 测试库的根级用例、浏览器种子，以及 AT-47 备份恢复演练（需显式开启和原生 Temporal，W11 已在干净环境留证据）。
    - 新失败已按要求在 `4ba32f97` 的干净副本上复核归因（见 D377）；没有合并引起的失败。
    - D377 11-09 补修：你选了“`s0_0001` 排除扩展成员”并修完再落地；已在本分支修好并验证（见 D377），第一段那 6 个失败随之消除。
    - 三套测试库、检查点库和草稿区副本都已销毁。
  - 落地：本轮停在集成分支，等你确认后再落到 `pdos-next/design-v1.1`。集成分支是 `4ba32f97` 的后代，可以快进。
- 集成记录 11-10（第五轮第一批）：集成分支 `claude/frosty-villani-38f085` 从主线 `c13c3fd6`（与本分支 tip 一致）起合 7 个分支；未推送，`pdos-next/design-v1.1`、主工作区和预览库都没动。D47、W4 小修下一批合入，PG 全量等它们合入后统一跑。
  - 合并（按此顺序）：W11 `refs/heads/claude/trusting-poitras-e6aea6`（`ee8514d9`）、自动化规则 `refs/heads/claude/suspicious-babbage-15fcbf`（`e7ce05e7`）、W6 ⑥ `refs/heads/claude/fervent-vaughan-7ad67a`（`005477af`）、W6 ⑦ `refs/heads/claude/relaxed-swartz-67a3a9`（`210bdd58`，无迁移）、W6 ⑧ `refs/heads/claude/epic-chatterjee-780576`（`a0fafa8b`）、W7 `refs/heads/claude/wonderful-visvesvaraya-922b5d`（`7b1a1c05`，无迁移）、W9 BOM `refs/heads/claude/hopeful-joliot-438789`（`168712a7`）。之后单独提交重导的 `openapi.json` 和一处修复。
  - 迁移按合并顺序从 `s0_0870` 起排，现 head `s0_0876`，链条线性：
    - W11 `s0_0910` → `s0_0870`；自动化规则 `s0_0905`、`s0_0906` → `s0_0871`、`s0_0872`；W6 ⑥ `s0_0880` → `s0_0873`；W6 ⑧ `s0_0890`、`s0_0891` → `s0_0874`、`s0_0875`；W9 `s0_0900` → `s0_0876`。
    - 文件名、revision、down_revision、`schema_s0_xxxx` 模块名与 import、降级保护和前置核对的报错文字，以及代码注释、清单、确认稿、证据里的号一起改，SQL 都没动。D47 分支上的 `s0_0868`、`s0_0869`、`s0_0870`–`s0_0879` 是占位号，下一批按真实 head 再排。
  - 前置核对原样保留：`s0_0872`（原 `s0_0906`）按 SHA-256 核对 `automation_service_start`、`assert_automation_service_run` 仍是 `s0_0840` 原文；`s0_0873`（原 `s0_0880`）按 md5 核对 `guard_discussion_message`、`require_discussion_version` 仍是 `s0_0869` 原文。本批其他迁移都没碰这四个函数；`create` 往返的两次升级都通过。
  - 确认稿：P105、P109、P110、P111、P113、P115、P116、P117 按编号排在 P99 之后，全部保留。
  - 冲突按各自原位保留：清单里 W6 ⑥、⑦、⑧ 各段和 D390–D447 各段都留；D38、D39、D41、D75–D78、D341 这几行逐行取改过的一边。语义合并三处：
    - `worker.py`：保留 W11 的优雅停机 `main()`，加入 W6 ⑥ 的回复投递 activity 和讨论回复发现，告警走 W11 的 `unavailable()`；注册工作流 18 个；
    - `project-workspace.tsx`：W6 ⑦ 把“现在”页整块换成概览，W6 ⑥ 在这个文件里仅有的两处改动（任务视图和项目讨论的 `onOpenRun`）带到新结构上；
    - `route.ts` 个人视图白名单：W6 ⑦ 的 `project-cockpit` 和 W7 的 `run-decisions` 都留。
    - 另外，`auxiliary-operations.json` 合成 97 项、无重复；原件生命周期目录里 W6 ⑥、⑧、W9 三段各与原分支一致。
  - 跨分支衔接，都没接上，保留登记：
    - 工作日计算：W11 的日历接口与自动化规则的周一至周五估算对不上，没有切，原因写在 D443（W6 ⑥ 冷却期 D391 同理）；
    - 跟进升级推送收件箱：W6 ⑥ 已提供规则例外的主动提及，但调用方还缺，原因写在 D441；
    - W6 ⑧ 降级通知接通知中心：D413；W9 替代料批准接 D47：D433（D47 合入后）；W6 ⑦ 概览与驾驶舱接状态更新周期：D401、D444。
  - 合同：`openapi.json` 用 `tools/export_contracts.py` 重导，相对主线只增（接口操作 322→339、结构 151→161；讨论的 `NewMessage` 改为带模块前缀，D398）；`payloads.schema.json`、`operations.json`、`acceptance.json` 导出无变化。v1.1 只有 W6 ⑧ 改过，三份合同里的 sha256 与现文一致；合同校验通过（87 operations、94 events、70 acceptance）。
  - 修复一处（`0fcd13f4`）：W11 新增的 `work_calendars`、`work_calendar_versions` 没登记进原件生命周期目录，3 个“目录等于模型”的无库用例在 W11 分支上本来就失败；已按实际列登记。
  - 验证（`tools/local_environment.py create` 建独立临时 `pdos_test`，显式 `TEST_DATABASE_URL`，未用 `.env`，未碰预览库）：
    - 前端：typecheck 通过，lint 0 错误（4 条警告是原有的），`.mjs` 1978 个、`.test.ts` 757 个全部通过。
    - 合同校验通过。
    - 无库全量：10917 通过、3 失败、111 跳过，3 个失败就是上面的目录用例，修复后通过；2024 个 ERROR 全是缺库。`tools/tests` 72 个里 4 个失败，`c13c3fd6` 上同样失败，登记 D470。
    - 迁移：`create` 的 head→base→head 往返和 seed 通过；往返后 pgvector 函数权限是默认值（D377 修复仍有效）。
    - 7 个分支受影响的 PG 用例，61 个文件共 458 个：441 通过、3 跳过（AT-47 演练要显式开启；两个自动化 Temporal 用例要本机 Temporal 服务）、14 个失败或报错。这 14 个都是本机合盖睡眠造成的：运行中途 16:28—16:42 睡眠（`pmset` 有记录），醒来后预览和限期复核都过期了（`PREVIEW_EXPIRED`、`PROFESSIONAL_REVIEW_EXPIRED`）；在同一库上单独重跑，14 个全部通过。
    - 没有合并引起的失败。
    - 测试库、检查点库和草稿区副本都已销毁。
  - 下一批：D47、W4 小修合入后统一跑 PG 全量，再等你确认落地。

**W5 人工审阅与资格准备（验证欠账；你本人做，会话只负责出查阅单）**
- D30 〔你〕52 题和 24 份资料逐题审阅定版（目前还不是 golden）；回放回答按六维和硬失败具名审阅（代理审阅不能算真人审阅）。
- D31 〔你〕Prompt A/B 用真实模型同题评分（目前 not_scored）；S2–S5 技能包启用并建评测集，其中 build_execution、change_control、quality_issue、release_handover、test_verification、work_management 六个技能包要先在评测规则 §4 补专属小节（见 D240 余项）；签 rfq 资格集的参考答案（随 D20-A2）。
- D32 〔你〕work_management 的 T0 资格要 10–20 个多品类计划给你审阅。仓库只有两个品类种子（auto-tire-inflator、bicycle-pump），帐篷泵和气垫泵需要另建品类。

**W6 P34→P33 实施（设计已定未实现；按 ①–⑧ 的顺序；前置 D17、D18）**
- D33 ✅ 11-07 实施、11-08 验证完成 ① 项目成员、租户角色目录和迁移（P34-1，是 P33 的前置），本地提交、未推送，[证据](../docs/reports/evidence/w6-d33-project-team-20261107/result.md)。迁移为 `s0_0859`（down `s0_0858`；分支上为 `s0_0855` 接 `s0_0854`，11-08 集成时排在 M1、D214、D58、D215 之后改号）。
  - 可用能力：项目成员（具名人员、多角色、每个角色最多一名主责人、加入与离开时间、添加人与移出人）；租户级、版本化的角色目录，未发布时用设计稿 §4.1 的 12 个角色作可编辑初始值，租户管理员发布新版本，被担任的角色只能停用不能删（P60 第 4 项）；G0 物化时同一事务把加入项目受众的人登记为成员，预览和回执列出（P55）；负责人整张变更一次确认（`project.member.set`，T1）；成员须有当前品类授权，负责人不能代授，页面显示“需要品类授权”；小Pai 不能成为成员，AI 身份对成员表零权限；私有项目中“受众 = 当前成员”由数据库在提交时核对；品类共享项目成员不改变可见范围；项目“更多 → 团队”页面亮暗两种主题已在浏览器验收。
  - 验证（11-08）：受影响范围回归 1796 个用例里 70 个失败。其中 3 个由 D33 引起：测试直接删项目受众行，违反“私有项目受众 = 当前成员”；已改为由负责人经团队命令移出成员，其中履约用例先验收已提交的任务再移出（按拍板 ①）；同时修正待交接计数，已验收兑现的承诺不再算未交接。其余 67 个在基点同样失败：44 个在 D27 的修复前清单里，23 个在基点副本上逐条复现，登记为 D262。改动后重跑团队、三个受影响文件、表目录和命令目录共 100 个，全部通过。
    - 11-08 第三轮集成时发现：`test_session_presentation_pg`、`test_project_discussion_history_pg` 的共用夹具也直接删项目受众行，同样被拒，未修，见 W4 第三轮集成记录。
  - 11-07 拍板（用户，经设计会话转达）：① 移出成员时，成员资格和角色立即结束；此人有未交接事项的，项目受众保留到交接完成，页面标“待交接”，交接完成后由负责人“完成移出”；没有的立即移出。② 私有项目加成员时，一并加入负责人本人所有的型号、立项定义 v1（及变体）受众，不是其所有人的不代加，成员行标“需要型号资料可见，请联系 某某”；这些受众记下来源，完全移出时撤回随本项目加上的，原本就有的或别处授予的保留；定义来源里的私有原件不自动扩大。
  - 余项：
    - ✅ 11-08 已收（D37 ⑤）**对 P56 的临时偏离**：移出即撤项目受众，只经服务器核对的交接通道保留本人未交接事项的查看与办理，交接完成后自动完全移出（“完成移出”按钮保留为兜底）。原记录：交接期内被移出的人仍能看到整个项目，比 P56“项目讨论和其他内容立即不可见”宽。
    - ✅ 11-08 已做（D37 ⑤）设计稿 §4.4 待接事项卡片：团队页逐条列出待接的任务、承诺、外部等待；账号停用时给负责人发卡片（P99）。小Pai 起草改派候选仍归 W8。
    - 小Pai 起草团队名单：服务器侧已就绪（AI 身份不能增删成员、智能体不能成为成员、整张名单一次确认）；起草工具和提示词归 W8，本次未动 agent kernel。
    - 设计稿 §4.4 离开交接的起草与待接事项卡片未做。
    - 角色目录管理界面未做，目前只有接口（`/v1/role-catalog`）；正式角色内容待 D66。
    - “需要型号资料可见”只检查型号、定义、变体三层受众，不检查定义来源里的私有原件。
    - 已有问题（与本项无关）：新建测试库的升-降-升往返在 `s0_0784` 降级时失败（D260）；ORM 与迁移比对在基点已差 7 项（钉钉摘要索引、6 个向量索引，D261）；回归中 67 个既有失败见 D27、D262。
- D34 ② NPI 新品框架的配置、版本和发布（`work.framework.publish`），加确定性框架检查器，并停用混合三代模板目录（templates.py 中新品 81 个任务 + 15 个门禁项）。框架 v1 和角色目录的内容见 D66。
- D35 ③ G0 后自动起草计划；基线前的 T0 情形（adopt/apply/bind/assign）；`work.task.revise`；整次撤回时逐条列出未撤回项；修订 S5 合同和 work_management 技能包的来源规则；8 个新操作并入 operations.json（现为 87 项）。
- D36 ④ 阶段节点服务器接口和日历口径（同时补上 UI 缺的阶段模板、健康度、冻结点合同）；规格冻结 `product.definition.publish`（P23 派生入口的前置），派生草稿收进提案（随 D20-A1）。
- D37 ⑤ 讨论与评论、提及解析、通知降噪；⑥ 共享串里的 @小Pai（受众核对与 P31 共用）和小Pai 主动提及；⑦ 单项目驾驶舱和管理者驾驶舱的读模型、状态更新周期；⑧ 资格评测集、按运行指标自动降级、判据登记进 acceptance。
  - ⑤ 同时收掉 D33 余项“对 P56 的临时偏离”：被移出的人交接期只保留本人未交接事项的可见与办理，交接完成后自动完全移出；最迟在真人试点前。
  - ⑤ ✅ 11-08 讨论与评论、@成员提及、通知降噪、稍后提醒（D73）、SSE 与 30 秒轮询（D74）、P56 交接、讨论导出（D279）。分支 `claude/eloquent-mclean-240ee2`，本地提交、未推送，[结果与证据](../docs/reports/evidence/w6-discussions-20261108/result.md)。迁移占位 `s0_0873`（交接通道）、`s0_0874`（讨论与通知），接 `s0_0861`，**集成时按真实 head 重排**（11-09 第四轮集成已改为 `s0_0868`、`s0_0869`，接 W11 的 `s0_0867`）。用户 11-08 裁定见确认稿 [P98](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p98)（静音只挡关注变化和摘要）、[P99](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p99)（停用先提醒，已承接任务改派留 W6 ③）。
    - 可用能力：项目讨论主题、任务与文档评论（受众随对象实时复核，客户私有文档下的评论只对其受众可见）；评论记下对象版本；编辑留版本、撤回留“已撤回”；@成员（看不到对象的人置灰并被服务器拒绝）、@角色、@全体（限负责人）、@任务引用，@小Pai 返回“未开放”留给 ⑥；通知五类、自动关注、操作人不收、10 分钟合并、按项目级别/静音/每日摘要、稍后提醒、归档；SSE 经 BFF 透传，断线每 30 秒轮询，恢复后按游标补齐，流内每轮复核会话且不刷新空闲计时；移出即项目零可见，只经交接通道办理本人事项（评论、登记开始、提交成果需一次确认），验收/改派/承诺验收/外部等待记录后自动完全移出；停用账号给负责人发待接卡片；项目导出含“讨论与评论”表。AI 身份对 6 张新表零权限，作者守卫要求 actor=requester=本人。
    - 证据：PG 10 例（`tests/projects/discussions_pg`）+ 团队 10 例 + 生命周期目录 75 例通过；受影响范围回归 1988 过、28 失败、3 个准备阶段错误：本次引起的 5 个（work 纯逻辑测试的 IO 接缝）已修、导出 1 个按新表改断言，20 个在基点副本上同样失败（D262 与定义者归属），其余为数据库容器被系统杀进程的环境问题、单跑通过；合同校验与迁移往返通过；前端 typecheck、lint、`.mjs` 1928 项（1 项与本次无关的时序用例单跑通过）与 BFF 路由 90 项通过；浏览器两人走通讨论、@、通知、稍后提醒、交接全流程，亮暗与 375px。
    - 余项：D366–D376（分支上登记为 D321–D331，与主线 11-08 竞品场景评估的 D321–D328 撞号，11-09 集成时改号）。
  - ⑥ ✅ 11-09 共享串里的 @小Pai 与小Pai 主动 @ 人（P34 第 4、5 项，P52、P54、P62、P105）。分支 `claude/fervent-vaughan-7ad67a`，本地提交、未推送，[结果与证据](../docs/reports/evidence/w6-xiaopai-threads-20261109/result.md)。迁移占位 `s0_0880`（接 `s0_0869`；11-10 第五轮集成改为 `s0_0873`，接 `s0_0872`），**集成时按真实 head 重排**。用户 11-09 裁定见确认稿 [P105](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p105)（补充信息时服务器按对象推定 @ 谁）。
    - 可用能力：项目讨论与任务、文档评论里 @小Pai，发帖同一事务按发起人本人发起运行，范围由服务器从项目绑定；每位发起人每串一个会话并续接（P52），串内公开内容冻结为动态背景、追加在 context 末尾，共享串不进个人记忆；运行经唯一注册的小Pai 工作流（Temporal → LangGraph），写入按原档位。运行结束后 worker 按发起人重建本次读取的全部来源，再按串内每位受众本人的权限逐一复核：全部可见才以小Pai 署名、注明应某某请求贴回运行自己的回复（正文由 SQL 从运行结果读取），否则只贴“小Pai 已回复发起人”；发起人可事先选“只给我看”。运行卡显示进行中、等你回答、完成、部分完成、失败；发起人可查看私下回复、在小Pai 中打开或去回答。分享按 P62：读过客户私有资料只能分享链接，读者逐人复核来源；其他情形分享正文须确认提示，回执记分享人、范围与未覆盖的来源种类。小Pai 的回复只能由发起人或负责人撤回、不能编辑。小Pai 主动 @ 人只限三种：小Pai 分派任务通知受派人（P53）、补充信息时按 P105 @ 任务受派人或负责人（通知不带问题原文）、自动化规则例外（原语已备，规则侧接入归自动化规则会话）；同一对象同一原因冷却 1 个工作日。只经交接通道可见的人、看不到对象的人不能发起或读取；AI 身份对新表零权限。
    - 证据：新增 PG 12 例（`tests/projects/discussions_pg/test_agent_thread.py` 11 例、`test_agent_thread_temporal.py` 1 例：投递工作流经本地 Temporal 跑通）；新建隔离库上受影响范围回归 618 例，3 个表目录用例因漏登 `notified_wait` 失败、补登后通过，其余 608 过、7 跳过（4 个回放检查补跑通过）；合同校验通过；前端 tsc、eslint、`.mjs` 1942 项、BFF 路由 90 项通过；浏览器两人走查（亮暗、375px）截图 11 张，运行结束由测试替身完成、投递为真实宿主。
    - 余项：D391–D399。
  - ⑦ ✅ 11-09 单项目概览与管理者驾驶舱读模型（并 D76、D39 概览部分、D41 项目集前半）。分支 `claude/relaxed-swartz-67a3a9`，本地提交、未推送，[结果与证据](../docs/reports/evidence/w6-cockpit-20261109/README.md)。**无迁移**（占位 `s0_0885`–`s0_0889` 未用）、无新命令、无新实体；P107、P108 未用。
    - 可用能力：概览读模型 `GET …/projects/{id}/overview` 与“概览”页——健康度（P61 五档，带规则 id/版本与依据）、阶段位置、下一节点四时间与滑期、当前出口条件、出口成果显示“阶段节点未建”、需要办理（阻塞/待接收/待决定，每条写负责人，“去办理/查看”定位原记录、不在概览执行命令）、下一 Build、关键承诺、开放风险、未关闭问题、超期外部等待、7 天到期、团队与空缺角色、小Pai 值班摘要（只读、不计入待办）、计算规则说明；全部按读者 RLS 与各领域读取过滤。管理者驾驶舱 `GET /v1/personal/project-cockpit`：“项目”页第四视图（P75-2/3），一行文字计数可点筛选，按健康度分组，与项目列表同源；项目集/品类/负责人筛选，视图存本浏览器；资源冲突、状态更新缺失、小Pai 例外标“未接入”；旧 `?area=cockpit` 计数卡片页改为此视图。项目集：看板按成员健康度分组，详情加阶段、健康度列，每行“归属”直接换项目集（复用已登记 `project.set.move`）。
    - 验证：PG（隔离 `pdos_test`，显式 `TEST_DATABASE_URL`，已销毁）新增 3 例 + 规则 9 例 + 治理 5 例，改 `activity.py` 后与项目动态合跑 46 例全过；邻近 7 个文件 83 例全过。前端 tsc、eslint 0 错误，全部 `.mjs` 1952/1952。合同重导只增两条读接口，校验通过（87/92/67）。浏览器亮暗两种主题与 375px 走查（截图 00–13），含驾驶舱筛选、概览“去办理”、项目集直接换归属；概览读取由 2.8–5.4 s 优化到约 0.5–0.9 s。
    - 余项：D400–D409。
  - ⑧ ✅ 11-09 资格评测集、按运行指标自动降级、抽检、判据登记，以及 AI 价值指标（W8 D117）。分支 `claude/epic-chatterjee-780576`，本地提交、未推送，[结果与证据](../docs/reports/evidence/w6-d37-8-qualification-20261109/README.md)。迁移占位 `s0_0890`（指标函数与索引）、`s0_0891`（三张表），接 `s0_0869`，**集成时按真实 head 重排**（11-10 第五轮集成改为 `s0_0874`、`s0_0875`，接 `s0_0873`）。用户 11-09 裁定见确认稿 [P109](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p109)、[P110](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p110)。
    - 可用能力：
      - 价值指标（D117）：按“租户 × 技能包 × 模型版本”从执行账本里已完成的 T0 写入、回执、整次或单条撤回、之后的人工正式改动确定性计算撤回率、人工修改率、草稿保留率、原样保留率，只读；管理员在设置 › 小Pai与模型 › 技能与资格查看，附口径与依据运行。
      - 自动降级：撤回率 >5%（最近 20 次 T0 运行）对所有 T0 技能生效，人工修改率 >30%、框架检查失败率 >10% 只对 `work_management`；窗口不满记 N/A 不判定。T0 闸门越线即改走一次确认，并由数据库函数重算事实后写降级记录（原因、阈值、指标、依据运行、资格负责人）；人撤回运行时同事务记录。恢复只能经 `ai.skill.qualify`，且只能用降级之后的审阅。不经模型判断。
      - 抽检（P42）：运行编号哈希 20%，每周（北京时间）补足到 min(2, 当周 T0 数)；`ai.skill.spot_check.record`（T1，当前租户管理员本人）标注正确、普通错误或关键错误（五类），关键错误同事务暂停，普通错误计入人工修改率。
      - 评测集：`ai.skill.eval_set.register`（T1）按“租户 × 技能包”登记固定版本（评测规则 §5.2 字段，内容摘要固定，版本连续），审阅可引用评测集案例，按当前技能与模型统计覆盖。不授予任何资格。
      - 通知：技能资格页置顶“待复审”（技能、事实、依据运行、资格负责人），“技能与资格”子标签带计数。
      - 判据：AT-64–AT-66 写入 v1.1 附录 B 与 `acceptance.json`；两条新命令按 D56 先例登记在附录 A 表下与辅助操作合同；§06.12 末段加注指向 P42。
      - 三张表只追加，AI 身份零读写，只有当前租户管理员本人可读；降级记录无应用写入权限。
    - 证据：见上面链接（PG 用例、前端检查、合同校验、迁移往返、浏览器亮暗与 375px 走查）。
    - 余项：D410–D417。
- D366 讨论与评论首批只挂项目、任务、文档；问题、Build、提案条目下的评论未接（设计稿 §6.1 列出的其余对象），需要时按同一受众复核方式扩展 `discussion_subject_open` 与 `discussion_person_open`。
- D367 文档评论只有后端与 PG 测试，前端文件页尚无评论入口。
- D368 @对象只支持任务引用（渲染为标签），设计稿 §7.1 的“被提及于”反向链接列表未做。
- D369 通知合并窗口 10 分钟是代码常量（P41 第 9 项要求租户可改的缺省值），租户设置入口未做；小Pai 主动提及的冷却期已随 ⑥ 实现（缺省 1 个工作日，同为常量，租户可改并入 D391）。
- D370 “关注动态改为每日摘要”目前只在收件箱“每日摘要”视图列出未读关注变化，未并入个人每日摘要的定时推送；“提及若干分钟未读才推送到手机”与钉钉推送属第二批（P41 第 5 项）。
- D371 30 秒轮询回退走常规鉴权，会像现有轮询一样刷新会话空闲计时；SSE 流内用不计活动的核对（`peek`），不会。是否让轮询也不计活动，随 D214 余项一并定。
- D372 交接视图提交成果时沿用任务已固定的来源，不能另选资料；外部等待在交接期的办理只有后端（无前端入口）。
- D373 浏览器验证中，测试夹具扫描的原件在预览 API 下被判“无当前有效扫描”（D215 规则，扫描配置不同），第二份种子改用不带原件的登记资料；真实原件来源的交接提交只由 PG 测试覆盖。
- D374 ✅ 11-09 随 D37 ⑧ 写入：AT-64–AT-66 进 v1.1 附录 B 与 `contracts/acceptance.json`，附注日期和依据。原记录：AT-65、AT-66 判据尚未写入 `contracts/acceptance.json` 与 v1.1 附录 B（归 ⑧，P41 第 11 项）。
- D375 本分支重导了整份 `contracts/openapi.json`，其中也包含 M1、D42 此前未导出的接口；集成时按真实 head 再导一次。
- D376 自动完全移出在任务验收或改派、承诺验收、外部等待记录后触发；负责人取消任务（P48）和停用者已承接任务的改派随 W6 ③（P99）。
- D390 ✅ 11-09 定并实施：§7.4 第 2 种“补充信息时 @ 谁”由服务器按串所挂对象推定，任务评论串 @ 受派人（无则负责人），项目讨论串不另 @ 人，通知不带问题原文，见[P105](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p105)。原记录：设计未定义“负责这项信息的人”。
- D391 冷却期（1 个工作日，上海时区周一至周五）与通知合并窗口（10 分钟）都是代码常量，P41 第 9 项要求租户可改；工作日历（D221）接通后冷却期改按租户日历。
- D392 钉钉群（P31）的群内引文核对仍用企业检索台账与群成员绑定那套，未切到本项的“全部读取来源 × 每位受众”核对（`agent_delivery.audience_check`），P62 第 3 项要求两渠道共用一套。
- D393 串内运行过程只给发起人看（在小Pai 中打开）；设计稿 §7.3 第 3 项“有权看回复的人可以展开看过程（B18）”对其他受众未做，需要先定他人读取运行过程的权限口径。
- D394 小Pai 在串内运行中准备的一次确认候选、T0 回执与撤回入口仍只在发起人的小Pai 会话里办理；串内确认卡（P64 他人可确认）未做。
- D395 任务负责人“交给小Pai 处理”的委托（设计稿 §7.3 第 7 项，WorkRequest）未做。
- D396 收件箱筛选没有“小Pai 需要我”分类、通知未显示后端已返回的签名“小Pai · 按某某的规则”（收件箱页面归 W7）；自动化规则例外的主动提及由自动化规则会话调用 `agent_mentions.notify(..., "agent.rule_exception", latest={"rule_owner_id": …})` 接入。
- D397 串内小Pai 运行本身（XiaopaiWork + 合成模型）没有端到端跑过；PG 与浏览器里的“运行结束”由测试替身完成。投递工作流已经本地 Temporal 跑通（发现 → 工作流 → activity → 注册图节点 → SQL 投递）。
- D398 `openapi.json` 里讨论的 `NewMessage` 因新增 `agent_private` 与收件箱同名结构不再合并，组件名带模块前缀；集成时按真实 head 重导并核对前端类型生成。
- D399 小Pai 的公开回复与分享不给串的关注者发“关注的变化”通知（按 DC-11 §5 小Pai 写入不通知的保守口径）；是否通知关注者待评。
- D400 小Pai 值班摘要的非零路径没有 PG 用例：小Pai 的真实写入要经 Temporal 运行，本次未下载；只覆盖“近 7 天未写入”。另外这些写入目前不能按运行撤回（`core/run_revert` 不含 `work.task.create`），取消小Pai 自建未承接的任务随 W6 ③（P48）。
- D401 状态更新周期、“状态更新缺失”和小Pai 例外：读模型已留位并标“未接入”，等自动化规则会话落地后接入概览、项目列表与驾驶舱计数。
- D402 跨项目资源冲突读集未接入：驾驶舱“资源冲突”标未接入，冲突仍在各项目计划候选比较里看。
- D403 P0/P1 分级未建：概览按问题记录的风险等级（严重/高/中/低/未分级）列出未关闭问题，没有映射成 P0/P1；对应关系待定。
- D404 “本周滑期节点”只看当前值（预测晚于基线或未履行承诺），不回溯本周内何时变化；要做“本周”需预测历史。
- D405 驾驶舱保存视图只存在本浏览器（每人便利，不跨设备）；需要时并入个人偏好。
- D406 跨项目比较现按阶段模板的出口条件；框架出口成果随阶段节点（D36，依赖 D34、D66、D223）建成后改接，概览与驾驶舱的“阶段节点未建”同时替换。
- D407 旧 `?area=cockpit` 入口的外框没有套“项目”页样式，375px 下左右留白比“项目”页宽（无横向溢出）；`app-shell.tsx` 一处条件，留给 W7/壳层。
- D408 “需要办理”未列交样待品质接收（验证交接 offered）：按品质专业角色、按型号读取，需另接；现可从“试制与验证 → 交样与接收”办理。
- D409 项目负责人默认进“概览”（P75-1）归 W7，未改；项目集详情表在窄屏要横向滑动才看到“归属”列（沿用既有表格约定）。
- D410 `work_management` 的人工修改率按 P41 原口径（承接前负责角色、交付物、依赖或工期被改，或任务被删，最近 50 个小Pai 建立的任务）待 W6 ③ 的 `work.*` T0 命令上线后接入；框架检查失败率待 W6 ② D34 的检查器留下记录后接入。目前两项显示 N/A。
- D411 人工修改按回执所指对象判断：提案条目、型号定义条目的回执指向整个提案或定义版本，人改同一提案里别的条目也会算作修改。草稿类的修改率只作价值指标、不触发降级（P109），条目级口径待细化。
- D412 越线降级在 T0 闸门里记录，闸门在小Pai 运行的事务里执行：降级记录由数据库函数重算事实后写入，`triggered_by` 记为小Pai 身份，AI 身份对该表零直接权限。人工修改率越线（只 `work_management`）没有独立的定时复核，要等下一次 T0 尝试或撤回时才落记录；在此之前闸门照样按实时计算拒绝 T0。
- D413 通知中心、收件箱与外发事件：降级记录没有命令回执，而 outbox 事件必须绑定回执和品类，所以 `ai.skill_quality_held` 事件未写；抽检关键错误随 `ai.skill_spot_checked` 外发。资格负责人停用时“通知全部当前租户管理员”目前只体现在置顶横幅（管理员都能看到），未单独推送。随 W6 ⑥、W7 合并后补（P110 第 3 项）。
- D414 抽检周界固定按北京时间；租户工作日历（D221）接通后是否改用租户时区未定。抽样函数只看最近 500 次 T0 运行，更早的运行不能标注。
- D415 抽检标注与评测集登记的前端没有本地恢复记录（提交后网络中断，重试会被“已标注”或版本号拒绝，须刷新核对）；评测集用 JSON 文本录入，没有逐字段表单。
- D416 待复审计数只在“技能与资格”子标签上，顶层“小Pai与模型”标签和侧栏“设置”没有；计数在页面打开时读一次，不实时刷新。
- D417 浏览器走查的资格行是合成种子（关闭触发器写入，模型未配置，页面显示“模型 未登记”）；真实的审阅→具名批准→降级→重审恢复链路只由 PG 用例覆盖。抽检标注与评测集登记两条命令在浏览器里实际提交并取得回执。

**W7 UI 对齐余项（实现缺口；依据 10-26 对照报告，涉及的文件多数自 10-25 起没改过）**
- D38 ✅ 11-09 我的工作（分支 `claude/wonderful-visvesvaraya-922b5d`，本地提交未推送，[证据](../docs/reports/evidence/pdos-next-w7-my-work-20261109/README.md)）。可用：“待我处理”按要我决定、要我接收、要我验证、等外部回复分组，另列“我的任务”（用户 11-10 选定，见[确认稿 P111](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p111)）；“承诺”页切换“我承诺的 / 别人承诺给我的”，后者来自个人项目工作新队列 `received`（带承诺人，过滤规则同“我承诺的”：已验收履行的不列）；“继续提案”改为提案 / 入口 / 状态 / 更新四列并标私有（提案列表接口加 `entry_kind`、`updated_at`）。余项：阶段进度条 D420，“最新预计”D421，开测承诺接收方 D422，导出 D425。原记录：双向承诺（我承诺的 / 别人承诺给我的）；“继续提案”缺入口和更新列；“继续项目”缺阶段进度条（随 D18）。
- D39 项目：任务工具栏收成一行，默认显示当前阶段，补任务编号和状态图标；~~概览缺健康度摘要和直接办理入口~~（✅ 11-09 随 D37 ⑦，[证据](../docs/reports/evidence/w6-cockpit-20261109/README.md)）；计划页里程碑下重复列出明细；文件页缺版本和所属对象汇总。
- D40 ✅ 11-08 提案和专业页 UI 补齐（分支 `claude/busy-kare-1f02fd`，本地提交未推送，[证据](../docs/reports/evidence/pdos-next-d40-ui-20261108/README.md)）。原记录：方案 A/B 并排、单元格直改，待决问题可手动增删；专业页的长表单改成按需打开的抽屉；型号页仍是 7 个标签；成员页缺责任列和范围；个人偏好缺待处理提醒和默认首页。
  - 可用：提案方案按列并排，名称/类型/说明单元格直改，改动累积后“保存修订”一次保存（`proposal.item.patch`），可添加、删除方案；待决问题同一行直改，“添加问题”与改问题/负责人/期限都走 `proposal.question.create` 预览加一次确认，删除走 patch remove，状态与答复随“保存修订”；确认框标题按操作区分（原先改派也显示“确认提交 G0”）。专业页有摘要或记录列表的分区改为标题旁“专业办理”打开右侧抽屉（880px，窄屏全屏，关闭后未保存填写保留），记录详情改为详情抽屉；产品定义改为版本紧凑列表，详情与编辑各在抽屉。型号页改为单页概要（用途、当前定义、平台关联、当前项目）加“版本与派生”表，7 个专业区按需在抽屉打开，旧 `?view=` 深链仍可直达。成员页三列：责任取 D33 项目团队与角色目录（角色、主责、项目负责人，按项目分行），范围标当前品类或“需要品类授权”。个人偏好加“需要我处理的提醒”（侧栏“我的工作”旁显示要我决定 + 接收 + 验证的数，读不回不显示）和“默认首页”（我的工作 / 收件箱 / 项目，只在未指定页面时生效）；存于现有 `personal_preferences.body`，**无迁移**（未用占位号 `s0_0878`），两字段不进入小Pai运行上下文；`contracts/openapi.json` 已重新导出，差异只有这两个字段。
  - 验证：前端全部 `.mjs` 测试 1924 通过，tsc 通过，eslint 0 错误；服务器偏好单元与 PG 测试 38 通过、受影响的运行上下文测试 12 通过、`test_public_api` 与 `validate_contracts` 通过（隔离 `pdos_test`，已 destroy）。浏览器用三个合成账号走查，亮暗两种主题和 375px，截图 22 张。
  - 余项：D336–D341。
- D336 ✅ 11-09 W7 修：重读时保留文档，读回后同一次渲染替换文档并清掉已保存的草稿；表格焦点等保存结束、输入框解锁后再落到相邻行；视图结果仍先撤下再重读（来源原文可能已失效，原有测试要求）。浏览器验证：触发重读后单元格元素未卸载，输入与焦点保留。原记录：（11-08 D40 走查时发现）提案页在窗口重新获得焦点和每次保存后都整页重读：文档先卸载再出现，删除/新增后的焦点无法落到相邻行，重读期间在单元格里的输入会丢（草稿本身保留）。建议重读时保留旧文档显示，只在读回后替换。
- D337 ✅ 11-09 W7 修：参与人接口加只读 `can_read_proposal`（与 `proposal.question.create` 同用 `m3_audience_member`）；问题负责人下拉只列可读者，表下提示另有几位需先共享，已指定但不能读的负责人行内标出。原记录：（11-08 D40 走查时发现）待决问题负责人下拉列出品类全部参与人，私有提案选了不在受众内的人时服务器按规则拒绝，但错误显示在页面顶部、离该行很远。参与人接口若能带“可读此提案”标记，可只列可选的人并就地提示。
- D338 成员页的责任在浏览器端汇总：先读全部可见项目，再逐个项目读团队（并发 4）。试点规模可用；项目多时应加只读的品类团队汇总投影，一次读回。
- D339 专业记录详情抽屉只有单元测试；D40 的合成环境里没有试制、质量、变更记录，未在浏览器用真实记录走查。随 D43 补。
- D340 型号概要未显示设计稿的“工程配置”行（无项目时没有现成只读来源）；设计稿 A/B 下方的“当前取舍”行也未放，正式数据中取舍记录在提案“更多 → 决策记录”。需要时另定读取口径。
- D341 ✅ 11-09 W7 修：未指定页面的入口最多等 1.5 秒读回偏好再显示首页，超时按默认显示且迟到的偏好不再跳页；提醒数口径改为要我决定（含小Pai运行，每个运行计一项）+ 要我接收 + 要我验证，本人在办任务和等外部回复不计。慢偏好场景只有单元覆盖，浏览器未复现（偏好接口约 0.4 秒）。原记录：默认首页在偏好读回后才切换，接口慢时会先闪一下“我的工作”；提醒数只计要我决定、接收、验证，不含“我的任务”和小Pai等待。
- D420 （11-09 W7）“继续项目”的阶段进度条依赖阶段节点（D36），未做。
- D421 （11-09 W7）承诺页没有“最新预计”：承诺记录只有承诺时点，计划引擎的预测是项目级候选，没有按承诺登记的预计事实；现只显示承诺日期与到期状态。
- D422 （11-09 W7）开测承诺没有记录接收方，因此不进入“别人承诺给我的”，只在“我承诺的”列出。
- D423 （11-09 W7）整包确认只覆盖品类运行里的标准候选（T0/T1 内容候选、研究来源登记、G0 提交）；资料跟进、复验准备、品类创建候选和个人运行仍在对话中逐项办理，个人运行没有候选读取接口。
- D424 （11-09 W7）待答问题在“要我决定”只展示，作答仍跳到对话中。
- D425 （11-09 W7）“我的工作”导出（D56）未含“别人承诺给我的”和小Pai运行分组。
- D426 （11-09 W7）`run-decisions` 读取最多 30 个运行、每运行 200 条候选，超出时界面提示，未按运行分页。
- D41 ~~项目集：健康度看板、详情里的阶段和健康度列、直接换归属~~（✅ 11-09 随 D37 ⑦，复用 `project.set.move`，[证据](../docs/reports/evidence/w6-cockpit-20261109/README.md)）。收件箱：工作通知、同事提及、聊天关联项目，这部分和 D37 合在一起做。
- D42 ✅ 11-08 附件入口与历史栏（分支 `claude/charming-almeida-2d1941`，本地提交未推送，[证据](../docs/reports/evidence/pdos-next-d42-d55-attachments-20261108/README.md)）。个人聊天携带附件按用户 11-08 选定的 B 案实施，决策见[确认稿 P91](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p91)。
  - 可用：个人聊天输入框有“附件”入口，可勾选本人当前可读的已登记原件（新接口 `GET /v1/personal/agent-input-sources`，跨品类、带所属品类），或选存放品类后上传新文件；拖入输入框即打开上传并预填，本人确认上传后走原有原件登记、扫描、去重路径，扫描解析完成后自动加入本次携带；已携带资料以小标签显示在输入框上方，可逐个移除；续问可再加附件，并沿用上一轮服务器已绑定的附件（每份重新核对）。品类小Pai 同样支持拖入和上传后自动携带。服务器按 run 上下文逐份核对（本人以人员身份、来源品类成员资格、小Pai 在该品类的读取授权、受众、精确版本、原件安全），运行记录 `versions.personal_sources` 记下每份来源的品类和数据类别；数据库守卫改为条件放行（迁移占位号 `s0_0860`，集成时按真实 head 重排）；权限收回后运行按既有规则隐藏、续问 403；M1 召回经 RLS 与依赖清单两层复核。历史栏改为随视口（1000px 断点）和整页/侧栏状态更新。
  - 集成注意：① `server/pdos_next/agent/kernel/bootstrap.py` 只改了 `binding_for` 个人入口路径（约 10 行），主工作区另一线程对该文件有未提交改动，落主线时会冲突，需手工合并；② `s0_0860` 的升级前置条件是三条函数（`kernel_read_set_visible`、`kernel_source_reference_gate`、`kernel_source_reference_clock`）与 s0_0855 head 逐字一致，若集成分支上别的迁移改过它们，须按真实 head 重新生成 `schema_s0_0860.py`（11-08 集成时核对：s0_0856–s0_0859 都没有重定义这三条函数，也没改它们依赖的 `direct_source_set_visible`、`scope_actor`、`scope_requester` 和所读表的策略，SQL 不变，只把 down 改为 `s0_0859`）；③ `security_runtime/parser-image.json` 指向本机重建的解析器镜像（只在本机有效），其他机器须用 `containers/evidence-parser/build.py` 重建。
  - 余项：两项待复现风险（新候选不替换已打开的编辑区、品类冷恢复时名称取 AI 原候选）未做，相关文件在主工作区另一线程中；`contracts/openapi.json` 未重导出新接口（同 M1，下次统一导出）；见 D274–D276。
  - 11-08 第三轮集成时发现：`test_source_views` 一条旧测试仍断言 `/v1/personal/agent-input-sources` 为 404，在本分支上就失败，未修，见 W4 第三轮集成记录。
- D43 UI 冻结候选检查：10-26 之后大批改动一直没跑过整链。要做：
  - 亮暗主题 × 多尺寸各跑一遍；
  - 补余验：新上传文件进 Run、品类候选保存、会话改名/置顶/归档、320px 宽度；
  - 补样本后再验：手机确认、新保存提案续接，目前缺合成样本；
  - Prompt 设置页截图；知识页 10-29 因 RAG 改过，需要你目测确认；
  - 数据问题：旧合成原件的安全扫描失效（SOURCE_UNAVAILABLE），外部生效回执有指纹冲突。
- D52 ✅ 11-08 ⌘K 执行命令与快速创建，[证据](../docs/reports/evidence/pdos-next-d52-command-palette-20261108/README.md)。面板在对象搜索之外加“快速创建”和“跳转”：只接 4 个已登记、已实现的页面入口（项目内新建任务 `work.task.create`、写状态更新 `work.status_update.create`；有产品管理权的品类新建立项提案 `proposal.create`；新建品类 `category.create`），单元测试逐条对照 `operations.json` 的档位；可见性只认服务器当次读回的 `capabilities.product_management` 与项目成员 `can_write`，读不回就不显示；T2 不进面板，完整编号只定位。选中命令只打开原页面的同一个表单，确认与服务器权限检查照旧。键盘 ↑↓/Enter/Esc，亮暗与 375px 已在浏览器按产品经理、工程师两个合成账号走查。余项：只在当前所在项目给项目内快速创建；外部等待、质量问题、变更、Build、验证请求等需对象上下文的入口未接。D108 的恢复条件已满足。原记录：P22 的 B19 已确认，但现在 ⌘K 只能搜索跳转（`object-search.tsx`）。按命令登记表和角色收窄。
- D55 ✅ 11-08 DOCX、拖入、照片登记（F12），随 D42 一起完成，[证据](../docs/reports/evidence/pdos-next-d42-d55-attachments-20261108/README.md)。服务器原件接收原来只认 TXT/MD/PDF/XLSX，现补：DOCX（隔离解析器容器内只用标准库解析正文段落和表格行，每段/每行一个可定位行；拒绝宏、ActiveX、嵌入对象、外链模板/子文档、实体声明和超限压缩；无正文时记为需要 OCR）；照片 JPG/PNG/WebP/HEIC 只按文件头核对类型后登记为原件，派生一行登记文字（格式与字节数、“未执行 OCR”），解析码 `OCR_NOT_PERFORMED`，可作为来源被引用，不识别图像内容（OCR 属于记忆层 M4）。宿主机预检、对象存储、上传目标、前端校验与选择框同步放开；解析器镜像已在本机按新源码重建。拖入：输入框整体可拖入，品类与个人小Pai 都适用。
- D271 ✅ 11-09 W7 修：全局样式在 base 层补 `dialog { margin: auto }`；核对 51 个 dialog：抽屉与侧栏类（DetailSheet/RetainedSheet、知识详情、手机导航、候选编辑区）都显式 `margin:0` 不受影响，其余模态（新建品类、确认框、各 Build/制造/型号专业确认等约 25 个原先贴左上角）现在居中；ui-lab 的 dialog 都自带边距。浏览器量得无类名模态左右、上下边距相等。原记录：（11-08 D52 走查时发现）原生 `<dialog>` 多数贴左上角显示：Tailwind v4 预置样式把 dialog 的 margin 清零，全局 `dialog` 样式没有补居中；`web/src` 的 55 个 dialog 只有 7 个自带 `m-auto`。可见于新建品类、新建提案对话框（页面按钮与 ⌘K 打开的一样）。随 D43 一并核对哪些本应居中。
- D274 ✅ 11-10 已修（新迁移 `s0_0915_personal_run_lifecycle`，占位号，接 `s0_0869`，**集成时按真实 head 重排**，11-11 第五轮集成改为 `s0_0887`，接 `s0_0886`；本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md)）：`m3_lifecycle_nodes` 加个人运行一段，口径同钉钉个人回答：个人运行没有品类，只要 `versions.personal_sources` 里有来源的品类回执是 c，就以 `agent_runs` 节点进入品类 c 的图，链接只取回执是 c 的那部分来源；同一个运行在每个来源品类各进一次。品类运行不变；与品类运行一样只进全图，不进按标识的根查找。生命周期时钟早由 `s0_0860` 推进，这次补的是图。迁移前后用 `require_functions` 逐字核对 `s0_0852` 的原定义和新定义，两个方向都核对；函数属主仍是 `pdos_next_owner`。验证：新 PG 用例 2 个（每个品类图只含本品类的来源；清除规划读取的引用摘要把运行计入，同一原件 19→20；退到 `s0_0869` 时 19→19，两个用例都失败）；受影响的 PG 与迁移文件 17 个、336 个通过；`s0_0869`↔`s0_0915` 往返通过。余项 D462。原记录：个人运行携带业务来源后，原件生命周期图（`m3_lifecycle_nodes`）仍按品类只扫 `agent_runs.category_id = c` 的运行，看不到个人运行对来源的引用；清除或保留规划可能漏算这些引用。读取时已复核（来源撤回后回答收起引用、运行按权限隐藏），但生命周期侧应参照钉钉个人回答按 `source_dependencies.category_id` 登记的做法补上（P91 实施时发现，11-08）。
- D462 （11-10 修 D274 时登记）生命周期图每次构建都扫描租户内全部个人运行（`category_id IS NULL`，有索引），再逐行查 `versions.personal_sources` 的品类；没有按来源品类的索引。试点规模可用；个人运行多了以后可加表达式索引或单独的来源回执表。
- D275 本地预览没有 Temporal worker 时，上传的原件不会自动扫描和解析，附件面板会一直停在“扫描与解析完成后才可携带”；D42 验收是用脚本调用同一套扫描/解析函数补的。闭环检查点（D43）应在带 worker 的预览环境里再走一遍上传→自动携带。
- D276 附件面板重新打开时，上传组件会从本地恢复上一份上传的回读记录；按 D42 的取舍，恢复的记录不会再自动加入携带（避免把旧文件带进新对话），需在“选择已有原件”里手选。若希望保留“未完成扫描的文件完成后自动加入”，需要把待携带意图持久化到会话草稿，另议。

**W8 小Pai 架构余项（实现缺口）**
- D44 三处结构问题：
  - 操作者指令以 role:user 注入（graph.py:201-203）：🟡 11-08 负例已补并本地提交（未推送），[证据](../docs/reports/evidence/w8-d269-d44-20261108/README.md)。
    - `test_injected_instructions_pg.py` 3 例：原件、知识条目、MCP 返回里各嵌入“忽略以上规则……写入任务、发到外部、改范围和受众”。模型桩一看到就照做。
    - 结果：写入任务、新增共享知识（要已加载技能）、外部共享与跨品类读取（服务器绑定范围）、读外网（原文只能在隔离子任务读）、调用未准入或未授权的 MCP，全部被服务器拒绝。没有回执，运行范围和受众不变，除脚本模型外没有出站。注入文字只出现在工具结果里，没有进 role:user 消息。
    - 没有暴露要修的缺陷。结构问题本身未改：初始 role:user 信封里仍有来自资料的文字（D356），“不可信”标注有缺口（D357）。两者都要改模型可见的提示，须走 Prompt A/B。
    - 原记录：先补“原件内含指令”的负例。
  - 运行中等人确认没有通用抽象，目前只有 `await_category_adoption` 一例；
  - tools 闭包约 280 行。
- D45 续建与补写：
  - 记忆五层：按[记忆层设计](../docs/design/2026-11-05-xiaopai-memory-layer-design.md) §13 分期实施（D253 已确认，P84–P90），迁移按实施时真实 head 编号：
    - M1 情景回忆：🟡 11-07 已在分支 `claude/m1-episodic-memory-324cdf` 实现并本地提交，待你决定合并（未推送）。
      - 可用：迁移 s0_0855 新增 `memory_episodes`、`memory_episode_marks`、`memory_index`、`memory_session_settings`、`memory_tenant_policies`；运行收尾时，数据库从同一事务里提交的工作状态版本投影出一条情景（延迟触发器，含使用清单、企业检索状态、未完成事项），任何运行身份（含 AI）都不能直接写、改、删情景；置顶/隐藏、纠正记录（来自运行反馈）、分词索引和会话开关只接受本人以人的身份写，AI 身份被数据库拒绝。只读工具 `memory.search`（所有范围都下发，查询人与范围由服务器绑定，逐条按当前权限、依赖清单和出站类别复核，归档会话与隐藏条目不返回，索引滞后时补扫未索引情景、不冒充零结果）；`conversation.history` 可按 session_id 读本人其他会话（隐藏规则照 P32，引用不沿用）；品类、型号、提案、项目范围的运行在运行信封背景区放同范围最近 3 次目录（≤300 token，只用 SQL，钉钉与个人入口不放，超预算先裁）；后台 Temporal 分词索引（扫描器 + 工作流，幂等键 = 来源 + 版本 + 嵌入配置版本）；会话列表搜索走同一索引；“不进记忆”开关（新会话随首条消息、已有会话在输入区切换）；回答下方“用到了 N 条记忆”；工作状态闲置超过租户时效（缺省 30 天，管理员可改）不自动带入，“本次携带”一键恢复；本人可添加约束、确认或不采用待确认的转述约束（以本人身份追加版本）；写入关口：提议只认本人原话里的明确指代词，页面资料、原件文字不能触发，索引只收本人原话。生命周期目录已登记 5 张表；AT-71–AT-74 写进 v1.1 附录 B 与 `contracts/acceptance.json`，`memory.search` 登记在附录 A。
      - 证据：见[M1 证据说明](../docs/reports/evidence/pdos-next-memory-m1-20261107/README.md)（隔离临时库 `pdos_test` 上的门禁与受影响回归、前端测试、合同校验、迁移往返）。
      - 缺口：① 小Pai 提议转述约束要改输出合同，冻结提示词 1.0.0 写着“服务器拒绝转述”，须走提示词版本升级与 Prompt A/B，当前按版本关闭，只有人工添加/确认路径可用；② ✅ 11-13 已实现会话删除（分支 `claude/memory-session-controls-bb2951`，本地提交、未推送，迁移占位号 `s0_0940`，[证据](../docs/reports/evidence/pdos-next-memory-session-controls-20261113/README.md)）：本人删除后情景、标记、索引、向量和未采纳的提议立即清除，只留不含正文的删除记录，余项见 D520、D521；③ 情景卡只显示范围对象的当前标题，焦点对象未逐个列标题；④ `contracts/openapi.json` 未重导出（导出会整体重排约万行），新接口在下次统一导出时进入；⑤ 未做真实 Temporal 下的索引工作流联调、HTTP/浏览器整链与亮暗/多尺寸检查；⑥ 理想记忆组与单类消融要等 M2a/M2b，评测题仍是候选，须你确认才入库；⑦ v1.1 §06.4/§06.7/§06.8 等正文待同步未改。
      - 下一步：合并后在闭环检查点补 Temporal 联调与浏览器检查；M2a 本人记忆条目（含情景向量化、`memory_candidates` 走 Prompt A/B）。
    - M2a 本人记忆条目：🟡 11-08 已在分支 `claude/intelligent-banach-bd90dd` 实现并本地提交，待集成（未推送）。迁移占位号 `s0_0865`、`s0_0866`（接 `s0_0861`；`s0_0862`–`s0_0864` 归并行会话），**集成时按真实 head 重排**。11-09 第四轮集成时编号不变，`s0_0865` 的 down 改为 W4 的 `s0_0864`。
      - 可用：
        - 条目：`memory_notes`（只有身份）＋ `memory_note_versions`（口径 / 背景 / 叫法，≤200 字，作用域为全局或品类、产品、提案、项目，服务器按当前可读性校验；可自设有效期；叫法指向标准词或对象引用），修改即追加版本，最多 50 条。只有本人以真人身份能写、改、删，AI 身份被数据库拒绝。删除即清除全部版本正文和来源提议，只留删除记录（`memory_note_deletions`）。
        - 冲突：代码按作用域重叠（同范围或任一方全局）和分词重合找出相似旧条目（同叫法词，或共享 ≥2 个词、重合度 ≥0.34），本人选合并（旧条目追加合并版）、替换（旧条目标“已替换”并记失效时间，留在历史）或都保留；没选不保存。
        - 提议卡：`memory_candidates` ＋ 本人决定表。服务器在运行收尾时按确定性规则接收：只认本人这一轮原话里的“记住”类说法（主动提议须引用本人本会话至少两轮原话、每会话最多一次、本人与管理员都未关闭），页面资料与原件文字不能触发或填写，作用域只能是全局或本次运行的范围，7 天过期；不进记忆、钉钉、管理员关闭时一律不接收。**按提示词版本关闭**（冻结提示词 1.0.0 没有这项输出，`MEMORY_CANDIDATE_PROMPT_VERSIONS` 为空）；本人“记住 / 忽略”和冲突选择的路径可用，运行回答下方和“我的记忆”页都显示提议卡。
        - 常驻注入：运行首次组装上下文时，服务器取本人全局条目和本次范围条目，口径、叫法进约束区，背景和“可能过期”进背景区，标“不是业务事实，不能作为依据引用”，≤1,000 token（本范围、最近确认优先，告诉模型还有几条可用 `memory.search` 查），冻结于运行，不进冻结前缀；超预算时背景区与情景目录先裁，再把约束区截到只剩本范围条目。个人入口只带全局条目；不进记忆、钉钉、管理员关闭时不读。每次模型调用前复核：带入的条目被删除或范围不可读时停下。“用到了 N 条记忆”列出用到的条目（已删除的只说已删除）。
        - 个人叫法：只对本人生效，`memory.search` 和企业检索 `assistant.search` 都按本人确认的叫法补充标准词，结果里标明补了什么。
        - `memory.search` 支持 `kinds=["note"]`：只查本人条目，范围同情景，逐条复核状态与可读性。
        - 管理员：租户策略加“自由文本记忆”“主动提议”两个开关（设置 › 小Pai与模型 › 记忆策略）；只看启用状态和条目数量（`memory_note_statistics`，非管理员被数据库拒绝），看不到正文。本人可在“我的记忆”关掉主动提议。
        - 情景向量化：数据类别新增“本人会话记录”（`owner_session`，嵌入配置和服务商协议均可选，默认不勾）。勾选后，后台以记录本人身份、在注册执行图内把本人原话（不含页面资料和回答）送嵌入服务；服务商由配置的连接判定，数据类别为“本人会话记录”加原运行携带的客户类别，私有运行的情景不发送；每批写出站回执（`memory_embedding_calls`：服务商、类别、P26 判定、费用，无正文）并计入租户索引预算。`memory.search` 在查询向量可用时与关键词 RRF 融合；已勾选但查询向量不可用时标“仅关键词”，不冒充零结果；未勾选时零出站。派发角色只能经触发器维护的开关镜像（`memory_vector_profiles`）找到待向量化的情景 ID。
        - “我的记忆”页：设置 › 个人偏好下新增，含待确认提议、添加（口径 / 背景 / 叫法、作用域、有效期）、冲突三选一、修改、历史、删除确认、已替换或过期列表、主动提议开关；亮暗两套主题、375px 已走查。
      - 证据：见[M2a 证据说明](../docs/reports/evidence/pdos-next-memory-m2a-20261108/README.md)。记忆 PG 43 个全过；前端 `.mjs` 1924、`.test.ts` 752 全过；合同校验通过。11-09 回归：无库全量 42 个失败或错误、PG 批次（599 个）46 个失败或错误，都在基点 `07c023e5` 上复跑对照，两边名单逐行一致或串行复跑两边都通过，没有 M2a 引入的失败。
      - 决定：D295–D297 已定为 [P92](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p92)–[P94](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p94)，与实现一致。
      - 余项：D298–D303。
    - M2b 范围条目与场景配方 🟡 机制已实现（11-13 至 11-14，分支 `claude/memory-m2b-scope-notes-6ba1bd` 本地提交，未推送、未合并；按 P87 和 [P121](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p121) 第 3、4、6 项的口径；迁移 `s0_0900` 是占位号，接 `s0_0887`，集成时按真实 head 重排）。小Pai 侧的预填和自动记录还走不到，等 D500、D501：
      - 可用能力：
        - 四张表：`scope_notes`（身份：挂靠对象、种类、主张键）、`scope_note_versions`、`scope_note_evidence`、`scope_note_relations`，全部只追加。版本字段按目标架构 §5.7 的统一契约：事情发生的时间、生效起止、可信状态（有人这样说 / 已核实 / 推断 / 有争议）、业务确认状态（讨论 / 提议 / 成员确认 / 已关联正式记录）、正式对象及版本、来源权威性（服务器按证据算）、生成方式、复核日期。种类四种：约定、关注点、决策背景、观察；决策背景不挂正式对象时标“未形成正式决定”。替代按生效时间判断，补录的更早信息只进历史。
        - 可见性跟随挂靠对象（品类、产品、提案、项目）的受众，读取时现算，不存受众副本；条目引用的对象对读者不可读时，这条对他隐藏。
        - 三个操作，登记在 v1.1 附录 A（表下条目，表内 87 项不变）、`contracts/auxiliary-operations.json`、`events.json`、`payloads.schema.json`：`scope_note.save`、`scope_note.retire`（T1，成员预览受众后确认一次；小Pai 只能预填）；`scope_note.observation.record`（T0，P121 第 4 项的通道，只能记一条未核实的观察或给已有条目补证据链接）。档位按操作登记，所以 T0 通道是第三个操作，不是 `scope_note.save` 的一个参数。没有“租户 × 技能包 × 模型版本”资格时被拒，由注册执行图转成待本人确认；有资格时署小Pai 名、标“提议”、不置顶、只进背景区，只能记在本次运行自己的范围上。`scope_note.retire` 带运行编号时按运行撤回小Pai 自动记下的观察和证据链接。
        - 数据库守卫：每个版本提交时必须对上同一事务的通用回执；AI 写入身份直接插表被拒；本人绕过命令插入也被拒；不能改、不能删（只停用或撤回）。
        - 上下文带入：运行首次组装时按技能合同里的记忆配方（`x-memory`；没有声明时用默认配方）取当前范围链上的条目，只有未降级的“约定”进约束区，其余进背景区，标明不是业务事实、不能作为依据；不超过 800 token，置顶优先。带客户标签的只在运行绑定了同一客户时带入。按 D481 的教训，运行行上只存条目编号、版本号和分区，正文每次从版本表按当前权限读；条目停用、撤回或不可读后不再带入，已带入过的运行在下一次模型调用前停下。个人范围和钉钉入口不带入；“不进记忆”的会话照常带入。
        - 范围近况（只读，不存）：项目范围复用驾驶舱动态流的查询，加本范围备忘的变更，不超过 400 token，冻结在运行开始的时点。
        - `memory.search` 的 `kinds=["scope_note"]`：在 `recall.search` 里只加了一处调用，实现在 `agent/memory/scope_note_search.py`；范围是运行自己的范围链，逐条按当前权限复核。
        - 页面：驾驶舱概览、提案页、品类页各有“团队备忘”区（查看、记一条、修改、历史、停用或撤回、已停用列表）；保存前显示服务器给出的受众和进入哪个区；相似条目须选替代、标为冲突或都保留。“我的记忆”页每条口径和背景有“分享到项目”，提议卡有“记为项目备忘”。“用到了 N 条记忆”里团队备忘单独列出。作者停用或失去品类授权后标“已离开”，复核人显示为对象负责人。
      - 证据：见[M2b 证据说明](../docs/reports/evidence/pdos-next-memory-m2b-20261113/README.md)。范围条目测试 45 个全过（他人不可读、AI 不能直写、无资格不走 T0、撤权后不返回且不带入、停用后运行里不留正文等）；已有记忆测试 76 过、13 跳过（可选的真实服务商与 Temporal 用例）；受影响后端回归 441 个里 440 过，1 个验证开测夹具的时间窗用例在批量里出错、单独重跑通过；迁移 `s0_0887 ↔ s0_0900` 往返通过；合同校验通过；前端类型检查、lint 通过，`.mjs` 1997、`.test.ts` 757 全过；品类页和提案页已在浏览器走查亮暗两套主题，品类页另看了 375px。
      - 余项：D500–D514；D299 的两个入口见该条。个人条目迁移到统一契约（P121 第 6 项后半）未做，记在 D512。
    - M3 沉淀与改进：“经验沉淀”技能包与系统自动化规则、事件扇出与触发起草、改版标待复核、纠正分流、程序性汇总与修订候选审核页、接 Prompt A/B。依赖 M2a、M2b、D246；“经验沉淀”须 golden-case 与资格；
    - M4 感知：扫描件 OCR、照片读数、低置信区域附图片区域。依赖 OCR 与视觉服务的出站判定；
    - 并行：MQE、HyDE 对照评测，租户与品类术语表，pg_trgm 模糊匹配，说法变体评测（52 道候选题）；
  - 上下文 X2/X3 续建；
  - 资格阶梯和评测看板（含影子比对）；
  - 116 条“何时调用”说明待领域负责人补写；
  - 状态机没有集中声明，VerificationRequest 的写入口散在 5 个模块（I01）。
- D295 ✅ 11-08 定：停用保留，见[P92](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p92)。关闭后不带入对话、不检索、不能增改，本人仍可查看和删除，重新打开后恢复；M2a 已按此实现。 原记录：管理员关闭“自由文本记忆”后已有条目怎么办，设计只写了“可以关闭”。
- D296 ✅ 11-08 定：不发送，只做关键词，见[P93](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p93)。私有运行的情景只做关键词；带客户类别的情景须配置里也勾选了客户类别才发送；M2a 已按此实现。 原记录：情景向量化时私有运行的情景是否发送，设计只写“数据类别由服务器判定”。
- D297 ✅ 11-08 定：按 30 天保留期清，见[P94](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p94)。主表、版本、来源提议立即清除；进行中的运行在下一次模型调用前停下；过往检查点副本按 D58 的 30 天保留期清除。删除确认、删除结果和接口返回都已如实告知（M2a）。 原记录：删除条目时“清除正文”的边界没写清，过往运行检查点里的信封副本是否同步清除。
- D298 🟡 11-14 Prompt A/B 支持打开；提示词草稿 1.1.0 已列入放行集合，但没有激活，所以提议路径对当前激活的 1.0.0 仍然关闭（本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-proposal-20261113/README.md)）。
  - 可用：提示词 1.1.0（1.0.0 未动）的输出合同加入 `memory_candidates`；`memory.search` 调用说明补上本人条目、叫法、向量是否可用，并加了 `as_of` 参数；服务器接收规则补齐（见下）。
  - “纠正两次以上”定稿：主动提议须引用本会话至少两个不同运行里的本人原话，每段引用里有固定的纠正说法，且与提议文字有共同的词；每会话最多一次、可关。
  - P121 第 8 项里与提议有关的三小项已做：本人说“这只是讨论，不算决定”时作废本会话待确认候选并防止再次提议（新表 `memory_proposal_voids`）；遗忘后的抑制指纹（新表 `memory_suppressions`，不含正文；本人之后重新明确交代的不受限，确认后解除）；`memory.search` 的 `as_of`（只是查询条件）。迁移 `s0_0920` 是占位号，集成时重排。
  - 离线同题控制通过：12 题无新增准入失败，固定准入 16,445 → 17,095 token。
  - 真实模型 A/B（MiniMax-M3，每题每组 1 次）：既有评测题答出全部关键事实 A 4/5、B 5/5，多出来的提议 0，追问 A 3、B 0；提议探针里不该提议的误提 0/7（B 两轮都是），该提议的 B 提了 4/6（第一轮 6/6），没提成的两次是模型引用不逐字或没带纠正说法、被服务器拒收；回答里说“已记住”的探针 A 4 个、B 0 个。合计约 760 万 token。
  - 这些数字只说明方向：每格 1 次，同一个探针两轮结果不同；探针 14 个是本会话写的，未经你确认。
  - 余项：D530（激活）、D531（被拒收时的提示）、D532（固定说法的漏提）、D533（抑制指纹的摘要方式）、D534（其余缺口）。
  - 原记录：模型输出 `memory_candidates`、`memory.search` 调用说明（目前只写情景）须随新提示词版本走 Prompt A/B 后再开放；主动提议“纠正两次以上”的服务器判定（引用本人本会话至少两轮原话）随之定稿。现在提议路径按提示词版本关闭，只用测试和本地种子脚本模拟过。（M2a，同 M1 缺口 ①）
- D299 🟡 11-14 两个入口已做（M2b 分支，未合并，[证据](../docs/reports/evidence/pdos-next-memory-m2b-20261113/README.md)）：“我的记忆”页每条口径、背景有“分享到项目”，提议卡有“记为项目备忘”；都是本人选项目、看过受众后确认一次，生成一条新的团队备忘，个人条目不变。“分享到项目”面板已在浏览器看过，带库测试覆盖“只有本人能分享自己的条目”；预览租户里没有项目，选了项目之后的保存只由带库测试和同一个表单组件覆盖。“记为项目备忘”还没有在真实提议卡上点过，因为提议路径按提示词版本关闭（D298）。余项：“提议加入品类术语表”仍随并行轨的术语表实现。
- D300 🟡 11-14 已改（本地提交 `69f81d00`、未推送，分支 `claude/memory-retrieval-gaps-7ba7bc`，[证据](../docs/reports/evidence/pdos-next-memory-retrieval-20261114/README.md)）：
  - 可用：情景向量后台流程在真实本地 Temporal 上跑通（派发 → 已注册工作流 → 以本人身份嵌入 → 回执），历史里只有固定引用和小结果。`memory.search` 有了自己的查询嵌入端口，宿主能绑定独立嵌入凭据就默认接上，勾选“本人会话记录”即可融合检索；`assistant.search` 的生产默认仍是仅关键词。数据库查询嵌入守卫（`s0_0838`）原来只认 `assistant.search`，`s0_0960` 改为也认 `memory.search`，其余证明不变（安全守卫放宽，请复核）。换模型：新配置与旧配置并存时两套都写，新空间建好前继续查旧空间，建好后切换；一次查询只用一套空间；旧配置停用后不再派发、不再查询；切换期间关键词检索照常，不出现伪零结果。
  - 验证：带库测试新增 3 例（含 1 例 HTTP → Temporal 实际运行，查询词与原话无共同关键词，靠向量找到）；`tests/agent/memory` 93 通过、12 跳过；相邻企业检索查询嵌入等 138 通过；迁移降级、升级各两次通过。全部是合成服务商，不代表检索质量。
  - 余项：真实嵌入服务联调见 D550；旧向量物理清理见 D551；切换前的评测关口见 D552。
  - 原记录：情景向量化未做真实 Temporal 与真实嵌入服务的联调；`memory.search` 的查询向量复用企业检索的查询嵌入端口，生产默认不配置这个端口，所以勾选后实际仍是“仅关键词”并如实标注。换嵌入模型时的重嵌与切换（设计 §14.9）未做。
- D301 ✅ 11-13（分支 `claude/memory-session-controls-bb2951`，本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-session-controls-20261113/README.md)）“我的记忆”手动添加和修改时可以选产品、提案；可选项来自新增的只读接口 `GET /v1/personal/memory/scope-options`，只列本人当前可读的对象，一次最多 50 条，页面上还没有搜索框。 原记录：“我的记忆”手动添加时作用域只能选全局、品类、项目；产品、提案作用域只能经提议卡或接口写入。
- D302 ✅ 11-14 已同步（本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-proposal-20261113/README.md)第五节）：v1.1 §06.8 增加“个人记忆”一段、附录 A 的 `memory.search` 按实际能力改写，只按 P84–P94、P121 已批准的内容写，没有新增规则；`contracts/auxiliary-operations.json` 同步，三份合同文件的 v1.1 摘要随之更新，合同校验通过。 原记录：v1.1 §06.8 与附录 A、`contracts/auxiliary-operations.json` 中 `memory.search` 的说明仍只写情景记录，未同步 M2a 的条目、叫法与可选向量。
- D500 〔你〕（11-14，M2b）技能包什么时候登记范围条目的三个操作和记忆配方。现在 18 个技能包的 `allowed_operations` 都没有 `scope_note.*`，`context-schemas.json` 也没有 `x-memory` 声明；机制已经做好并有测试（声明后技能摘要随之变化，不认识的声明使技能目录加载失败）。登记会改变相关技能包的摘要和工具摘要，按 P87 第 8 项，这些技能包在试点租户已有的 T0 资格须重审。
  - 选项 A：现在就登记（`work_management` 加带业务记忆配方的技能包），合并后相关技能包的 T0 资格立即失效，等你重审。
  - 选项 B：随下一批提示词与技能包版本一起登记，和 Prompt A/B、`memory.search` 调用说明（D298）同批评测。
  - 建议 B。在此之前：页面办理、上下文带入（按默认配方：范围链上的条目，置顶优先，800 token 内）、`memory.search` 都能用；小Pai 在真实技能里看不到这三个工具，不能预填，T0 通道也走不到。配方里的 `personal`、`knowledge` 两段现在只校验、不改变个人记忆和设计规则的装载。
- D501 〔你〕（11-14，M2b）观察类操作要不要进“草稿类”资格清单。试点里凭你本人审阅 10–20 个案例授 T0 资格，只对 `qualification_binding.DRAFT_OPERATIONS` 里的操作开放；一个技能包只要列了清单外的 T0 写操作，整个包就不能按这条路取得资格。`scope_note.observation.record` 没有加进去。
  - 选项 A：加入清单，列了它的技能包仍可凭审阅记录取得 T0 资格（P121 第 4 项说的“取得资格后可以自动写入”）。
  - 选项 B：不加入，观察类自动记录等正式资格流程；试点里一律由成员确认。
  - 建议 A，和 D500 同批做；加入清单不等于授予资格，资格仍由你审阅后给。
- D502 （11-14，M2b；D500、D501 打开之前不会发生）整次运行撤回 `ai.run.revert` 不认识范围条目的回执：一次运行如果自动记了观察，整次撤回会报“含尚不支持撤回的结果”。已有替代办法：`scope_note.retire` 带运行编号，按运行撤回那次运行自动记下、尚无成员接手的观察和证据链接。恢复条件：`core/run_revert.py` 加范围条目分支，`revert_subjects_consumed` 加对象类型。
- D503 （11-14，M2b；随 D500）小Pai 预填范围条目后，对话里和“我的工作”里没有待确认卡。现在通用准备只把预填好的命令放在工具结果里；持久候选（`PreparedCandidate`、`domain_candidates`）是按操作封闭登记的，这三个操作没有接。已验证的部分：没有资格时命令被拒、不写任何行，同一条命令由本人预览并确认后写入并标“小Pai 起草，成员确认”。恢复条件：`bootstrap.prepare_candidate` 加分支记候选事件，`domain_candidates` 列表和前端 `candidateLabels` 各加一项。讨论中被 @ 和业务事件触发的起草属 M3。
- D504 （11-14，M2b）复核期限固定 90 天（`scope_notes/reads.REVIEW_DAYS`），P87 第 4 项写的是租户可配。要在记忆策略上加一列和一个设置项。
- D505 （11-14，M2b）“包含其他客户项目资料”的开关不存在（RAG 设计 §7.1 的那个选择还没有实现），所以带客户标签的条目只在运行绑定了同一客户时带入和检出，没有跨客户的显式放开。品类和产品层的客户标签是自由文字，提案层必须是提案上登记的客户标识，项目层在来源提案有登记时必须取其一。
- D506 （11-14，M2b）范围近况只有项目有业务动态；提案、产品、品类范围没有可复用的动态流查询，只带备忘变更。
- D507 〔你〕（11-14，M2b；和 D481 一起定）进行中的运行遇到已带入的团队备忘发生变化时怎么办。现在的做法：备忘停用、撤回或对本人不可读，运行在下一次模型调用前停下；备忘被修订或被替代，不停，继续用运行开始时选定的那一版。D481 对个人条目的口径还没定，定了之后两边对齐。
- D508 （11-14，M2b）“待复核”“对象已更新”和作者离开后的复核转交只在读取时标出来，没有通知复核人，也没有进“我的工作”。改版或变更生效后的确定性标记和通知属 M3 的事件扇出。项目层“被移出项目”按项目成员记录判断，没有成员记录的项目只看账号停用和品类授权。
- D509 （11-14，M2b）页面上不能加证据链接、不能挂别的正式对象：表单只能把决策背景关联到挂靠对象的当前版本；接口支持运行、讨论、回执、原件、业务对象五种来源和 G0 决定。历史里只显示证据条数。
- D510 （11-14，M2b）钉钉入口不带入、不检索团队备忘（P31 的引文规则没有接）。
- D511 （11-14，M2b）驾驶舱的备忘区没有做浏览器走查（预览租户里没有项目）；提议卡上的“记为项目备忘”没有在真实卡片上点过（D298）。组件是同一个，项目范围的读写和项目运行的带入有带库测试。
- D512 （11-14，M2b；不在本次范围）个人条目迁移到统一契约（P121 第 6 项后半：`memory_note_versions` 加事情发生的时间、生效起点、业务确认状态、证据链接、关系，现有条目迁移一次）未做，会动 `notes.py`、`assemble.py`，与主会话的改动冲突，另排。范围简报、任务笔记（P121 第 2、5 项）须先有消融结果，也不在本次范围。
- D513 ✅ 11-15 已同步（集成分支，本地提交、未推送）：v1.1 §06.7 加“记忆配方”一段（P87 第 8 项）；§06.8 五层里“项目事实摘要”注明由范围条目与范围近况承担，并补“情景记录”“范围条目与范围近况”两段（P85、P87、P121 第 1、3、4、6、8 项）。只按已批准决定写，没有新增规则；合同里 v1.1 文档的哈希随之更新，合同校验通过。 原记录：D513 （11-14，M2b）v1.1 正文还没有按 P87、P121 同步：§06.7 的上下文合同没有写记忆配方，§06.8 的“项目事实摘要”一层没有改成范围条目与近况视图。附录 A 的三个操作已登记。
- D514 （11-14，M2b；和 D481、D507 一起看）会话历史的依赖清单（`conversation_acl`）没有把团队备忘列为依赖：`memory.search` 返回的备忘卡和带入过备忘的回答留在本人的会话历史里，备忘之后被停用、撤回或对本人不可读时，这些历史轮次不会随之隐藏。当前运行有复核（见 D507），续接的后续运行没有。个人条目是同样的情况。
- D473 ✅ 11-12 定：九条全部按推荐，见[P121](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p121)。 原记录：按你 11-12 的任务书写了[记忆系统评估与目标架构 v0.1](../docs/design/2026-11-12-xiaopai-memory-system-assessment-and-target-architecture.md)，与记忆层设计 v0.4 和 P84–P94 不同的 9 处列在其附录 A；你同日逐条确认。只读了代码和已有证据，没有运行测试或模型。记忆层设计稿开头和[设计索引](../docs/design/README.md)原写“未实施”，已改为“M1、M2a 已合入”，并注明 P121 修订的九处。
- D474 〔你〕P121 的实施未排期：[目标架构](../docs/design/2026-11-12-xiaopai-memory-system-assessment-and-target-architecture.md) §9 的 B0–B8 何时开工、归哪个工作包待你定。它与 D45 里未做的 M2b、M3 重叠（范围条目、事件沉淀、纠正分流），开工时须合并排期，不要两头各做一遍。其中：
  - B0 先行：现在没有任何一次带记忆的真实模型评测，记忆门禁评分器只有自身的单元测试记录，排序系数（半衰期 30 天、置顶加 0.25、被纠正乘 0.5）都是未校准的初始值。
    - 🟡 11-13 B0 已做无模型回放和真实模型下的基线 0、1、2，[证据](../docs/reports/evidence/pdos-next-memory-b0-20261113/README.md)。
      - 可用：[时间线候选 8 条](../docs/evaluations/xiaopai-memory-v0/README.md)（20 个探针、9 道真实模型问题，未经你确认）；无模型回放与评分工具 `tools/xiaopai_memory_timeline_baseline.py`；真实模型运行 `tests/agent/memory/test_eval_memory_timeline_real_pg.py`（默认跳过，设环境变量才跑）；情景索引工作流在真实本地 Temporal 上跑通（M1 缺口 ⑤ 的索引部分）。
      - 基线 1 按你 11-13 的决定只在评测注册：评测测试的进程里把 `memory.search` 的处理函数换成“搜本人原话加回答摘要”，去掉个人条目和情景目录；产品的工具注册表、工具名、提示词都没动。
      - 无模型回放：七项零容忍门禁 0 次违反；`memory.search` 召回当前实现 6/9，其中按结论里的说法问 0/3。
      - 真实模型（MiniMax-M3，每题每组 1 次）：回答里写出全部关键事实的题，基线 0 为 0/5，基线 1 为 4/5，基线 2 为 2/5；检索到全部事实的题 0/5、5/5、4/5；追问数 8、3、2；平均 token 约 17.9 万、10.5 万、15.1 万；按本人约定用英文起草只有基线 2 做到（1/1）；越权、删除残留、不进记忆仍读取三组都是 0。27 次计分运行共约 392 万 token。
      - 更正：11-13 早些时候记的“当前实现 4/5”把工具返回里的事实也算了进去，按最终回答是 2/5。
      - 11-13 P122 修正后重跑（27 次运行，证据第五节）：回答里写出全部关键事实的题，基线 0 为 0/5，基线 1 为 5/5，基线 2 为 4/5；检索到全部事实的题 0/5、5/5、4/5；回答被换掉 0 次，预算用完没有回答 1 次。基线 2 比基线 1 少的一题是 TL-08 q1（按结果里的词问，检索不到）。上一行是修正前的数字。
      - 这些数字只是第一次基线：题少、每格 1 次（同一题两次运行结果不同）、候选未确认，验收集的 3 条也已经跑过看过，之后都只能当调参集；基线 1 同时去掉了条目和目录，差别不能全归到索引内容上。
      - 11-13 D482 改完后：无模型回放当前实现 6/9 → 9/9；真实模型只复验了 TL-08 q1 当前实现 1 次，检索和回答都是 2/2（见 D482）。三组基线没有整体重跑，上面的数字仍是 D482 之前的。
    - 11-13 你要求并行完成余项，已开三个会话，各自独立工作区、本地提交、不推送，迁移用占位号（主会话占 `s0_0888`）：范围条目 M2b 与 P121 第 3、4、6 项（分支 `claude/memory-m2b-scope-notes-6ba1bd`，占位 `s0_0900` 起）；提议入口 D298、D476、D302 与 P121 第 8 项的三小项、第 9 项（`claude/memory-proposal-entry-15ed77`，`s0_0920` 起）；删除会话、本轮不记、D301、D475 第 1 条（`claude/memory-session-controls-bb2951`，`s0_0940` 起）。集成时按真实 head 重排迁移号，并合并各分支对本清单的改动。没有开的：M3（依赖 M2b、D246 和 golden-case 资格）、M4（依赖 OCR 与视觉服务的出站判定）、D300（需要真实嵌入服务）、任务笔记与范围简报（须先有消融结果）、Temporal 保留期（部署时配置）。
    - 11-14 第一批三个会话都已报告做完，都只在各自分支本地提交，未合并、未推送；本会话只核对了分支上有提交，没有审代码，数字是各会话自己报告的：删除会话、本轮不记、D301、D475 第 1 条在 `claude/memory-session-controls-bb2951`（已接到 `f7425553` 上，迁移占位 `s0_0940` 接 `s0_0888`；报告整链迁移往返通过、回归 401 通过 0 失败；留 D520、D521 待你定）；提议入口在 `claude/memory-proposal-entry-15ed77`（`0650948f`；报告 Prompt A/B 支持打开，提示词 1.1.0 已列入放行集合但没有激活，当前 1.0.0 下提议路径仍关着，激活需要具名评审人，见 D530；前端两处小改动没做类型检查，全量回归没跑）；M2b 在 `claude/memory-m2b-scope-notes-6ba1bd`（`362dd1f8`，基点 `fbcda6bc`，未变基；报告受影响回归 441 个里 440 通过、1 个时间窗用例批量里出错单独重跑通过；技能包登记 D500、D501 待你定）。
    - 11-14 你说“继续完成其他没有完成的，可以用 opus5 high 来完成”，第二批开了两个会话（Opus 5，high）：B0 评测补齐（上限组、每格 3 次、T03/T04/T05/T13/T24 的题、新验收时间线；分支前缀 `memory-b0-eval`，真实模型上限 2,500 万 token，D 编号从 D540 起）；情景向量联调 D300 与对象标题索引（D482 余项 ①；分支前缀 `memory-retrieval-gaps`，迁移占位 `s0_0960` 起，D 编号从 D550 起）。仍然没有开的：M3、P121 第 6 项里个人条目迁移到统一契约（都要等 M2b 落地）、M4（依赖 OCR 与视觉服务的出站判定）、任务笔记与范围简报（要等 B0 的评测底座和 M2b）、Temporal 保留期（部署时配置）、各分支的集成（要你说合并才做）。
    - 11-15 集成（你定“在新分支集成”）：分支 `pdos-next/memory-integration`（独立工作区 `.claude/worktrees/memory-integration`，本地提交、未推送，没有合入 `pdos-next/design-v1.1`），起点 `f7425553`。第一笔是本会话的 D477 两处改动，然后依次合并会话删除、向量与对象标题、M2b、提议入口四个分支；B0 评测分支还在跑，没有合并。
      - 冲突：本清单（各分支只改各自条目，逐项取最新一条）；`bootstrap.py` 一处（会话删除和范围条目各加一行模型调用前的复核，两行都留）；三个合同文件的 v1.1 文档哈希（取合并后文档的哈希）。
      - 迁移重排为一条链：会话删除 `s0_0940` → `s0_0889`，向量与对象标题 `s0_0960` → `s0_0890`，范围条目 `s0_0900` → `s0_0891`，提议防护 `s0_0920` → `s0_0892`；四个迁移不替换同一个数据库函数。清单里其他条目提到的占位号按这个对照读。
      - 验证：新建独立临时库（54222）整链迁移往返通过；合同校验通过；前端类型检查、改动文件的代码检查通过，前端 `.mjs` 测试 2001 个全过；后端受影响回归（记忆、范围条目、主图与最后一轮、会话历史依赖清单、企业检索里与记忆有关的文件、生命周期目录、目录结构）11-16 跑完：452 通过、44 跳过、1 失败。失败的是会话删除测试里“每条情景 2 行索引”的预期，向量分支加了第 3 行（对象标题），删除本身按会话清掉全部行，只改了测试里的预期数字，该文件 11 个重跑通过。第一次选的范围太大（整个 `tests/core` 等），跑了 13 小时没完被我停掉；Docker 11-15 重启过，测试库换了端口。前端 `.test.ts` 那一组没有跑成：我用的运行方式在主检出上同样 63 个里 51 个失败，是方式不对，不是合并引入的。
      - 现在不再被集成挡住的：D551（旧向量清理，要定观察期）、D512（个人条目迁到统一契约）、M3。D530 建议的“集成后先重跑一次离线控制再激活 1.1.0”还没做。
    - 缺口：上限组（理想记忆）没跑；每格多次运行没做；T03、T04、T05、T13、T24 还没有对应的题；情景向量的联调仍是 D300。
    - 环境：独立临时库 `pdos-next-test-20261002-44c36df2`（57105，状态文件 `.local/memory-eval-b0.json`）留给 B0 后续用，收尾时销毁。
  - P121 第 7 项：Temporal 命名空间的历史保留期须在部署时配成不超过 30 天并核对（同 D378 阶段 3 的前置检查，迁移决策记录 Q4）；目前仓库里没有试点部署。11-13 核对：仓库里没有任何地方配置保留期，本地开发服务都用 `start-dev` 默认值；实测本次测试起的本地服务默认是 24 小时；本机共用的开发服务 D378 已核对过（`pdos-agent-local`、`default` 1 天，综合预览的命名空间 7 天）。部署时须显式配置，不能依赖默认值。
  - P121 第 2、5 项（任务笔记、范围简报）须先有消融结果，增益为正才上线。
  - 11-12 你同意补入：目标架构 §6.9 增加条目核对（拿条目对照来源，只发“疑似不符”提示）、常驻升降建议（按使用统计给置顶、归档、改作用域的建议）、整理任务的节奏与预算。三者只产出提示和建议，不改条目，不改变 P121；归 B6，用例 T27、T28，同样先过消融。
  - 🟡 11-13 P121 第 8 项的前两小项已实现（分支 `claude/memory-session-controls-bb2951`，本地提交、未推送，迁移占位号 `s0_0940`，集成时按真实 head 重排，[证据](../docs/reports/evidence/pdos-next-memory-session-controls-20261113/README.md)）：
    - 删除会话：本人在会话列表和对话页的“更多”里删除自己的会话。删除只能经数据库函数 `memory_delete_session`，它自己校验“本人以真人身份、且是自己的会话”，AI 身份和他人被拒；四张记忆表仍是只追加，只有带删除记录的会话才允许删行。删除后 `memory.search`、情景目录、跨会话 `conversation.history`、会话列表与搜索都不再返回它，不能续接；调取过它的进行中运行在下一次模型调用前停下；索引和向量化写不回来。有进行中的运行时拒绝删除。确认和结果都写明哪些立即清除、哪些 30 天内清除、哪些保留。登记为辅助操作 `agent.session.delete`。
    - 本轮不记：发起或续接时带 `memory_turn_off`，这一轮不读个人记忆、不留情景、不产生提议，会话开关不变；输入区“记忆”里可勾选。
    - 余项 D520、D521；其余三小项（“这只是讨论”作废、抑制指纹、`as_of`）不在本分支。
- D520 〔你〕删除会话后，运行记录里的原话和回答正文保留多久：现在删除只清记忆层，运行记录（含原话、回答）、工作状态、会话标题、其他会话调取时带入的片段都还在，只是从列表和回忆里消失；凭运行编号仍能打开该次运行。P121 写的是“回执与审计按 I17 保留，保留期边界按 D193 与 D217”，D193 只说回执在租户存续期内不删，D217 还没写，所以没有自行决定。建议：没有回执、也没被别处引用的运行，删除会话后与检查点同期（30 天内）清掉原话和回答正文，只留不含正文的骨架；有回执或被引用的运行保留正文，年限写进 D217。删除确认里现在如实写着“保留多久由试点协议规定，目前还没有定”。
- D521 （11-13 实现会话级控制时登记）待同步与小缺口：① `agent.session.delete` 在辅助操作目录里登记为 T2、具名本人，档位待你确认；v1.1 §06 与附录 A、P20 的判据“不存在删除会话的命令”未同步。② 本人失去品类权限后删不了该品类下自己的会话（与读取规则一致）。③ `memory.search` 在“本轮不记”时由工具层把提示改成“本轮”，`recall.unavailable` 本身的文字没动，集成时可并进去。④ 讨论串里上一次 @小Pai 的会话被删后，下一次 @小Pai 会新开会话。⑤ ✅ 11-14 已补：分支变基到 `f7425553`，`s0_0940` 改接 `s0_0888`；全新独立库上整链迁移往返通过；完整受影响回归 401 通过、13 跳过、0 失败；删除会话时 `episode`、`answer` 两种索引行都清掉。仍未做：无库全量回归，浏览器的品类侧栏与 375px，真实 Temporal 联调，见证据“11-14 补验”。
- D477 🟡（11-13 真实模型基线测出，同日查明原因，三处都已改，见[P122](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p122)）依据以往运行记录作答时，最终回答经常出不来：27 次运行里 7 次的回答被换成“结果未通过……核对”，6 次以“运行预算已用完”结束，其中 3 次是关键事实已经找到。两个原因都和记忆内容能不能被引用无关（此前的猜测不成立），[证据第四节](../docs/reports/evidence/pdos-next-memory-b0-20261113/README.md)：
  - 回答被换掉：最终输出过不了结构校验，重试 2 次后整个输出（含模型写的摘要）被换成固定的一句话（`graph.py` 的 `verify`）。直接抓到的错误是追问里的 `options`、`depends_on` 不是数组，以及 `result` 不是对象。MiniMax-M3 用收尾函数交结果，服务商不强制参数结构。D378 阶段 3 记过同样的现象两次，当时没有登记。
  - 预算用完：一次运行最多 12 次模型调用，到上限时只留工具结果、不给模型写回答的机会（`graph.py` 的 `partial`）。以此结束的 6 次都正好 12 次模型调用，其中 5 次在不进记忆组。
  - 已修 ①（你 11-13 同意并确认保留三种写法）：`providers/agent_client.py` 解析最终输出时，把追问的 `options`、`depends_on` 按三种抓到过的写法读成数组（空值或空字符串、`{"item": […]}` 外套、数组的 JSON 文本）；数组项不动，其他写法仍打回；输出合同和提示词没改。模型实际写的就是后两种，不是空值。`test_minimax_wire.py` 新增 12 例，共 47 通过；服务商协议与主图无库测试 176 通过。真实模型复验 4 次运行：没有再出现这两个字段的结构错误，没有回答被换掉；仍出现 `result` 不是对象 1 次（重写后通过）和模型调用上限用完 1 次。样本只有 4 次。
  - 已改 ②③（你 11-13 定“两处都改”）：`graph.py` 主图里，最后一次模型调用前在上下文末尾告诉模型只作答（工具定义和前缀不变；工具额度用完时也给一轮作答，这一轮的工具调用不执行；最后一轮的追问列入未完成事项）；最终输出只是没过结构校验且重试用尽时，保留模型写的摘要并标“未经系统核对”，被引用核对拒绝的仍不出。隔离子任务不变。新增 `test_graph_final_turn.py` 12 例（此前记成 13，更正）；带库跑主图、插件路径、等待恢复、记忆等已有测试 245 通过、12 跳过；更大范围回归没跑。
  - 真实模型复验 5 次：一次在第 12 次调用给出了回答，一次正文被保留并带标注；一次模型在最后一轮没有听、仍调工具，照旧预算用完。“告诉模型”不是硬拦，不总管用。
  - 已补 ④（你 11-13 定“也读成空数组”）：复验里抓到的第四种写法，`depends_on` 写成空对象 `{}`，现在读成空数组；非空对象和文本 `"{}"` 仍打回。`test_minimax_wire.py` 再加 3 例，共 50 通过。这一种写法没有再跑真实模型复验。
  - 11-13 修正后重跑三组基线（你定“重跑三组基线”，27 次运行，约 365 万 token，[证据第五节](../docs/reports/evidence/pdos-next-memory-b0-20261113/README.md)）：回答被换掉 7 → 0；预算用完没有回答 6 → 1；回答里写出全部关键事实的题，不进记忆 0/5 → 0/5、只搜历史 4/5 → 5/5、当前实现 2/5 → 4/5。每格仍只有 1 次，除前两项外各格的变化分不清是修正还是波动。用满 12 次调用的 4 次运行里 3 次在最后一轮作答，1 次模型没听、仍调工具。正文保留但未经核对 1 次。
  - 11-14 余项 ②③ 已改（你 11-14 答“都做”，记入 P122 补充；本地提交在集成分支 `pdos-next/memory-integration`，未推送）：两种新写法读成数组，外套里是单个对象的仍打回；主图最后一轮的工具调用一律不执行，提示语里写明。`test_minimax_wire.py` 54 通过、`test_graph_final_turn.py` 12 通过；主图、插件路径、等待恢复、协议解析等 10 个测试文件带库重跑 142 通过（其中两个原先假设“最后一轮的调用会执行”的用例已按新规则改写）。工作区里同时有另一个会话未提交的 `graph.py` 改动（D479），回归是在两者叠加的代码上跑的。没有用真实模型复验。
  - 余项：① `result_json` 写坏导致 `result` 不是对象仍会出现（重跑里 2 次运行各被打回 1 次，重写后通过）；② 硬拦只保证不执行最后一轮的工具调用，不保证模型给出回答；要强制作答，得在最后一轮限定模型只能调用收尾函数，没做。
  - 对记忆评测的影响：修正前同一道题三次运行，两次有完整回答、一次被换掉；修正后重跑里这层噪声基本去掉，剩下只搜历史 5/5 对当前实现 4/5，差在 TL-08 q1（按结果里的词问，当前实现检索不到），对应 P121 第 1 项。
- D476 ✅ 11-14 词表已收窄并测了误提议和漏提议（本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-proposal-20261113/README.md)第二节）。
  - 可用：固定说法只留面向小Pai 今后行为的明确说法；“我一般”“我习惯”“别忘了”“我说的”已去掉；“以后给我表格形式的周报”现在放行；疑问句、否定、主语不是小Pai 的不算。个人叫法另认本人的命名句。
  - 无模型回放 522 句（合成，未经你确认）。独立写的留出集 210 句上，规则冻结后只测一次：对话提议误放行 5.5%、漏 20.0%（原词表 12.7%、80.0%）；个人叫法漏 33.3%；纠正漏 40.0%；“只是讨论”漏 30.0%；后三项误放行 0–5%。
  - 这是只看固定说法这一关的口径：误放行是误提议的上限，漏就是这条路漏提的下限。我自己写的调参集上几乎全对，不能当真。
  - 余项：漏提仍然不低，要不要接受见 D532。
  - 原记录：（11-13 回放测出）对话提议的固定触发词表漏掉了明确的长期交代：“以后给我表格形式的周报”在测试进程里打开提议闸门后仍被拒收，原因 `trigger_not_explicit_remember`（词表有“以后都”“以后一律”“以后请”，没有“以后给”），而同一张表里有“我一般”“我习惯”。P121 第 9 项收窄词表时要一并补上这类说法，并用回放会话同时测误提议和漏提议。随 D298（新提示词版本）一起做；[证据](../docs/reports/evidence/pdos-next-memory-b0-20261113/README.md)。
- D530 〔你〕（11-14）激活提示词 1.1.0 需要具名评审人，本会话没有激活。建议：集成后先重跑一次离线控制（内核文件变了旧报告会失效，不花模型费用），再激活；命令见[提示词工作流](../docs/runbooks/pdos-next-prompt-code.md)。两点请知悉：
  - 11-15 集成后已按建议重跑离线控制（集成分支，代码含四个记忆分支和 D477 的最后一轮硬拦）：通过，新增准入失败 0，没有调用服务商和数据库，[报告](../docs/reports/evidence/pdos-next-memory-proposal-20261113/prompt-control-after-integration/result.md)。激活仍需你指定具名评审人；建议里的“1.0.0 加新说明”那一组真实模型补跑没做。
  - `memory.search` 的新说明和 `as_of` 参数是工具定义的变化，合入后在 1.0.0 下就生效；A/B 只测了“1.0.0 加旧说明”对“1.1.0 加新说明”，没有测“1.0.0 加新说明”。建议合入和激活一起做；要先合入不激活的话，我可以补跑这一组（约 100 万 token）。
  - 激活后“回滚到 1.0.0”即关闭提议路径；已存下的候选仍可由本人确认或忽略。
- D531 🟡（11-14 A/B 里发现并已补）模型写回答在服务器核对之前，提议被拒收时回答仍会说“已提出卡片”，界面上却没有卡片。已改：运行的候选视图返回 `declined`（数量和一句说明，不含正文），对话页在卡片位置显示“没有生成卡片，也没有记住任何内容”；带库测试覆盖接口。余项：前端这处改动和 `voided` 状态没有做类型检查和页面走查（本机没有装前端依赖）。
- D532 〔你〕（11-14 回放测出）固定说法盖不住自然说法：留出集上明确交代漏掉 20%，个人叫法 33%，纠正 40%，“只是讨论” 30%（例：“往后你回我的时候少讲客套话”“你把电机功率弄混了，是 12W”“这个还没定，只是聊一下”）。两个方向：
  - 接受（建议）：漏掉的代价小，本人可以再说一遍“记住……”或在“我的记忆”里直接添加；误提议的代价是信任。之后按真实使用里被拒收的说法补词表，每次补都换一份新的留出集重测。
  - 改成由模型判断意图、服务器只核对“是本人原话、不是页面资料”：漏提会少，但这改变了 P84 第 7 项和 P121 第 9 项的固定词表做法，需要你另行决定。
  - 另请定：“不用记了”“别记了”这类撤回说法现在不算“只是讨论”，要不要也触发作废。
- D533 （11-14）遗忘抑制指纹用的是每条随机盐加 SHA-256，不是目标架构 §5.7 写的带密钥摘要：仓库里没有可用的租户密钥设施。不存正文，也查不了现成的对照表，但能读到这一行的人可以拿猜的句子去试。它只挡文字完全相同的再次提议，换一种说法挡不住（旧话由“来源运行不再提炼”那条规则挡）。建议等有租户密钥服务时换成带密钥摘要。
- D534 （11-14）提议入口这次没做的：
  - 迁移 `s0_0920` 是占位号，集成时按真实 head 重排；另两个并行分支也各有占位迁移。会话删除（D520 一带）清候选时，`memory_proposal_voids` 的标记行只追加、不随会话清除（不含正文）。
  - 情景记录里标注“这只是讨论”没有做（目标架构 §5.6.7 场景 5 的最后一小项）。
  - 转述约束（`paraphrased_constraints`）的模型输出仍然关闭，没有纳入 1.1.0。
  - 真实模型评测每格只有 1 次；探针和回放语句都未经你确认；只测了 MiniMax-M3。
  - 独立临时库 `pdos-next-test-20261002-63494176`（64236）留着供集成前复验，收尾时销毁。
- D475 评估时发现的三处小缺口（都有代码依据，均未修）：
  - ✅ 11-13 已修（迁移占位号 `s0_0940`，[证据](../docs/reports/evidence/pdos-next-memory-session-controls-20261113/README.md)）：情景的 `usage.notes` 记下用到的个人条目 ID、版本和区，不含正文；投影版本改为 `memory-episode/v2`，以前的情景不回填。 原记录：情景记录的使用清单只投影了情景和会话，不含用到的个人条目（`memory_project_episode` 触发器在 M2a 没有更新）。
  - 纠正只记去向（两种：改事实、改技能），没有代码消费；设计 §14.9 的四路分流未实现（归 M3 / B6）。
  - ✅ 11-13 已随 D481 改代码。 原记录：个人条目被修改或替换时，进行中的运行继续用旧文字（`assemble.recheck` 只拦删除和不可读），注释写的是“替换也停”。影响小，下一次运行即生效；改代码还是改注释待定。
- D481 🟡（P1；11-13 外部审阅；你 11-13 定“先修 D483 和 D481 还有 D482”，按 P1 口径改代码；前两条已改，本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-d481-d483-20261113/README.md））记忆被纠正或删除后，进行中和已结束运行里的副本处理不完整：
  - 已改 ①：`assemble.recheck` 现在对照最新修订和有效期。带入的条目被修改、替换、过期、删除或范围不可读，运行都在下一次模型调用前停下，提示里写明是哪一种。模型已经看过旧文字，所以是停下，不是悄悄换成新文字。
  - 已改 ②：运行行上不再存条目正文。`AgentRun.versions.memory_notes_context` 和 `memory_aliases` 只存条目 ID、版本和所在的区，正文每次从版本表读；条目删除后运行行上没有可清的副本。已结束的运行不可改（`kernel_run_guard`），所以没有走“删除时回头清运行行”的路。
  - 验证：`test_memory_notes_pg.py` 新增 2 例（运行行里查不到正文，删除后也读不回；修改、替换、过期各自停下），记忆目录带库测试 86 通过、12 跳过。
  - 余项：③ 没做，见下面第三条（归 M3 / B6）。④ 这次改动之前建的运行，行上仍有当时冻结的正文，读取时已不再使用，但行本身清不掉；pdos-next 目前没有真实数据。⑤ 另见 D484。
  - 原记录：
  - 运行首次组装把个人条目正文冻结在 `AgentRun.versions.memory_notes_context`，并带进主图消息。`assemble.recheck` 只拦删除、缺行、范围不可读，不对照最新修订，也不管已过期；审阅用真实守卫验证：修改、替换、过期都放行，删除被拦。D475 当时判“影响小”，审阅按 P1 计，待你定按哪个口径。
  - `notes.purge` 删条目版本和来源提议，不清 Run 上的冻结正文；删除回执写的是“随检查点最迟 30 天清除”，但这份副本在业务库的运行行上，不是检查点，检查点清理（D58）和 Temporal 历史保留期（D474 的 P121 第 7 项，试点配置待核验）都清不到它。
  - 反馈纠正只记去向、没有消费方，即 D475 第 2 条。
- D482 🟡 11-13 已改（你 11-13 定“先修 D483 和 D481 还有 D482”；本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-d481-d483-20261113/README.md））：
  - 可用：迁移 `s0_0888` 给 `memory_index` 增加第二种行；每条情景除本人原话外，另索引回答摘要和未完成事项。`memory.search` 两种行一起打分，结果卡片标出命中的是原话还是回答，并带回答前 200 字的摘录，标明不能作为依据引用；出站类别不覆盖或来源已撤权的照旧不返回。会话列表搜索仍只匹配本人原话。以前索引过的情景会补索引。工具定义和提示词没改。
  - 验证：带库测试新增 6 例；无模型回放 `memory.search` 召回 6/9 → 9/9（按结论里的词问 0/3 → 3/3），七项门禁仍是 0；真实模型只复验了 TL-08 q1 当前实现 1 次：由“预算用完、检索 0/2”变为完成、检索和回答都是 2/2，约 5 万 token。三组基线没有整体重跑。
  - 余项：① ✅ 11-14 已做（本地提交 `69f81d00`，[证据](../docs/reports/evidence/pdos-next-memory-retrieval-20261114/README.md)）：新增第三种索引行 `object`，收运行关注的具体对象（读过的资料、钉住的来源）在索引时的标题，以本人身份、在行级权限下读，读不到的不收；范围对象的标题仍不收。卡片 `matched_in` 标 `object_title`，不返回标题原文；会话列表搜索仍只匹配原话；对象撤回后逐条复核照旧挡住；旧情景经 `s0_0960` 补索引。带库测试新增 3 例；`source` 种类无单独测试。② 情景向量仍只发送本人原话，回答摘要是否也发给嵌入服务待你定。③ 目录仍只放最近 3 条，没改。④ 打分没有按词的稀有度加权，回答文字长，容易带出低分的无关情景；现在靠排序，没有设分数下限。
  - 原记录：（P2；11-13 外部审阅，证据即 D474 的 B0 结果）旧结论能存能读，但用户按结论里的词找不到：情景关键词只索引目标原话（`memory/index.py`），目录只放最近 3 条（`recall.CATALOG_SIZE`）。TL-08 目标运行排第 6 条，真实模型搜 4 次、读 6 次历史仍没找到；无模型回放同类问法 0/3，加入回答摘要后 3/3。P121 已批准索引摘要、对象标题和未完成事项，随 D474 的实施做，不另排。
- D484 〔你〕（11-13 修 D481 时从代码读出，未逐行验证）个人条目删除后，另有两类副本不在这次修复范围内：模型在运行里用 `memory.search` 查到的条目卡片（含正文）和叫法展开，留在工具调用记录 `agent_tool_calls.result` 里；模型的回答也可能转述了条目内容。前者是运行台账，后者是对话记录，是否随条目删除而清、怎么清，需要你定；删除回执目前只说了检查点里的副本。
- D550 〔延后：有真实嵌入连接且你授权出站时〕（11-14 D300 第 3 步）情景向量没有做真实嵌入服务联调：本机没有已配置的真实嵌入运行环境（`.env.example` 无嵌入项，运行元数据无嵌入连接，11-01 真实评测也未启用嵌入出站），只做到合成服务商。恢复条件：租户运行配置里有 OpenAI 兼容的嵌入连接（凭据经本地 KMS 绑定）和计价卡，并由你授权把合成的本人原话和查询词发给该服务商。满足后按 `test_memory_vectors_temporal_pg.py` 的流程跑一次，记录回执、用量和“仅关键词”对“融合”的召回对比。[证据](../docs/reports/evidence/pdos-next-memory-retrieval-20261114/README.md)
- D551 〔你；11-15 已集成，不再被挡〕（11-14 D300 第 4 步）旧配置停用后，旧向量不再派发、不再查询，但行还在：`memory_episode_vectors` 有只追加触发器，而会话删除分支的 `s0_0940` 正在把它换成删除守卫。建议集成时在那个守卫里加一条：配置版本停用或被取代超过观察期（建议 30 天）且已有更新的完整空间时，允许清理旧版本的向量；回执不删。[证据](../docs/reports/evidence/pdos-next-memory-retrieval-20261114/README.md)
- D552 ✅ 11-14 你定“建好即切换”，不加评测关口；代码维持现状，无改动。〔11-15 待你确认〕这条“你定”是向量分支会话记下的，我在能查到的会话记录里没找到你的原话，所以设计 §14.9 仍写着“检索评测通过后才切换”，没有改，也没有写决定记录；你确认后再同步设计稿并补 P 记录。原记录：（11-14 D300 第 4 步）设计 §14.9 写的是“重嵌完成且检索评测通过后，查询切到新配置”。现在的实现是建好即切换，没有评测关口；旧配置在你停用前仍可回退。建议：真实嵌入可用（D550）之前保持建好即切换；可用后加一道关口，用记忆评测集（D474）对新旧空间各跑一遍，召回不低于旧空间才切换。[证据](../docs/reports/evidence/pdos-next-memory-retrieval-20261114/README.md)
- D483 ✅ 11-13 已修（你 11-13 定“先修 D483 和 D481 还有 D482”；本地提交、未推送，[证据](../docs/reports/evidence/pdos-next-memory-d481-d483-20261113/README.md））：`memory/history.py` 里，出站类别不覆盖的轮次只返回运行编号、状态和“未发送”的说明，不再返回提问；其余轮次的提问只返回本人原话，去掉前端拼接的页面资料。`test_memory_recall_pg.py` 新增 1 例：经注册的 `conversation.history` 处理函数读带页面资料的历史轮次，返回内容里查不到页面资料标记，也查不到私有轮次的原话。同一会话内的历史读取没有改。 原记录：（建议 P1；11-13 记忆审阅）跨会话历史在出站分类不覆盖时隐藏了回答，但仍返回原始 `goal`，其中可包含前端拼接的页面资料。用合成标记直接调用 `history.other_session` 验证，返回 `outcome_state=hidden`、`historical_outcome=null`，页面资料标记仍在 `goal`。未调用外部模型。修复时将不覆盖的轮次限于必要元数据，并用带页面资料的历史轮次补一条注册工具到模型入参的负例；P121 的情景摘要索引复用同一出站与撤权校验。
- D303 ✅ 11-10 已修（本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md)）：`core.models` 是模型登记的入口；先导入 `kernel.models` 时，登记在内核表还没定义时就加载后面要用它们的模块（`session_presentation_models` 要 `KernelRow`，`preproject.models` 要 `AgentRun` 和 `agent_runs` 表）。改法：`KernelRow` 挪到 `kernel_row.py`；`preproject.models` 改为导入模块本身，并按目标表名判断 `action_receipts` 外键，不再解析外键；`project_work_task_context` 按它自己的注释先导入登记。内核表仍在登记原来的位置注册：若让内核表先定义，`core.models` 那段“给已登记的表补品类外键”的循环会多给内核表补 7 条库里没有的外键，所以没有改 `Base` 的位置。验证：新用例在全新解释器里分别先导入原先失败的 6 个内核模块，全量 DDL 指纹与先导入 `pdos_next.core.models` 一致，也与基点相同；基点上这 6 个全失败；`pdos_next/agent/kernel` 下 114 个模块单独导入全部成功；无库全量 10816 通过、0 失败。余项 D461。原记录：单独 `import pdos_next.agent.kernel.models` 会循环导入（`session_presentation_models` 取不到 `KernelRow`），只有先导入 `pdos_next.api` 才正常。
- D461 （11-10 修 D303 时登记）同类循环还在其他登记成员上：单独先导入 `pdos_next.domain.categories.preproject.models`、`pdos_next.domain.projects.work.models` 仍报循环导入（基点相同）。D303 只修内核；`pdos_next/agent/kernel` 下的模块现在都能单独导入。
- D46 用 AI 候选新建品类一次也没跑通，原因是研究端口没接（随 D20-A3、D62）。
- D54 冻结前缀里加一句护栏（F10）。prompt 1.0.0 还没有这句，走 10-31 建好的 Prompt A/B 流程。
- D58 ✅ 11-07（已本地提交，未推送）LangGraph 检查点保留 30 天、按天清理（P78 第 3 项、D193）：
  - 覆盖：`originals/lifecycle/catalog.py` 登记检查点库的表和列（`CHECKPOINT_COVERED_COLUMNS`）与 30 天保留期；检查点库里出现目录外的表或列时整轮拒绝清理，同业务库的做法。
  - 清理：`workflows/checkpoint_retention.py` 按服务器构造的线程 ID 把检查点归到运行或嵌入批次。归属的最新检查点超过 30 天，且运行已结束（completed/partial/failed/cancelled）或批次已结束（ready/unavailable），才删掉它的全部检查点行。排队、运行中、等待中（含待对账）的运行和排队、运行中、可重试的批次一律保留；业务库查不到归属的、线程 ID 认不出的也保留。会话布局下同一线程里其他运行的命名空间不受影响。
  - 定时：新增每租户长驻工作流 `TenantMaintenance`（`workflows/maintenance.py`），固定 ID、持久计时器、每天一轮，由 worker 的发现循环启动，做法同自动化监督；一轮失败只记日志，下一轮照常。
  - 迁移 `s0_0857`（分支上为 `s0_0855`，11-08 集成时按真实 head 改号）：调度角色只能经 `checkpoint_retention_owners` 读运行和批次的开闭标志，直接读两张表仍被拒；批次表原来只在人员范围内可见，给属主角色加了按当前租户限定的只读策略（只有这个函数用到）。
  - 测试：`tests/workflows/test_checkpoint_retention.py` 26 例（线程 ID 解析、目录校验、每日循环与失败后继续、启动去重）；`test_checkpoint_retention_pg.py` 3 例，用真实 LangGraph 检查点和各状态的真实运行验证只删已结束且超期的归属，并验证目录外的列会拒绝清理、跨租户看不到。受影响的既有测试（workflows、originals、生命周期目录、worker 进程等）544 通过、6 跳过。迁移 0855 单步往返通过。
- D243 ✅ 11-04（已本地提交，未推送）每个运行同一时刻只有一个尝试在做：按运行的会话级咨询锁（`agent/kernel/run_lease.py`，独立自动提交连接，进程退出即释放），后来的尝试边发心跳边等；SDK 的异步取消在执行期间被屏蔽，被放弃的尝试在下一次模型或工具调用前停下（LangGraph 从中断的那一步续跑，前面的步骤不重做），交回取消、不再把运行标为失败；拿到锁后先复核，前一尝试已结束或已停在问题处的，直接返回原结果；对账活动拿不到锁时稍后重试；执行超时 10→60 分钟（存活由 45 秒心跳判断）。测试：`test_run_attempts.py`（含 SDK 取消落在轮中间的 W1 情形）、`test_run_lease_pg.py`；受影响的 35 个 Temporal/PG 测试文件除原有环境缺口外全过。11-06 真实回归复测通过：超时并发造成的失败 33 → 0，最长 31 分钟的轮次也没被判超时；唯一一次尝试被放弃由合盖休眠造成，旧尝试按设计交回取消（[11-05 回归结果](../docs/reports/evidence/pdos-next-real-eval-20261105/result.md)）。 原记录：超时重试与未停下的尝试并发（W1 失败的头号原因）：`XiaopaiWork` 推进 Activity 的执行超时是 10 分钟、最多 3 次（`workflows/xiaopai.py:44-46`）。Activity 是线程池里的同步函数，超时后 Temporal 派出第二次尝试，第一次的线程要到下次心跳才收到取消，期间两次尝试并发推进同一个 Run，第二次撞上“原调用须按回执对账”和绑定保护后 `INTERNAL_ERROR`。W1 共 33 个运行因此失败（31 个执行超时、2 个心跳超时），拆分 API/Worker 后没有减少；另有 6 次模型调用的预留一直没结（约 4.19 美元）。一轮几次长输出就会超过 10 分钟（单次输出最多 11,167 token）。要定的是：超时后怎样保证旧尝试先停、再续跑，而不是并发或直接失败。
- D244 ✅ 11-04（已本地提交，未推送）`agent_client.parse_turn`：响应完整但 `result_json` 写坏或以纯文本收尾时，按正常回合返回、用量照实记账，`result` 记为空值，让核对必然失败并进入图里已有的格式修正回合（有次数上限）；空对象 `{}` 仍是合法结果。没有改工具定义。测试在 `test_minimax_wire.py`。11-06 真实回归复测：这一类未知 0 次（W1 38 次）；另发现完整响应被记成未知的新原因，见 D254。 原记录：服务商响应完整，却被记成“结果未知”：最终输出函数里的 `result_json` 是一段再转义的 JSON 字符串，模型约 2% 的调用会写坏（缺逗号、多余尾部、键重复），另有少数以纯文本收尾，`agent_client.parse_turn` 一律按 `PROVIDER_INVALID_RESPONSE unknown=True` 处理，整轮等 300 秒对账后失败，还按上限占账。W1 中 1677 次调用里 38 次，15 个运行因此失败。可选改法：解析失败按已知失败处理并给一次格式修正回合；或把 `result_json` 改为对象参数。
- D246 〔待定〕工具失败在账本和返回给模型的结果里一律是 `SOURCE_UNAVAILABLE`，真实原因（范围不符、本轮查找预算用完、缺基线型号、参数越界）被藏起来，模型分不清该换工具、该停还是该补参数。W1 中 11-02 以后范围不符 98 次、预算用完 93 次。须与 v1.1 §08.7 错误码收敛相容：公开错误码不变，考虑在给模型的工具结果里附一个可行动的原因类别。
- D247 ✅ 11-04（已本地提交，未推送）P76 第 4 项三处收缩一起做，同时落实 P44：
  - (a) 工具可声明必需的运行范围（`ToolSpec.scope_requires`），范围不满足的既不下发、也不能调用；5 个项目级读取在品类范围不再下发；
  - (b) 写工具一律须先加载列出它的技能，T2 准备也一样（取代 P37 第 2 项）；
  - (c) `preload_when` 改为服务器能判定的条件（提案起草视图 / 评审视图、是否有客户原件，带声明顺序），预载由技能目录推导；不绑提案的运行不预载；
  - P44：`proposal.g0.submit` 改 T1，小Pai 预填、只有负责人本人能确认（领域原有 `owner_only` 检查）；`proposal.share` 为 T1 且标“仅准备”（`prepare_only`，不绑执行操作），负责人在页面办理；这两项和 `proposal.g0.decide` 补进 `proposal_drafting`、`gap_check`；附录 A、操作合同、调用须知和评测细则 G-S3 同步；
  - 18 个技能包各升一个补丁版本（`preload_when` 变了，技能摘要随之变，已有资格须重审）。
  效果：品类运行零技能下发 66 → 29 个工具（约 30k 字符），提案起草页 38 个，评审页 35 个；零技能面和起草面都能放进 32k 窗口。代价：6 个治理类 T2 准备工具（`project.create`、`category.member.grant`、`provider.agreement.register`、`ai.skill.qualify`、`mcp.connector.allow`、`knowledge.rule.publish`）没有技能列出，小Pai 不再看到，由人在管理页办理。约 20 处测试夹具改为按运行范围计算披露摘要。受影响范围回归：无库测试与 HEAD 相比无新增失败（修好 2 个），`tools/` 测试全过，45 个 PG 测试文件的 39 个失败都在 HEAD 或已知清单中（[证据](../docs/reports/evidence/pdos-next-real-eval-20261101/regression-p76-item4.txt)）。11-06 真实回归复测：F=48000 下回答不完整 61 轮里 43 轮 → 55 轮里 6 轮，首次调用输入约 41–43k → 13.6–16.4k，项目级读取在品类范围被拒 98 次 → 0，服务商实际输入最大 45,205 仍不超 F（[11-05 回归结果](../docs/reports/evidence/pdos-next-real-eval-20261105/result.md) §3、§6）。 原记录：品类问答一次下发 66 个工具，工具定义约 30–37k token，其中 31 个是写入或审批类，另有 `build.read`、`test.run.read` 等项目级读取在品类范围内必然被拒，模型却常去调用（失败率 77–94%）。固定部分约 40k，超过 F=48000 的一半，导致 F=48000 下 61 轮里 43 轮回答不完整，基本不可用。按技能和范围渐进下发工具，与 D29 的 `preload_when` 一起做。
- D248 ✅ 11-08（已本地提交，未推送）主循环准入下限按你 11-07 的决定定为 1.22，写成带出处的配置。token 估算系统性偏低。11-07 用两批真实回归的全部逐运行文件（主工作区 `live/runs/`，只读）复核了 2770 次有估算和实际计数的模型调用，数字见 [D248 复核](../docs/reports/evidence/pdos-next-real-eval-20261105/d248-estimate-calibration.json)：
  - 主循环 1245 次：实际 ÷ 估算 p50 1.099、p95 1.169、最大 1.211（11-05 批最大 1.211，比 11-03 报告的 1.173 高）。隔离子任务（`assistant_extract`/`assistant_compare`）1525 次：p50 0.939、最大 0.967，是高估。只有 MiniMax-M3 一个模型。
  - 1.15 并没有完全兜住：主循环有 88 次准入值低于实际（最差低 4.8%）。这些调用离 F 都还有距离，实际输入一次也没超过 F。
  - 现行代码首轮直接用 1.15，相当于“校准比 1.0 + 15% 余量”；上下文设计 §6.1 写的是“按校准比估算并留 15% 余量”。
  - 只要做到实测零低估，主循环的准入就会比现在严，原本放得下的调用里有一部分会先触发缩减：
    - 主循环下限 1.18（约 p95）：低估 88 → 20，多缩减 59 次（4.7%）；
    - 1.22（实测最大值向上取整）：低估 0，多缩减 110 次（8.8%）；
    - 照 §6.1 字面（校准比 1.10 × 1.15 ≈ 1.265），或改估算（工具段 ×1.12、其余 ×1.06）后再留 15%：低估 0，多缩减约 155 次（12.5%）。
  - 隔离子任务一律保持 1.15，不降。
  - 实施：`agent/kernel/context_calibration.json` 按“协议 × 模型 × 主循环/子任务”记下限及其决定、证据和样本；openai-compatible 的 MiniMax-M3 主循环 1.22、子任务 1.15，没有实测记录的路线一律 1.15。加载时拒绝低于 1.15 或低于自身实测最大值的下限，余量只能比原来大。`context_budget.measure` 以 max(下限, 上一次实际 ÷ 估算) 为系数，`fit_messages`、宿主准入和网关一路传下限。网关在每次请求准入时把下限和校准输入一起冻结进运行（`context_admissions`），重放沿用当时的值；本次之前已准入的请求按 1.15 重放，调用键不变。评测基线工具的探针路由不带模型身份，仍按 1.15。
  - 测试：`tests/agent/kernel/test_context_calibration.py` 15 例（配置与证据文件逐项一致、按协议/模型/隔离选下限、会缩小余量或缺出处的配置被拒、缩减循环每一步用同一下限、网关冻结与旧准入按 1.15 重放），连同既有准入测试共 36 例通过；tools 相关 3 个文件 24 例通过。受影响的 49 个服务端测试文件 468 通过、18 跳过、5 失败。这 5 个在不含本次改动的已提交 HEAD 上以相同错误失败，与下限无关：`test_context_x3_full_disclosure.py` 2 例是测试桩 `ScriptedProvider.turn()` 不接收 `prompt_identity`；`test_development_budget_pg.py` 1 例报固定上下文超过窗口；`test_eval_v0_history_state_pg.py` 的 CTX-04（F48000/F64000）2 例报模型调用未形成可用结果。
  - 原记录：token 估算系统性偏低约 10%：418 次有估算和实际计数的调用，实际 ÷ 估算 p50 约 1.10、最大 1.173。准入靠约 1.15 的校准系数兜住，余量来自系数而不是估算本身。改估算或把系数写成有依据的配置。
- D252 ✅ 11-04（已本地提交，未推送）P67 实施，缺省输出预算按你 11-04 的决定定为 16k（确认稿 P67 已加修订）：所有模型路由在 `bootstrap.route()` 统一取“连接配置的输出上限”与 16,384 中的较小值，请求的 max_tokens、上下文预留 R（预算 + 4k）和费用预留都随之变化；路由摘要在一次运行内保持一致。W1 那套 524288 的配置下，上下文预留 R 从 528,288 降到 20,384 token；费用预留中的输出部分从 524,288 降到 16,384 token，按 W1 价卡约从 0.66 美元降到 0.02 美元，未知调用的过度占账（D57）随之回落；11-06 真实回归已确认：单次输出封顶 16,384（W1 有 5 次失控到约 52 万），未知调用每次约 0.043 美元。窗口须为公布或实测值（P67 第 3 项）仍是配置规则，未加校验。 原记录：P67 实施：R 按本次调用的输出预算 + 4k，连接配置的输出上限只作钳制，窗口须为公布或实测值；做完复核 D57 的未知调用占账。〔待定〕P67 建议主循环缺省 8k，但 W1 实测单次输出最多 11,167 token（推理 7,882），8k 会截断，缺省值要重定。
- D254 ✅ 11-07 已修并本地提交（未推送）：`providers/agent_client.py` 的流式累积改为 id 以第一块为准，相同的重复忽略，中途换成不同 id 仍按断流记未知。`test_minimax_wire.py` 加两个用例：照 11-06 抓包每块重复完整 id（15 块 × 30 字符），修复前整条记成未知、修复后得到原 id 且用量照记；同一调用中途换 id 仍记未知。与 D255 合跑（独立 `pdos_test`）：受影响的 107 个测试文件 1630 通过、27 跳过；22 个失败在不含这两项改动的代码上同样失败，不由本次引起。 原记录：工具调用 id 被重复拼接，完整响应被记成未知（11-06 真实回归发现，[结果](../docs/reports/evidence/pdos-next-real-eval-20261105/result.md) §4.1）：
  - 现象：MiniMax 流式返回时，有时在同一工具调用的每一块里都重复给出 id。`providers/agent_client.py:338` 把它们拼接起来，超过 `ToolCall.id` 的 200 字符上限（`agent/kernel/types.py:45`）后，整条响应按 `PROVIDER_INVALID_RESPONSE unknown=True` 处理。
  - 影响：1177 次返回里 3 次超限，CTX-04 第 3 轮因此对账后失败；另有 2 次带着重复 id 照常往下走。
  - 改法：id 以第一块为准，相同的重复忽略，不同才报错；补一个重复 id 的线协议用例。
- D255 ✅ 11-07 已修并本地提交（未推送）：
  - `evidence.extract` 改为下发处理函数自己的 `ExtractInput` 定义（`row_schema` 必填，含 kind、version，说明写明照抄 `skill.load` 返回的值）；`skill.load` 新增只有 `name` 的 `SkillLoadInput`。
  - 技能声明的行结构只在元数据里，加载结果原来不含，模型无从知道要写 `rfq_requirement`/`"1"`。`skill.load` 结果现在附带该技能的 `row_schemas`（没声明的技能不加这一项）。
  - `default_registry` 不再给读取和计算工具填空定义，缺参数模型的直接拒绝构建。新增 `test_tool_parameter_definitions.py`：加载全部技能后，六种隔离范围下发的工具都有参数定义。修复前 4 个新用例失败；合跑结果见 D254。
  - 仍有缺口：`review_pain_clustering` 和 `test_verification` 允许调用 `evidence.extract`，却没有声明 `row_schemas`（服务器已登记 `user_voice` v1，测试读数没有登记行结构），它们的抽取仍会被 `row_schema_not_declared` 拒绝。改技能包会改版本并触发资格重审，等你决定。
  - 原记录：两个工具下发时没有参数定义（11-06 真实回归发现，§4.2）：
    - `evidence.extract` 下发的参数是空对象，处理函数却要求 `row_schema`（含 `kind`、`version`），30 次调用全部 `VALIDATION_FAILED`。
    - `skill.load` 同样没有定义，7 次被拒（只接受名称）。
    - 改法：工具定义从处理函数的参数模型生成，并加一条检查：处理函数需要参数、定义却为空的不得下发。与 W8 的“116 条何时调用说明待补写”相关。
- D256 ✅ 11-08 余项已修并本地提交（未推送）：
  - `tools/xiaopai_real_eval_runner.py` 的续接等待每次轮询都按当前状态重新判断（`stop_kind`）。超过 30 分钟观测上限后又停在问题处的，按回放规则取消后续接，记为 `awaited_unobserved_completion` → `cancelled_open_question`，不再等 20 分钟后把整格记成错误（CTX-01 停在 25/31 轮的原因）。待对账的继续等自动对账。
  - 问题和待对账在 API 上都是 `waiting_input`，现在只按错误码区分：`EXTERNAL_OUTCOME_UNKNOWN` 是待对账，与服务端 `run_reconciliation.required` 同一判据；其余是问题。原来按最近 3 个事件里有没有 `reconciliation_required` 来猜。
  - 测试：`tools/test_xiaopai_real_eval_runner.py` 9 例，含 CTX-01 情形。`tools/` 全量 80 通过；4 个失败在 `test_local_host_profiles`，是原有的。
  - 余项：CTX-01 少跑的 6 轮等下次真实回归补跑。
  - 环境：长批次须接电源并用 `caffeinate -s`（`-i` 挡不住合盖休眠，11-06 一次 12 分钟的休眠使 2 个运行失败）。
  - 原记录：评测运行器缺口（11-06，§4.3）。已修并本地提交（未推送）：脚本导入路径补上 `server/tests`；父题停在问题处时 `bind_action_parents` 不再崩溃（`tools/xiaopai_real_rag_fixtures.py:439`）。未修：运行超过 30 分钟观测上限后又停在问题处时，后续等待只认结束状态，CTX-01 因此停在 25/31 轮；“待对账”在 API 上也显示为 `waiting_input`，要结合错误码区分。
- D257 🟡 11-08 子调用并发已做并本地提交（未推送）。真实回归没跑，要你另行授权。单轮长尾的主因不在串行，另登记 D268（11-08 已修）。[分析与验证](../docs/reports/evidence/pdos-next-real-eval-20261105/d257-extract-timing.md)
  - 改法：
    - `assistant.extract` 里每条非结构化引用各跑一个隔离子图。原来逐条串行，现在最多 N 个同时跑（`agent/enterprise_search/assistant_fanout.py`）。
    - 结果按引用原顺序合并，与串行逐条相同。
    - N 由 `PDOS_ASSISTANT_EXTRACT_CONCURRENCY` 配置，取 1–8，1 就是原来的串行。worker 组装适配器时校验，非法值启动即报错。
  - 缺省 2，依据：
    - 11-05 回归的 130 次抽取里，非结构化引用 1 条 68 次、2 条 15 次、3 条 45 次，没有超过 3 条。估算 2 路把抽取 p95 从 8.2 降到约 5.9 分钟，3 路约 5.6 分钟，再往上几乎没有收益。
    - 连接：每个 worker 缺省 4 个活动线程。抽取进行中，每个活动常驻占 2–3 个应用库连接（运行租约 1 个，组合锁 1–2 个），SQLAlchemy 缺省连接池共 15 个，只剩 3–7 个给短事务。2 路时最多 8 个子图共用这些连接，再高容易等池。每个子图另占 1 个检查点库连接。
    - 预算：同一运行的子调用同时持有各自的 token 与费用预留，预算快用完时并发越高越早被拒。
    - 服务商：同一密钥的并发限额未知，11-05 已是 4 个运行同时跑。
    - 主机侧开销有一部分是 Python 计算，受 GIL 限制，3 路以上的收益不确定。
  - 没变的：
    - 每个子调用各自的预算与费用预留、运行回执和幂等键。领取与释放都按“运行行 → 调用 → 预算”的顺序加锁，并发不改变各自预留和记账的内容。
    - 结果顺序与账本记账。
    - 一个子调用以领域错误失败时，只记为该引用失败，其余照跑，与原来相同。
    - 非预期错误时，未开始的不再开始，在跑的到下一个安全点停下，按引用顺序抛出第一个错误。
  - D243 补洞：抽取子图的主机在启动时建好，活动设的“已放弃”信号原来传不到子图，被放弃的尝试会把整个抽取跑完。现在：
    - 活动把信号放进运行上下文（`run_lease.attempt_scope`）。
    - 子图在每次模型和读取调用之前检查，在领取之前停下。
    - 线程池等所有子线程停下才返回，子线程活不过本次尝试。
  - 测试（隔离 `pdos_test`，head `s0_0855`）：
    - `test_assistant_fanout.py` 21 例，连跑 15 次全过。
    - `test_assistant_extract_concurrency_pg.py` 5 例，用真实账本、价格卡与验证预算：
      - 3 个子调用同时在途；
      - 各自预留并按实际结算，占用归零；
      - 被放弃后不再发起子调用，下一尝试从检查点续跑，没有重复发送（内存检查点与 PostgresSaver 各一遍）；
      - 取消；
      - 一条被服务商拒绝。
    - `test_run_attempts.py` 加 1 例。
    - 反证：去掉子图里的安全点，被放弃的尝试还会多发 2 次子调用，测试失败。
    - 受影响范围回归（104 个文件）：910 通过、22 失败、4 个错误。这 26 个在不含本次改动的代码上逐条同样失败，其中 12 个是缺检查点库环境，其余与 D27 同类。
  - 可选项，属于规则，本次未加：给单轮总时长设上限，例如超过 N 分钟就停在问题处并说明进度。与 30 分钟观测上限、60 分钟活动上限一起，由你决定。
  - 余项：
    - 真实回归复测，花钱，要你授权；
    - Temporal 运行时下的联调未跑。
  - 改到的文件：`activities.py`、`run_lease.py`、`assistant_adapter.py`、`assistant_graph.py`，新文件 `assistant_fanout.py`。没有改 `context_budget.py`、`gateway.py`、`host.py`（D248），也没有改 `assistant_ledger.py`（M1）。
  - 原记录：单轮最长 31 分钟（11-06，§4.4）。F=48000 的轮次修复后能做完，平均每轮模型调用 4.6 → 11.4 次，上下文单轮 p95 从 11.3 分钟升到 24 分钟。长尾在企业检索的隔离抽取 `assistant.extract`：子调用串行，每个 1–2 分钟，一次抽取可达 17 分钟。可考虑子调用并行或给单轮总时长设上限；与 30 分钟观测上限、60 分钟活动上限一起看。
- D268 ✅ 11-08 已修并本地提交（未推送）；真实回归没跑。[剖析与修复](../docs/reports/evidence/pdos-next-real-eval-20261105/d268-guard-pass.md)
  - 原因（剖析确认）：每次守卫都把当前运行和每个前序轮次的谱系各走一遍（`assistant_inheritance.registry`），同一个祖先的检索读取在一次守卫里被重复证明、整行（含很大的 `versions`）重复读取，次数随轮次增长。守卫 SQL 条数约是轮次的平方：每轮多出的条数依次是 17、18、22、26、30……
  - 改法：`assistant_ledger.one_pass(session)` 是一次守卫内的记忆，挂在本事务上，事务结束就丢弃。
    - 每个前序运行的封存检索读取只证明一次，之后返回深拷贝；
    - 本事务里已按普通 RLS 读到的运行行不再重读，`carried()` 复用它们时照样逐条核对会话与请求人；
    - 只在 `carried()` 和 `work_state.check_frozen()` 里启用。
  - 权限口径不变：下一次守卫（包括同一次模型调用发出前的复核）照旧把全部历史按当前权限、撤回和扫描状态重新证明一遍。
  - 效果（隔离 `pdos_test`，离线服务商，第 12 轮）：
    - 守卫 SQL 425 → 114 条，之后每轮固定约 9 条；
    - 耗时 1.6 → 0.6 秒，测量时本机负载很高，只作参考；
    - `check_conversation` 120 → 70 条；
    - 剩下的时间约 97% 是等数据库返回。
    - 按此外推，第 24 轮守卫约 1480 → 220 条，未实测。
  - 测试：
    - `test_guard_pass_pg.py` 4 例：一次守卫和一次会话检查里每个封存调用只证明一次、下一次守卫全部重证；SQL 每轮增量不变；两次守卫之间撤回资料会被拒；记忆只在本事务内、返回副本。
    - 反证：换回修复前的代码，前两例失败（4 轮时同一调用被证明 5 次）。
  - 受影响范围回归（132 个文件）：1249 通过、19 失败。
    - 15 个在不含本次改动的代码上逐条同样失败，与 D27 同类。
    - 3 个 `test_work_state_candidates` 是因为假会话没有 `info`，已改为没有 `info` 时不启用记忆，重跑通过。
    - 1 个 `test_recovery_pg[statistics_only]` 是比较一个没有 `ORDER BY` 的查询结果摘要，重跑通过，与本改动无关。
  - 余项：
    - 每个前序轮次仍各跑一次谱系递归查询、一次恢复根查询和一次会话绑定查询，每条证明 2 次 principals 查询，都是线性的。再降要改 `lineage()` 或证明函数，这次没动。
    - 真实回归复测，花钱，要你授权。
  - 改到的文件：`assistant_ledger.py`（M1 也改过，合并时注意）、`assistant_inheritance.py`、`work_state.py`。没有改 D248 的三个文件。
  - 原记录：单轮长尾的主因：每步的守卫随会话变长而线性变慢（11-08 由 11-05 回归数据发现）。子模型调用 HTTP 各轮约 10 秒，CTX-01 第 18–24 轮抽取子图每次模型调用前的主机工作 p50 130 秒、p95 228 秒，领取到发出 HTTP 再约 23 秒；第 0–5 轮是 8.4 秒和 1.9 秒，RAG 单轮题 3.4 秒和 0.7 秒。最长的抽取只有 1–2 条引用，D257 的并发缩不短它们。
- D269 ✅ 11-08 两处余项都已修并本地提交（未推送），无迁移，[证据](../docs/reports/evidence/w8-d269-d44-20261108/README.md)。
  - 停在领取之前：
    - 研究、MCP、`evidence.extract`、`assistant.compare` 的子图（连同 D257 的企业检索抽取）每次领取模型或读取调用前，都检查本次尝试的停止信号。
    - 启动时建的主机没有自己的信号，改读 `attempt_scope` 里的（`run_lease.check_attempt`）。
    - 主图并行读取的线程池、`evidence.extract` 的原件线程池改为复制上下文，信号能进线程。
    - 被放弃或取消后不再领取新调用，也就不再发出新的外部请求。
  - 已领取的调用走完：
    - 网关在领取模型调用前做最后一次检查；领取后的复核（`_recheck_dispatch` → `context_guard`）不再停。原来停在这里会留下 started 调用，下一尝试只能对账，即第二项。
    - 已发出的请求照常落到自己的调用行，下一尝试重放，不重发，与 D257 的规则一致。
    - 被放弃的尝试不写父调用：研究作业、MCP 读取、比较、抽取保持 started，半截结果不进账本，由下一尝试接续。
  - 取消：数据库本来就拒绝取消后的领取和落账。测试锁定：迟到结果不落账，调用记为 unknown + `CANCELLED_RUN`，没有未释放的预留。
  - `evidence.extract` 改为可接续的编排调用（同 `assistant.extract`、`research.fanout`、`mcp.read`）。否则子图停下后，下一尝试会卡在对账。
  - 测试：
    - `test_child_attempt_stop_pg.py` 8 例：四类子图各一例“放弃后接续、不重发”，各一例“取消时迟到结果不落账”。
    - `test_run_attempts.py`：安全点参数去掉 `context_guard`，加上 `model_step`、`read_callback`；另加 8 例（启动主机读范围信号 6、复核不停 1、并行读取线程带信号 1）。
  - 反证：
    - 撤掉修复后，4 个“放弃”用例和 10 个单元用例失败：研究子图跑完整次扇出，MCP 与比较子图在信号后又发一次模型调用。抽取的取消用例也失败，原因只是还没有接续入口。
    - 只去掉抽取线程的上下文复制，抽取子图也停不下。
    - 研究、MCP、比较的取消用例撤掉修复照样通过，因为是数据库挡住的。
  - 口径：“租约失效”按 Temporal 放弃本次尝试处理（D243 的 superseded）。租约连接本身断开不会被发现，另登记 D358。
  - 受影响范围回归（96 个文件、1105 例，11-08 晚补跑完）：
    - 1035 例通过，其中 21 例是补上本任务的检查点库后通过的。
    - 27 例报错是 `test_registered_snapshot_reads.py` 的夹具问题，见 D27 的 11-08 补记。
    - 2 例失败（`test_public_temporal_domain.py`），因为本机没有 Temporal 可执行文件。
    - 41 例跳过：27 例要 Temporal，14 例绑定历史端口 53502。
    - 失败和报错的 37 例在 `07c023e5` 上同样失败或报错，没有本分支新增的失败。
  - 余项：真实 Temporal 下的整链未验证。本机没有 Temporal，镜像要下载，须你授权。
  - 原记录：D243 停止信号的两处余项（11-08 做 D257 时发现）。① 研究、MCP、`evidence.extract`、`assistant.compare` 的隔离子图，与原来的企业检索抽取一样，用启动时建的主机，收不到“已放弃”信号，被放弃的尝试会把这些子图跑完。不会并发写坏账本（后来的尝试在租约处等待），只是浪费时长和费用。② 主循环里，模型调用发出前的复核（`gateway._recheck_dispatch` → `context_guard`）在领取之后；信号恰好落在两次检查之间时，这次调用留在 started，下一尝试会把它当成要对账的未知调用。
- D356 初始 role:user 信封里有来自资料的文字（11-08 做 D44 负例时核对，未改）：
  - 操作者目标和下列内容在同一条 role:user 消息里：
    - 提案条目的 `source_refs[].quote` / `statement`，是原件、知识的逐字片段；
    - 会话摘要，是模型输出，可能复述注入文字；
    - `work_state` 的焦点标题、未完成事项和问题；
    - 记忆目录；
    - 目标末尾的页面资料块，有边界标记。
  - 原件里的注入文字经提案引用，就能到操作者指令的位置。
  - 服务器侧控制不看位置（D44 负例证明写入、范围、出站都由服务器判定），但模型更难分辨。
  - 改法：把资料从操作者消息里分出来，或逐字段标注。这是模型可见提示结构的改动，按不可协商项 4 须走 Prompt A/B。
  - 提案引用这条路径还没有端到端负例。
- D357 资料“不可信”标注有缺口（11-08，未改）：
  - `category.knowledge.list` 把整条知识（含 `origin=imported`）直接返回主循环，工具登记为 `trusted`；企业检索则把导入知识标为 `untrusted`。`taint` 只记在运行结果里，没有动作据它放行或拦截，不是越权缺陷。
  - 冻结提示词 1.0.0 第 50 行只把网页、导入文件和 MCP 回复列为不可信，没提知识条目和信封里的资料。
  - `evidence.extract` 子图的说明（`extract_graph.py`）没写正文不可信；企业检索抽取和 MCP 子图写了。
  - 后两项是模型可见文字，须走 Prompt A/B。
- D358 ✅ 11-10 已修（本地提交、未推送，[证据](../docs/reports/evidence/w4-w7-w8-debt-20261109/README.md)）：`run_lease` 交出 `RunLease`，`held()` 在租约自己的会话里查 `pg_locks`，看本后端是否仍持有本运行的锁（驱动可能悄悄重连，查询成功不等于锁还在）；一旦失去就一直算失去。Activity 的心跳线程每 10 秒探测一次，失去时置与 Temporal 放弃相同的停止信号，本次尝试在下一个安全点停下，按 D243 的 superseded 处理（抛 `CancelledError`，运行状态不动，交给下一尝试）。租约连接加 TCP keepalive（`tcp_user_timeout` 只在 Linux 生效），对端失联时探测报错，不会挂住。验证：PG 用例真实终止租约后端——探测发现并保持失去，不持锁的会话不算租约，Activity 在下一个安全点停下、运行仍为 running；单元用例 2 个（心跳发现失去；持有时照常完成）。反证：去掉心跳探测 3 个失败；探测改为只看查询成功 1 个失败。受影响的 8 个文件 162 个通过（`test_activity.py` 的 3 个用本 worktree 自建的检查点库）。余项 D460。原记录如下：原记录：
  - D243 的租约是独立连接上的会话级 advisory lock。连接一断锁就释放，本次尝试并不知道；这时 Temporal 若开下一尝试，两次尝试会重叠。
  - 改法：心跳线程每 10 秒探测租约连接，断了就置停止信号。要完全隔开，落账时还得核对租约仍在本会话。 11-12 P101 下线原路径后，同一探测接到插件路径：每个节点在拿到租约后由 `run_lease.lease_watch` 每 10 秒探测，失去即置停止信号；节点外壳把停在安全点映射为可重试的 `ATTEMPT_SUPERSEDED`，由下一次尝试接手（`tests/agent/kernel/test_run_attempts.py` 后三项）。
- D378 🟡 11-12 LangGraph 执行迁移到 Temporal 官方插件（`temporalio-langgraph==0.1.0`）。[决策记录](../docs/design/2026-11-12-langgraph-temporal-plugin-migration-decision.md)经你 11-12 确认（“全部按推荐”），登记为 [P100](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p100)，AGENTS.md 第 6 条和运行架构收口合同已修订。阶段 0–2 已本地提交（`2bde2847`、`2d2fb179`、`18dca876`，未推送）。
  - 阶段 1 试点 ✅：个人摘要图已能在插件上按节点执行（`PersonalSummaryGraphWork`，只由测试启动，不接生产派发；worker 已注册插件）。可用能力：节点外壳（心跳、取代信号、错误映射）、Workflow 驱动与 `resume` 信号队列、图外的 open/close Activity。[证据](../docs/reports/evidence/langgraph-temporal-plugin-20261112/README.md)：7 项试点测试通过（正常完成并回放、节点内杀 worker 后已完成节点不重跑、重复与乱序信号、超时重试、停止后收尾、拒绝非固定信封），真实数据库端到端 4 项通过（另建隔离库 `pdos-next-test-20261002-de9db19e`，状态文件 `.local/graph-plugin-runtime-20261112.json`，原 `pdos_test` 未动）；连同原有工作流测试与回放检查共 68 通过、3 跳过。实测结论见决策记录 §10：不需要升级 temporalio；同步节点须包异步外壳才能发心跳；continue-as-new 的 `cache()` 带的是全部节点输出，主图改用只带 state 的续接。
  - 阶段 1 余项：continue-as-new 和 workflow 侧节点中断只做过一次性实测，未入测试套件，随阶段 2 的主图测试补；隔离库 `de9db19e` 保留给阶段 2，清理放检查点。
  - 阶段 2 主内核 ✅：`XiaopaiGraphWork` 与主图（`agent/kernel/plugin_graph.py`）已实现，开关 `PDOS_XIAOPAI_GRAPH_TENANTS` 默认空，生产路径不变；`xiaopai.py`、`activities.py` 未改。可用能力：主图 7 个节点各为一个 Activity、答复与采用按引用恢复、读取结果与服务商续接数据存账本引用、结果未知的模型调用不重发并转对账、历史过大时 continue-as-new。证据同上（“阶段 2”一节）：主图端到端 13 项、等待与引用恢复 10 项、旧工作流历史回放与条件边确定性 16 项，共 39 通过；旧路径回归 128 通过；经过内核图的 171 个测试文件整批回归 3630 通过、1 项偶发失败（单独运行在改动前后都通过，见 D380）。设计细化与实测体积见决策记录 §11。
  - 阶段 2 缺口 G1–G5 ✅ 11-12 补完（决策记录 §11.4）：品类采用真实全链路、隔离抽取子任务在新路径 `tools` 节点内、真实 worker 进程被杀后不重发并转对账、工具执行中取消与模型应答期间真实撤回、重试的进度事件与每节点重建耗时（中位约 60–70 毫秒）。合并复跑 153 通过、2 跳过。
  - 阶段 3 合成租户试运行 ✅ 11-12（你授权，并选择在隔离库新建合成租户、真实调用 MiniMax）：三轮共 9 次真实模型运行全部走 `XiaopaiGraphWork`，状态为 completed 或 partial，无失败、无待对账、无残留占用，历史均回放通过；continue-as-new 真实发生 4 次且无重跑；最大单个 payload 36 KB。partial 的原因都来自合成租户配置或模型输出格式，与执行路径无关。结论、体积修正和未覆盖项见决策记录 §12，原始记录见证据说明“阶段 3”一节。试运行脚本 `tests/agent/kernel/test_xiaopai_graph_plugin_real_trial.py` 需显式设置环境变量才运行。已本地提交（`97a19b16`）。
  - 阶段 3 补做 ✅ 11-12（决策记录 §12.3）：研究子任务经生产 worker 真实入口在新路径上通过，研究进行中两次杀掉并重启 worker，搜索与网页请求各只发出一次；MCP 子任务通过，连接器凭据和回复中的注入指令都没有进入 Workflow 历史；真实模型下“追问 → 答复 → 恢复”走通；长会话（8 份资料、同一会话 5 轮）最大单个 payload 59 KB、单次执行历史最大 2.26 MB，续接 2 次无重跑，其中一轮遇到真实的“结果未知”，没有重发、已自动对账。合并复跑 142 通过、1 跳过。顺带修了 `test_research_runtime_process.py` 末尾一条过时断言（主图检查点线程名早已改为按会话分命名空间，该用例需显式开启、平时不跑，所以一直没被发现）。已本地提交（`19a3a5a2`）。
  - 阶段 3 余项：真实用户规模的租户（多人、长期会话、真实资料量）没有测过；本机 Temporal 开发服务无认证、只监听回环，历史保留 1–7 天，部署环境须另定访问控制、备份和保留期。
  - 下线原路径 ✅ 11-12（你要求直接下线，因为尚未发布；[P101](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p101)，决策记录 §13）：所有新运行都以 `XiaopaiGraphWork` 启动；删除了 `XiaopaiWork`、`advance_xiaopai_run`、租户开关、试点工作流类型和原个人摘要图；worker 注册表 17 个工作流类型；评测工具改用插件 worker；AGENTS.md 第 6 条和收口合同改为单一路径口径。约 25 个依赖原路径的测试文件迁到新路径或删除，新增测试支持 `tests/agent/kernel/graph_inline.py`。回归：第一批 668 通过，10 个失败中 1 个是本次应改的计数断言（已改），其余 9 个在上一个提交上同样失败或同样的顺序下同样失败；第二批（显式开启的端到端与进程级用例）33 通过、1 个原有失败。详见证据说明“下线原路径”一节。已本地提交（`681016f4`，未推送）。
  - 下一步〔你〕：是否在试点部署上使用（目前没有试点部署，见 D210）。未结束的本机 `XiaopaiWork` 工作流升级后不能继续，需要取消后重新发起。
  - 环境清理 ✅ 11-12：按你的要求删除了隔离库 `pdos-next-test-20261002-de9db19e`、检查点库 `pdos-next-state-de9db19e-pg`（连同各自的数据卷）、网络 `pdos-next-state-de9db19e` 和两个状态文件；删除前核对了容器 ID 与标记。库里只有合成测试数据，没有做备份。其他环境（f117bb5b、c351c0ca、agent-state）未动。需要这些库的测试（`*_pg.py`、进程级用例、真实模型试运行）以后要重新建环境才能跑。
- D379 `agent.kernel.models` 有循环导入（11-12 做 D378 时发现）：新进程里先导入 `domain.my_work.summary_runtime` 或 `summary_graph` 会报 `cannot import name 'KernelRow'`（出错点在 `session_presentation_models`）；先导入 `pdos_next.workflows.worker` 则正常，所以 worker 入口不受影响。试点的测试 worker 用“先导入 worker 模块”绕开，未修。
- D380 `tests/knowledge/pg/test_answer_footprint_pg.py::test_uncited_private_parent_footprint_remains_when_only_public_source_is_requeried` 在整批运行中偶发失败（11-12 做 D378 阶段 2 回归时出现 1 次：模型节点内报“当前身份没有这个品类的操作权限”）。单独运行通过，且在原始 `graph.py` 上同样通过；原因未查，怀疑与同批其他用例的顺序或时间窗有关。
- D381 节点或 Activity 重试时会重复发出 `model_started` 进度事件，过程视图多显示一个步骤（11-12 做 D378 时实测；旧路径 Activity 重试时同样如此）。账本调用、出站检查和调用计数不受影响。要修应在过程视图按轮次去重。
- D382 ✅ 11-13 已清理（决策记录 §13.3，[证据](../docs/reports/evidence/langgraph-temporal-plugin-20261112/README.md)“清理主图检查点遗留代码”一节）：`AgentKernel.execute` 只剩隔离子任务的驱动，主图恢复、回答处理分支已删；`session_checkpoints.py`、`BoundHost.checkpoint_layout` 已删，新建运行不再写 `checkpoint_layout`；只验证原路径恢复的测试删除，其余主图测试改用测试支持 `tests/agent/kernel/pure_graph.py`。回归：内核、企业检索、工作流、我的工作四个目录加回放检查共 3961 项，3900 通过、60 跳过、1 失败（企业检索一条“1 秒内”计时断言，整批负载下 1.09 秒，上一个提交上同样会失败，D385）；显式开启的进程级用例 13 项中 12 通过，1 项等待超时、单独重跑通过（D385）。有意保留两处：① 检查点保留清理（D58）的线程分类器不动，它还要识别并清掉库里 P101 之前留下的主图检查点行；② 数据库函数 `automation_service_start` 仍往运行记录写一个已无人读取的 `checkpoint_layout` 键，去掉要加一条迁移，没有为此单独加，下次改这个函数时顺带去掉。
- D383 测试顺序依赖（11-12 发现，原有问题）：`tests/integrations/dingtalk/test_channel_pg.py`、`test_service_loss_pg.py` 和两个自动化用例（`test_service_budget_pg`、`test_service_fulfillment_pg` 各一项）排在某些内核测试之后会失败（“permission denied for table agent_validation_budgets”“Admitted service attempt binds its exact new Run and real admission time”），单独运行或按目录运行都通过。已定位到至少 `tests/agent/kernel/test_revoked_terminal.py` 在前时会触发；可能与 D380 同源。原因未查。
- D384 两处原有的失败用例（11-12 发现，都与当天的改动无关，在上一个提交上同样失败）：① `tools/tests/test_local_host_profiles.py` 4 项，期望的报错文案与实现不一致；② 需显式开启的 `tests/agent/kernel/test_context_x3_temporal_pg.py`，结果续读恢复“带观测时刻的列表”时报来源过期（`domain_reads._restore_list`）。
- D385 两条随负载波动的用例（11-13 做 D382 回归时出现，都与当次改动无关）：① `tests/agent/enterprise_search/test_recovery_pg.py::test_registered_family_search_and_authority_batch_stay_constant_sql_and_under_one_second` 的“1 秒内”断言贴着阈值，同一个库上改动前后各有失败（1.04–1.09 秒）和通过；② `tests/agent/kernel/test_worker_process_recovery.py` 与其他进程级用例同批运行时出现 1 次等待 worker 状态超时，单独运行 3 项全过。都未修。
- D460 （11-10 修 D358 时登记）租约失去后到停下仍有窗口：最长一个心跳（10 秒）加上到下一个安全点的时间；这期间 Temporal 若已开下一尝试，两边仍可能各落一次账。要完全隔开，须在落账事务里核对租约仍在本会话（D358 原改法的第二步），涉及每个内核写事务，未做。核对运行（`reconcile_xiaopai_run`）也持租约，时间很短，未加探测。

**W9 业务域余项（实现缺口；按闭环推进）**
- D47 部分完成：12 条 not_implemented 已实现 10 条，余 2 条（11-08 实现 2 条；11-09 按 P95–P97、P120 实现 7 条；11-10 按 P95 两条补充确认实现试模；worktree `elastic-noyce-fad368`，本地提交未推送，[证据](../docs/reports/evidence/pdos-next-d47-operations-20261108/README.md)、[逐条盘点](../docs/reports/evidence/pdos-next-d47-operations-20261108/inventory.md)）。原写 14 条是 11-01 的数字；`my_work.query`、`provider.agreement.register` 此后已以接口实现。余下：`customer.sample.send`（D318）、规格冻结 `product.definition.publish`（归 D36）。
  - ✅ `supply.commitment.record`（T0；F25、AT-20）：
    - 每条供方承诺是一条版本链，动作有建立、改期改量、关闭、重开，绑定固定 Build 的真实需求物料。
    - 具名本人可用本人陈述作来源（`human_recorded`）；小Pai 只能引原文行，且须有当前资格和绑定运行。
    - 检查日为承诺日 +1 天，到期后进“我的工作”外部队列。
    - 承诺不计入库存与齐套；供应面板按 BOM 行显示需求、承诺、实到。
    - 已加入 `build_execution` 0.1.3-draft。
  - ✅ `work.forecast.refresh`（T0 确定性引擎；P82 D181、P58、P66，AT-18/19）：
    - 用当前计划和任务的实际开始、提交时间重算区间、浮时和关键路径。
    - 只写新预测，不改计划、基线和承诺；单列为“系统重算”。
    - 意图绑定服务器算出的输入摘要：同日同输入时重放；输入变了返回 409，并附当前摘要。
    - D181 固定案例用纯函数测试验证。
    - 已加入 `work_management` 0.1.3-draft。
  - 迁移占位 `s0_0868_supply_commitments`（down `s0_0861`）、`s0_0869_forecast_refreshes`（down `s0_0868`），**集成时按真实 head 重排**（11-11 第五轮集成改为 `s0_0877`、`s0_0878`，down 接 `s0_0876`）：文件名、revision、down_revision、快照 `schema_s0_0868.py`/`schema_s0_0869.py` 以及降级保护文字里的号要一起改。两次迁移都没有改共享函数（`m3_lifecycle_*`、工作管理公共守卫都没动），只新建本闭环的表、函数、策略和触发器。
  - 验证：
    - PG：供应承诺 6 项，预测重算 3 项。
    - 纯函数：规则 8 项，合成 5 项。
    - 受影响的公共 PG 371 项通过（2 项失败均为既有或并发干扰）。
    - 无库全量 10770 项通过（1 项失败为基点既有，记 D313）。
    - 前端：`.mjs` 1924 项、`.test.ts` 752 项通过，tsc、lint 均 0 错误。
    - 合同校验、迁移往返和降级保护通过；浏览器亮暗两套主题走通。
  - 余项：两条闭环的余项是 D314、D315；待定的 10 条是 D305–D312；规格冻结 `product.definition.publish` 归 D36。
- D305 ✅ 11-10 按 [P95](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p95) 及两条补充确认实现 `npi.tooltrial.create`（T1，工程或制造具名本人一次确认）：
  - 首次试模同时登记模具第 1 版（零件、版本、供方模具编号、穴数，可选关联本 Build 受控导入的模具资源），之后的试模引用模具，信息变化时续版；试模记录轮次、目的、材料批次、参数、穴位、问题与纠正措施。模具、试模与验证请求在同一事务，模具版本与试模共用一张公共回执（回执主体是试模，数据库核对模具版本正是该试模引用的版本）。
  - 验证请求按已有验证准备建立，结构与校验同 `verification.request.create`，只是职责按试模（工程或制造）核对；这个入口只对试模开放，单独新建请求仍只认工程或品质。正式请求表守卫未改：请求第 1 版仍记为 `verification.request.create`，试模记录持有请求标识。
  - `test.disposition.decide` 加可选处置结论（接受/拒绝）：请求来自试模而未填时拒绝；其他处置不变，未填时保存的输入没有这个键、摘要与原来一致。CAPA 配对核验（`quality/capa/paired.py`）的闭合键检查同步改为“未填结论时不要求该键”，否则所有未填结论的处置都会被判为缺语义（无库全量发现）。准备度（`_resource_report`）的模具项读最近一次试模所在测试的具名处置：接受为已验收，拒绝为未通过，尚无处置为未知。
  - 入口：供应页“试模登记”；读取 `GET …/builds/{build}/tool-trials`。迁移占位 `s0_0877`（11-11 第五轮集成改为 `s0_0886`；只新建两条版本链）。技能包 `build_execution` 增加 T1 条目（仍为本分支未发布的 0.1.4-draft）。余项见 D472。
- D306 ✅ 11-09 按 [P95](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p95) 实现 `npi.fixture.accept`（T2，制造具名）：
  - 治具身份取 Build 当前受控导入的资源（kind=fixture），同一命令办理接受、拒绝、撤销，可带有效期与条件，每次一个新版本；
  - 准备度计算（`_resource_report`）用本地验收决定替换同用途同工序的导入验收事实：接受为已验收，拒绝或撤销为阻断，有效期外阻断，无记录为未知；
  - 入口：资源依据面板的治具行；读取 `GET …/projects/{project}/fixture-acceptances`。迁移占位 `s0_0872`（11-11 第五轮集成改为 `s0_0881`；同时把 6 条新 T2 加入具名决定无到期清单）。余项见 D319。
- D307 ✅ 11-09 按 [P96](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p96) 实现 `quality.capa.effectiveness.decide`（T2，品质具名）：
  - 有效：同一事务关闭问题（状态 closed、关闭结论、有效性决定）；无效：回到措施中，根因与 CAPA 清空，用现有 CAPA 起草、根因决定重新办理，上一轮留在历史版本；延长观察：新截止日须晚于当前截止日；
  - 措施实施人不能决定；有效须有结论为“适用”的当前具名复核且观察期已满；无效须引用复核或观察记录；
  - 入口：质量页“CAPA 有效性决定”，读取 `GET …/projects/{project}/capa-effectiveness`。迁移占位 `s0_0875`（11-11 第五轮集成改为 `s0_0884`；问题状态加 closed、操作清单与事件映射）。余项见 D320。
- D308 ✅ 11-09 按 [P96](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p96) 实现 `supply.alternate.approve`（T2，工程具名）：绑定 Build + BOM 行 + 当前 BOM/配置摘要，须引用带当前具名复核的测试运行；可带有效期、可撤销、可重新批准；只进入该 Build 的齐套计算（`approved_alternates` 接入齐套与新鲜度），BOM 不变，过期、撤销或 BOM 变化后不再计入。入口：供应页“替代料批准（本轮）”。迁移占位 `s0_0874`。余项见 D319。D241 的替代料依赖解除。
- D309 部分完成 11-09 按 [P97](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p97)：
  - ✅ `customer.acceptance.record`（T2，内部具名成员）：五类范围逐项登记（承认、条件承认、未承认、不涉及，带条件与到期日），签样单须为上传原件并核对原文行；阶段评审读取只列出承认情况，不进门禁检查；入口：供应页“客户承认（签样单）”与阶段页。迁移占位 `s0_0876`。
  - 未实现 `customer.sample.send`，转 D318；关联外发记录在外发接通前返回 503。
- D310 ✅ 11-09 按 [P120](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p120) 实现 `evidence.source.withdraw`（T2，来源负责人或品类负责人）：只办理已被签署决定使用（封存或发布的定义引用、被批准决定或封存定义消费的事实）或已共享的原件与登记资料；撤回后列出使用它的业务记录并在读取时显示需重核，同时触发企业检索清理。T1 `evidence.original.withdraw` 增加两条守卫：只能撤回本人上传、未被签署决定使用的原件（P9）。入口：资料面板“具名撤回来源”。迁移占位 `s0_0873`（两个只读判定函数）。余项见 D319。
- D311 ✅ 11-09 按 [P120](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p120) 实现 `product.definition.update`（T1）：修改整体字段生成下一草稿版本，原样带入条目与来源，原版本不变；规格冻结后与派生型号的定义被拒。入口：定义页最新版本“修改整体字段”。迁移占位 `s0_0870`（扩展 `protect_fixed_definition`、`m3_definition_item_atom` 的操作清单）。
- D312 ✅ 11-09 按 [P120](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p120) 实现 `engineering.interface.update`（T1）：同一命令建立、修订、各专业确认或提出异议；挂在工程配置系列的当前版本下；负责人须为项目成员且不能代替确认；修订后原确认转为已取代；受影响项须经变更图真实所有者读取，变更图新增接口节点只沿登记项传播，待核实线索单列。入口：Build 准备页“接口合同”。迁移占位 `s0_0871`。D49 的“接口合同与设计责任人”随之关闭。余项见 D319。
- 11-09/11-10 迁移占位 `s0_0870`–`s0_0877`（down 依次接 `s0_0869`），**集成时按真实 head 重排**（11-11 第五轮集成改为 `s0_0879`–`s0_0886`，`s0_0870`→`s0_0879` 起按序加 9）（文件名、revision、down_revision、快照 `schema_s0_087x.py` 与降级保护文字一起改）。其中 `s0_0870`、`s0_0872`、`s0_0875` 修改了共享函数或约束（`protect_fixed_definition`、`m3_definition_item_atom`、`ck_confirmations_decision_deadline`、`quality_issue_versions` 两个检查约束、`assert_quality_change_receipt`），集成时须与其他分支对同一函数的改动合并，不能整段覆盖。`s0_0877` 只新建模具与试模两条链。
- D313 既有测试失败：`tests/agent/kernel/test_source_views.py::test_get_only_router_uses_current_context_and_read_snapshot`，`GET /v1/personal/agent-input-sources` 期望 404、实际 500。在基点 `d6abcbf2` 源码上同样失败（11-08 第三轮集成带入 D42 后），与 D47 无关，未修。
- D314 预测重算余项：
  - 已开始的任务缺“剩余工期”录入口，引擎要求 remaining，所以预测保持未知；
  - 按同品类历史实际用时校准排期（P33、D181）未做；
  - 任务实际变化后不会自动重算，现在由人或小Pai 发起命令；
  - AT-67 尚未写入附录 B 和 `acceptance.json`（P82 待同步）；
  - 预测误差与承诺兑现率指标未做（D181、D191）；
  - 预测记录只与计划自带的排期比较，不与已批准基线比较。
- D315 供应承诺余项：
  - 小Pai 经合格运行写入的端到端 PG 未验证，缺可复用的合格运行夹具，同 D280；
  - 小Pai 写入的承诺不支持按运行撤回（与外部等待相同，`ai.run.revert` 尚未覆盖这类回执）；
  - 检查日按自然日 +1，没有用工作日历（D221 接通后可改）；
  - 承诺没有接入 `m3_lifecycle_*` 图遍历：原件级生命周期靠通用触发器，品类级图遍历不含这两张表；
  - 页面没有原文引用选择器，人工只用本人陈述，原文引用由接口和小Pai 使用；
  - D199 供方画像从现在起可以积累数据。
- D316 本机开发环境问题：多个会话的本地预览都用 `localhost`（端口不同），浏览器共用 `pdos-next-session` cookie，会互相覆盖，导致偶发 401（11-08 走查时遇到，重新建立本地会话后正常）。改用 `127.0.0.1` 访问时开发服务器不完成水合。只影响本机多会话并行走查。
- D317 ✅ 11-10 试模的两处阻塞已解决并实现（见 D305）：
  - 处置结论字段：用户 11-09 选 A（“给处置加接受/拒绝字段 (Recommended)”），已实施。
  - 305-3 与 305-4 冲突：用户 11-10 选 A（“试模带出的请求按试模职责校验 (Recommended)”），已实施；两条指定测试（制造人员发起试模成功带出请求、制造人员单独新建验证请求仍被拒）通过。
  - 原记的“需放开正式请求表守卫”未发生：请求由验证模块在同一事务内按原样写入，守卫不变。
- D318 客户样品外发 `customer.sample.send` 未实现（P97 已定，真实外发仍未授权）。按 P97 要复用外部移交管线，需要：授权表的放行包与两份放行外键改为按用途可空；材料所有者增加“客户样品”用途分支（前置：工程与制造开工授权、样件已分配）；回执现在要求宿主配置的受信签发方，P97 的“内部具名人手工登记回执”需要在该管线新增人工登记的签发性质。改动集中在 `external_handoff`（约 3.8k 行，含 AT-29/30 对账），本轮未做。客户承认的“经 PDOS 外发必须关联”在外发接通后补。
- D319 11-09 实现部分的余项（D306、D308、D310–D312）：
  - D306：资源读取（`manufacturing/resources/owner.py`）仍报告 `NATIVE_ACCEPTANCE_OWNER_UNCONNECTED`、治具验收显示未知；测试资源服务的同类读取未接；模具（tooling）验收已由 D305 接入准备度。
  - D308：没有核对证据运行实际测的是该替代料（运行到物料只有间接关联）；批准后要重新记录供给快照再算齐套才计入（齐套命令按意图去重），旧齐套显示需重算。
  - D310：撤回判定沿生命周期图遍历，资料多时有性能风险；“已被签署决定使用”按现有 `m3_evidence_signed_consumed` 口径（封存或发布定义、被批准决定或封存定义消费的事实），不含其他 T2 决定表；T1 撤回新增的“本人上传”守卫改变了原行为（原先品类可见原件任何写入者可撤）。
  - D311：派生型号的定义不在本命令内；协审与“评审中”归 D36。
  - D312：受影响项只支持有真实所有者读取的类型（不含模具、治具、接口之间）；参与专业用租户项目角色标识；待核实线索由人或小Pai 填写，未接自动推断。
- D320 D307 余项：
  - “有效”路径的 PG 测试中，具名复核读取用替身；现有夹具链没有走到具名复核，独立品质人员也不存在（夹具只有一名同时实施措施的品质人员）。真实的具名复核链与独立决定人待补端到端测试。
  - 观察到期注意项仍按 CAPA 要求的原截止日，延长后的截止日未进“我的工作”。
  - 页面证据选择只列出当前复核与观察记录。
- D472 （原 D379，11-12 落地时与 D378 系列撞号改号）D305 试模余项（11-10）：
  - “测试含试模样件”按“该验证请求由试模带出”判断，没有逐个样件核对来源；同一请求混入非试模样件的情形未区分。
  - 准备度只对关联了受控导入模具资源的模具生效；页面登记新模具时还不能选导入资源（接口支持 `tooling_new.resource`），未关联的模具不进准备度。
  - 处置结论必填的 PG 测试用替身把请求标为来自试模；从试模一路走到开测、结果与处置的端到端链未测（现有夹具链太长）。准备度接入只有映射单测，未用带模具资源的 Build 做 PG。
  - 模具清单只按项目读取，跨项目复用同一副模具未设计（P95 未要求）。
  - 既有纯函数内核 `manufacturing/trials/handlers.py`（`ToolTrialCreate` 合同，要求已存在的模具引用，问题与批次为引用对象）未被本实现使用，也从未登记到命令管线；其合同与 P95 第 1 项（首次试模同时登记模具）不一致。集成时决定收敛或退役。
- D471 （原 D378，11-12 落地时撞号改号）11-09/11-10 受影响 PG 组合回归（20 组、1858 项，机器负载 26–39，单轮 2 小时）中 13 项失败、7 项错误。逐项归因：
  - 本次新增的接口、治具测试单独重跑全部通过（10 项）；组合运行中失败是一次确认超过 10 分钟有效期。
  - `test_definition_parent_lineage_pg.py::test_native_derivation_uses_latest_parent_in_its_actual_variant_lineage` 写死 `alembic_version == 's0_0756'`，任何更新的 head 都会失败，属既有。
  - `test_business_audience_summary.py::test_summary_cannot_expand_ancestor_audience_and_source_revoke_hides_build` 插入项目受众时重复键，单独重跑同样失败，与本次改动无关（未改受众表）。
  - 其余（我的工作、收件箱、项目集、个人偏好、变更执行 4 项、部分观察复核、企业检索 1 项）报错为开工授权时间窗、确认过期或 `indexed_as_of` 晚于 `as_of`，与高负载下的长耗时一致；本次未改这些路径。需在负载正常时于集成检查点重跑确认。
- D48 S3–S5 余项：
  - S3：Issue 停在 awaiting_verification，要接真实观察、具名复核和 T2 关闭；
  - S4：7 张表有生命周期缺口；真实外发和外部接收〔你授权〕；
  - S5：其他生效范围、其他专业分诊、爬坡反馈、知识入口；PG7 断言与 23514/409。
- D49 核对与补齐：
  - 准备度三维聚合是否已统一；
  - 日常录入和交样比设计更严（`human_recorded` 只出现在 external_wait）；交样整批接收；
  - 原领域缺口：语音输入、引用漂移、~~接口合同与设计责任人~~（11-09 随 D312 关闭）、当前制造成熟度、独立项目资料包、全库知识检索。
- D56 ✅ 按权限导出 Excel，导出内容带“AI 起草”标识（F41、C16）。（11-08，worktree `xenodochial-tharp-12e9c0`，本地提交未推送，[证据](../docs/reports/evidence/pdos-next-d56-export-20261108/README.md)）
  - 可用：项目（任务、风险与待决项、承诺、状态更新）、我的工作（四个注意项队列加本人任务、承诺）、BOM 差异（本版对上一版）、测试汇总（已选轮次的当前运行与测量值）四类导出，入口分别在项目任务“更多”、我的工作页头、BOM 版本记录、已选轮次摘要。每类都直接调用对应页面的读取函数，行与字段过滤与页面一致，不另写权限。
  - AI 标识：写入者是 AI 身份或回执带 AI 运行（AI 起草、人确认）即为“AI 起草”；人改过的字段转为人工，所以行分“AI 起草 / 部分 AI 起草 / 人工”，AI 起草的单元格带批注并在“AI 起草字段”列列出。封面写明行数与 AI 行数，文件另带隐式元数据（自定义属性 `AIGC` 等）。
  - 审计与身份：新表 `export_audits` 只追加，记导出人、范围、行数、AI 行数与单元格数、是否含 AI、文件 sha256；审计未落库不交付文件。只有具名本人能导出：服务端拒绝 AI 身份、运行与代办上下文，数据库策略同样拒绝 AI 身份写审计；`pdos_agent` 无写权限。
  - 登记：v1.1 附录 A 增“拍板表 C16、优化评估 F41 登记的操作”段，`auxiliary-operations.json` 增 `export.workbook.download`（READ、仅具名本人、4 个 GET），三份合同 sha256 同步；`openapi.json` 只增这 4 条路径。
  - 口径（用户 11-08 确认）：导出是读者本人的 READ，不经系统向外部发送，不走 T2；依据 F41“按读者权限过滤”与 C16“不需决策记录”。DC-11 §7 的客户报告外发仍是 T2，不在本操作内。
  - 迁移：占位号 `s0_0861`（down `s0_0855`），**集成时按真实 head 重排**（文件名、revision、down_revision 与快照文件名 `schema_s0_0861.py` 一起改）。11-08 集成时编号不变，down 改为 `s0_0860`；s0_0856–s0_0860 没有重定义它用到的 `category_access`、`kernel_append_only`、`scope_actor`、`scope_requester`；s0_0856 给 `tenant_administrators` 加的是管理员读取的放行策略和插入、更新的限制策略，审计读策略里“本人管理员行”的判断不受影响。
  - 验证：PG 6 项（项目导出含两种角色、私有受众与跨租户；我的工作与审计私有；AI 身份与代办上下文拒绝、审计只追加；字段级 AI 判定；BOM 差异与私有 BOM；测试汇总）；工作簿 4 项；前端 1895 项 `.mjs`、tsc、lint 0 错误；合同校验；迁移往返；浏览器亮暗两套主题走通项目、我的工作、BOM 差异导出，取回的 xlsx 与审计 sha256 一致。
  - 余项：D278–D283。
- D278 Word/PPT 客户模板导出（D185 采纳部分：8D、Gate 包、周报按客户模板导出并带“AI 起草”标识）。依赖：
  - 客户模板原件登记与版本（docx/pptx 解析按 R14 进隔离容器）；
  - 8D 的数据结构（品质问题与 CAPA 现在没有 8D 视图）、Gate 包（阶段评审包）、周报（`work.status_update`）的导出读取；
  - docx/pptx 的隐式标识写法另定；`export_audits.view` 枚举扩展要迁移。
  可复用本次的读权限调用方式、AI 判定与审计。
- D279 ✅ 11-08 随 D37 ⑤：项目导出新增“讨论与评论”表，按读者当前受众过滤（客户私有文档下的评论对无权者不导出），撤回内容只导出“已撤回”，提及标记导出为“@姓名”；PG 用例 `test_customer_private_document_comments_follow_its_audience`。原记录：讨论导出（确认稿 P41 第 7 项并入 D56）：P34 讨论与对象评论尚未实现，没有可导出的数据。
- D280 真实小Pai 运行写入的行在导出中标“AI 起草”，端到端 PG 未验证。原因是没有可复用的 `work_management` T0/T1 运行夹具（候选准备要走企业检索跟进上下文）。本次覆盖到的：真实版本行加“哪张回执算 AI”替身的字段级判定，以及真实 agent 主体识别。下次有小Pai 建任务或 BOM 候选的 PG 夹具时补一条。
- D281 〔你〕隐式元数据（自定义文档属性 `AIGC`，字段名照 GB 45438-2025 文件元数据要素）是否满足合规要求，未做合规核对。（11-08 用户已确认导出按读者本人 READ 办理、不走 T2，原第二点关闭；所有导出都带显式加隐式标识。）
- D282 ✅ 11-09（随 D98）差异计算移到 `domain/builds/configurations/bom_diff.py`，页面 `GET …/configurations/boms/{bom_id}/review` 与 Excel 导出共用；页面在 BOM 版本记录里显示增删改、用量与位号变化及规则卡，导出增加位号列。原记录：BOM 版本差异的页面视图（D98）仍未做；本次只有导出。差异计算暂放在 `domain/exports/views.py`，D98 落地时移到配置领域，由页面和导出共用。
- D283 导出审计只能由导出人本人和租户管理员经数据库策略读取，没有查看页面或接口；需要审计查看时再补（管理员页）。

<a id="automation-templates-20261109"></a>
- D71 + D190、D75、W6 ⑦ 状态更新周期 ✅ 11-09 自动化规则模板最小版（worktree `suspicious-babbage-15fcbf`，分支 `claude/suspicious-babbage-15fcbf`，本地提交未推送，[证据](../docs/reports/evidence/automation-templates-20261109/result.md)）。用户 11-09 定 [P115](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p115)（跟进规则对每个项目默认生效）、[P116](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p116)（状态更新起草的目标文本、缺失判定与周期归属）。
  - 可用能力：
    - 四条确定性跟进规则（分派未回复、承接未推进、承诺到期提醒、外部等待升级）对每个项目默认生效。
    - 规则负责人和接收人是项目负责人；结果是“要我决定”里的只读注意项，零模型。
    - 未回复与未推进分别计时，都是 1 个工作日（按周一至周五估算并标注）；事情一有进展注意项即消失；不给负责人自己升级。
    - 项目负责人可在“设置 · 自动化规则”选“项目状态更新起草”，为本人负责的项目设一个周期（每项目一条），到点由小Pai 经 Temporal→LangGraph 起草，只准备 `work.status_update.create` 一种 T1 候选，本人确认后具名发布。
    - 起草后 1 个工作日未发布显示“状态更新缺失”；周期时间与缺失状态对项目可见者开放（`GET …/project-work/status-cadence`），规则本身只有负责人可读。
    - 模板目录 `GET /v1/categories/{c}/automation-templates`。
  - 验证：
    - 纯函数测试 421 个通过（含 `test_personal_attention` 一条按新设计更新的断言）。
    - 受影响 PG 范围（attention_pg、automations/pg、work_pg、external_wait_pg）首轮 56 通过、2 跳过、5 失败；5 个失败都是缺检查点库的环境问题，补检查点库后两个摘要文件 12 个全部通过。其中新增 PG 用例 5 个。
    - 迁移 `s0_0905`、`s0_0906` 升降往返通过；合同重导出后校验通过。
    - 前端 tsc、eslint 通过；automation 相关 node 测试 53 个、全部 BFF 路由测试 277 个通过。
    - 浏览器走查：负责人“我的工作”4 条升级，亮色、暗色与 375px 暗色；设置页选“项目状态更新起草”、选项目、预填与保存草稿（暗色）。走查中发现两个新接口不在 BFF 白名单（404），已修并补测试。页面上“预览启用”返回 401，此后预览会话整体失效，同一 token 直连 API 仍正常，判断为开发模式本地会话问题，未追查；激活由 PG 覆盖，设置页 375px 未截图。
  - 迁移：占位号 `s0_0905`（down `s0_0869`）、`s0_0906`，**集成时按真实 head 重排**（11-10 第五轮集成改为 `s0_0871`、`s0_0872`）。`s0_0906` 先用 SHA-256 核对 `automation_service_start`、`assert_automation_service_run` 仍是 `s0_0840` 原文，别的分支改过这两条函数时须重新生成 `schema_s0_0906.py`。
  - 冲突风险：`my_work/attention.py` 加两个数据源（W7）；`agent/kernel/host.py` 一行（W6 ⑥、W8）；`contracts/openapi.json` 整份导出。
  - 余项：D440–D447。
- D440 跟进规则参数固定为 1 个工作日，不能按项目关闭或调参（P115 定“以后再按 B 补”）。
- D441 跟进升级只进注意项，不推送收件箱：通知管线的 SQL 丢弃小Pai 身份的非分派类通知。等 W6 ⑥ 的“小Pai 主动提及·自动化例外”，集成时处理。11-10 第五轮集成核对：W6 ⑥ 已提供规则例外的主动提及 `agent_mentions.notify(..., "agent.rule_exception", latest={"rule_owner_id": …})`，但还接不上：跟进升级是读取时算出的注意项，没有小Pai 运行上下文，也没有规则负责人（P115 每个项目默认生效）；提及要求小Pai 代一位在职的人写入且收件人不是这个人，而升级的收件人正是项目负责人本人。接入要新增按租户的发现步骤，并定“小Pai 代谁发出”，保留登记。
- D442 周期起草的候选进“要我决定”依赖 W7 D78（按运行聚合候选）；现在候选只在规则的运行记录里，负责人从规则详情打开原运行确认。
- D443 任务两个计时的时区暂用常量 `Asia/Shanghai`（任务本身不带时区），承诺和外部等待用各自记录的时区。租户工作日历（D221）接通后，`work_weekday_add` 与 `add_weekdays` 一起换成日历。11-10 第五轮集成核对：W11 的租户工作日历已合入，但接口对不上，没有切：Python 侧 `rules.add_working_days(calendar, at, days)` 要先按租户用 `service.factory(s, tenant)` 读日历，而 `status_cadence.state()` 是不带会话的纯函数；SQL 侧 `work_calendar_add(at, days)` 按会话租户读日历、不带时区参数，而跟进与模板注意项在 SQL 里写死了“按周一至周五估算”的依据和标签，换成日历后要带日历名称与版本（P117 回执口径）；`project_status_cadence` 是定义者函数，它读日历表时的 RLS 也要核对。W6 ⑥ 冷却期（D391）同理。需要单独改，保留登记。
- D444 “状态更新缺失”只出了接口；概览、项目列表、管理者驾驶舱的展示归 W6 ⑦。
- D445 受理后的小Pai 运行实际准备出状态更新候选未端到端跑过（需脚本模型夹具，真实模型回归要授权）；PG 只验证到受理绑定项目，单元测试验证守卫只放开这一种候选。
- D446 承诺到期提醒只给项目负责人；承诺人本人的到期提示不在四类分诊里，需随 W7 D38 在“承诺”页显示到期状态。
- D447 周期设置用通用规则表单，首次时点须手填含时区的 ISO 时间，没有“每周几、几点”的选择器。

**W10 阶段验收检查点（验证欠账；集中做，放在 W6–W9 之后）**
- D50 整仓回归：S0 之后没跑过（5603 项基于 s0_0728，现在 head 是 s0_0854）。23 项修复要在本分支的环境里复跑，并跑 make check。
- D51 阶段验收：
  - S1 完整附录 B；S2–S5 验收（附录 B 自己写着“均未执行”）；
  - 恢复性能验收：P13 暂缓至今，coverage_publication p95 4.09 秒，超过 3 秒门槛，是已知例外；
  - Temporal 目前用 SQLite 回退，不能作为正式依据；
  - 下方 M2 行写“出口待 B7/B8”，与 M1 行“B8 已关闭”矛盾，要改；
  - 确认定时任务 `pdos-s3-s5` 是否还在跑。
- D249 真实评测环境的缺口（W1 中 6 题、4 个上下文格因此没跑或没跑完）：
  - HTTP 评测运行时没接三处端口（需求准备快照、专业资格），PUR-09、QUA-09、QUA-10 受阻；测试夹具在进程内接了，评测运行时没有；
  - ENG-10、PRD-10 的父题没有形成子题需要的引用；CTX-06、CTX-08、CTX-10、CTX-11 前置受阻；
  - 模型配置是租户级的，评测切换 F 时预览里的小Pai 一起受影响；评测与预览共用库、租户和命名空间（D59）。
  下次真实回归（D129）前补齐。

**W11 试点上线准备（所有材料都没考虑到的方面；可与 W6–W9 并行，真人试点前必须完成）**
- **首版 MVP 候选预检（2026-11-07）**：暂以 P27 的小Pai起草 → 本人确认保存 → G0 具名批准 → 项目驾驶舱为首发候选范围。已提交源码 `8e28a81f` 在独立合成环境通过锁定依赖的前端生产构建（Node 22、pnpm 11.16.0）、前端 64 项、后端 89 项及恢复前后的 Web/API 冒烟。空库升到 `s0_0854` 通过，完整降级在 `s0_0784` 的确认约束校验处停止；已把合成库备份恢复到空库并重跑冒烟。首批使用者和托管目标待定（D210）；托管试点仍须补正式登录（D214）及目标环境恢复与运行验证。11-07 未提交修复未纳入本候选，本次验证未调用真实模型。[检查记录](../docs/reports/evidence/pdos-next-mvp-20261107/checks.txt)
  - **11-07 代码审查修复**：小Pai 的 G0 提交候选按实际提案版本登记并由负责人一次确认，具名人工回执详情绑定候选事件；修复预载 RFQ 行结构和无效 `skill.load` 参数、手动建提案刷新后的原请求恢复、运行租约占用业务连接池，以及旧输出预算绑定的兼容。定向后端 211 项无库、38 项独立 PostgreSQL、前端 46 项及锁定依赖的生产构建通过。已有运行只有在历史路由摘要仍匹配当前服务商配置时才沿用原预算。真实模型和目标环境联验仍待完成。[回归证据](../docs/reports/evidence/pdos-next-mvp-20261107/review-fixes.txt)
- D210 〔你〕部署方案：阿里云各服务的规格、网络、域名、TLS，以及 ICP 备案（原工程用过 pdos.beepump.net，要核对备案主体是否覆盖新的 ECS）。拍板表 B15 推荐“单机 compose 放内网”，与阿里云计划不一致，要一起定（D88）。
- D211 备份与恢复（11-08 本地部分完成，未提交云上操作，[手册](../docs/runbooks/backup-and-restore.md)，[证据](../docs/reports/evidence/w11-ops-20261108/README.md)）：
  - ✅ 工具 `tools/backup_restore.py`（备份 / 恢复到新标记环境 / 核对 / 外发审计 / 清理）；本地按 AT-47 演练通过；
  - 〔你〕RPO/RTO 建议 ≤24h / ≤4h、备份保留天数；
  - 等 D210：RDS 自动备份与按时间点恢复、OSS 版本控制、KMS 删除保护的具体规格，以及试点前云上实演一次恢复。
- D212 发布与回滚（11-08 手册完成，[手册](../docs/runbooks/release-and-rollback.md)）：✅ 迁移前快照 → 迁移 → 冒烟 → 回滚；工作流改动必须用 patch，回放检查工具 `tools/workflow_replay_check.py` 及测试（含“记下 patch 标记后回滚旧代码会失败”）；`X-Real-IP` 写法。〔你〕通知提前量与维护窗口；服务器命令等 D210。
- D213 监控告警与值班（11-08 实现，[手册](../docs/runbooks/monitoring-and-on-call.md)）：✅ 探活、错误率（`/ops/metrics`，令牌开关）、队列积压（迁移 `s0_0867`（分支上占位号 `s0_0879`，11-09 集成时改号）的 `ops_health_counters` + Temporal 队列）、模型失败率；探针 `pdos_next.ops.probe`。等 D64：钉钉群机器人地址与密钥；〔你〕阈值终值、值班人与响应时限。
- D346 ✅ 11-09 realm 改为 `pdos-next`；旧版没装上 schema 的环境，下次 `start` 时补装，`status` 显示是否已装（[证据](../docs/reports/evidence/w11-ops-20261109/README.md)）。
- D347 ✅ 11-10 AT-47 演练链补上测试结果一环：工程配置 → 测试结果（`test.results.import`，结果通过）→ 制造发布 → 固定该测试运行的发布包 → 决定 → 交接；恢复后测试结果页逐页与备份时刻一致；未补回签发方配置时，专业权威显示“签发方不可用”，演练逐项断言（[证据](../docs/reports/evidence/w11-ops-20261109/README.md)）。
- D348 ✅ 11-09 收到 SIGTERM/SIGINT 后的停机办法（可重入）：
  - 立即停止取任务和事件投递；
  - 在途 Activity 有 `PDOS_WORKER_SHUTDOWN_GRACE_SECONDS`（默认 60）秒跑完，到时取消，再最多等 15 秒；
  - 仍不结束的放弃，进程以退出码 3 结束，由 Temporal 超时后重试；
  - 发布手册第 4 节已更新（[证据](../docs/reports/evidence/w11-ops-20261109/README.md)）。
- D349 ✅ 11-09 Worker 的 `/ops/metrics`：
  - 与 API 同口径，用同一个 `PDOS_METRICS_TOKEN`，没有令牌时不开监听；
  - Activity 按结果计数（拦截器）；
  - 探针可选读取 Worker：探活，以及 Activity 失败率（警告）；
  - 监控手册 §2.1 已更新（[证据](../docs/reports/evidence/w11-ops-20261109/README.md)）。
- D350 主机 / RDS 指标与云监控告警随 D210。
- D214 ✅ 11-07 真人登录（与 D86、D192 一起做，本地提交、未推送，[结果与证据](../docs/reports/evidence/pdos-next-sign-in-20261107/result.md)）：
  - 你选“密码 + 限流”（11-07）；钉钉扫码等 D64；
  - 登录签发带空闲超时的会话（7 天有效、空闲 12 小时失效），Web 只放在 HttpOnly cookie；同一登录名 15 分钟内失败 5 次、同一来源 30 次即暂停；管理员可强制下线，本人可退出；
  - 迁移 `s0_0856_human_sign_in`（接 `s0_0855`；分支上原为 `s0_0855` 接 `s0_0854`，11-08 集成时因主线 M1 已占 `s0_0855` 改号）；登录前只走认证角色的专用函数，应用角色读不到口令哈希和链接哈希，Agent 角色零权限；
  - 租户开通脚本 `tools/tenant_provision.py`：建首个管理员、首个品类和 72 小时邀请链接，只在本地带标记的合成环境演示；生产开通要等 D210 并另行授权；
  - 前端 `/login`、`/invite` 和设置里的“账户与邀请”；本地浏览器走通登录、邀请、停用；
  - 验证：账户边界 11 项、全表守卫 90 项、迁移往返、契约校验、BFF 8 项与全部 `.mjs` 前端测试、typecheck/lint 通过；
  - 余项：~~停用时“未结事项交项目负责人”归 W6（P56 交接）~~ ✅ 11-08 随 D37 ⑤ 接上（停用即给负责人发待接卡片，P99）；反向代理要设 `X-Real-IP`（随 D210/D212）；首次登录告知归 D217。
  - 11-08 已合并进本地集成分支 `claude/frosty-villani-38f085`（未推送）：迁移改为 `s0_0856`，本项发现的两个既有问题由 D258、D259 改为 D260、D261（见 W4 末尾的集成记录）。
- D215 ✅ 11-07（已本地提交，未推送）过期原件定时重扫；生产扫描档与病毒库更新只写进[运行手册](../docs/runbooks/original-file-scanning.md)，未做任何生产操作，执行前仍须授权：
  - 规则不变：扫描通过的回执仍只有 24 小时有效，过期或扫描配置变化后照旧不能下载、不能被 AI 引用；定时重扫只是续期。
  - 定时：D58 的每租户维护工作流加一项 `original_rescan`，每小时一轮。调度角色经 `original_rescan_candidates`（迁移 `s0_0858`，分支上为 `s0_0856`，11-08 集成时改号；只返回引用）列出已解析、来源有效、未隔离、当前回执为通过但已超过它自己政策的有效期，或做于当前已不使用的扫描配置（病毒库更新后）的原件；每个候选在原扫描申请人范围内重跑真实扫描判定，确认只是过期或配置变化，才经与页面“重新请求扫描”相同的 `request_scan` 提交，之后走原扫描工作流（`originals/rescan.py`）。幂等键 `rescan:{原件}:{epoch}`，每轮每租户最多 5000 条，按回执时间分页。
  - 原因可见：过期原件的安全状态在原因里加一条“已列入每小时一次的自动重新扫描”，或说明为什么不能自动重扫（原申请人已无写入权限、原件未解析）；重扫失败或检出风险按普通扫描结果记下，页面显示具体原因；前端补了这几条及扫描器超时、错误、版本不符等原先缺的中文说明（`web/src/lib/original-security.ts`）。
  - 测试：`tests/originals/test_original_rescan_pg.py` 5 例（满 24 小时前不重扫；过期后显示待重扫、提交新请求并发出扫描事件、处理中不重复提交、通过后可下载；重扫失败原因可见且不自动重复；申请人失权时显示原因；扫描器规则版本变化后续期；函数只授权调度角色、跨租户看不到）；`test_original_rescan.py` 9 例；维护工作流测试改为覆盖两项任务。受影响范围（originals、workflows、core、categories/products、上传视图与 worker 进程）841 通过、2 跳过、8 失败；8 个失败在改动前的 d730291d 上同样失败（技能登记变化、API 列表对象、ORM 与迁移比对、写死旧迁移号 `s0_0756` 的断言、受众唯一键），不由本次引起。前端该文件 12 例、eslint、tsc 无错误。迁移 0856 单步往返通过。
  - 未处理（写在手册“已知缺口”）：扫描执行时绑定或配置已变、扫描 Activity 不写结果就返回的请求，页面会一直显示“扫描处理中”，定时重扫不接手；小Pai 选资料面板的扫描标签读缓存状态，过期后仍可能显示“已记录扫描通过”。
- D216 〔你，写决策记录〕数据出境：P28/P29 允许接入任意兼容端点，客户原件可能出境。给服务商连接加“境内/境外”属性；境外服务商是否默认禁止客户原件、客户名和个人信息，由你来定。这涉及出站规则，不能自行加严。
- D217 〔你〕试点协议与个人信息告知：写明数据归属、保密、退出时的导出和删除，以及“AI 草稿不构成工程结论”；首次登录时做个人信息告知。
- D218 〔你〕试点成功与退出标准：3–5 条可观测的判据、停止条件、怎么回到原来的工作方式。开始前先用旧方法计时，作为基线（与 D191 有关）。
- D219 支持与培训：开一个钉钉支持群并承诺响应时限；每次发版写一段中文说明；按角色准备 30 分钟的上手材料（D90 只管产品内引导）。
- D220 历史资料首批导入：由人发起批量上传，指定品类和受众，走扫描和去重。先导入 50–200 份测试报告、8D、规格书，否则 RAG 的“复用历史经验”无从谈起。
- D221 ✅ 11-09 实现，本地提交，未推送（[证据](../docs/reports/evidence/w11-ops-20261109/README.md)）。用户 11-09 定：按租户管理设置办理，不进附录 A，没有 AI 档位；工厂与供应商日历分开、带版本，见[确认稿 P117](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p117)。
  - 已做：
    - 工厂日历登记法定假日、调休上班、停线；供应商日历另建，互不影响。
    - 每次保存是完整的新版本，只追加。只有租户管理员本人能写，AI 身份、代办和运行都被服务和 RLS 拒绝；成员和小Pai 只读。
    - `rules.add_working_days` 与周一至周五估算同一口径，SQL 版本是 `work_calendar_add`；`planning_snapshot` 供排期引擎用。结果回执带日历名称和版本（`calendar_name`、`calendar_revision`）。
    - 设置里新增“工作日历”页。
    - 迁移占位 `s0_0910`，接 `s0_0869`；11-10 第五轮集成改为 `s0_0870`。
  - 余项：
    - 跟进规则分支的 `business_days`、`work_weekday_add`，以及自动化规则，集成时切到本日历；
    - D36 排期接 `planning_snapshot`。
- D222 反馈进评测集：按现行规则，反馈是私人记录，审阅人看不到。建议加一个“本人选择分享给审阅人”的动作；审阅人每周把确认过的样本加入候选题集，人工定版后才进 golden。
- D223 〔你，必须在 D34 之前定〕CEHub 687 条检查项的去向。v1.1 和确认稿对它零引用；拍板表 A1② 推荐“其余条目进技能包，只作缺项提示”。其中 407 条只属于派生、JDM、翻新、OBT、变更这五类项目，而这五类还没有框架。不先定，停用旧模板目录时，这些经验会一起失去使用方。
- D224 规模化前再做（先登记）：
  - 安全合规：等保 2.0 二级与安全基线（加密、依赖漏洞扫描、密钥轮换、外部渗透）；
  - 样件与量具：金样/限度样管理（用途、签核人、有效期、借出记录）；MSA 与量具 GR&R（EOL 是 P33 的永久红线）；样件二维码标签打印（D109 的前提）；
  - 防泄密：下载水印；
  - 运营：产品使用分析（只计数，不记内容）；规模基准（20 个品类、200 个项目、2000 行 BOM、50 人）；SLA。
- D225 可选，有需要再说：
  - APQP/PPAP 客户特殊要求包（有车厂客户时）；
  - 生成式 AI 备案适用性的法务判断；
  - 对外文档的英文版；
  - 模型同名静默更新的指纹比对；
  - 零件承认书；
  - 电子签核与签字扫描件并存。

**你本人的外部动作（随时可做，可并行）**
- D60 ✅ 11-05 已迁到 `~/Developer/ai-native-R&D-platform`（经你同意：位置、只复制需要的、短暂停 Temporal）。做法是复制后核对，不是移动：
  - 不复制可重建或无用的：`web/.next`（11G）、`server/.venv`（在新位置按 `uv.lock` 重装，115 个包版本一致）、`.local` 里 70 个旧预览构建（29G）、`__pycache__`、96 个 iCloud 冲突副本（含 `.git/index 2…9`、空的 `server 2` 等；其中 12 个已被 iCloud 清成占位）；
  - 其余 12.5G 逐文件核对：83,752 项路径、类型、大小、链接一致，73,316 个文件内容哈希一致；HEAD、分支、275 行 git 状态（含未提交改动）一致，`git fsck` 无问题；
  - 本地 Temporal（61596）停机复制数据库后从新位置启动，`environment.json` 的程序路径已改，命名空间与记录保留；冒烟：合同校验、134 个无库测试、2 个 PG 文件、Next.js 与 tsc 均正常；
  - 剩余〔你〕：旧文件夹仍在桌面并继续同步 iCloud，确认新位置用着没问题后再删（删前须你同意，删后 iCloud 上的副本也随之删除，未复制的旧预览构建和缓存一并清掉）；`~/Documents/pdos-ui-linear` 断链见 D10。 原记录：把仓库迁出 iCloud 桌面目录。冲突副本还在不断产生，这一步要排在整仓重组之前。
- D61 原工程生产下线 S5：按[下线手册](../docs/runbooks/original-production-decommission.md)执行。
- D62 研究后端：授权一家商用服务商，或先恢复 searxng（A3）。
- D63 选定真实 embedding 服务商，经 T1 确认 profile 和数据类别后做 shadow 对比（P30）。
- D64 钉钉应用凭据、组织范围和账号绑定方式（P31 真实联通）。
- D65 （可选）Anthropic 路线凭据；生产前提供阿里云 KMS 凭据。
- D66 框架 v1 的内容和租户角色目录的内容；首批试点范围和反馈审阅人（RAG §16 第 5 条）。
- D67 到期提醒：22 个演示身份 11-08 到期；MiniMax 价格卡 11-18 到期，首笔真实账单要复核。
- D68 `docs/design/PDOS/` 下你最初的原件（产品空间 PDF、设计方向整合 docx、Build Centric 设计包）已在整仓重组中删除，现在只能从标签 `archive/pre-restructure-2026-11-01` 取回。是否恢复到仓库，由你定。

**NPI 框架与小Pai自主建任务设计（2026-11-01，仅文档）**：按用户“agent 可以根据品类自己创建任务，只需要遵循 NPI 的基本框架即可”，形成[设计草案 v0.2](../docs/design/2026-11-01-npi-framework-agent-task-planning-design.md)：项目模板改为 NPI 基本框架（阶段、出口成果、条件成果与红线、阶段节点），小Pai 按品类自主建立、分派与维护任务，代码执行框架检查；基线批准、阶段决定与个人承诺仍由人作出。核对发现现行模板目录混合 CEHub 三代版本（新品 81 个任务 + 15 个门禁项）。同日按用户“深化驾驶舱、项目内成员、@ 组内成员以及小Pai，参考其他项目管理软件”，形成配套[项目团队、驾驶舱与 @提及设计草案](../docs/design/2026-11-01-project-team-cockpit-mentions-design.md)：成员与角色以品类授权为前提，@小Pai 取发起人权限与档位的交集，本次读取的来源全部对串内受众可见才贴回串里；参考 Linear、Asana、Jira Rovo、Notion、飞书项目等做法。**用户 2026-11-01 一并确认 P33、P34**：原文已移入[确认稿](../docs/design/2026-10-08-pdos-next-design-confirmation.md)，v1.1 §02.1、§02.12、§03.13、§05.3、§05.4、§05.12.6、§06.5、§06.12 与附录 A 已加注（新增操作列在附录 A 表下，87 项主目录不变），合同指纹同步，`validate_contracts.py` 通过。**剩余/下一步**：未实施；按两份设计的建设项施工待用户安排；新品以外的项目类型框架、≥95% 门槛是否适用，以及 P34 实施细节（群聊 @小Pai 是否首批、评论锚定、保留期限、钉钉推送）待定。

**2026-10-31 Prompt 一等代码闭环已完成（本次授权范围）**：**可用能力**：主提示词成为独立版本化代码资产，设置页可读主提示词/技能正文与 digest；草稿登记、diff、同题 A/B、具名激活和历史回滚贯通，注册表锁与完整源码指纹防止篡改/丢失更新。新 Run 记录语义版本，旧 Run 重放不改历史；案例审阅、T0 与 RLS 绑定 Prompt，旧审阅/批准/撤销请求按新旧规范化 digest 恢复，未找到回执不盲重试。生产激活版仍为原 1.0.0，无迁移或真实模型调用。**必要证据**：76 项纯回归、57 项受影响 PG/T0（另 2 条已证实 HEAD 基线失败 deselect）、5 项离线工具、7 项 helper、10 项 SSR 通过；12 题 A/B 无新增准入失败，副本激活/回滚成功；类型、ESLint、生产构建、合同与三份复审 APPROVE。详见[实现与验证](../docs/reports/evidence/pdos-next-prompt-code-20261031/result.md)和[操作手册](../docs/runbooks/pdos-next-prompt-code.md)。**剩余边界/下一步**：A/B 仅离线控制，真实答案质量、引用与真人试点未评；10 条 HEAD 既有回放/撤回失败单列，未宣称整仓全绿；未做浏览器截图、生产激活、真实外发、部署或 push。

**2026-10-27 小Pai UI-lab 连续工作区检查点已完成（本次授权范围）**：**可用能力**：首轮与续聊统一输入，按本人×范围×会话恢复草稿；短答留在消息流，品类资料、提案、文档和表格进入主编辑区；保存后保留原会话，历史恢复消息与成果，手机逐层切换编辑/对话。真实保存提案由追加 `agent_session_bindings` 续接，通用私有成果由 `agent_work_products` 保留 AI 原文、人工追加版本、幂等与冲突恢复；当前 head 为 `s0_0824`，RLS、append-only、来源版本、T0/T1/T2 和原请求恢复保留。**必要证据**：受影响后端 67 项、前端 109 项通过，TypeScript、Ruff、生产构建、合同导出和 Impeccable 通过，正式源码 ESLint 0 errors（6 个既有 warning）；真实双标签页 v2→v3 冲突读取与草稿保留、320/390px 暗色和 900/1280px 边界已核对，迁移项目守卫实际 UPDATE/INSERT 负例均拒绝并回滚，最终代码复审 APPROVE。详见[实现、验证与边界](../docs/reports/evidence/pdos-next-pai-ui-lab-20261027/result.md)及[浏览器记录](../docs/reports/evidence/pdos-next-pai-ui-lab-20261027/browser-final.md)。**剩余边界/下一步**：普通候选手机确认和新保存提案后的浏览器续接尚缺现成合成样本，已有组件/原生模态/CSS 与 PostgreSQL/API 覆盖，后续有样本补看，不为此新增真实模型调用；无过滤 lint 仍受未跟踪备份解析错误影响，配置与备份均未改写。UI-lab 其他页面差异、模型质量、S1–S5、生产部署与真实外发不在本闭环完成声明内。

**两份小Pai设计续建（2026-10-30 UTC，本轮本地收口）**：**可用能力**：A–G/X1–X3既有能力、项目当前事实/历史、本人摘要及原六项失败修复保留；新增溢出后保留可信工作状态另开空历史会话，可移除最近两个实际延续技能，版本/启用变化明确拒绝，空选择不被默认预载补回。恢复时保留全部READ（含未引用来源）的当前权限复核。[实现与验证](../docs/reports/evidence/pdos-next-context-recovery-skills-20261030/result.md)。**必要证据**：168项纯检查另加1项夹具类型检查、60项去重PG/API、40项前端/helper及88项BFF通过，758输入生产构建、类型/Ruff/ESLint与离线合同通过；153原生输入及构建输入结束SHA不变，无迁移（head s0_0854）。按用户委托已制作52道候选题和24份合成资料；原28道HTTP检索题的正向macro recall@5为97.92%、@10为100%，4权限负向及4编号控制通过，QUA-04仍第10，[关键词证据](../docs/reports/evidence/pdos-next-keyword-query-grammar-20261029/result.md)。来源权限物化和同32768向量64次同SELECT诊断均保留，四ANN配置无稳定收益，strict及关键词默认不变，[实测](../docs/reports/evidence/pdos-next-ann-quality-performance-20261029/result.md)。CTX09/12另4项定向原生控制已通过断言，[实际状态](../docs/reports/evidence/pdos-next-context-fixture-completion-20261029/result.md)保留partial/预算停止，不重写旧24格。**剩余/下一步**：CTX-09原题仍partial，已核对为候选题绑定需修订：自然9条仅2451tokens（低于4000上限），3→6/9并非设计DoD，不能由此新增生产特性；已给出[可审阅修订候选](../docs/reports/evidence/pdos-next-ctx09-binding-audit-20261030/ctx09-revision-draft.md)与[核对证据](../docs/reports/evidence/pdos-next-ctx09-binding-audit-20261030/result.md)，未改原题/旧分数。候选题人工审阅、真实岗位题/真人试点、真实模型与embedding同题质量、长会话正确率/缓存/时延/成本尚未验。按用户要求不调用真实模型，无真实发送、推送或生产操作；不能宣布两份设计正式验收全部完成。

**小Pai上下文设计（2026-10-28，仅文档）**：按用户“上下文按主流做法优化，保证不丢失、不溢出、能聚焦，并评估安全/功能/体验取舍”，形成[设计草案 v0.1](../docs/design/2026-10-28-xiaopai-context-design.md)。对照代码列出 9 个现状问题：上一轮准备过候选、读取结果有变化或用过未登记复核器的读工具时，整轮回答不进入下一轮；运行中历史变化即 SOURCE_STALE；自加载技能不跨轮；无上下文窗口与计量；运行内工具结果只增不减；跨轮历史无体积控制等。提出分段预算、会话保留规则、工作状态、固定缩减顺序与 context_incomplete、单条结果上限与续读、缓存与可观测，分 X1（随 RAG 切片A）、X2（随切片B）、X3 三个切片。**2026-10-28 用户确认**：§13 Q1 选（a），登记为[设计确认稿 P32](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p32-会话记录按历史运行记录保留撤权才隐藏更新只标注运行内冻结历史用户-2026-10-28)，设计稿升为 v0.2，v1.1 §06.8 已加注。当前仅文档，未修改代码；`server/pdos_next/agent/kernel/conversation.py` 当日有在途修改，实施时按当时代码核对。 **切片A + X1 实施与六项修复（2026-10-28）**：可用能力——个人自由问答轻量预载与服务器“未查公司资料”标注、窗口配置与六段体积记账、历史更新保留/撤权隐藏、三轮正文与旧轮目录、运行内冻结及撤权 partial、最近两项技能延续、Anthropic 缓存标记；按用户追加授权，已修复运行详情遗漏绑定字段（保留受限查询与私有正文隔离），更新渐进披露断言及快照测试摘要推导，六项既有PG失败全部消除。必要证据——同一最终候选复用核对后的53502/pdos_test（s0_0824），79项PG/API集中回归和65项披露/执行绑定纯测试全部通过，Ruff与目标差异检查通过；定向7项与集中组重叠不累计。前轮269项纯检查、前端149项与类型/lint证据保持各自范围。[实现、最终验证与历史对照](../docs/reports/evidence/pdos-next-slice-a-x1-20261028/result.md)。剩余缺口——前轮另两项目录数量既有失败已在上述全设计续建检查点修复，真实模型及缓存命中实测按用户要求暂不调用；切片B企业检索与个人偏好、X2/X3仍待后续（11-03 注：已于 10-30 前实施，余项见 W1）。未新建库、迁移、读取.env、放宽守卫或提交推送；当前只记录预算，不宣称全局防溢出、全仓库门禁全绿或正式验收完成；旧提示/技能合同的运行恢复保留VERSION_CONFLICT守卫。

**小Pai日常问答与企业RAG设计（2026-10-27，仅文档）**：按用户确认的全岗位共用、日常问题轻量回答及向量RAG等上下文方向，已形成[实施设计草案](../docs/design/2026-10-27-xiaopai-daily-assistant-enterprise-rag-design.md)。草案细化同一Agent的权威当前事实读取、企业关键词/向量混合检索、服务器引用、检索前后权限复核、派生索引恢复和A日常问答→B企业问答→C混合检索→D岗位扩展与试点四个切片；真实embedding配置不阻塞A/B。2026-10-27 已按评审修订为 v0.2：不可信原文改由隔离只读子任务读取、主循环只收证据行；评估问题集 v0 与 jieba 全文投影前移到切片B；后台 embedding 出站单列且须管理员一次确认；召回连接权威表过滤、不复制受众名单，并补跨范围携带（I14/I22）、批量授权与 p95。**P30 已确认（用户 2026-10-27）**：日常问答范围、后台 embedding 出站须管理员一次确认 profile 与数据类别、混合检索按同题集实测决定默认三条，已登记到[设计确认稿 P30](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p30-小pai日常问答进入产品范围后台索引-embedding-出站须一次确认启用混合检索按实测决定默认用户-2026-10-27)，v1.1 §01.9/§06.9/§07.5/§07.7/I24 已加注，合同 provenance 已同步到新的 v1.1 哈希。**2026-10-28 第二轮评审修订为 v0.3（仅文档）**：关键词召回改为 OR + IDF，补停用词表与编号通道；回答依据四态标注；同 lineage 跨轮引用继承；Issue/CAPA/Change 内部记录前移到切片B；embedding 未知用量保守占账；问题集标注应命中来源并加“该查没查”题；A/B 增加时延观察目标；参考市面产品增加关系一跳扩展、快慢两档、个人偏好，以及切片E（相似历史、定时摘要）、F（核实答案、缺口报表）、G（钉钉只读入口）。用户同日确认：embedding profile 启用维持 T1；钉钉只读入口纳入，登记为[设计确认稿 P31](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p31-钉钉只读入口纳入小pai范围按提问人权限默认私发用户-2026-10-28)；P30 第1条标注细化与 R14 jieba 位置两处加注；v1.1 §01.9/§06.9/I24/R14 已加注，合同 provenance 已同步到新的 v1.1 哈希。**2026-10-28 并入体验评审为 v0.4（仅文档）**：同品类补查与背景条、资料三入口与资料比较、按任务的结果结构、“继续处理”直出复验请求候选、当场纠正、摘要四问三组、进度与结果保存、钉钉深链；首期围绕三个工作场景，外部等待、供应承诺、Build/TestRun 结构化读取前移到切片B，并增加首期验收故事；未找到/未引用的页面文案改为按范围与记录数的具体说明，确认稿 P30 与 v1.1 §01.9 第二次加注，合同 provenance 已同步新哈希。**下一步**：从切片A实施（与上下文设计切片X1同步），逐步操作说明见[实施交接](../docs/design/2026-10-28-slice-a-x1-implementation-handoff.md)；切片C的真实服务商出站仍待管理员确认 profile；切片E、G在切片B之后可与C并行。**另记**：`tools/validate_contracts.py` 仍因在途改动新增的4个 `work.stage.*` 辅助事件（事件数 90≠86）失败，与 P30 无关，留给该在途改动收口（11-03 注：已消除，合同校验通过，92 个事件）。当前仅文档，未修改代码、迁移或业务合同，未授予T0/T2资格，未改变S1–S5、生产或真实外发状态。

**2026-10-26 模型服务商界面管理检查点已完成（P29）**：页面可直接填写 API Key、Base URL 和模型名称，保存多份独立连接并通过原 T1 确认切换，刷新恢复当前选择。Key 经专用管理员接口进入 KMS/本机 Keychain，普通配置/命令/回执不存原值；保留原凭据、服务商政策身份及资格/计量守卫。180项纯后端、13项实际PG/API、8项表单和87项BFF检查通过，类型/Ruff/ESLint通过；实际预览走通 Keychain 保存、切换、刷新、切回及390px明暗表单。已清理本次合成连接和测试Key，原MiniMax仍启用，历史回执保留，无迁移或新增真实模型调用。界面实现无剩余阻塞；真实云KMS创建与新第三方服务商调用仍需对应环境权限/密钥/有效计量和资格。见[本轮证据与边界](../docs/reports/evidence/pdos-next-model-connections-ui-20261026/result.md)和[页面操作说明](../docs/runbooks/pdos-next-tenant-model-runtime.md#从页面添加与切换p29)。

**2026-10-26 基础 LLM 通用接入检查点已完成（P28）**：按用户要求开放任意 OpenAI 兼容 Chat Completions API，不限 MiniMax；模型设置可配置自定义端点/模型/版本、两种输出参数、工具/JSON Schema/JSON对象/JSON文本响应及流式开关。旧配置/路由绑定、MiniMax 与 Anthropic 原适配、凭据保护及资格/预算/出站守卫保留；164项后端、6项实际PG/API事务、7项前端及Ruff/ESLint通过，源码类型在排除既有重复生成声明后通过。合成预览API/Worker按原参数重载，原模型配置保留；无迁移或新增真实模型调用。接入实现无剩余阻塞；新服务商真实连通性与质量仍需其端点、密钥绑定、价格卡及适用资格，不能据此宣称所有服务商已真实验证。见[验证证据与边界](../docs/reports/evidence/pdos-next-openai-compatible-20261026/result.md)和[接入手册](../docs/runbooks/pdos-next-tenant-model-runtime.md)。

**S1 最小演示切片已关闭（用户指定范围，2026-10-22）**：同一合成品类提案已完成小Pai真实 MiniMax 起草 → 本人一次确认保存 → 本人提交并具名批准 G0（P27）→ 实际项目驾驶舱。保存回执 `ed39ee43` 与 G0 回执 `325a1235` 已核对；提案最终 v4，生成型号、封存定义 v1 和“便携充气泵 · S1 演示项目”，两项噪声待办由本人负责、期限 2026-11-20，驾驶舱实际可见。受影响 G0 24 项、前端 16 项、模型协议 48 项通过（另 1 跳过）；候选扩展组 5 通过/6 个已有摘要夹具失败已对照记录。演示共 7 次模型调用、含未知保守占账合计 $0.138995，未超 $1/8 次；仅本演示租户启用起草/查漏，无 T0 资格。回执、截图、验证范围及限制见[切片证据](../docs/reports/evidence/pdos-next-s1-20261022/result.md)。本切片无待批准事项；完整 S1 附录场景、M3 其他缺口与平台候选夹具修复仍保留，其余在途工作继续。

**本地预览导览（2026-10-22）**：[预览入口](http://127.0.0.1:59650/preview)复用 S1 合成账号与实际项目，按当前权限读取项目和 G0 待办，串联我的工作、驾驶舱、提案、计划及专业工作台。进展直接读取本清单当前里程碑；`/plan` 的旧 N/P/Q 底账已折叠为历史，不算当前完成率。7 项解析检查、类型/lint 与实际页面跳转、亮暗窄窗口核对通过。未增加模型调用、技能启用或业务数据；完整专业案例、全岗位小Pai接续和各阶段剩余验收仍保留。见[预览证据与恢复](../docs/reports/evidence/pdos-next-local-preview-20261022/result.md)。

**2026-10-26 专业页面接入检查点已完成**：按整个 ui-lab/platform 逐页复核正式导航，补齐 14 类专业记录列表/详情/历史及实际对象接续，制造/物料/成本固定项目并保留旧草稿与原待定请求，概览读取真实 Build；原专业办理、具名决定、发布、外部交接与反馈能力保留。发现的项目动态超时已修复，同一合成项目读取由约46秒降到约3.4秒。282项组件、234项库、50项制造恢复、24项变更契约及29项后端（含3项PG）通过；最后5项变更组件子集复核、类型/lint/Ruff/离线缓存字体构建及桌面/390px/320px明暗核对通过。详见[专业页面验证与边界](../docs/reports/evidence/pdos-next-platform-ui-20261023/professional-completion-20261026/result.md)。部分旧合成原件安全扫描失效及外部生效回执冲突继续如实保留，恢复有效来源后才能继续对应正式办理；不覆盖其他小Pai建设缺口或正式验收状态。

**完整产品 UI 设计候选（2026-10-23）**：**2026-10-25 用户已确认设计；正式功能迁移继续在建**。最新用户以列表截图再次指定直接复刻ui-lab/platform；项目目录三视图已与原稿共用展示组件，移除额外筛选/读取信息并补查看计划直达与中等宽度图标栏，30项受影响检查及类型/lint通过，见[项目页复刻](../docs/reports/evidence/pdos-next-platform-ui-20261023/project-directory-replica-20261025/result.md)。该目录复刻批次当时缺少阶段/健康度/门禁真实读集；已由下述资源与门禁功能检查点补齐，未以示例冒充。最新按用户“优化项目等图标排列”对齐正式导航17px图标列、常用项目方形标识、项目工具栏与手机排列；12项入口回归及类型/lint通过，亮暗/折叠/390px核对见[图标排列证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/icon-alignment-20261025/result.md)。最新按用户四页反馈对齐知识状态表与侧读、组织共享项目集列表/看板及批量移入/移出、项目计划三视图和紧邻文件的更多菜单、收件箱通知/聊天/真实项目关注。项目集共享范围已由用户明确确认；s0_0818 在隔离测试库及已备份合成预览副本落地，7项PG/API、62项前端、86项代理和受影响回归、类型/lint通过；真实页面创建、移入、读回及窄屏核对见[四页证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/four-page-parity-20261025/result.md)。最新按用户“参考gpt”将停止移入输入区方形图标，后台继续移入右上角菜单；个人/品类同步，原取消接口与运行恢复保留，50项相关检查及类型/lint通过，见[运行控件简化](../docs/reports/evidence/pdos-next-platform-ui-20261023/pai-controls-20261025/result.md)。最新按用户截图补回复上方可折叠处理过程：阶段摘要、灰色工具动作和实际耗时，个人/品类/历史统一，手动展开状态不被刷新覆盖；60项相关前端及类型/lint通过，实际键盘折叠/刷新保留已核对，见[可折叠过程证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/pai-progress-20261025/result.md)。最新按“对话详情不对”对照原稿改为轻量上下文/技能/关联页面，运行记录及反馈撤回单独打开；个人、品类和历史统一，54项前端及类型/lint通过，实际展开/关闭/Escape/输入保留已核对，见[对话详情修正](../docs/reports/evidence/pdos-next-platform-ui-20261023/pai-details-20261025/result.md)。本轮按用户两张小Pai截图修正正式对话正文、结果卡片、输入区、标题历史及独立编辑/保存后旁聊；真实合成提案已人工确认保存v1，普通问候真实完成。83项前端、113项后端纯检查与类型/lint通过，构建范围及截图见[小Pai对话对齐检查点](../docs/reports/evidence/pdos-next-platform-ui-20261023/pai-conversation-fidelity-20261025/result.md)。**新发现待补**：品类会话新建提案后自动重读续写的服务器上下文绑定（现有守卫拒绝）；冷恢复卡片名称及个人历史品类卡片仍有缺口，未宣称全部一致。最新按用户“更改代码做到和UI设计一样”直接重排正式导航、小Pai两栏、品类五列表及资料行、提案文档与按需旁聊、我的工作、收件箱和项目列表；品类列表补真实负责人/可读型号/自有草稿投影。215前端及最后29项子集、6实际PG、类型/lint/构建通过，桌面/390px明暗及旁聊保留输入已核对，见[正式界面忠实对齐检查点](../docs/reports/evidence/pdos-next-platform-ui-20261023/design-fidelity-20261025/result.md)。本轮仅将已覆盖主界面按原稿落代码，不抹去下述09/11/14缺口。用户“帮我补齐”后，已补连续会话历史、品类/提案AI候选独立编辑与人工修订、保存后保留同份文档/旁聊、草稿上下文、品类名称/主要场景、提案搜索状态与完整分页、紧凑问题/规格批量编辑、统一我的工作责任/承诺列表、实际NPI模板任务与阶段/日期、组织消息及个人阅读/关注/归档状态、知识列表和项目文件、手机编辑/对话切换。当前正式预览57859已备份升级0817；215前端、85代理、20实际PG检查及类型/lint/构建通过，桌面、390px与暗色已核，具体覆盖、日志、指纹和未验证范围见[差异补齐检查点](../docs/reports/evidence/pdos-next-platform-ui-20261023/parity-completion-20261025/result.md)。最新按用户确认“整个ui-lab/platform”与A方案保留原有能力，使用Impeccable将项目四标签、更多专业面板、型号与设置统一为新布局；任务/状态更新/提案查找改侧抽屉，专业维护折叠并保留输入、固定范围和保存后摘要刷新，概览动态收为可展开紧凑行，旧链接进入新面板。78项受影响检查、类型/生产构建通过，lint 0错误/6项既有警告；桌面、390px明暗、单击重开、焦点和实际页面读取已核对，见[全范围UI迁移检查点](../docs/reports/evidence/pdos-next-platform-ui-20261023/full-replica-20261025/result.md)。**2026-10-25 资源与门禁功能检查点已完成**：当前/候选A/B实际资源冲突与原承诺影响比较、连续计划修订及历史保留、显式阶段模板、任务里程碑、具名基线批准/固定评审/阶段决定已接入新UI；目录、概览、计划与门禁共用真实健康度及专业签核读集，缺失和失效如实待核对。s0_0819–0822 已在核对并备份的隔离测试与合成预览库落地；60项集中回归、6项增量实库联验（含重叠）、68项前端及最后17项子集复核、类型/Ruff/构建通过，lint 0错误/6项既有警告。实际页面走通冲突2→0、计划v1→v2、基线/评审/具名决定推进至设计、原请求恢复及390px明暗/比较表局部滚动；范围、指纹和证据见[资源与门禁检查点](../docs/reports/evidence/pdos-next-platform-ui-20261023/domain-completion-20261025/result.md)。本轮范围无剩余实现阻塞；真实业务材料、其他专业域逐域写入与权限矩阵、完整S1–S5及生产验收仍保留，不能据此标记全平台全部完成。原[14组只读审查](../docs/reports/evidence/pdos-next-platform-ui-20261023/overall-parity-review-20261025/result.md)和[前批品类/小Pai整链证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/material-pai-parity-20261025/result.md)保留。以下保留设计预览演进记录。按用户将 S1 扩展为最终全产品设计、从使用者出发参考 Linear 的要求，已提供[统一交互预览](http://localhost:57859/ui-lab/platform)与[完整设计说明](../docs/design/2026-10-23-pdos-full-product-ui-candidate.md)。经 grill-me 确认的小Pai保持独立通用聊天与页内面板，项目上下文、技能、成果、后台会话和会话管理见[小Pai修订证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/xiaopai-revision/result.md)。按本轮反馈新增[收件箱](http://localhost:57859/ui-lab/platform?view=inbox)（通知、私聊/群聊、关注动态）；我的工作收拢为待办、双向承诺和已完成；资源需求与协调融入项目的工作与计划和本人待办；[前轮工作与组织协作证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/work-organization-revision/result.md)保留其27个交互检查点。按用户最新反馈，项目集改为与项目同级的独立入口，页面提供列表/看板与新建、详情批量移入及集内项目行更换归属，侧栏保持单层；现为六个主入口，九岗位及原业务页面保留。当前13个不同交互检查点、类型/lint通过，含3项增量快照断言误报后的完整快照复核，见[项目集修订证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/project-set-list-revision/result.md)。最新按用户反馈移除“项目”页中的项目集筛选、归属列与移动控件，归类管理集中在独立项目集页面，见[简化验证](../docs/reports/evidence/pdos-next-platform-ui-20261023/project-page-simplification/result.md)。最新取消资源协调独立页面与入口，计划内资源需求与我的工作共用冲突详情、方案比较及办理结果；18项浏览器检查与类型/lint通过，含确认字段和手机单选布局修正，见[资源融入证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/resource-integration/result.md)。最新按用户反馈将项目主视图收拢为概览、任务、计划、文件，默认进入任务；任务列表/看板、新建编辑与我的工作同步，专业页收进更多；小Pai改为右下角悬浮入口并保留上下文，隐藏 Next.js 开发指示器 N，见[项目任务与悬浮入口验证](../docs/reports/evidence/pdos-next-platform-ui-20261023/project-tasks-floating-pai/result.md)。本轮按用户进一步纠正改用现有 NPI 清单的阶段任务与额外任务两类来源，直接读取任务层、交付物与要求，默认当前阶段并支持来源筛选；列表收紧为桌面40px/手机44px，额外任务与个人待办同步，见[NPI与紧凑列表验证](../docs/reports/evidence/pdos-next-platform-ui-20261023/npi-compact-tasks/result.md)。最新按用户反馈优化任务搜索位置、负责人下拉比例及页面对齐：工具栏分组、统一控件高度与箭头留白、长标题省略及焦点反馈，保留40px/44px密度；14项浏览器检查、四种宽度、明暗截图及类型/lint通过，见[任务页细节证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/task-page-polish/result.md)。最新优化产品经理的紧凑工作清单与继续提案、可搜索品类总览/共享知识和提案列表/文档视图；私有客户资料与共享知识分开，草稿修订及具名提交预览、已批准只读、对象级小Pai上下文可用，30项浏览器检查和类型/lint通过，见[产品管理细化证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/product-category-proposal/result.md)。最新补齐品类新建与竞品库、用户声音、规格字典维护：紧凑列表与侧边表单支持新增、修订、撤回/恢复和历史回看，新品类可用于提案与小Pai上下文，字典修订不改写旧提案引用；27项不同交互/布局检查（含3项文案定位误报复核）及类型/lint通过，见[品类维护证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/category-maintenance/result.md)。最新按用户反馈补齐品类名称/主要场景编辑，以及小Pai对话候选→可修订→一次确认创建→品类页；保留稳定关联、取消和重名校验，26项浏览器检查及类型/lint通过，见[品类编辑与小Pai创建证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/category-edit-pai/result.md)。最新补齐竞品、用户声音与规格字典的小Pai新增/维护，自动带入品类、资料类型、记录版本及未保存输入；候选可对话补充或直接编辑，确认后追加版本，跨页目标、过期候选、撤回恢复和旧提案引用均已核对。30项浏览器检查及类型/lint通过，见[品类资料小Pai证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/catalog-pai/result.md)。最新接通小Pai提案新建/完善，固定带入当前品类资料、原版及未保存编辑，明确确认后私有创建或追加修订；聊天改为统一紧凑摘要与按需编辑，品类共享知识改为平面资料行。20项交互检查及最终类型/lint通过，见[提案与对话精简证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/proposal-pai-dialogue/result.md)。最新按用户反馈将品类、竞品/用户声音/参数与提案的「查看与编辑」统一改为左侧独立编辑区、右侧继续对话；草稿跟随对话更新并保留手动输入，窄屏可切换，历史会话压缩为34px单行标题。17项交互/布局检查、最终类型/lint及布局扫描通过，见[独立编辑区与会话密度证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/pai-editor-workspace/result.md)。10/24最新按用户要求让品类资料/提案保存后保留双栏与原对话，已保存内容可继续编辑或对话完善，绑定刚保存的对象/版本追加修订；优化字段分组、保存阅读态、焦点与窄屏切换，见[保存后接续与编辑优化证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/pai-save-continuation-20261024/result.md)。10/24进一步将提案方案A/B并排、规格及待决问题改为紧凑行内表格，保存阅读态保持一致；补齐增删焦点与窄屏局部滚动，13项浏览器检查及类型/lint、布局扫描通过，见[提案表格编辑证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/proposal-compact-tables-20261024/result.md)。最新补齐关键规格行内删除与当前品类字典选择新增，保留单位/版本与旧引用、重复和空态提示；普通对话完善不自动加回已删除规格，13项浏览器检查及类型/lint、布局扫描通过，见[规格增删与字典选择证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/proposal-spec-picker-20261024/result.md)。最新将规格选择器改为搜索与多选，跨搜索保留选择、可选项优先、180px内部滚动、一次加入并保留单位/版本；19项浏览器检查及类型/lint、布局扫描通过，见[规格搜索多选证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/proposal-spec-multiselect-20261024/result.md)。最新在原选择器底栏加入全选搜索结果/清空已选，保留跨搜索选择与已有规格，桌面/手机不增加常态高度；14项检查、类型/lint及布局扫描通过，见[规格批量操作证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/proposal-spec-bulk-actions-20261024/result.md)。10/25整体走查统一公共标题、列表与工具栏密度，收紧本人工作/项目集/收件箱/承诺/资料行，修正侧栏高度与手机计数；保留NPI任务及小Pai保存续聊，10项DOM/交互记录、桌面/900px/390px明暗走查与类型/lint、布局扫描通过，见[整体紧凑优化证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/overall-polish-20261025/result.md)。全部合成内容，刷新重置，无真实消息发送或业务/模型调用；待用户预览，该原型轮次当时未接入正式持久服务；后续聊天与项目集接入以本段最新记录为准，阶段验收与冻结规则未变。[初版证据](../docs/reports/evidence/pdos-next-platform-ui-20261023/result.md)及早期[A/B/C方案](../docs/reports/evidence/pdos-next-s1-ui-options-20261022/result.md)保留对照。

**统一产品本地预览（2026-10-23）**：按用户纠正，[入口](http://localhost:57859/)直接进入正式产品“我的工作”，同一个演示身份沿统一导航访问项目、知识、品类/提案、设置和小Pai；已移除主入口的九案例/角色选择。使用既有独立副本中的现场反馈/变更项目与实际 Build 记录，未把不同租户案例拼接为同一履历；为该合成账号在副本中启用本品类产品管理入口，专业资格和原 S1 保留。8 项会话入口、类型/lint、实际 BFF 身份保持与首页/项目/知识/提案导航、深链刷新核对通过。小Pai已按用户开发期 MiniMax 不限额授权接通，18个注册技能启用且T0资格为0；独立Temporal/Worker/LangGraph真实问候约8秒完成，共3次调用、$0.028178，保留首次格式失败记录并修复有限重试入口。输入与图19项、前端恢复7项及类型/lint通过；空队列及未完成模块如实显示，不改变阶段验收。见[统一入口证据](../docs/reports/evidence/pdos-next-comprehensive-preview-20261022/product-mode/result.md)与[小Pai启用和恢复](../docs/reports/evidence/pdos-next-comprehensive-preview-20261022/pai-enabled/result.md)。

**GitHub 分批同步与旧代码清理（2026-10-22）**：近期功能、设计与证据按组留存，目标分支 `pdos-next/design-v1.1`；原版源码核对归档标签后移除，运行框架/golden/生产下线资产保留。验证、删除范围与同期在途改动边界见[同步记录](../docs/reports/evidence/repository-sync-20261022/result.md)。不改变业务阶段验收状态。远端为公开仓库，按用户选择只发布不含旧历史的快照：10-22 为 `codex/pdos-next-snapshot-20261022`，2026-10-31 在同一分支追加 10-30 前全部改动的快照提交，本地开发提交不推送，见[追加发布记录](../docs/reports/evidence/repository-sync-20261031/snapshot-publication.md)。

**依据**：[完整目标架构 v1.1](../docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md)（用户 2026-10-08 批准并冻结）、[设计确认稿](../docs/design/2026-10-08-pdos-next-design-confirmation.md)（K1–K9、C1–C14 已全部确认）、[执行计划](../docs/design/2026-10-07-xiaopai-product-execution-plan.md)。原工程（`server/` + `web/`）已停用归档（标签 `original-final-2026-10-08`），原 N/P/Q 65 项、Sprint、原版生产与 Q0–Q6 人工出口随之归档，下方 N/P/Q 条目只作历史记录。

| 里程碑 | 状态 | 说明 |
|---|---|---|
| M0 停用与冻结 | 进行中 | S1 代码归档、S2 数据备份、S3 停服务、S4 删除数据库容器已完成；S5 生产下线待用户按[下线手册](../docs/runbooks/original-production-decommission.md)执行；S6 义务归档、S7 外部服务已定。v1.1 已批准；AGENTS.md、DC-11 §6、设计索引、执行计划、整理稿已同步；契约 JSON 同步后提交 |
| M1 S0 整体重构 | 通过（带 1 项已知性能例外）；B0–B8 已关闭 | [P12](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p12-s0-性能出口调整用户-2026-10-10)已采用：19 条沿用通过结果；`coverage_publication` p95 4.09 秒/242 SQL（门槛 3 秒）保留为 1 项已知例外，已停止调优/采样，未重跑完整 32×30。当前冻结候选 `s0_0728` 完整后端回归 5603 通过、1 跳过，前端 673 项及类型/lint/生产构建通过；空库迁移往返、普通属主业务备份恢复与回执/事件重放、HTTP/浏览器实际登记原件→记录事实→T1 撤回→历史刷新及小Pai失能/取消链通过。自有 3 个临时库已备份停服，主测试库、共用运行时、Temporal、M3、原 STATE 与卷保留。见[最终出口与证据](../docs/reports/evidence/pdos-next-s0-20261008/final-candidate/p12-s0-closure.json)。M6 按 P3 改为同步受理 + 后台工作 ID、按 §08.11 收窄读集，在负载低于 CPU 核数的机器上与 CAPA 输入/读取、质量读取一起复测；真实模型/资格、生产启用及 M3/S1 验收另行完成。 |
| M2 小Pai 内核与公开研究 | 独立本地候选；正式出口待 B7/B8 | [候选边界](../docs/reports/evidence/pdos-next-m2-20261008/candidate-boundaries.md)：原 217 项候选通过、1 项公共 ORM 比较留至汇合，含公共撤回 6 项；106 个注册工具、12 个技能包、单小Pai 图。新增[受控调用绑定](../docs/reports/evidence/pdos-next-m2-20261008/trusted-call-binding/result.md)：85 项受影响纯测试通过，提供同 Session prepare/finish 与只读已完成恢复；0716 [独立私库证据](../docs/reports/evidence/pdos-next-m2-20261008/trusted-call-binding/private-db/result.md)已完成：76 项（29 实库、47 纯检查）和独立 graph 恢复 11 项通过。类别生命周期维护权限与公共领域接入留至 B7。真实模型调用 0 次，合成检查不授予资格。主库迁移、实际资格/领域执行与 HTTP→Temporal 接线在 B7 完成，最终候选在 B8 验证 |
| M3 品类研究到立项（S1 第一个闭环） | M3 续建已在本地汇合；标准品人工核对、平台关联、小Pai候选采用、提案内委派、RFQ行匹配、三入口G0项目承接、跨品类个人工作、指定项目首版计划接续、Worker进程恢复、租户宿主配置及默认研究/快照登记验证通过，M3 未完成 | 从冻结 `0eccfe0` 的真实 head `s0_0728` 单调续建；迁移 `166c5fa`、品类资料 `efe1454`、证据 `40f954a`、派生 `6f81c6b`、读取证明 `b02ea67`、个人品类对话 `ad6aad1`、G0/生命周期 `964def4`、[立项四视图与规格比较](../docs/reports/evidence/pdos-next-m3-20261010/proposal-views/result.md) `fe20b87`、[共享与事实撤回](../docs/reports/evidence/pdos-next-m3-20261010/proposal-sharing/result.md) `92fd7e3` 已登记。新增[定义条目/完整续版/三方核对](../docs/reports/evidence/pdos-next-m3-20261010/definition-items/result.md)：稳定条目版本、追加移除、实际读取与撤回、保真继承和变体父链；真实迁移0753–0756往返、最终200实库、251纯检查（受影响13项复验与其重叠）、52不同前端、类型/lint/最终构建及实际手机/桌面亮暗恢复通过。定义条目检查点已冻结 `933e011`；新增[单边规格一致性](../docs/reports/evidence/pdos-next-m3-20261010/spec-bounds/result.md)：0757精确往返、139实库及最终比较7项复验、491纯检查、60前端、最终构建和实际页面响应丢失恢复通过；未给端点保持为空。单边规格已冻结 `4fbd8ae`；[真实原件版本绑定](../docs/reports/evidence/pdos-next-m3-20261010/original-binding/result.md)另有27实库/195纯检查通过，绑定实际挂载版本并保留扫描和签约守卫。原件绑定已冻结 `8c8c516`；新增[隔离定位分页与覆盖基础](../docs/reports/evidence/pdos-next-m3-20261010/extract-pages/result.md)，新读取版本2、247项检查及27实库通过。新增[隔离抽取作业派发与恢复](../docs/reports/evidence/pdos-next-m3-20261010/extract-dispatch/result.md)：`evidence.extract` 真实派发隔离子任务、行结构须由实际加载技能声明且登记于服务器行注册表、宿主账本逐字核对引文并计算覆盖、未解析原件明确 `source_not_parsed`、子任务检查点崩溃恢复与技能内容钉住、结算结果对当前固定来源重验后精确重放；9 项纯检查、5 项实库、215 项定向及 1526 项全量回归通过。新增[失败原件解析库存](../docs/reports/evidence/pdos-next-m3-20261010/parse-inventory/result.md)：迁移 `s0_0758` 落 `uploaded_originals.parse_manifest`（真实往返与约束正负例），解析器声明全部检查位置（文本行/PDF页/XLSX单元格）经隔离协议入 seal，覆盖精确区分已知/未知（PARTIAL_TEXT 不再整体未知），并修复 `page:`/`cell:` 引文定位文本核对缺口；隔离解析容器镜像按现行源码重建重钉；6 项纯检查、4 项实库、93 项定向及 1530 项全量回归通过（覆盖 `d4b864e` 前端导航提交，无后端重叠）。新增[抽取 Claim 消费证明](../docs/reports/evidence/pdos-next-m3-20261010/extraction-consumption/result.md)：AI 的 `extracted` Claim 引用客户原件时必须以 `extraction_ref={call_id,row_index}` 消费本 Run 已结算 `evidence.extract` 的已核对行，引文逐字一致、内容等于行字段唯一投影、可用性等于行派生值、行内读取调用逐条复核；注册文档与快照保持既有路径零影响（95 项回归确认）；4 项纯检查、8 项实库、161 项定向及 1542 项全量回归通过。新增[标准品人工核对闭环](../docs/reports/evidence/pdos-next-m3-20261015/standard-match/result.md)：品类主页选择型号与客户规格，按实际已发布定义/字典版本/单位/工况逐项核对；未知不补造、部分重叠不判满足、来源撤回及草稿不可冒充可用标准品，修改或失败不沿用旧结果，可回查实际型号，不创建提案/项目。100项定向回归+1项补充检查、19项BFF、类型/lint/生产构建、桌面亮色/320px暗色与失败重试通过；本机单型号/单规格20次读取p95 485.32ms且业务记录数不变，无新增迁移或攻防；B8汇合读取模块33项通过，扩展组68项通过后主动中断、不作完整联验通过。新增[平台关联人工闭环](../docs/reports/evidence/pdos-next-m3-20261015/platform-links/result.md)：0759 落租户共用平台、按型号/变体受众过滤的追加关联与 Current；一次确认完成新建并关联/更新/解除，历史按需读取，基线可读当前平台引用；小Pai 注册读取与候选准备保留 AI 作者和本人确认。135 项受影响检查经增量复核（最终读取/技能 14 项）、22 项 BFF、类型/lint/构建、实际桌面亮色/320px 暗色与保存响应丢失后刷新原请求恢复通过；迁移往返、ORM 对齐、并发唯一编号和失败原子回滚通过，无新增重复记录。新增[小Pai候选采用与回执恢复](../docs/reports/evidence/pdos-next-m3-20261016/domain-candidates/result.md)：平台/立项提案等内容候选随运行持久保留，实际预览后本人一次确认，断线保留原请求并按真实回执恢复；0760 修复人工采用提案的 Run/确认回链，保留 AI 作者、G0 独立性及撤回守卫。49 项定向实库、27 项前端/BFF、类型/lint/最终构建与桌面亮色/320px暗色实际采用及提案跳转通过，响应丢失后刷新零二次写入，迁移真实往返通过。新增[提案内小Pai委派](../docs/reports/evidence/pdos-next-m3-20261016/proposal-pai/result.md)：提案页可直接委派起草/抽取/查漏，服务器绑定真实提案与原件，历史按本人/提案过滤并重验当前受众；原委派响应丢失后刷新零自动派发，人工重试返回同一作业，明确拒绝释放编辑。23 个不同实库病例（首轮22通过/1预期误写后定向复核通过）、38项前端/BFF、类型/lint/最终构建及实际桌面/320px亮暗恢复通过；关闭工作流时如实显示受理待执行，模型调用0。新增[RFQ抽取行自动匹配](../docs/reports/evidence/pdos-next-m3-20261016/rfq-match/result.md)：注册 `calc.spec_compare` v3 消费本 Run 已结算并重验的 RFQ 行，保留原值/单位/工况/单边界，以固定参数引用或唯一精确字典键名映射并核对指定已发布共享型号；歧义/缺项/非规格要求不误报整体满足，保留原覆盖/失败与代码统计。94项纯检查、26项实库及最后3项重叠增量复验通过；原调用重放零新增业务/模型意图，字典或来源变化拒绝旧结果，无新增迁移/前端/重复攻防。新增[三入口G0到项目承接](../docs/reports/evidence/pdos-next-m3-20261016/g0-handoff/result.md)：客户/自主新品/派生变体按固定提交显式确认新身份，批准后读取实际具名决定、型号/变体、封存定义v1、项目与任务/风险并进入驾驶舱。5项实库、41项前端/BFF、类型/lint/最终构建及实际三入口项目跳转、读取失败重试和320px暗色通过；保存响应不确定后刷新零二次POST，原请求同回执由实库重放覆盖，浏览器二次回执对照未取得；不新增迁移/模型调用/攻防。新增[提案级私有上下文与出站绑定](../docs/reports/evidence/pdos-next-m3-20261016/proposal-context/result.md)：实际提案/条目/Claim/基线来源在受理时绑定Run，私有提案读取与注册图继续执行接通；模型发送及结果前比较元数据水位，原件间接引用保留客户资料分类，协议不足或撤回拒绝继续。最终34项实库、247项纯检查及Ruff通过；单原件水位核对56.26ms/20SQL且正文SELECT=0，单样本HTTP受理2066.77ms/34SQL、原请求重放1254.60ms/11SQL且仅1Run，不作p95结论。新增[同一运行内采用新事实与快照](../docs/reports/evidence/pdos-next-m3-20261016/context-admission/result.md)：实际T0/T1回执将本运行Claim/已登记快照原子纳入来源登记，同一注册图完成登记→采用→重读→结果，原件范围/资料分类不扩大；保存失败完整回滚、原回执重放不重复、撤回后拒绝继续。34个不同实库病例（集中33通过/1测试导入失败后该项补验通过）、200项纯检查及Ruff通过；真实模型0次，无迁移/前端/重复攻防。新增[私有提案规格对标](../docs/reports/evidence/pdos-next-m3-20261016/private-spec/result.md)：`calc.spec_compare` v4接实际Run绑定，三入口私有提案可对标共享型号/竞品，保持普通读取、字典/单位/工况和来源守卫；同一注册图读取比较后继续完成，恢复重验当前来源/内容，其他私有对象不随之开放。最终集中28项实库加原比较7项（合计35个不同病例）、74项纯检查及Ruff通过；真实模型0次，无迁移/前端/重复攻防。新增[私有基线/派生差异/平台分析](../docs/reports/evidence/pdos-next-m3-20261016/private-analysis/result.md)：按真实提案来源登记读取私有型号/变体、三方差异及明确绑定来源的BOM，提案差异同一RR快照只投影一次正文；已固定定义拒绝原地编辑，来源撤回/平台变化拒绝旧读取。0761修复品类Run携带型号来源的旧限制，保持实际来源范围和权限；迁移真实往返/ORM/普通属主及有历史时拒绝不安全降级通过。累计60个不同实库病例经增量复验、240项纯检查与Ruff通过，四轮注册图完成；私有基线单样本1127.99ms/78SQL，不作p95结论。新增[品类运行草稿写回](../docs/reports/evidence/pdos-next-m3-20261016/source-writeback/result.md)：品类提案Run消费真实型号资料，同一注册图记录Claim→采用→读回→完成；T0/T1保留实际作者/Run/本人确认，失败原子回滚、原请求恢复不重复，未绑定/撤回/待处置来源继续拒绝。0762统一命令与SQL来源解析并保留实际来源受众，真实迁移往返/ORM/普通属主/不安全降级拒绝通过；89个不同实库病例经集中与增量复验、205项纯检查及Ruff通过。新增[已绑定基线快照读取](../docs/reports/evidence/pdos-next-m3-20261016/baseline-watermarks/result.md)：明确读取已绑定发布/继承草稿时复用本次RR元数据水位，直接定义正文一次读取、上游原件/快照正文不重复加载，未绑定候选保留普通校验。43个不同实库、113项纯检查及Ruff通过，四轮私有分析/两轮规格比较注册图完成；私有发布基线单样本964.78ms/63SQL，不作p95结论。新增[个人工作与跨品类项目投影](../docs/reports/evidence/pdos-next-m3-20261016/personal-projects/result.md)：普通本人会话按当前权限一次快照批量读取项目、固定G0定义、真实计划、负责人和待办，列表完整翻页，单项目直接读取；本人个人/品类运行统一接续，读取失败可重试且不冒充空或零。10个不同实库病例及1项后端纯检查、56项前端/BFF、受影响Ruff/lint、类型及最终构建通过；实际桌面亮色/320px暗色、个人运行跨范围接续及模拟503后真实刷新恢复通过，修复项目列表窄屏和旧链接误映射。无新增迁移、业务权限或模型调用。新增[指定项目首版计划接续](../docs/reports/evidence/pdos-next-m3-20261016/project-planning/result.md)：项目列表/驾驶舱直接带原项目进入计划，普通RR直达读取不受列表截断，输入和未知保存请求按用户/型号/项目隔离并保留原请求；实际候选→一次确认应用→刷新→原驾驶舱读回2任务，独立库核对1候选/1计划/2工作包/2任务/1依赖。27项不同实库+1项后端纯检查、64项前端、受影响Ruff/lint、类型与生产构建通过；实际桌面亮色/320px暗色及读取503后刷新恢复通过。保存响应丢失浏览器拦截未生效，实际正常成功，不宣称该项浏览器通过；原回执重放和未知请求恢复由实库/组件覆盖。无新增迁移/权限/模型调用。新增[实际Worker进程恢复与离线取消](../docs/reports/evidence/pdos-next-m3-20261016/worker-process/result.md)：鉴权API真实lifespan→本地Temporal→正式Worker主入口进程→Activity/LangGraph→独立PG检查点，Worker离线期间提交回答，重启在同一Temporal工作与同一检查点线程继续；T1实际落1Claim/同回执，离线取消后重启仍取消、占用归零。2个不同进程/实库病例集中及检查点增量复验、Ruff通过，历史输入只含引用。该检查点模型/密钥/费率用合成端口注入，未获得真实资格；默认宿主配置由下述闭环补齐。自有任务均终结，共用本地Temporal已由管理脚本恢复并保留，SQLite开发历史不冒充生产恢复。新增[租户模型默认宿主接线](../docs/reports/evidence/pdos-next-m3-20261016/tenant-host/result.md)：官方阿里云KMS精确当前版本/元数据读取、租户服务商和十进制价格卡经同一服务器文件接默认API/Worker，密钥不落文件；Run钉住服务商并从所选钱包绑定额度。完全默认Worker主入口仅替换KMS/模型网络，实际提案候选→本人确认→保存及合成费用240微美元/占用归零通过，轮换显示需重绑；89项配置纯检查、30项网关/预算/配置/恢复及1项默认宿主进程检查，共120个不同病例（30实库/90纯检查）与Ruff通过。自有任务全终结，配置示例和运行手册已补；无迁移/前端/真实KMS或模型调用。新增[默认公开研究宿主与快照登记](../docs/reports/evidence/pdos-next-m3-20261016/research-host/result.md)：可选服务器research配置接Searx/隔离读取/私有作业卷，主图与研究子图各用独立PG检查点；出站重验当前Run/协议并留元数据回执，研究卷失能只阻断依赖能力。完全默认API/Worker仅替换网络传输，实际搜索→逐字台账→本人确认→1快照/同登记回执，恢复同job_id且不重跑模型，7次合成调用结算840微美元/占用归零；150项纯检查、29个不同实库病例经集中与定向复核及Ruff通过，共179项。未做研究中途进程重启或真实网络验收。新增[公开查询投影与固定研究结果](../docs/reports/evidence/pdos-next-m3-20261016/research-projection/result.md)：实际query/URL按当前绑定客户名/型号/文件名、原件/提案/已读事实做字面匹配，无命中按public、有命中按实际类别核对协议，模型请求仍用完整Run政策；服务器固定来源/台账/覆盖/失败并纠正partial状态，个人/品类/提案统一展示。21个不同实库、69个不同纯检查及24项前端，共114项经集中与增量复核通过，Ruff/lint/类型/最终构建及实际1280亮色/320px暗色、片段展开/刷新/重开原运行通过，模型调用数不变。无新迁移/真实网络/攻防，临时预览已收尾。新增[研究来源页面登记与原回执恢复](../docs/reports/evidence/pdos-next-m3-20261016/snapshot-ui/result.md)：snapshot_candidate接既有候选卡片，实际读取证明/快照重验后本人一次确认，保留AI作者/Run/回执；缺失来源和取消/失败不开放新确认。24个不同实库病例经集中与定向复核、12项前端及Ruff/lint/类型/最终构建通过；实际1280亮色登记、320px暗色提交成功后替换一次响应为503并重开同回执，各仅1次预览/保存POST、1快照/回执，模型调用数不变。未知状态卡片文案在浏览器后仅作一次文字修正并由组件/最终构建覆盖。无新迁移/真实网络/攻防，临时预览已收尾。新增[研究中途Worker接续与作业隔离](../docs/reports/evidence/pdos-next-m3-20261016/research-restart/result.md)：固定原研究调用/作业/参数计划，子图按实际回执恢复来源，不同作业同问题不共用检查点；仅编排可接续，未知模型/网络调用仍禁止盲目重发。59个不同实库、142项纯检查及Ruff经集中与增量复核通过，共201项；最终实际3个Worker/2次硬重启沿用同一Temporal工作/子图线程，搜索/网页各1次、7次合成模型调用，T1仅1快照/回执且占用归零。无迁移/前端/真实网络/攻防，本轮自有4个作业终结并保留共用运行时。新增[跨品类对象查找与连续跳转](../docs/reports/evidence/pdos-next-m3-20261016/object-search/result.md)：本人当前权限下按名称/完整ID查找项目、型号、立项提案、品类，元数据单快照读取与跨类型完整分页，打开原对象后重核权限；全局/提案页共用入口，两种快捷键分工并保留弹窗焦点，失败可重试、空结果不冒充不存在。11项实库、80项不同前端及Ruff/lint/类型/最终构建通过，共91项；实际1280亮色/320px暗色、四类跳转、独立提案继续查找、503后保留输入重试通过。首样本48.54ms/6SQL不作p95结论；浏览器零业务POST/模型调用，无迁移/权限扩展/攻防，临时预览已收尾。新增[服务商协议管理员登记](../docs/reports/evidence/pdos-next-m3-20261016/provider-agreements/result.md)：设置页接通租户共用协议读取、具名T2登记/续版/停用与原回执恢复；保留当前权限和Receipt/Audit/Outbox原子性，串行首版冲突，到期原请求仍可恢复。16项实库、75项不同前端及Ruff/类型/最终构建通过，共91项；实际正常登记/停用及成功响应丢失后重开同回执，恢复场景仅1次业务POST，无重复记录。最终1280亮色/320px暗色查看并修复复选框排版；提案空分组文案如实说明资料缺口。无迁移/真实协议/模型调用/新攻防，预览已收尾；真实材料与完整M3/S1出口仍保留。新增[租户技能启用与停用](../docs/reports/evidence/pdos-next-m3-20261016/skill-management/result.md)：十二项当前配置接T1一次确认、普通成员只读、租户共用版本冲突与原回执恢复；0763增加状态版本/回执，往返与ORM对齐且原资格事实不变。19实库、47纯执行绑定、50前端检查通过，共116项；实际正常启用/停用、320px暗色丢失响应后重开同回执且零二次写入，1280亮色/类型/lint/Ruff/构建通过。单入口20次HTTP p95 354.86ms/25SQL，不代替S1性能出口。预览已收尾，无真实模型/资格授予/新攻防；下一步补预算与资格材料办理，完整M3/S1仍保留。新增[本人模型预算闭环](../docs/reports/evidence/pdos-next-m3-20261016/budget-management/result.md)：沿原本人权限接T1建立/更换/全部停用、实际用量与分页历史及原回执恢复；0764–0765往返/ORM对齐，旧额度、用量和Run绑定保留，连续配置版本修复停用后同额度新建误回旧预算。73后端+1交互测量+52前端共126不同病例通过，最后18项重叠增量复核停用提示和旧调用结算；类型/lint/Ruff/构建及实际1280亮色/320px暗色三步操作和丢失响应重开通过，零重复分配。单入口20次HTTP p95 265.13ms/26SQL，不代替S1性能出口。预览收尾，无真实模型/支出/资格授予/新攻防；下一步资格材料和准入，完整M3/S1仍保留。新增[本人案例审阅与具名试点资格](../docs/reports/evidence/pdos-next-m3-20261016/skill-qualification/result.md)：本人私有案例批量T1登记、10–20不同案例具名T2批准/撤销、服务器试点准入根及实际技能/相关工具/模型身份绑定，严重错误暂停且仅接受之后的新审阅；实际具名资格→领域T0写入→撤销与历史回执恢复贯通。0766–0769空库往返/ORM/普通角色权限通过，原技能历史保留。139个不同后端病例经集中与增量复核、57项前端/BFF，共196项；Ruff/类型/lint/构建及实际1280亮色/320px暗色审阅、丢失响应刷新同回执和撤销通过，批准仅1次业务POST，零重复。合成预览收尾，无真实准入/资格/模型调用/外发/生产或新攻防；下一步结合真实材料恢复模型联验，完整M3/S1及正式性能/恢复出口仍保留。新增[MCP管理员准入与技能工具授权](../docs/reports/evidence/pdos-next-m3-20261016/mcp-management/result.md)：具名登记/停用、工具增补/移除、逐项授权/续期/撤销、分页历史和原回执恢复贯通，实际隔离服务消费当前工具合同绑定；新增无关工具不要求重复确认。0770真实往返/原事实保留/ORM对齐，80不同后端+57前端共137项、Ruff/类型/lint/构建及实际1280亮色/320px暗色通过；授权响应丢失刷新同回执仅1次业务POST。每操作20样本HTTP p95登记208.45ms/授权169.69ms、最多25应用SQL，不代替S1出口。自用预览收尾，真实MCP/模型/凭据解析/外发0次；下一步默认注册图MCP发现/读取桥接及获授权真实联验，自动化规则管理仍属S5，完整M3/S1未完成。新增[默认图MCP发现与隔离读取](../docs/reports/evidence/pdos-next-m3-20261016/mcp-graph/result.md)：固定注册入口按实际模型账本的已加载技能发现有效只读工具，官方SDK Streamable HTTP/Bearer接独立KMS引用与私有结果，原文只进只读子图、主循环仅收已核对行；凭据回显先脱敏，原文指令不授予权限。169个不同病例（40实库/129纯）经集中与增量通过，含完整160字符工具名；真实持久Run为3主模型+2隔离模型/1页/1派发，原父读取证明一致，合成75token归账且未授予T0资格。响应落盘中断可重建接续、未落盘待核对均保持1次网络调用，撤销时停止处理；0770保留、Ruff通过，无新迁移/前端/重复攻防。协议为进程内ASGI、模型与KMS合成、子图检查点内存，未冒充真实服务或Temporal/PostgreSQL进程恢复；主图外发与S5规则仍待后续，完整M3/S1及获授权真实联验保留。新增[中断运行核对与超时出口](../docs/reports/evidence/pdos-next-m3-20261016/run-reconciliation/result.md)：本人管理员核对、真实回执补记、预算预留释放和未知费用估算、响应丢失后读回同一追加事件；真实Temporal五分钟计时、执行三次耗尽及技术收尾临时故障后的持久重试接通，零LLM/领域/外部重发。75个不同后端病例（含2个真实Temporal）及57项前端/BFF、类型/lint/最终构建、0771普通属主精确迁移往返与ORM零差异、桌面亮色/320px暗色刷新恢复通过；浏览器仅1次POST。原目标不误标全部完成，真实模型与完整M3/S1出口保留。新增[小Pai处理过程与固定历时](../docs/reports/evidence/pdos-next-m3-20261016/process-panel/result.md)：个人/品类/提案展示实际步骤、绑定依据、提交回执及历时，三类独立分页，失败重试与终态重开恢复；完成/失败/取消记录与Run同事务，不展示模型原文或内部推理。71个不同后端与62项前端共133项检查、类型/lint/构建及桌面亮色/320px暗色通过；个人取消仅1次POST、刷新仍为同一固定历时，管理员收尾取消传参缺陷已修复。无迁移/真实模型/新攻防，完整M3/S1仍保留。新增[小Pai私有运行反馈](../docs/reports/evidence/pdos-next-m3-20261016/run-feedback/result.md)：六类问题、补充说明与实际加载方法/原运行版本绑定，当前本人权限、原子追加、并发原请求恢复和完整分页贯通，反馈不进入模型上下文或改变业务/资格。51个不同后端与66项前端共117项检查、Ruff/类型/lint/最终构建及桌面亮色/320px暗色通过；品类保存响应丢失后GET读回同一原记录，个人无模型版本保持未知，各仅1次POST。无迁移/真实模型/新攻防，预览已收尾，完整M3/S1及真实材料联验仍保留。新增[原工作续接与短记忆](../docs/reports/evidence/pdos-next-m3-20261016/run-continuation/result.md)：个人/品类/提案沿实际会话、对象和来源继续，前后Run互查，保留原目标/未完成项与可核历史摘要；同会话研究来源池复用、分页、出站重核、并发原请求恢复贯通。0772迁移真实往返、已有历史拒绝丢弃及ORM对齐；71个不同后端与67项前端共138项检查、Ruff/类型/lint/最终隔离构建通过。实际桌面亮色响应丢失后GET读回、最终320px暗色个人续接，各仅1次POST；原1Claim/回执保持，自有待执行作业取消收尾。无真实模型/新攻防，既有每Run检查点布局沿用，完整M3/S1和真实材料联验仍保留。新增[会话持久线程与追问恢复](../docs/reports/evidence/pdos-next-m3-20261016/session-thread/result.md)：按v1.1 §06.2将新Run接同会话单线程、各次工作独立存储命名空间；旧布局按原检查点恢复，不搬迁/重发。99个不同受影响病例及Ruff通过，含真实Worker三次启动接续追问、PG同线程双namespace、原检查点不变和零重复Claim；4个自有Run终结、占用归零、专用Temporal无运行中工作，0772保持，无前端/新攻防。用户明确国内MiniMax M3且没有协议，已准备[未启用联验草案](../docs/runbooks/minimax-cn-m3-validation-draft.md)，DTO/失效价格守卫核对通过；真实价格、KMS、适用数据协议/范围及对应外发授权仍待补齐，未启用真实调用或资格。新增[按技能投影资料与快照恢复](../docs/reports/evidence/pdos-next-m3-20261016/context-projection/result.md)：十二个技能声明本地上下文合同，渐进补充当前方法所需资料；快照绑定方法/内容摘要、确切读集及范围，开发测试删字段报错、生产记录原因，详情刷新可查。208不同后端经集中与增量补验、10前端共218项通过，含实际三入口完整条目、默认宿主及真实Worker恢复；类型/lint/Ruff/隔离构建与1280亮色/320暗色页面通过，查看仅GET。新过程读取20样本p95 81.72ms/最多17SQL，不代替正式S1性能；8个自有进程Run终结、占用0，0772保持，无迁移/新攻防。技能版本与digest变化不继承旧T0资格；真实MiniMax材料及完整M3/S1出口仍保留。新增[MiniMax M3原生工具与私有协议续接](../docs/reports/evidence/pdos-next-m3-20261016/minimax-wire/result.md)：按官方function合同回传结构化结果，私有思考/工具消息随调用与PG检查点保存，重启及账本重放恢复原消息；公开事件无思考片段，内部回读不充当批准，格式纳入模型资格身份。181个不同受影响病例及Ruff通过；实际默认宿主经两Worker、同Temporal任务和同检查点完成三次合成HTTP，离线答复后续接并由本人一次确认落1私有提案/回执，AI草稿来源与本人确认保留。合成150token/639微美元归账、占用0、专用Temporal空闲；0772保持，无前端/迁移/新攻防。真实模型/KMS均0，MiniMax未启用，真实价格、协议、权限及完整M3/S1出口仍保留。新增[S1集中回归保留测试适配](../docs/reports/evidence/pdos-next-s1-20261017/local-candidate/repairs.md)：五份旧测试对齐实际上下文快照、提案范围、状态事件与来源拒绝码，增加失败零残留核对，业务代码/迁移/前端不变；216个不同定向病例及Ruff通过。前两轮集中回归分别在5失败/306通过、7失败/675通过处停止，均不作完整通过；[该候选检查点](../docs/reports/evidence/pdos-next-s1-20261017/local-candidate/checkpoint.md)最终1648通过/24失败/8跳过，出现具体失败后主动停止扩展，非完整通过；其中21项共享旧快照夹具已修复并[188项定向通过](../docs/reports/evidence/pdos-next-s1-20261017/local-candidate/snapshot-fixture-fix.md)，原余3项确认消费间歇失败已于2026-10-22按[确认消费收口](../docs/reports/evidence/pdos-next-m3-20261022/confirmation-consumption/result.md)关闭：修正运行/实际披露绑定、非期限功能测试固定业务时钟，新增三入口真实过期拒绝与重新确认/原执行请求回执恢复；最终同进程34项实库及164项纯回归通过，原单独及五进程重放记录保留、不作为本次关闭依据。国内M3公开人民币分档报价已核对并补入未启用草案，账号计费/汇率/凭据/外发仍待落实。用户2026-10-17明确暂跳性能验收，本轮不运行性能采样；原标准保留，暂缓不视为通过。旧来源解析按用途继续收敛。真实KMS、协议和价格材料获得授权后再接真实模型。S2按用户2026-10-17明确授权及确认稿P13提前恢复，S1保持未验收；S3–S4仍按原顺序。三入口真实模型、实际服务商协议、真实KMS接入和实际Worker的真实模型联验、正式性能/恢复及完整M3/S1出口仍保留。真实模型调用0次，资格及完整M3/S1出口未完成。新增[跨页候选原请求恢复](../docs/reports/evidence/pdos-next-m3-20261019/confirmation-consumption/result.md)（2026-10-19）：**可用能力**：保存结果未知时可继续读取第51条以后的候选，已采用回执零POST恢复；未采用仅在原事件/命令核对后显式重放，保留原令牌及新动作锁。**必要证据**：修复前2项失败已复现，最终15项组件/载荷检查、类型、受影响lint通过，哈希及原始输出见报告；仅合成传输端口，无浏览器/BFF实链。**后续状态（10/22）**：原3项确认消费失败已按[确认消费收口](../docs/reports/evidence/pdos-next-m3-20261022/confirmation-consumption/result.md)关闭；10/19定向1过/2失败历史仍保留，本次修正旧夹具和新品类候选实际披露核对、未放宽确认或运行守卫。真实模型/KMS/资格与完整M3/S1出口继续保留，无迁移或归档工程修改。原聊天已关闭B8并登记“通过（带1项已知性能例外）”；2026-10-15 功能提交 `5ba7e39` 与 B8 以 `00f86e1` 汇合，桌面主目录已快进到该候选并保留原 UI 设计稿未提交改动，两侧证据均保留；无push/生产。新增[全局导航重组（七入口）](../docs/reports/evidence/pdos-next-m3-20261013/nav-restructure/result.md)：依用户 2026-10-13“整个产品最主要的是项目管理这一块，产品只是项目的前置部分”，全局入口改为我的工作/项目驾驶舱（跨项目经营总览+单项目驾驶舱两层）/项目列表/项目集（占位）/产品品类工作区（品类主页含立项提案小Pai入口、提案列表、知识、规格字典）/小Pai（右侧常驻栏）/知识；v1.0 遗留机会与实验等三页签按 C3 移除，活动归入型号区，品类工作台内嵌两级页签，旧链接一次性映射。全部为读视图与既有 T1/T2 入口归集，不改后端与契约，BFF 仅按既有校验样式放行 GET knowledge/parameters；该历史候选跨品类聚合为前端逐品类汇总，现已由上述个人项目投影替代；项目 timeline 实绩保持不填零。262 项前端测试、类型/lint、实际浏览器亮暗/桌面/390 与七入口整链通过，含 T1 手动建品类正例；该导航候选未含的四类对象查找和提案内小Pai已由上述闭环接通，真实模型调用仍保留 |
| M6 S2 实物与专业交接 | 多批/分批接收/多 Run 功能闭环已接入并完成合成联验；S1 与 S2 均未验收 | 按[确认稿 P13](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p13-暂缓性能验收并提前恢复-s2用户-2026-10-17)恢复建设；[项目入口](../docs/reports/evidence/pdos-next-s2-20261017/project-workbench/result.md)后新增[实物与专业链](../docs/reports/evidence/pdos-next-s2-20261017/physical-chain/result.md)：同一 Build 两 Lot 各一件样件，先接收/测试 A，部分与最终原值返回后继续接收 B，两个 Run 各自固定范围/资源/承诺/开测，全部返回及逐 Run 具名处置后才汇总请求；首次时钟、旧 Run、Lot/实际配置和消费证明保留。真实合成 API 完整链通过（主目录及固定副本为同一病例，不重复计数）；305 后端纯检查、83 前端、6 项实库补充检查及最终固定副本构建/实际页面读取通过，源码变化与覆盖限制见报告，不宣称整仓完整回归。0773–0774 迁移与历史拒绝验证已记录；临时预览已关闭，克隆停服留备份。性能暂缓，S1真实模型/资格继续保留；原3项确认消费失败已按[确认消费收口](../docs/reports/evidence/pdos-next-m3-20261022/confirmation-consumption/result.md)关闭；按 P21 已接续 S3，当前施工见 M7；S4/S5 仍按各自依赖续接。 |
| M7 S3 问题与迭代 | 根因/双专业批准/新配置/实施→本人完成→新轮实物复测与回链已贯通，正式措施履行可由实际 owner 读取；S3 未验收 | 按 P21 接续，[分批失败/根因措施/变更分析](../docs/reports/evidence/pdos-next-s3-20261017/quality-continuation/result.md)、[共享整改与订单准备](../docs/reports/evidence/pdos-next-s3-20261017/order-preparation/result.md)、[双专业批准与实际配置实施](../docs/reports/evidence/pdos-next-s3-20261017/approved-implementation/result.md)、[本人完成与新轮实物复测](../docs/reports/evidence/pdos-next-s3-20261017/actual-continuation/result.md)后新增[正式措施履行读取](../docs/reports/evidence/pdos-next-s3-20261017/formal-fulfillment/result.md)：默认启动实际接线，两项正式措施从完成锚、原批准计划/Selection共同回执、双专业批准、实施原件和本人完成逐项read/refresh，由另一具名人的真实事务读取为formal_change/applicable；Issue指针及所列九类业务/共同记录数未变。只在完整实际证明及刷新相等后清除对应待接线诊断，不从保存标签推定。真实已消费T2可空期限与共同层一致，有期限时仍核过期；默认启动不登记资格或出版人，显式owner保留。新固定候选1项合成API/实库全链及333项受影响纯检查通过；20文件lint、19文件格式通过，api.py保留原有空行差异且只交付两处启动接线，错误目录只含一条原因映射，其他共享改动排除。前序745323e的1条链/83纯检查及8992874的478后端/189前端/构建属于独立候选，不累加冒充本候选全验；跨人员原私有请求键仍不可见，实际回执关联由现存受控布尔函数核对并最终重验，原共同组和来源守卫保留；真实app-role完成锚预检通过。前两次实际尝试分别因DTO辅助错误中断及私有请求关联缺失失败，连同初始静态失败均留证，未计为通过。本例直接读措施owner，完整方法/配对适用性、具名复核独立性、完整观察与评效尚未通过；真实Rule保留新样件身份/方法/判据及原一天观察期，未创建观察、有效性或关闭，Issue仍awaiting_verification。下一步接真实观察和具名复核、有效性证据与共同T2决定/关闭；上传实施原件、跨续版未知捕获恢复保留；原3项确认消费失败已按[确认消费收口](../docs/reports/evidence/pdos-next-m3-20261022/confirmation-consumption/result.md)关闭。S1/S2/S3验收未完成、性能暂缓、真实模型/外发仍保留原边界。 |
| M8 S4 制造交付 | 制造发布/Pilot/固定包/双专业决定、固定外部移交/回执及有限例外/撤回已接通；S4 未验收 | 按 P21 及 [S4 合同](../docs/design/2026-10-17-pdos-next-s4-manufacturing-delivery-contract.md)续建。[制造发布](../docs/reports/evidence/pdos-next-s4-20261017/manufacturing-publication/result.md)、[原生 Pilot](../docs/reports/evidence/pdos-next-s4-20261017/native-pilot/result.md)、[固定包保存/续版/恢复](../docs/reports/evidence/pdos-next-s4-20261017/release-packages/result.md)后完成[受控发布政策与独立具名决定](../docs/reports/evidence/pdos-next-s4-20261017/release-policy/result.md)：可信宿主固定真实原行与当前专业发布依据，同次材料收集消费政策及有限规则；未知/不支持保留，零全 Issue 关闭/良率门槛/新增 T2 TTL。最终合成 HTTP/独立 pdos_test 验证政策→固定包明确续版→两位本人分别工程/制造 T2→同一原提交重放/尾部失败回滚→政策撤回后保留原包和两份决定并需复核；131 项精确独立拼装纯检查及归属 lint/格式通过，不累加整仓覆盖。0781 表迁移往返/metadata、0782 空期限修复往返及有历史拒绝回退已留证，失败和规范化回退修正均保留。新增[空范围修复与两专业页面联验](../docs/reports/evidence/pdos-next-s4-20261017/release-decision-browser/result.md)：发现空批次/产线会筛掉政策检查后在零批准/零确认停止，修复范围比较并使旧政策读取依据需复核；136项发布纯检查及新候选实际页面/独立pdos_test联验通过，明确核对两项实际政策检查后由两位本人分别T2，成功响应丢失→刷新零命令提交→显式重放同一决定，政策撤回后保留两版包和两份决定；原API汇总READY通过不再作为规则执行证据。8个精确归属文件另作独立HEAD拼装核对；发布前端运行输入未变，复用既有构建，专属预览/浏览器及凭据已收尾，数据库/备份保留。新增[固定外部移交与独立回执](../docs/reports/evidence/pdos-next-s4-20261017/external-handoff/result.md)：实际owner核对固定包/双决定、manifest与编号版本映射，一次共同T2原子保存授权/意图/Current，可信原件逐条记录发送/接收/生效、未知对账/部分接收/冲突，项目绑定和私有来源在inputs即核对。最终1条合成HTTP/实库全链、209后端纯检查（精确HEAD+38文件独立复核同数）、76不同前端检查及HEAD+8独立构建通过；0783实际往返/ORM/普通属主/Agent零直接权限及有历史拒绝降级通过。实际只读页面读回六原回执、桌面/320px暗色通过，后续两项后端修复以最终API覆盖，未宣称最终页面T2提交；前序失败与保留历史逐项留证，专属会话/预览/凭据已清理，数据库与备份保留。新增[有限例外、附条件发布与具名撤回](../docs/reports/evidence/pdos-next-s4-20261017/release-exceptions/result.md)：固定实际政策/包/原检查与完整范围，本人T2保存限制和风险控制，原unknown/blocked不改满足；显式续包消费仅得附条件放行，另一名获当前授权的本人追加撤回、保留原批准，无新增T2期限。216后端纯检查及精确HEAD拼装复核、114不同前端、独立构建、两条合成HTTP/实库链和实际页面本人批准/另一名本人撤回通过；成功回传丢失→刷新零提交→显式原请求同回执，0784往返/ORM/权限与有历史拒绝降级通过。46精确归属保留他人改动；两处导入换行有AST等价证据。首次构建/静态失败及HEAD既有目录provenance失配留证，未称全局合同校验通过；专属预览/凭据已收尾。无网络发送，默认无真实issuer；下一步按依赖接续S5行动任务→分派→本人承接/承诺→成果提交/验收→具名周报引用。Worker真实外发与业务协议/政策权威/资源资格/真实外部接收生效仍未授予。七个既有表生命周期库存缺口继续拒绝全局清理。S3 一天观察/评效、S1 未验收、性能暂缓及真实外发/生产边界保持。 |
| M9 S5 项目行动与个人工作 | 任务/独立承诺、G0接续、外部等待/风险、经验候选到具名规则及现场反馈正式计划、双专业批准、继任开发Build实际采用、Change独立验证与分别关闭可用；S5 未验收 | 按 P21 与 [S5合同](../docs/design/2026-10-18-pdos-next-s5-project-work-contract.md)续建。前序证据：[履行](../docs/reports/evidence/pdos-next-s5-20261018/commitment-fulfillment/result.md)、[动态](../docs/reports/evidence/pdos-next-s5-20261018/project-activity/result.md)、[项目运行](../docs/reports/evidence/pdos-next-s5-20261018/project-run-context/result.md)、[注意项](../docs/reports/evidence/pdos-next-s5-20261018/personal-attention/result.md)、[G0任务](../docs/reports/evidence/pdos-next-s5-20261018/g0-work/result.md)、[外部等待](../docs/reports/evidence/pdos-next-s5-20261018/external-wait/result.md)、[风险跟进](../docs/reports/evidence/pdos-next-s5-20261018/risk-followup/result.md)。新增[实际资源日历联验](../docs/reports/evidence/pdos-next-s5-20261018/resource-calendar/result.md)：固定采用版本、送达后时钟及资源失效均完成实库核对；[经验候选与具名规则](../docs/reports/evidence/pdos-next-s5-20261018/knowledge/result.md)：T0候选、实际结果回执、明确配置适用性、独立知识职责/资格及T2发布，续版/私有来源/失效重核保留。0799–0800真实往返、ORM零差异/有史拒退、138后端纯检查、45前端/BFF、2条最终PG链及最终构建/页面原键恢复/具名发布/双主题窄屏通过；预览及短登录收尾并新备份。新增[现场/客户反馈](../docs/reports/evidence/pdos-next-s5-20261018/field/result.md)：未知来源→具名实际配置定位→独立遏制/改善→原生Field变更草稿/固定图/双线影响→固定实际结果跟进，父版本不随处置续写。136后端纯检查、32前端/BFF、最终真实PG链及页面原键恢复/一次确认/双主题窄屏通过；0801往返与0805有史拒退、三表ORM零差异，部分尝试历史保留。新增[现场反馈正式计划与复验回链](../docs/reports/evidence/pdos-next-s5-20261018/field-selection/result.md)：未来意图经逐项T2、双专业批准进入真实配置实施，新Build/样件/Run结果回原反馈；531后端与231不同前端/BFF、类型/lint/最终构建及同病例恢复联验通过。PG7末尾测试辅助断言失败保留，不计整条pytest通过；0806–0807往返/有史拒退、来源库存、实际页面原请求同回执恢复与亮暗窄屏已核，证据范围及剩余限制见报告。新增[work技能与M9实际采用/独立验证/关闭](../docs/reports/evidence/pdos-next-m9-20261022/result.md)：补齐全部13条work命令及变更三条收尾声明，18个技能包无work/change覆盖缺口；本轮普通合成HTTP/PG整链在0813完成两项实际Lot/样件采用→新Run原值映射→独立品质T2验证→单独T2关闭，四笔共同组/关闭后原键重放与本人自验拒绝通过。0813补齐已注册两个T2的确认约束漏项，往返/六项实际正负检查与有历史拒退已核。前序82项及收尾76项技能、453项领域纯检查、81项BFF、封存M9候选构建及实际closed页面刷新/亮暗窄屏通过（同期其他会话的/plan及小Pai入口改动不在本轮覆盖）；自有预览/短登录收尾并留库/原件备份。仅限明确继任开发Build，未授予租户资格。剩余：其他实际生效范围、其他专业分诊、爬坡反馈与完整知识入口/小Pai技能接续；不以 owner 猜审批人或资格。S1/S5未验收、性能暂缓、S3观察与既有23514/409未闭合项保持。 |
| UI 已确认界面实施 | 进行中；明确项目/个人范围、固定技能手选与品类经验候选可用；真实模型复验完成，浏览器余验及领域缺口保留 | 按P15–P20/P22续接。[2026-10-23续建与证据](../docs/reports/evidence/pdos-next-ui-20261022/result.md)：手选固定技能受理/执行前重核、覆盖默认预载，个人目录隔离；品类null型号候选表单与原请求恢复。320前端/BFF、210后端检查通过，归属及540输入当前共享UI副本构建/类型/lint通过；PG后仅异常语句折行，AST一致。承诺履行/产出已核桌面亮暗与实际PG/API；新上传手选→Run、品类候选保存、会话改名/置顶/归档恢复及320px仍未完成，59573来源被浏览器明确拒绝后未重试/绕过，真实模型授权不替代该许可。用户本轮批准[本地开发MiniMax不限额](../docs/design/2026-10-23-local-development-minimax-policy.md)，真实账本/停止控制保留；0813→0814往返/守卫通过，旧预算/历史未覆盖。最终合成Run completed、一次实际模型$0.021796、零业务回执；本轮含两次未完成尝试共5次$0.063137，不算质量/资格或阶段验收。旧工具披露断言与现行合同冲突已基线复现并修订测试，字段级结构反馈已补。前序[HTML对齐](../docs/reports/evidence/pdos-next-ui-20261017/html-match/result.md)、[本人会话管理](../docs/reports/evidence/pdos-next-ui-20261018/session-presentation/result.md)与相关历史证据保留；旧知识完整manifest缺损不补造。[剩余差距](../web/design-qa.md)：阶段模板/健康度/冻结点缺服务器合同，其他专业分诊/完整通知、正式阶段评审、接口/责任人/漂移、当前制造成熟度、独立项目资料、全库知识检索及语音仍缺。当前未宣布全部UI、S1–S5验收或生产启用完成。 |

**S3–S5 自动续工（用户 2026-10-17；S3 已接续）**：按[确认稿 P21](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p21-s3s5-前置满足后自动续工用户-2026-10-17)登记本次授权。本聊天自动续工 `pdos-s3-s5` 已启用，每小时核对一次；S2 实际配置→Build/试模→多批产出/样件→具名品质接收→部分/最终测试结果的功能闭环有同候选记录/回执和必要验证证据后，自动启动 S3，并按各自依赖接续 S4/S5 的独立部分，无需再问是否开工。S2 已新增同候选多批/双 Run 功能联验记录，实际能力与覆盖见 M6；已核对记录及施工归属并接续 S3（M7），S4/S5 仍按各自依赖接续；不以合成联验改写 S1/S2 验收状态。性能暂缓沿用 P13；真实模型、出站、资格、push 与生产仍保留对应授权。开工前核对现有施工占用、文件归属与候选，公共变更/迁移/验证统一协调；条件不变时保持安静，开工/完成/失败/需用户条件才通知。

**B8 冻结与 M3 续建（用户 2026-10-10）**：先本地提交冻结当前候选，不 push；97 个大于 5 MB 的原始证据已迁入 `~/pdos-evidence-archive/`，逐个 SHA-256 校验及[路径清单](../docs/reports/evidence/archive-manifest-20261010.json)保留。B8 按[冻结源码清单](../docs/reports/evidence/pdos-next-s0-20261008/final-candidate/b8-freeze-20261010/source-manifest.json)继续余下出口，期间当前工作树不改业务代码。M3 从冻结提交另开分支、优先 iCloud 外工作树；仅在 B8 登记“通过（带 1 项已知性能例外）”后合并。续建顺序：候选迁移固化到 B8 真实 head → 两份品类种子的规格字典及品类知识/PromotionProof → `evidence.link.create`、`evidence.claim.withdraw`、`proposal.share` 身份检查 → 派生/变体接唯一 `variants.py` → 小Pai立项对话及技能包（真实模型待用户授权）→ 第一批立项视图、收紧 `project.create`、AT 场景与演示案例；原每段交 Claude 审查要求已由用户后续取消，改为 Astra 自审与必要验证。

**M2 工具下发审查（2026-10-08，仅文档）**：[按技能分组与缓存方案](../docs/design/2026-10-08-m2-skill-tool-delivery-proposal.md)已完成源码审查与离线载荷复核：主循环 106 个工具、167,596 字节；12 个技能并集仅 32 个主循环工具、6,255 字节。建议固定窄入口、按技能追加具体 schema，并保留合格协议的原生追加路径；已列出冻结 §06.3.3、可信调用证明及恢复影响。方案待评审，未实施或修改冻结架构；真实成本/时延/误选对照与正式 M2 出口仍未完成。

**S2–S5 技能包补齐（2026-10-18，用户指示“先补 S2–S5 的技能包”）**：新增 5 个技能包 `build_execution`、`quality_issue`、`test_verification`、`change_control`、`release_handover`（`server/pdos_next/agent/skill_packages/`），各含治理元数据、按注册表逐条核对的 allowed_operations、数据语义与使用原则；context-schemas.json 新增 `project` profile（与 category profile 同形，纯新增）；`default_preload` 对“已绑定项目且无提案”的运行不再预载 proposal_drafting，改为只留技能目录由 `skill.load` 决定。**可用能力**：137 个主循环工具中有技能授权的从 33 升到 98，build/npi/supply/cost/quality/test/verification/change/release/integration/engineering 全部命令现在都能经已声明方法被调用；单组可见面 12–25 个工具、24.7–66.0 KB（全量 291,811 B）。**必要证据**：tests/agent/kernel 纯检查 1467 通过、11 跳过、0 失败（新增全技能 tier 一致、project profile 绑定、禁治理与禁 T2 执行、S2–S5 覆盖、项目预载共 5 组断言）；改动文件 ruff check 通过，format 差异属既有风格未重排无关代码；未跑 DB 用例（未设 TEST_DATABASE_URL），test_checkpoint.py 缺 M2_TEST_CHECKPOINT_URL 未跑。**剩余缺口/下一步**：①**10/22 已补五类结构读取**：`build.read`、`build.lot.read`、`build.sample.read`、`quality.issue.read`、`test.run.read` 已接真实项目范围、分页、id/revision/固定关系、受理时服务器元数据出站绑定、当前RLS和旧结果恢复重验；三个相关技能升0.1.1-draft。内核纯回归1570通过，3项沙箱环境失败定向复核通过；当时1项change三命令技能声明缺口已由下述10/22补齐。最终2项实际PG读取/恢复/撤权与协议零派发、原三入口3项PG上下文回归及lint通过，源码范围和失败恢复见[读取证据](../docs/reports/evidence/pdos-next-domain-reads-20261022/result.md)。仅结构元数据，basis_status=not_assessed；请求当前版、测量/失败事件、Change/发布/移交正文读取仍缺，不推定就绪/可用或来源当前适用；②**10/22已补** `work_management` 0.1.0-draft，覆盖全部13条work命令（含计划），并补change_control三条收尾操作升0.1.1-draft；前序82项及当前76项技能检查通过，覆盖与M9实库证据见[本轮报告](../docs/reports/evidence/pdos-next-m9-20261022/result.md)，当前18个包无work/change注册命令缺口；③新包未在任何租户启用（`TenantSkillEnablement` 无行），T0 资格未授予，自动规则运行仍禁业务写入，当前只在对话或页面触发的运行里按一次确认可用；④真实模型调用 0 次，评测集与 rubric 条目待建，不构成阶段验收。

**整仓测试收集恢复（2026-10-18，用户指派）**：`pytest tests` 此前因 3 个同名测试模块（work_fulfillment/test_rules.py 与 automations/test_rules.py、work_fulfillment/test_storage.py 与 evidence_processing/test_storage.py、security_runtime/test_runtime.py 与 automations/test_runtime.py）报 import file mismatch 并 Interrupted，一条用例都跑不了；该缺陷在 HEAD 里（8fbb6dd 与首次导入），与本轮技能包无关。按仓库既有约定（88 个测试子目录原有 60 个带 `__init__.py`）给 8 个目录补包标记：work_fulfillment、evidence_processing、security_runtime、external_wait、knowledge、knowledge_pg、project_risk、change_coverage_transactions。**automations 不加**——它的 test_fulfillment_sources.py 有 `import test_trigger_sources` 同目录顶层导入，加包标记会直接 ModuleNotFoundError（已实测）。**必要证据**：整仓 `pytest tests --collect-only` 从「10089 收集 + 3 错误 + Interrupted」变为 10542 收集、0 错误；受影响纯目录 401 项通过；两个 DB 检查点目录（knowledge_pg、change_coverage_transactions）收集通过，8 项按未设 TEST_DATABASE_URL 在 fixture 阶段报错未跑，与其余 419 个 DB 用例同一形态。8 个包标记 ruff check 通过。**剩余缺口**：本次会话期间工作树又新增了 4 个无包标记的测试目录，同类撞名会复发，建议把「新测试目录带 `__init__.py`」固化为约定或加一条收集检查；tests/agent/kernel 同样无包标记（其 test_graph.py、test_transactions.py 目前靠对面有包限定才不撞），本轮未动。另有既存 141 项失败集中在 capa_link_phases、launch_plan_preview、change_capture_deadline 等 SQLAlchemy 测试替身层，不经过 agent_kernel，归属待协调，本轮未处理。

**M3 品类种子 C/D（2026-10-08，用户已确认）**：[决策口径](../docs/design/category-seeds/README.md#cd-confirmed)与两份 JSON/审阅版已同步：按用途划界、多功能泵及组合机归汽车，滑板车等兼用，自行车纳入电动/手动/CO₂；六市场为知识覆盖，各提案明确实际市场，考虑持续销售，认证负责人确认，客户额外要求挂对应提案/变体。61 个参数与 61 个测试项保持原草稿、87 条法规目录来源状态保留，JSON/审阅版及 56 条编号来源静态一致性通过，见[必要证据与剩余缺口](../docs/reports/evidence/pdos-next-m3-20261008/category-seed-cd/result.md)。手动/CO₂、搭电/补胎液及兼用场景的专用参数/测试与法规覆盖、具体配置认证适用及合规证据待专业确认；未操作数据库或授予资格，M3/S1 未判完成。

**v1.1 UI 重设计稿（2026-10-13 起，仅设计稿；v3 按用户当日指示落地使用逻辑）**：用户先后明确"主体是项目管理系统，品类开发是产品经理负责的立项前阶段"及"考虑实际用户使用逻辑与习惯，参考 Asana、Linear"。v3 据此重构：[2026-10-13-pdos-v1.1-ui-mockup.html](../docs/design/2026-10-13-pdos-v1.1-ui-mockup.html)，已登记[设计索引](../docs/design/README.md)。六个承重界面：我的工作（决定与阻塞卡 + 我的任务今日/本周/稍后可勾选 + 通知流未读分诊 + 最近访问）、品类开发（立项前漏斗与提案管道）、立项提案（一案一页七视图，G0 评审中）、项目列表（按 G1/EVT/DVT/试产分组可折叠，具名状态更新 + 更新人时间）、项目工作区（属性头：触发物/品类/负责/目标窗口/最近状态更新 + 七入口）、小Pai 对话。全局快速创建（任务/问题/样件交接/供应商承诺）与 ⌘K 命令面板（编号精确检索、直接执行命令），主动作带键盘提示；grill-me、过程面板、T1 候选与立项视图规则保持。视觉 token 沿用 UI 基线 v0.7.1，亮暗双主题与 320/390px 窄屏经无头浏览器自有隔离实例截图核对，未占用其他会话浏览器。设计稿不含业务代码、不触碰 B8 冻结；组合与资源、知识两屏未绘制，S1 实现时按 v1.1 §05.3 同一页面契约补齐。

**v3.1 交互审阅修订（2026-10-16，用户指示"先改交互问题"；仅同一份设计稿，不改业务逻辑）**：按交互审阅结果修订 9 处。（1）G0 由原稿的"3 位具名评审人会签 + 决定人"改回 v1.1 §03.14 的一名具名评审人——原写法与冻结设计及已实现的 `proposal_submissions.reviewer_id` 单值、`CheckConstraint("reviewer_id<>owner_id")` 均不符；同时写明 G0 不批预算、不冻结规格，避免评审人误读关卡份量。（2）品类页进度条原为品类级却显示单个提案状态，改为绑定"当前跟进 P-014"并提示其余提案在管道里。（3）关键规格表补"条目动作"列与逐条确认入口（当前评审人视角按权限禁用并给出原因，符合 §05.2"不显示永远可点的继续"），补"无字典版本不进对标与矩阵"规则。（4）新增"风险"视图，原七视图没有 §02.3a 要求的风险落点；待决问题补期限列与"负责/期限预填、评审人只改例外"。（5）界面不再出现 T0/T1/T2 内部词，按 §04.5 改为"一次确认"。（6）过程面板去掉 token 入/出（§09.5 不以 token 计价值），改显示耗时、写入条数与待确认候选数。（7）提案页与对话页已有常驻小Pai，不再叠加浮动入口。（8）"我的任务"写明每条都是挂对象的领域 Task、非个人清单（I11 第二套待办真值），通知流补与决定/任务的去重规则。（9）快速创建补"立项提案（经小Pai）"；竞品库补"来源 / 未知原因"列头。另把三张加宽的表包进横向滚动容器，390px 下不再裁切。亮暗双主题与 390px 已在本会话内置浏览器复核，标签闭合计数平衡，页面无横向溢出；未改业务代码、未动 B8 冻结。业务逻辑侧的审阅发现（G0 评审人单人规则在单产品经理租户下会死锁、跨品类对象缺范围根、字典外参数在立项期的处理路径、过渡期 `project.create` 人工入口与界面叙述不一致等）用户表示再想，未形成决策记录，本次不实施。

**v4 NPI 与项目管理补强（2026-10-16，用户："NPI 的阶段体现不足、项目管理、待办事项不清晰"，参照 Asana/Linear/飞书项目并按制造业 NPI 实际场景）**：同一份设计稿升到 v4，四处补强。（1）**阶段**：项目工作区属性头下加 NPI 阶段条（概念 / 计划 G1 / EVT / DVT / PVT 试产 / MP 量产，各带门禁结果与日期），新增「阶段与门禁」视图——DVT 出口条件按 v1.1 §03.7 规则判定并显示聚合结论 BLOCKED（硬阻塞 / 未知 / 有效例外分列，写明高完成度不抵消硬阻塞）、§04.11 三种成熟度（产品验证 / 制造 / 交付适用性）独立显示不合成一个分、PVT 进入条件前置可见、§03.9 冻结点与不可逆投入单列（结构冻结、开模授权、电芯长交期下单 10-18 前决定、认证送样冻结）、阶段历史具名不可改写。（2）**项目管理**：「工作与计划」补时间轴，基线 / 预测 / 承诺 / 实际四条按 §03.5 分列（承诺用菱形、冻结点用竖线、预测滑到 10-28 而对管理层的 10-24 承诺仍成立并超期显示），补工作包与责任表（分派 ≠ 承诺、WP-10 估时保持未知不虚构工时）。（3）**待办**：「我的工作」从"决定与阻塞 + 我的任务"改为按动作类型分诊——要我决定 / 要我接收 / 要我验证 / 等外部回复各带自己的时钟与对手方（接收后时钟才开始、无送达证据不认定对方响应），Task 只留在「我的任务」，对应 §02.11 四类对象不压成 Task。（4）**NPI 实物**：Builds 补模具与试模（T0/T1/T2 试次、模穴、整改、四方责任边界）、样件去向（破坏性消耗不可再分配）、PVT-P1 试产行；项目列表补健康度、下一门禁（承诺 vs 预测并列）、临近冻结点。亮暗双主题、1440 与 390px 已在本会话内置浏览器复核：阶段条窄屏自动折成两列、甘特横向滚动、各屏无横向溢出，标签闭合计数平衡（div 478 / table 27 / tr 117）。仍为设计稿：不含业务代码、不触碰 B8 冻结；组合与资源、知识两屏未绘制。

**v4.1 角色归属与主干归位（2026-10-16，用户："立项提案和品类开发是产品经理专属，产品应该还是要以项目管理为核心"）**：信息架构按此调整。侧栏主干改为 我的工作 → 项目（直接列出 4 个在办项目及其阶段，Linear/Asana 的项目脊柱）→ 组合与资源 → 知识；品类开发与立项提案移出主干，进入独立的「产品管理 · 仅产品经理」分组，顶栏标签顺序同步改为项目列表/项目工作区在前、两个 PM 屏在后并标 PM，快速创建里的立项提案同样按 PM 收窄。两个 PM 屏加角色说明：品类页写明工程/品质/生产/采购看不到品类与提案、从项目开始工作；提案页写明本案默认私有、只有负责人与具名评审人可读，项目成员看到的是项目属性里的「触发物」而非提案文档；项目列表写明立项前的品类与提案不在此显示。新增「以项目成员视角预览」开关：切换后 PM 分组与两个顶栏标签整体消失并自动落到项目列表，用来验证"对非产品经理，这就是一个项目管理系统"。此调整只改前台可见性与导航权重，不改 v1.1 §01.6 的页面契约，也不改品类为权限范围根的既有规则（品类成员权限本就决定可见性，此处是把它在界面上显性化）。亮暗双主题、1440 与 390px 已复核：窄屏折叠侧栏下项目列表项隐藏，六屏均无横向溢出，标签闭合计数平衡（div 484 / button 113 / tr 117）。

**项目列表美化（2026-10-16，用户"再美化一下项目列表"）**：该屏重做。顶部加工具条（分组：阶段/健康度/负责人 分段控件 + 筛选 + 我参与的）与右侧统计（4 个在办 · 有阻塞 1 · 有风险 1 · 待批准 1 · 正常 1），原本压在顶部的长说明并入底部一条。行信息重排为六列并用 `colgroup` + `table-layout:fixed` 统一列宽——此前各阶段分组是各自独立的表，列宽互不对齐：项目（名称为主、编号与触发物/品类为辅）、阶段（六段离散迷你进度条 概念/计划/EVT/DVT/PVT/MP，已过为绿、当前为橙带环，不是完成百分比）、健康度（色点 + 词，只有有风险/有阻塞才给一句定位原因）、负责（头像 + 姓名，原列表没有负责人）、下一门禁 / 冻结点（承诺与预测并列、预测滑期标红，临近冻结点作为红色警示副行）、最新状态更新（具名摘要 + 时间 + 下一步）。分组标题补全为 计划 · G1 启动 / EVT 工程验证 / DVT 设计验证 / PVT 试产与量产。窄屏下分组体横向滚动（表格 min-width 760px），不再把文字压成每行一个字。

**项目列表多视图（2026-10-16，用户"可以允许多视图模式"）**：工具条最左加视图切换，同一批事实三种读法。**列表**（默认，按阶段分组，上一条的六列）；**看板**：按 NPI 阶段分列（概念 / 计划 G1 / EVT / DVT / PVT 试产 / MP 量产），卡片带健康度色点、负责人、下一门禁与冻结点警示，概念与量产两列为空态并说明何时进入，明确写出卡片不能拖拽换列——阶段推进要满足出口条件并留具名决定，看板只是读法不是操作入口；**时间轴**：组合层面每个项目一行，已过阶段灰条、当前阶段橙条，门禁用菱形、冻结点用红色竖线，并点出 PRJ-0142 的 DVT 复测与 PRJ-0098 的试产在 10 月下旬争同一台架——跨项目资源冲突在组合层可见，具体取舍仍回到项目内的计划候选决定。分组按钮与列表底部说明只在列表视图显示。亮暗双主题、1440 与 390px 下三个视图均已复核：看板与时间轴窄屏横向滚动，页面无横向溢出，标签闭合计数平衡（div 544 / button 123 / span 681）。

**精简说明文字（2026-10-16，用户"减少一些功能的解释、备注"）**：说明条从 21 条减到 12 条，保留的也逐条收短。删除界面本身已经讲清楚的 9 条：我的工作的四类对象说明（分诊标签已写明）、通知去重规则、品类矩阵只读说明、提案风险说明（面板副标题已写）、工作包估时未知说明（表里已显示"未知，缺台架"）、工作与计划的四种时间说明（时间轴图例已有）、模具四方责任说明、方案对比依据说明、品类页型号说明。保留并收短的多为靠界面看不出来的规则：高完成度不抵消硬阻塞、预测滑期不改承诺、无字典版本不进对标、看板卡片不能拖拽换列、竞品口径（币种/采集时间/条件分组）、组合时间轴的台架撞车、待决问题的负责与期限预填、角色可见性四条。面板副标题与侧栏提示同步收短。无结构改动，标签闭合计数仍平衡（div 535 / td 491 / span 677），各屏渲染已复核。

**小Pai 对话与项目工作区优化（2026-10-16，用户"小Pai 页面需要优化，我想做的是对话式 agent，参考 Notion/Asana/Linear；项目界面优化"）**：按"项目界面 = 项目工作区"理解（项目列表上一轮已定稿）。**小Pai**：会话列表补状态点（运行中 / 等你确认 / 已完成）与范围、写入条数，并单列「后台委托」（竞品价格周跟踪，对应 AutomationRule）；顶部新增可改的范围选择与「已加载技能」chips（public_research / competitor_comparison / proposal_drafting + 9 个可按需加载，写明未加载不授予其写工具，对应 v1.1 §06.3.3 渐进披露），右上角「撤回本次运行」。线程里补三件此前缺失的东西：**运行中卡片**（实时步骤、已用 41 秒、停止、转后台继续，对应 Temporal 持久任务与取消释放预算）、**写入回执卡片**（写了什么、运行号、可整体撤回、直达提案，对应 ActionReceipt 与按运行撤回）、**消息级动作**（复制 / 重跑 / 运行详情）。输入区从单行输入改为带工具条的编辑器（@ 对象、/ 技能、附件、语音）加建议动作，并显式写明本次发送携带什么。**项目工作区**：属性头与项目列表同口径（健康度 + 下一门禁的承诺/预测并列、预测滑期标红），主动作从「项目设置」换成「写状态更新」（Asana status update 模式，此前列表显示状态更新却无处可写）；「现在」页把阻塞 / 待接收与交接 / 待决定三张面板合并为一张「需要办理」，用与我的工作相同的动作类型读法（要决定 / 阻塞 / 要接收 / 等外部）；右栏把小Pai 静默记录与具名状态更新合成一条「项目动态」流，并在其上放状态更新输入口。亮暗双主题、1440 与 390px 下六屏均已复核，无横向溢出，标签闭合计数平衡（div 559 / button 137 / span 712）。

**小Pai 多会话与全岗位可用（2026-10-16，用户"可以有不同的会话，就像 claude、chatgpt 一样"＋"所有用户都会用小Pai，可以从不同界面打开，自动导入相关技能包和上下文"）**：会话栏改成会话管理器——「新建对话」「搜索会话」，按 置顶 / 今天 / 过去 7 天 / 后台委托 分组（后台委托即 AutomationRule，列的是"竞品价格周跟踪 · 每周一 · 仅变动时提醒"），每条带运行状态点与范围，悬停出「…」给重命名/置顶/归档/删除，并写明删除会话不影响已写入的业务记录与回执。四个会话可真实切换，各有自己的线程：立项研究（运行中）、DVT 报告解析（等确认，两条可分别选择的 Issue 候选）、规格字典整理（已写入 3 条，带撤回）、竞品采购口径（无写入）。切换时标题、范围、已加载技能、建议动作和「本次发送携带什么」整组跟着变——这就是"从不同界面打开、自动导入相关技能包和上下文"的界面表达：品类会话载入 public_research / competitor_comparison / proposal_drafting，项目会话载入 test_report_parsing / issue_dedup / gap_check，其余标为"可按需加载"（未加载不授予其写工具，v1.1 §06.3.3）。小Pai 不随「产品管理 · 仅产品经理」分组收窄：顶栏标签与浮动入口对所有岗位保留，项目成员视角下侧栏注明"小Pai 照常可用，能读能写什么由你本人的权限和当前范围决定，不由对话给予"（§06.5 人发起仍受请求者有效范围约束）。浮动入口补 title 说明"在任意页面打开，自动带当前页面的范围与相关技能包"。亮暗双主题、1440 与 390px 六屏复核通过；窄屏下会话栏按既有响应式规则隐藏，会话名仍在面包屑可见。标签闭合平衡（div 593 / button 148 / span 722）。

**项目工作区第二轮优化（2026-10-16，用户"再帮我优化一下项目工作区"）**：上一轮只动了「现在」和属性头，这轮把几个偏薄的标签补成真内容。（1）**问题与变更**：问题表的来源精确到样件与配置（DVT-B1-L1 #07 · 定义 v0.8 + TL-05 T2 · 报告页码）并补「复验」列；变更从一行字展开为 ECR-008 的**双线影响**面板——产品线（Spec → BOM → 工程配置）与制造线（工序 → 工装 → SOP/控制计划）左右分栏，各栏把「显式依赖」与「小Pai 待核实线索」分开底色，底部是「已跨冻结点」警示（结构 ID 冻结 09-05、开模授权 09-12 在前，须走变更批准并重估模具与在途样件，列出受影响的 24 台在途样件与"客户样件：无"），动作是「提交双线批准」。（2）**评审与交接**：交接从一行改为 HO-0117 的**时钟**——验证请求建立 / 样件就绪 / 资料齐备 / 已提出交接 / 品质接收 / 承诺开测 / 实际开测 / 初步与最终结果，已发生的有具名人与时间戳，当前停在「已提出交接，时钟未开始」，未发生的写「未发生 / 未承诺」，对应 v1.1 §04.7 的十个时间点与"样件就绪 ≠ 可接收"。（3）**工程与制造准备**：此前只有制造准备矩阵，补上同名的「工程」那一半——工程配置 EC-07（定义 v0.8 / BOM v3 / 结构图纸 v0.8 / PCBA R2 / 固件 fw-0.7.3，各带负责人与状态）与接口契约（气嘴机械接口、驱动电流上限、散热边界，标出参与方与确认状态）。（4）**资料**：补引用漂移——结构图纸当前已到 v0.9 而本轮 Build 仍按 v0.8 执行，标红「引用已漂移」；BOM 标出 ECR-008 批准后将产生 v4、齐套需重算。另把 `.psub` 从仅项目列表生效改为全局，并让双线影响、门禁两栏与三种成熟度在 1080px 以下堆叠（此前窄屏被压成 125px 双列）。亮暗双主题、1440 与 390px 下八个标签页均已复核，无横向溢出，标签闭合平衡（div 624 / td 525 / span 797）。

**UI 界面决定三分法与契约补遗（2026-10-17，草稿待用户确认）**：10-13 至 10-16 八轮设计稿累积的界面决定只活在设计稿与本清单记录里，v1.1 §05 的页面契约没有它们。**可用能力**：已产出[界面决定三分法与契约补遗](../docs/design/2026-10-17-pdos-v1.1-ui-contract-addendum.md)，可供逐条确认——A 类 24 条（v1.1 已写明，实施照办不补契约，逐条标出依据节）、B 类 19 条（§05 未写但属细化，不新增对象/命令/档位、不扩范围，每条含规则/依据/判据）、C 类 6 条（改变 §05 或 §01.6 规则、扩大范围，逐条待确认并给选项：C1 信息架构改项目优先 + PM 分组、C2 项目成员视角预览开关、C3 项目健康度、C4 具名项目状态更新对象、C5 四分诊取代 §05.3 的阻塞/承诺分区、C6 小Pai 会话生命周期），另列仅演示素材（演示数据、文案、示例编号、图元与视觉选择）不构成约束。[设计确认稿](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p14-ui-重设计稿的界面决定按三分法登记草稿待用户逐条确认) §8 已加 P14 作引用条目。**必要证据**：三分法逐条对照 v1.1 §05 原文及其引用章节（§01.6、§02.11、§03.2/03.5/03.6/03.7/03.9、§04.5/04.7/04.11/04.13、§06.3.3/06.5/06.10/06.11/06.14、I03/I05/I08/I16/I17/I21/I23）；文档工作，未改业务代码、未动设计稿结构、未提交。**剩余缺口**：全稿未生效——确认前 v1.1 §05 原文仍是唯一页面契约，S1 前台只能做 A 类，C 类六条不得实施；确认后 B 类并入 §05（含 §05.3 新增"项目列表""阶段与门禁""小Pai 会话管理"三行）、C 类写成 P15 起的决策记录并同步 v1.1、补遗稿登记进设计索引。业务逻辑侧审阅发现（G0 单人评审在单产品经理租户死锁、跨品类对象缺范围根等）仍待用户再想，不在本稿范围。

**C 类六条已确认并同步（2026-10-17，用户"就按你的推荐写成 P15 起的决策记录"）**：补遗 C1–C6 按推荐逐条选定，写成[设计确认稿](../docs/design/2026-10-08-pdos-next-design-confirmation.md) **P15–P20**，并同步进 v1.1 六处：§01.6 全局主干改为"我的工作｜项目｜组合与资源｜知识"、品类与立项提案改为按权限显示的产品管理分组且默认落地屏仍是我的工作（P15）；§03.7 补项目健康度为纯规则投影、无人工字段、模型不参与、不得抵消硬阻塞或作门禁依据（P17）；§02.1 项目与工作模块新增 `ProjectStatusUpdate`、附录 A 新增 `work.status_update.create`（T1，AI 可起草不得自动发布）、§05.3 项目现在补"写状态更新"与项目动态（P18）；§05.3 我的工作改为四类动作分诊 + "我作出的承诺"第五组、阻塞作为状态标记（P19）；§05.4 补会话管理：列表/搜索/切换/重命名/置顶/归档，**不提供删除**，归档与重命名不影响 Run、ActionReceipt 与已写入记录（P20）。P16 确认"项目成员视角预览"不进产品，只留在设计稿作验证装置。补遗稿中 C1–C6 已标为已确认并保留原选项分析备查。**剩余缺口**：A 类 24 条与 B 类 19 条仍待用户确认，确认前 §05 其余部分以 v1.1 原文为准、B 类不得作为契约引用；P18 对象、命令及具名摘要已有 M9 本地闭环证据，完整活动流仍待完成；文档工作尚有未提交改动。

**B 类 19 条已确认并并入 §05（2026-10-17，用户"就按你的推荐把 B 类并进 v1.1 §05，B7 和 B9 按你说的改"）**：写成[设计确认稿](../docs/design/2026-10-08-pdos-next-design-confirmation.md) **P22**。B1 为 v1.1 §05.3 页面表新增三行（项目列表、阶段与门禁、小Pai 会话管理）；B2–B19 并入**新增的 v1.1 §05.12 界面契约补遗**，分 12.1 项目列表与视图（同源三读法、看板不可拖拽、组合层只暴露冲突、阶段进度是位置不是比例、四时间固定分四条、估时未知合法）、12.2 阶段与门禁（阶段条按模板渲染、窄屏堆叠不合并、下一阶段进入条件前置）、12.3 项目工作区（合并面板不减内容、引用已漂移且漂移不阻塞）、12.4 小Pai 会话（范围与技能可见且技能由服务器下发、携带内容可对账、转后台同一 Run、重跑是新运行、撤回受限须列未撤回项、档位三词且不显示 token）、12.5 全局入口（⌘K 不扩权）。两条按推荐修订：**B7** 删去 1080px 断点改归 [UI 基线](../docs/design/2026-08-09-ui-baseline.md)，只保留"堆叠不得合并为综合结论"；**B9** 承诺行改为"数据上不合并、显示上允许折叠"，避免承诺多时时间轴不可读。19 条均不新增对象/命令/档位。**实施先行约束**：B5（阶段条按模板渲染）与 B13（技能列表由服务器下发）最易被做成写死实现、返工代价最大。**A 类（2026-10-17，用户"不用确认直接提交即可"）**：免于逐条确认、整体认可，不改变 v1.1 文本，实施直接照办；若发现某条其实不是既有规则，按补遗 §5 移入 B 或 C 重走确认。**三类均已确认，补遗稿生效**，已登记进[设计索引](../docs/design/README.md)。**剩余缺口**：§05.12 与 P18 的对象/命令均为设计合同，前端与领域层尚未实现。

**业务逻辑设计分析与契约对齐（2026-10-17，用户“业务逻辑设计分析”→“帮我逐一确认，修复”）**：把 v1.1 与 `pdos-next` 实际代码对照了一遍。**已修两项**：① 命令登记表与代码脱节——19 个已注册操作（含 `change.selection.decide`、`quality.issue.root_cause.decide`、`quality.capa.verification.review`、`test.run.review` 四个 T2）在两份目录里都没有条目，已按实际档位、执行角色与事件补进 `contracts/auxiliary-operations.json`（18→37 条）；附录 A 的 `work.status_update.create`（P18）补进 `operations.json`（86→87 条），`project.status_updated` 补进 `events.json`（85→86 条）；`tools/validate_contracts.py` 自 a5537ff 起就因 provenance sha256 与计数过期而一直失败（并在 P18 那行 KeyError），已重新派生 provenance 并把输出计数改为按数据生成。② 档位 fail-open——`command_tools` 过去把不在 T1/T2 名单的 payload 一律当 T0，现新增显式 `T0_OPERATIONS`（19 条）与 `tier_of()`，未登记档位的命令在 `service.execute` 入口即报 `WRITE_TIER_UNREGISTERED`/`FORBIDDEN_SCOPE`，不再默认落到最宽档位。**证据**：新增 `server/tests/core/command_catalog/`（5 项通过，纯逻辑无需数据库）钉住“三档恰好划分 PAYLOADS”、“每个注册命令都在目录里且档位与事件一致”、“目录标 implemented 的必在 PAYLOADS”、“源目录校验器跑通”；`validate_contracts.py` 通过（87/86/63）；改动文件 ruff 通过。**决策**：[P23 派生入口统一到 G0](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p23-派生入口统一到-g0用户-2026-10-17按推荐)、[P24 试点期 G0 评审人必须是第二个真人](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p24-试点期-g0-评审人必须是第二个真人用户-2026-10-17按推荐)、[P25 CAPA 四个 PascalCase 事件名暂不改](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p25-capa-四个-pascalcase-事件名暂不改用户-2026-10-17按推荐)已写入确认稿，P23 同步并入 v1.1 §02.4 与附录 A 该行。**P23 已落代码**：`platform.link.create` 加“目标变体须带 G0 决定”守卫（草稿变体 preview 与提交都返回 `FORBIDDEN_SCOPE`/`variant_without_g0_decision`，不写任何关联行）；`tests/g0_fixture.py` 新增 `create_g0_variant`（派生提案→G0→真实变体身份）、`add_category_human`（同租户第三个真人，使评审人不必是 `setup.peer`）与 `published_parent`（复用派生测试里唯一那套 owner-only 合成发布 fixture）；原平台关联测试改用 G0 产生的私有变体，新增草稿变体被拒的负向测试，两项均通过。**顺带暴露**：`product.definition.publish`（规格冻结，T2）仍未实现，且 `protect_fixed_definition` 不允许把已存定义改成 `published`，所以派生提案在真实命令链上还拿不到可引用的发布父版——派生入口端到端走通的前置是先实现规格冻结，这也是 `variant.derive` 一直被当实际派生路径的原因。**服务端 tier 守卫的 DB 回归**：`tests/agent/kernel`+`tests/core/category_root` 在候选库 64245 上 1792 项通过、7 项失败，7 项全是缺 `M2_TEST_CHECKPOINT_URL` 等 checkpoint/Temporal 环境变量（已单跑复现 `KeyError: 'M2_TEST_CHECKPOINT_URL'`），与本次改动无关。**剩余缺口/下一步**：㊀ 派生草稿仍落在独立 `product_variants` 行而不是提案内，连同前端“型号派生与父版重核”页入口改写一起收口；㊁ P24 等用户提供试点租户的真实评审人人选，在那之前路径 A 的 G0 正向链只能验负向；㊂ 规格冻结（`product.definition.publish`）未实现，派生与定义演进都卡在它。**另记两处与 v1.1 的差距（本轮未改，属 S1/S2 建设量）**：时间真值四分里承诺、外部等待、基线、预测都没有表，`project_tasks` 也没有状态与负责人列，P17 项目健康度因此算不出来（`api.py` 的 `/health` 只是存活探针）；§03.7 准备度聚合目前只覆盖资源与配对品质两处，产品/验证、制造、交付适用性三维未统一实现。

**验收账号供给（2026-10-17，用户“帮我先做一个专门验收的账号”）**：新增 `tools/acceptance_account.py`（create / renew / list，`--state` 指定环境）：建 Principal + 品类 Grant（`can_write`、默认 `product_manager`）+ LoginSession，账号元数据与 token 写进该环境自己的状态文件（token 不打印、不入仓）。两道守卫：复用 `verify_test_target` 只认已标记的 `pdos_test`；并要求该库 `alembic_version` 等于仓库当前 head，否则拒绝——陈旧 schema 上的验收等于为没人发布的 schema 攒证据。**已建**：`.local/candidate-runtime-20261016.json`（64245，head `s0_0774`）里建了 `acceptance` 账号，自带验收租户/品类/型号，30 天有效。**已验**：经 `create_app` 真实请求，账号可认证、只看到自己的品类、伪造 token 返回 401。**边界**：这是验收演练账号，**不是** [P24](../docs/design/2026-10-08-pdos-next-design-confirmation.md#p24-试点期-g0-评审人必须是第二个真人用户-2026-10-17按推荐) 要的独立 G0 评审人——同一人持两个账号不构成独立评审，不得记成 G0 已独立评审通过。**预览环境已升级并接通浏览器（2026-10-18，用户“升到 s0_0788 并建验收账号”）**：升级前先用 `docker exec … pg_dump` 备份到 `~/pdos-preview-backups/2026-10-18-preview-53502-pre-0788/pdos_test-s0_0728.sql.gz`（51 MB，gzip 校验通过，143 张 CREATE TABLE 与升级前表数一致）。按本仓既有做法（`local_environment.environment()` + `python -m alembic upgrade head`）把 53502 从 `s0_0728` 升到 `s0_0788`，returncode 0，表数 143→197，`products` 行数 3458 不变。随后在该环境建 `acceptance` 账号（沿用既有预览租户/品类，30 天）。`local_environment.py serve-web` 新增可选账号名参数，`serve-web acceptance` 用该账号的 token 注入 `PDOS_NEXT_LOCAL_SESSION`。**已验**：API 8898 + Web 3028 起服，浏览器进入工作区，`/v1/session` 返回的 principal 正是该验收账号，`/v1/categories`、`/v1/personal/*` 均 200，伪造 token 401。
**工作流环境与试点准入已接通（2026-10-18，用户“create-db + create-server，再用 serve-api 起服；顺便把试点准入行补上”）**：旧 `.local/workflows.json`（marker 916f950f，容器已不存在）改名为 `workflows-916f950f-stale.json` 留档，不删。`create-db` 为当前 marker 新建状态库成功（loopback:58047）。**`create-server` 失败且非代码问题**：`docker pull temporalio/auto-setup:1.29.1` 报 `auth.docker.io … EOF`，本机拉不到镜像，本地也没有该镜像——属外部网络阻塞，未重复探测。改用本仓既有的无容器回退 `workflow_environment.py serve-native`：用 `.local/tools/temporal` 官方二进制起 dev server（127.0.0.1:58708，namespace `pdos-next`，SQLite 历史，`storage_mode=local-sqlite-development`），`health` 验到命名空间 `pdos-next`。**恢复条件**：拿到 `temporalio/auto-setup:1.29.1` 镜像（恢复 registry 访问或离线导入）后可改回容器方案；在那之前 Temporal 历史是 SQLite 开发回退，**不作为 PostgreSQL 正式验收依据**（该回退在工具里即如此标注）。随后 `serve-api` 按项目自身路径起服成功（8898），不再绕过工作流环境。
`acceptance_account.py` 新增 `admit` 动作并已执行：为预览租户写入 `tenant_pilot_admissions`，`approval_reference` 写明 “Local acceptance environment only; no pilot qualification”，不冒充真实试点准入。
**升级到 0790**：执行 admit 时工具按既有守卫拒绝，因为仓库 head 期间又从 `s0_0788` 动到 `s0_0790`（0789/0790 是另一会话**尚未提交**的工作树文件）。按同一路径再次 `alembic upgrade head`，预览库到 `s0_0790`、199 张表。**口径**：该库已应用两条未提交的迁移，若那两条在提交前被改写，本环境需重建。
**浏览器已核对**：3028 以验收账号登录，界面左下显示“验收账号（仅验收演练）· 本地合成环境”，小Pai 工作栏可打开。`model_available=false`（无模型凭据），因此只验到会话入口，未验模型实际调用。
**仍差一项**：`web/.next` 是 10-17 06:12 的构建，落后当前前端源码（另一会话仍在改前端），要看最新界面需重新 `pnpm build`。

**HEAD 既有失败 23 项（2026-10-17 发现，已逐项修完）**：跑覆盖 `g0_fixture` 调用方的套件时暴露，1202 通过、23 失败（48 分钟，候选库 64245，schema `s0_0774`）。**已定性为与本次改动无关**：库安静时重跑 23 项全部复现（排除并发写入干扰），再用 HEAD 的干净 git worktree 对同一个库跑同样 23 项，**同样 23 项全失败**，故既非本次改动、也非工作树里其他未提交改动引入。**分类（已取到错误签名）**：① `tests/builds/start/test_writer_projection.py` 12 项——用内存 SQLite，报 `no such table: categories`，测试自身的建表引导没跑；② `tests/categories/preproject/test_m3_lifecycle_catalog.py` 2 项——冻结表目录缺 `platform_link_current` 与 `tenant_pilot_admissions`，即新表没并进冻结清单（与登记表漂移同类）；③ `tests/categories/products/test_platform_links_pg.py::test_platform_migration_refuses_to_remove_committed_history` 1 项——末行断言 `alembic_version == "s0_0759"`，钉死在旧 revision，库不在该版就必失败；④ `tests/builds/professional_authority/test_current_policy.py` 4 项——权限撤销后 peer 仍能看到记录，是真实行为断言失败，需定位；⑤ `tests/categories/preproject` 其余 4 项（spec bound 2、review fixes 1、lifecycle concurrency 1）未细查。**已修（2026-10-18，用户“先修这 23 项既有失败”）**：
① 12 项 SQLite 引导——`builds`/`build_start` 都带 `category_lifecycle_fence`，`command_scope` 因此会锁品类根，而该用例的内存库只建了 `products`。新增 `sqlite_table()`：按 ORM 建 `categories` 表，去掉 SQLite 解析不了的 `key ~ '...'` 正则 CHECK，并用 `CreateTable(include_foreign_key_constraints=[])` 出 DDL（目标表不在这一张表的副本里，SQLite 也不强制外键）。12 项 1 秒内通过。
② 2 项冻结表目录——`COVERED_COLUMNS` 比 ORM 少 13 张表（M2 技能资格/自动化规则/MCP 控制、M3 平台与关联、试点准入）且 5 张表少 18 列。按 ORM 原样补齐；这 13 张都不带来源/原件引用列，不需要生命周期引用守卫，故不进 GUARDED（与 `audit_entries`、`outbox_events` 等 17 张既有未分类表同一处理）。该文件 58 项通过。
③ 3 项陈旧 revision 断言——`test_platform_links_pg` 与 `test_spec_bound_transactions_pg` 把“被拒的 downgrade 不动 stamp”写成 `== "s0_0759"` / `== "s0_0757"`，改为先读当前 stamp 再比对，不再钉死版本。
④ 4 项权限撤销——**不是 RLS 回归**。`model_audience` 是 restrictive 策略，靠子查询里 `products` 自身的 RLS 收口；而 G0 物化与资格导入现在会给具名评审人（`setup.peer`）写 `object_audiences` 的 products/projects 行，所以把对象改 private 已不足以让它失去可见性——实测最新一条 private 型号上确有 owner 与 peer 两条 products 受众行。测试新增 `_revoke()`，在断言“看不见”之前先清掉读者自己的受众行，再按原步骤授予/撤销。6 项通过。
⑤ 1 项封存定义——插入确实被拒，只是换了更靠前的守卫：`m3_definition_item_insert()` 报“definition is fixed”而非“sealed”。断言改为同时接受两种说法。2 项通过。
**同树并发（2026-10-18 发现）**：本仓另有一个会话在同一分支上连续提交并推进同一套库——施工期间迁移头从 `s0_0774` 走到 `s0_0788`，候选库 64245 也被升到 0788，`pdos_next/lifecycle_catalog.py`（现 `server/pdos_next/originals/lifecycle/catalog.py`）（本次改动文件之一）最近一次提交即来自该会话的 `2985e4a`。因此“23 项既有失败”的首次测量是在移动靶上取的：其中 1 项（lifecycle concurrency）在库升到 0788 后自行通过，其余按上面五类逐项修掉。后续在本仓做公共文件改动前先看 `git log`，避免与该会话互相覆盖。

**环境口径（重要）**：64245 这个库是按 `codex/m3-after-b8-20261010` 分支的工作树建的（`purpose: m3-after-b8`），不是按本分支建的，所以"HEAD 同样失败"只说明**本分支代码在那个环境里**同样失败。其中 ① 的 12 项用内存 SQLite、完全不碰 Postgres，与环境无关，是实打实的失败；②③④⑤ 在定性为回归之前，须在按本分支 head 新建的环境上复跑。**另注**：S0 冻结候选 `s0_0728` 的"后端回归 5603 通过"是在 schema 0728 上取得的，不能用它覆盖这 23 项。

**环境**：保留共用运行时状态库 `pdos-agent-state-b5181f4c` 与 Temporal 开发服务、`pdos-searxng-1`；pdos-next 原合成环境已删除；本轮由 `tools/` 重建独立标记的主回归库 `127.0.0.1:53502/pdos_test`，B8 迁移/恢复/浏览器使用另一个带独立标记的 `pdos_test`，私有旧链备份保留于本轮 `.local/`。原工程数据备份在 `~/pdos-preview-backups/2026-10-08-original-final/`。

**服务商数据协议改为可选治理工具（P26，用户 2026-10-18："不需要这个数据协议。目前阶段使用 Minimax。后续允许用户调用其他 API 包括 chatgpt、qwen 等"）**：出站前置取消——未登记协议不再拦截模型/研究/MCP 出站，每次出站的服务商与数据类别仍由服务器按当前 Run 绑定判定并记入运行回执；登记了当前有效协议的按"服务商 × 数据类别"限制执行，登记/续版/停用仍是管理员具名 T2。当前阶段模型服务商为 MiniMax（国内 M3）；多服务商租户自助配置（OpenAI 兼容 / Anthropic 原生）登记为后续方向，凭据进 KMS 不落文件。v1.1 §06.6.3/§06.9/§07.5、I24、AT-57、附录 A 及 AGENTS.md 不可协商项 7 已同步；代码对齐（`server/pdos_next/agent/kernel/policy.py` 及出站调用点、受影响测试）随本条目实施。MiniMax 真实接线的恢复条件收窄为：API 凭据（KMS 引用）、价格/计费材料与对应外部调用授权。**必要证据**：`policy.egress` 新语义及模型网关/MCP/研究出站 5 个调用点、6 个受影响测试文件（旧出站断言改写 + 新增"已登记协议限制类别"用例）在候选库 64245（s0_0810，与 head 一致）定向 42 项中 41 通过，唯一失败 `test_prompt_and_tool_prefixes_are_fixed_per_isolation_across_restart` 经干净 HEAD（b07e548）对照 worktree 复现，属 HEAD 既有、与本次无关；改动文件 ruff 通过。全量 `tests/agent/kernel` 1715 通过/181 失败/9 跳过，失败经同一对照归因：旧出站语义断言（已全部改写并通过）、HEAD 既有失败（如 `persistence.py:103 运行与服务器范围不一致`，干净 HEAD 同样复现）、另一会话未提交工作树改动所致（`server/pdos_next/agent/kernel/api.py` 与三个新视图模块；`test_m3_skill_contracts`/`test_management_api` 在干净 HEAD 通过）、checkpoint/Temporal 环境变量类；均非本次改动，归属协调保留。无迁移、无真实模型调用。另发现 iCloud 冲突副本 `server/pdos_next/research/egress 2.py`（旧语义残留，不可导入、不参与构建），未删除，建议随仓库迁出 iCloud 一并清理。**价格与计费材料已填好（2026-10-19，用户指示"根据网上数据自动填好"）**：MiniMax 官方定价页当日复核（标准档 ≤512k：输入 2.10 / 输出 8.40 / 缓存命中 0.42 CNY/百万 token，与 10-17 核对一致），按 CNY→USD 6.69274（open.er-api.com 2026-10-19；frankfurter.dev 2026-10-16 为 6.6862 交叉核对）折算填入 `config/minimax-cn-m3.draft.json` 价格卡（有效期至 2026-11-18；M3 无单独缓存写入价，新增输入按输入价计）；经真实 DTO 加载 + `RateCard.validate` 通过（50 KB 请求预留约 22,115 微美元、20k 输入/2k 输出结算约 8,786 微美元，仅量级自检）。未含账号折扣/订阅/汇率波动，首笔真实账单须复核；总输入 >512k 的对话按官方 >512k 档重新核价。MiniMax 真实接线剩余恢复条件：API key 的授权 KMS 引用（用户提供后替换草案占位 ARN）与外部调用授权。

**MiniMax 真实接线与首次真实调用（2026-10-19，用户已提供 API key）**：key 已存本机 macOS Keychain（`pdos-next-minimax-m3-api-key` 加版本伴随项），不落文件/日志/仓库。本机无阿里云凭据（官方凭据链实测 env/CLI/ECS 均不可用），新增本地开发 KMS 适配器 `server/pdos_next/agent/model_configuration/local_kms.py`（Keychain 后端，经 `TenantRuntime` 的 `kms_factory` 接缝接入，版本元数据读取不解密值），`host.py` 的 KmsLocation 放行精确标记对（`local`/`local-keychain`），`runtime_ports` 按标记选择工厂；**生产仍走阿里云 KMS**。真实租户运行时配置在 `.local/tenant-runtime-minimax.json`（预览租户 + 本地 ARN + 已填价格卡）。**必要证据**：`tests/agent/model_configuration` 92 通过（含新增 local_kms 3 项）；端到端凭据解析（绑定/取值/旧版本拒绝/价格卡经宿主配置 validate）通过；改动文件 ruff 无新增问题。**首次真实调用**（候选库 64245 合成租户、合成公开内容，经注册网关）：真实 HTTPS→api.minimax.cn 成功，456 输入/71 输出/128 缓存命中，4.8 秒，结构化结果 `{"ok": true}`，结算 201 微美元与价格卡逐项核算一致；出站回执 provider=minimax、类别 public、agreement_id 空（P26 语义）；预算 calls=1、held=0 无泄漏；更早一次无引导提示的尝试按 EXTERNAL_OUTCOME_UNKNOWN 如实结算未重发。**行为边界**：手工探针须在系统提示中指示调用 `pdos_agent_output` 收尾工具，否则 M3 纯文本作答判为无效；注册图冻结提示词自带此约束，不另修代码。**剩余缺口/下一步**：冒烟用直接预算行（未走设置页 T1 链）；预览/正式环境的模型配置确认、预算 T1、技能启用与真实业务内容联验，待预览环境升级重启并挂 `PDOS_TENANT_RUNTIME_CONFIG` 后办理；生产部署的阿里云 KMS 凭据待用户提供；本次冒烟不授予任何资格或生产启用。无 push、无生产操作。

**待用户处理**：S5 生产下线；仓库仍在 iCloud"桌面"同步范围内（同步冲突副本会反复出现），建议迁出；（可选）生产部署用的阿里云 KMS 凭据。S1 最小演示切片的本人保存、G0 提交与具名批准已完成，无该切片待处理事项。

<a id="queue-history-20261005"></a>

## 历史与归档

2026-11-01 整仓重组时，本清单删去了原工程停用前的历史队列、N0–N7/P/Q 原条目底账、旧清单迁移表与 vNext 补充；同时删去原工程代码、旧设计与历史证据。删除前的完整内容在本地标签 `archive/pre-restructure-2026-11-01`，可用 `git show archive/pre-restructure-2026-11-01:tasks/ai-native-integrated-todo.md` 查看。上文旧段落里的“下一步”不再作为指令，以[欠债总表](#debt-board)为准。

## 使用与更新

1. 从[当前队列](#current-queue)的[欠债总表](#debt-board)续接；每组开一个会话，开头写明所接的组号。
2. 做完一项就在原位改成 ✅ 并附证据链接，不另起段落；新发现的问题追加到对应组。
3. 证据放 `docs/reports/evidence/<主题>-<日期>/`，本清单只链接，不复制长日志。
4. 本文件是唯一活动状态来源；`web` 的“当前进展”页面只读取当前队列中的里程碑表。
