# docs/design · 设计文档索引

本文件是设计文档的导航索引，只整理归类，不改变任何文档效力。当前活动状态唯一来源仍是[整合清单](../../tasks/ai-native-integrated-todo.md)；新文档落盘后请在此登记分类。

## 最终方案速览（截至 2026-10-08）

- **产品形态**：AI-native 研发项目管理系统（PDOS）。决策背景见[全量新建说明](2026-08-09-cehub-v32-convergence.md)：以 preview 定稿为唯一产品形态基准，老 CEHub 仅可选复用。
- **主线工程是 pdos-next（用户 2026-10-08 定）**：
  - **pdos-next**（`pdos-next/`）：以[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)（2026-10-08 批准并冻结）为设计依据，决策背景见[设计确认稿](2026-10-08-pdos-next-design-confirmation.md)；建设顺序：S0 整体重构 → S1 品类研究到立项 + 小Pai 内核。
  - **原工程**（`server/` + `web/`）：2026-10-08 停用归档（标签 `original-final-2026-10-08`），数据备份不迁移；N/P/Q 与 Q0–Q6 随之归档。原工程的执行计划、完整设计合同等仅作历史对照与复用来源。
- **固定技术栈与 Agent 运行架构**（AGENTS.md 不可协商项 6）：Next.js + FastAPI + PostgreSQL + LangGraph(Python) + Temporal + shadcn/ui。所有 Agent 完整能力经 Temporal 工作流与 Activity 调 LangGraph，模型网关不得绕过注册执行图；统一规则见[Agent 运行架构收口合同](2026-10-07-agent-runtime-convergence.md)（已实施，两线共用）。
- **AI 写入分级**：[DC-11 T0/T1/T2 政策](2026-09-20-ai-direct-write-tier-policy.md)（已批准，实施中）。AI 身份经受控领域服务写入，`pdos_agent` 对业务表零直接写权限，永不取得 T2 执行权。
- **现行方向**：[DC-13 设计方向整合](2026-09-28-pdos-design-direction-integration.md)——原合同是领域基线，V2 设计包仅作体验层来源；AI 默认模式为"AI 先完成、引擎校验、人管例外"。执行顺序上产品经理开发第一（覆盖 DC-13 原 D14-04 先行顺序）。
- **对话式 Agent**：[DC-12 小Pai](2026-09-28-xiaopai-conversational-agent.md)（已批准，实施中）；入口与统一输入见[统一对话与文件输入](2026-09-11-unified-conversation-and-file-input.md)、[立项前改造](2026-10-05-preproject-redesign.md)。
- **UI 基线**：[UI 基线文档](2026-08-09-ui-baseline.md)（滚动更新至 v0.7.1）：shadcn/ui + Tailwind v4 + Geist，橙 `#c2410c`/`#fb923c`，圆角 8px，双主题，Phosphor 图标。
- **冻结共同合同**：对象合同 `docs/contracts/pdos-v1/`（N0-01），运行与授权政策 `docs/contracts/pdos-runtime-v1/`（N0-02，含 DC 冻结登记台账 freeze-record.md）。两者并行生效、作用域不同。

## 一、最终方案主线（当前权威链）

| 文档 | 角色 |
|---|---|
| [2026-09-09-ai-native-integrated-execution-plan.md](2026-09-09-ai-native-integrated-execution-plan.md) | 原工程整合执行计划（AGENTS.md 入口；N/P/Q 原义务与验收保留，不优先于 pdos-next 新工程） |
| [2026-09-10-pdos-complete-design-contract.md](2026-09-10-pdos-complete-design-contract.md) | 完整设计合同 v1.1，原工程唯一领域基线（统一阅读入口） |
| [2026-09-20-ai-direct-write-tier-policy.md](2026-09-20-ai-direct-write-tier-policy.md) | DC-11 AI 直接写入分级政策（T0/T1/T2） |
| [2026-09-28-pdos-design-direction-integration.md](2026-09-28-pdos-design-direction-integration.md) | DC-13 设计方向整合（V2 仅体验层来源） |
| [2026-09-28-xiaopai-conversational-agent.md](2026-09-28-xiaopai-conversational-agent.md) | DC-12 小Pai 对话式 Agent 与项目持续跟进 |
| [2026-10-02-pdos-complete-target-architecture-v1.md](2026-10-02-pdos-complete-target-architecture-v1.md) | **已被 v1.1 取代（2026-10-08）**，保留作历史对照。 |
| [2026-10-02-pdos-next-execution-plan.md](2026-10-02-pdos-next-execution-plan.md) | pdos-next 执行方案（G0–G5 切片与加速规则） |
| [2026-10-07-agent-runtime-convergence.md](2026-10-07-agent-runtime-convergence.md) | Agent 运行架构收口合同（LangGraph + Temporal，已实施，两线共用） |

**导读**：[PDOS-next 架构设计整理稿](2026-10-08-pdos-next-architecture-overview.md)（2026-10-08）汇总上述权威文档与唯一清单实现现状，作为 pdos-next 架构的统一阅读入口；不新增权威、不改变任何文档效力，活动状态仍以唯一清单为准。

## 二、生效领域合同

### 原版 S0–S5 与验收（原工程历史义务）

| 文档 | 范围 |
|---|---|
| [2026-08-09-preview-execution-plan.md](2026-08-09-preview-execution-plan.md) | 原版 S0–S5 规格、工程纪律与 canonical Exit 依据（配套 `docs/specs/cehub-v3.2-preview/`） |
| [2026-08-12-s4-1-quality-owner-contract-draft.md](2026-08-12-s4-1-quality-owner-contract-draft.md) / [quality-api-contract](2026-08-12-s4-1-quality-api-contract.md) | S4-1 CAPA 质量流程与 API 合同（已冻结） |
| [2026-08-12-s4-2-memory-search-contract.md](2026-08-12-s4-2-memory-search-contract.md) | S4-2 Memory + 向量检索契约 |
| [2026-08-12-s4-3-phase-two-agents-contract.md](2026-08-12-s4-3-phase-two-agents-contract.md) | S4-3 Phase2 双 Agent 合同 |
| [2026-08-12-s4-4-context-builder-layers-contract.md](2026-08-12-s4-4-context-builder-layers-contract.md) | S4-4 Context Builder 分层契约 |
| [2026-08-12-s5-1-dingtalk-connector-contract.md](2026-08-12-s5-1-dingtalk-connector-contract.md) | S5-1 钉钉连接器 v1（真实应用 gate 待批） |
| [2026-08-13-s5-2-erp-handoff-contract.md](2026-08-13-s5-2-erp-handoff-contract.md) | S5-2 ERP Handoff 契约 |
| [2026-08-13-s5-3-crm-entity-contract.md](2026-08-13-s5-3-crm-entity-contract.md) | S5-3 CRM 需求入口与实体收尾 |
| [2026-08-13-s5-4-phase-three-agent-contract.md](2026-08-13-s5-4-phase-three-agent-contract.md) | S5-4 Phase3 双 Agent 合同 |
| [2026-08-13-sprint-5-cutover-contract.md](2026-08-13-sprint-5-cutover-contract.md) | Sprint 5 全量切换与 CEHub 只读退役 |
| [2026-08-20-user-account-management-contract.md](2026-08-20-user-account-management-contract.md) | 生产账户管理 v1 |

### vNext 遗产（部分仍为执行依据）

| 文档 | 范围 |
|---|---|
| [2026-08-25-vnext-decision-conflict-improvement-register.md](2026-08-25-vnext-decision-conflict-improvement-register.md) | 决策台账 D1–D38（已生效；D3/D19/D32 按后续合同执行） |
| [2026-08-25-vnext-full-scope-axis-closure-and-gap-analysis.md](2026-08-25-vnext-full-scope-axis-closure-and-gap-analysis.md) | 十条功能轴闭环 + 体验合同 UX1–UX10（V0/V1 验收引为执行依据） |

### 2026-09 验收与架构附件

| 文档 | 范围 |
|---|---|
| [2026-09-08-v0-v1-acceptance-and-pilot-contract.md](2026-09-08-v0-v1-acceptance-and-pilot-contract.md) | V0/V1 验收与试点合同 |
| [2026-09-08-project-type-test-template-contract.md](2026-09-08-project-type-test-template-contract.md) | 项目类型与测试模板合同 |
| [2026-09-08-ai-test-plan-conversation-contract.md](2026-09-08-ai-test-plan-conversation-contract.md) | AI 对话调整测试计划合同 |
| [2026-09-08-original-production-exit.md](2026-09-08-original-production-exit.md) | 原版生产出口口径 |
| [2026-09-09-management-process-v1.md](2026-09-09-management-process-v1.md) | 研发管理流程 v1.1（七阶段 + 四专业 + ID 立项） |
| [2026-09-10-ai-native-architecture-consistency-contract.md](2026-09-10-ai-native-architecture-consistency-contract.md) | 架构一致性合同（整合计划的架构附件） |
| [2026-09-10-ai-context-tools-harness-contract.md](2026-09-10-ai-context-tools-harness-contract.md) | 上下文、工具与 Harness 专题合同 |
| [2026-09-11-unified-conversation-and-file-input.md](2026-09-11-unified-conversation-and-file-input.md) | 统一对话与文件输入（实施归属文档） |

### UI 线

| 文档 | 范围 |
|---|---|
| [2026-08-09-ui-baseline.md](2026-08-09-ui-baseline.md) | UI 基线（滚动更新至 v0.7.1） |
| [2026-09-30-project-workspace-usage-model.md](2026-09-30-project-workspace-usage-model.md) | 项目工作区使用模型（导航/入口重组） |
| [2026-10-01-role-scenario-ui.md](2026-10-01-role-scenario-ui.md) | 岗位场景 UI 使用模型（登录即本人工作） |
| [2026-10-01-product-manager-ai-native-ui-proposal.md](2026-10-01-product-manager-ai-native-ui-proposal.md) | 产品经理空间 AI-native 界面方案（首版已实施） |
| [2026-10-13-pdos-v1.1-ui-mockup.html](2026-10-13-pdos-v1.1-ui-mockup.html) | v1.1 目标架构 UI 重设计稿（2026-10-13 起多轮，现为 v4.1）：主体为项目管理，品类开发与立项提案为产品经理专属的立项前阶段，经 G0 汇入项目；我的工作按动作类型分诊、项目列表三视图（列表/看板/时间轴）、NPI 阶段条与门禁、四时间时间轴、小Pai 多会话与运行回执；使用逻辑参照 Linear/Asana/Notion，视觉沿用基线 v0.7.1，演示数据。其界面决定的契约化见下一行 |
| [2026-10-17-pdos-v1.1-ui-contract-addendum.md](2026-10-17-pdos-v1.1-ui-contract-addendum.md) | 界面决定三分法与契约补遗：A 类 24 条（v1.1 已写明）、B 类 19 条（已确认并入 v1.1 §05.3/§05.12，确认稿 P22）、C 类 6 条（已确认，确认稿 P15–P20）；另列仅演示素材不构成约束 |

### pdos-next 施工合同（wave 冻结版）

| 文档 | 范围 |
|---|---|
| [2026-10-02-pdos-next-reuse-and-parallel-plan.md](2026-10-02-pdos-next-reuse-and-parallel-plan.md) | 新旧工程复用矩阵与施工分工 |
| [2026-10-02-pdos-next-wave14-results-implementation-contract.md](2026-10-02-pdos-next-wave14-results-implementation-contract.md) | 第十四波：结果返回 |
| [2026-10-02-pdos-next-wave15-quality-loop-implementation-contract.md](2026-10-02-pdos-next-wave15-quality-loop-implementation-contract.md) | 第十五波：失败/Issue/CAPA/双线变更 |
| [2026-10-02-pdos-next-wave16-quality-followup-implementation-contract.md](2026-10-02-pdos-next-wave16-quality-followup-implementation-contract.md) / [wave16 回链修复](2026-10-03-pdos-next-wave16-link-phase-repair-contract.md) | 第十六波：品质整改后续 |
| [2026-10-03-pdos-next-wave17-staged-implementation-contract.md](2026-10-03-pdos-next-wave17-staged-implementation-contract.md) | 第十七波：CAPA 有效性首段 |
| [2026-10-03-pdos-next-wave18-professional-facts-contract.md](2026-10-03-pdos-next-wave18-professional-facts-contract.md) | 第十八波：规则/实际观察/具名复核 |
| [2026-10-05-preproject-redesign.md](2026-10-05-preproject-redesign.md) | 立项前改造（品类 + 活提案 + AI 先起草 + 小Pai 入口，已授权实施） |

## 三、待用户裁决

| 文档 | 状态 |
|---|---|
| [2026-10-22-pdos-v1.1-gap-analysis-and-competitive-review.md](2026-10-22-pdos-v1.1-gap-analysis-and-competitive-review.md) | **分析稿，不构成合同，未改 v1.1。** 对照海外 PLM/NPI 厂商、国内 IM 平台与国产 PLM、AI-native 工作工具期待清单及 2025–2026 用户调研，列出 44 条缺口 G-01–G-44（入口与交互面、信任控制与运维、领域对象与业务闭环、小Pai 技能与自动化、设计内部张力、国内约束与合规、商业）并分 P0–P3；其中 11 条改变范围或既有决定，须以决策记录（建议 P27 起）确认后方可进入建设。 |
| [2026-10-08-m2-skill-tool-delivery-proposal.md](2026-10-08-m2-skill-tool-delivery-proposal.md) | **待评审，仅文档，未实施。** M2 主循环 106 个工具与约 167 KB 定义的下发审查；建议固定窄入口与按技能追加 schema，具备资格时采用原生工具追加；包含缓存边界、可信调用证明、恢复及验证方案，未改 v1.1 冻结条款。其载荷数字（106 个 / 167 KB、并集 3.7%）已被下条 2026-10-17 实测取代。 |
| [2026-10-17-m2-tool-surface-decision.md](2026-10-17-m2-tool-surface-decision.md) | **C 已于 2026-10-18 经用户确认实施（未 push）；T2 门禁与 B 升级待决策。** 细化并取代上条的载荷数字：10-18 实测 137 个工具 / 291,811 B（17 个技能，39 个工具无技能归属）；区分缓存可解决的费用问题与缓存不解决的可见面问题；对比 A 窄入口 / B 原生 defer_loading+tool_addition / C 按技能组固定 / D tool search 的实际代价，含放弃原生 schema 的五条风险（含拆掉 §09 资格测量与重建写入证明）；建议并已实施 C 作底座（披露规则为 authorize 的前置镜像，实测下发由 137 个降至 45–62 个）、排除 D；修订节更正了 T2-prepare-only 必须保持披露这一规则错误，并记录 B 的优先级因执行类技能组增大与会话权限维度而提高。未改 v1.1 冻结条款。 |
| [2026-10-08-pdos-next-s0-refactoring-plan.md](2026-10-08-pdos-next-s0-refactoring-plan.md) | **用户 2026-10-08 已批准执行**。M1/S0 整体重构：B0 限时基线（慢路径引用旧证据、短路径实测）、B1–B8 分批与回归、迁移链一次性重置不留兼容层（决策 P1）、建项目过渡入口（P2）、性能分档（P3）、M2 在 B3 后与 B4–B6 并行并在 B7 汇合（P4）、品类为第一键的 RLS、施工合同整体标为已取代。活动状态以唯一清单为准。 |
| [2026-10-07-xiaopai-single-agent-runtime-plan.md](2026-10-07-xiaopai-single-agent-runtime-plan.md) | **已被设计确认稿与 v1.1 取代（2026-10-08）**，保留作决策记录。单 Agent 小Pai、工具/MCP（§4.3）、技能包（§5.1）等内容已并入 v1.1 §06；其施工清单（§11、§14）以原工程为对象，不再执行。 |
| [2026-10-07-xiaopai-product-execution-plan.md](2026-10-07-xiaopai-product-execution-plan.md) | **已按 v1.1 与确认稿 P4 同步（2026-10-08）**。pdos-next 的依赖：M0 → M1 的 B0–B3 → 并行【B4–B6 ‖ M2 小Pai 内核与公开研究】→ B7 → B8 → M3 品类到立项闭环 → 后续。活动状态以唯一清单为准。 |
| [2026-10-08-pdos-next-design-confirmation.md](2026-10-08-pdos-next-design-confirmation.md) | **已全部确认（2026-10-08）**。原工程停用、主线改为 pdos-next 后的设计冻结前确认稿：已定决定 K1–K9；待拍板 C1–C14（范围根、提案/定义关系、研究类对象去留、第一闭环、一致性与性能规则、形式化收敛、Agent 拓扑写回、试点资格、出站、术语、派生、数据迁移、复用范围、文档清理）；原工程复用清单与停用步骤 S1–S7。全部确认后并入目标架构 v1.1 冻结。 |
| [2026-10-08-pdos-complete-target-architecture-v1.1.md](2026-10-08-pdos-complete-target-architecture-v1.1.md) | **已批准并冻结（2026-10-08），pdos-next 现行设计依据**。完整目标架构 v1.1：并入设计确认稿 K1–K9、C1–C14（品类为范围根、立项提案与 G0、规格字典与共用规格条目、研究方法改技能包、§06 单 Agent 小Pai 整体改写、§08.11 一致性与性能规则、错误码收敛、服务商数据协议、试点资格、术语 S0–S5/ConfirmationBatch/AutomationRule、建设顺序）；新增不变量 I21–I24、ADR A21–A30、操作与验收 AT-49–63。取代 v1.0。 |

## 四、已被取代（仅供追溯，勿作依据）

| 文档 | 被谁取代/说明 |
|---|---|
| [proposal.md](proposal.md) / [m0-plan.md](m0-plan.md) | 2026-08-09 汇合决策降为工程参考 |
| [2026-08-21-product-usability-optimization-plan.md](2026-08-21-product-usability-optimization-plan.md) | 被 vNext 控制环方案吸收 |
| [2026-08-24-vnext-control-loop-upgrade-plan-draft.md](2026-08-24-vnext-control-loop-upgrade-plan-draft.md) | 草案，并入统一需求稿 |
| [2026-08-24-pdos-vnext-unified-requirements.md](2026-08-24-pdos-vnext-unified-requirements.md) | 整合草案，非 canonical；内容落入 09-10 完整合同 |
| [2026-08-25-vnext-object-contract-v1.md](2026-08-25-vnext-object-contract-v1.md) | 被 `docs/contracts/pdos-v1/`（N0-01 冻结）取代 |
| [2026-09-09-ai-native-architecture-reconfirmation.md](2026-09-09-ai-native-architecture-reconfirmation.md) | 静态盘点，架构解释以一致性合同为准 |
| wave 草稿：[w14](2026-10-02-pdos-next-wave14-results-contract-draft.md)、[w15 草案](2026-10-02-pdos-next-wave15-quality-loop-draft.md)、[w15 草稿](2026-10-02-pdos-next-wave15-quality-loop-implementation-contract-draft.md)、[w16](2026-10-02-pdos-next-wave16-quality-followup-draft.md)、[w17](2026-10-03-pdos-next-wave17-effectiveness-contract-draft.md) | 均被同 wave 冻结实施合同覆盖 |

## 五、历史记录与参考

- 决策/评审记录：[review-v0.1.md](review-v0.1.md)、[2026-08-09-cehub-v32-convergence.md](2026-08-09-cehub-v32-convergence.md)（决策背景，AGENTS.md 引用）、[2026-08-10-structure-and-delivery-review.md](2026-08-10-structure-and-delivery-review.md)、[2026-10-01-product-space-reference-analysis.md](2026-10-01-product-space-reference-analysis.md)、[wave14 衔接审查](2026-10-02-pdos-next-wave14-results-integration-review.md)
- 参考资料：[ui-baseline-mockup.html](ui-baseline-mockup.html)（历史视觉）、[2026-10-01-product-space-mockup.html](2026-10-01-product-space-mockup.html)（产品空间主参考）、[2026-09-10-lifecycle-role-tasks-and-ai-value.md](2026-09-10-lifecycle-role-tasks-and-ai-value.md)（业务解读）、[2026-09-28-pm-method-catalog-candidate.md](2026-09-28-pm-method-catalog-candidate.md)（候选，未冻结）
- [PDOS/](PDOS/) 子目录：用户提供的素材原件（`PDOS 产品空间.pdf`、`PDOS 设计方向整合.docx`、`PDOS_Build_Centric_V2_0_Design_Package.zip`，按 DC-13 仅作体验层/入口/AI 机制来源）。原冗余副本 `PDOS/2026-10-02-pdos-complete-target-architecture-v1.md` 已于 2026-10-08 经字节比对确认与主目录逐字节相同后删除，主目录[同名文件](2026-10-02-pdos-complete-target-architecture-v1.md)为唯一有效源。

## 六、相邻目录

| 目录 | 内容 |
|---|---|
| `../contracts/pdos-v1/` | N0-01 共同对象合同（DC-01~05、DC-09，2026-09-10 批准） |
| `../contracts/pdos-runtime-v1/` | N0-02 运行与授权政策合同（DC-06/07/08）+ `freeze-record.md` 冻结登记台账（DC-11/12/13 均登记于此） |
| `../specs/cehub-v3.2-preview/` | 原版 preview 规格 |
| `../runbooks/`、`../pilots/`、`../decisions/`、`../reports/`（含 `evidence/`） | 运维手册、试点度量、ADR、评审报告与验证证据 |
