# docs/design · 设计文档索引

本目录只保留 pdos-next 现行有效的设计文档。活动状态的唯一来源是[整合清单](../../tasks/ai-native-integrated-todo.md#current-queue)；新文档落盘后请在本页登记。

2026-11-01 整仓重组时删除了原工程（`server/` + `web/`）的合同与规格、vNext/Sprint 文档、wave 草稿和已被取代的设计稿。删除前的完整内容在本地标签 `archive/pre-restructure-2026-11-01`。现存文档里指向这些文件的链接可以这样查看：

```bash
git show archive/pre-restructure-2026-11-01:docs/design/<文件名>
```

## 一、现行依据（先读）

| 文档 | 作用 |
|---|---|
| [完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md) | 2026-10-08 批准并冻结；产品、领域、体验、运行架构与验收（附录 A 操作、附录 B 验收场景）的唯一设计依据 |
| [设计确认与决策记录](2026-10-08-pdos-next-design-confirmation.md) | 冻结后经用户确认的变更 P1–P122（最新 [P122 最终回答出不来的三处修正](2026-10-08-pdos-next-design-confirmation.md#p122)；[P121 记忆系统目标架构九处修订](2026-10-08-pdos-next-design-confirmation.md#p121)；[P120 来源撤回、定义更新与接口更新](2026-10-08-pdos-next-design-confirmation.md#p120)，原 P100，落地时撞号改号；[P101 下线小Pai 原执行路径](2026-10-08-pdos-next-design-confirmation.md#p101)；[P100 LangGraph 执行迁移到 Temporal 官方插件](2026-10-08-pdos-next-design-confirmation.md#p100)；P102–P104、P106–P108、P112、P114、P118 未使用或不在本分支）；与 v1.1 冲突时以较新的决策为准 |
| [架构导读](2026-10-08-pdos-next-architecture-overview.md) | 汇总权威文档与实现现状的阅读入口，不新增权威 |
| [AI 写入分级 DC-11](2026-09-20-ai-direct-write-tier-policy.md) | T0/T1/T2 政策，AGENTS.md 不可协商项 1 |
| [Agent 运行架构收口合同](2026-10-07-agent-runtime-convergence.md) | LangGraph + Temporal 的统一运行规则 |
| [LangGraph 执行迁移到 Temporal 官方插件](2026-11-12-langgraph-temporal-plugin-migration-decision.md) | 用户 2026-11-12 确认（P100、P101）；取代上一行的执行与检查点分工，原路径已下线；实施状态见清单 D378 |
| [UI 基线](2026-08-09-ui-baseline.md) 与[原稿](ui-baseline-mockup.html) | shadcn/ui + Tailwind v4 + Geist，橙色主色，双主题 |

## 二、建设计划与切片合同

| 文档 | 范围 |
|---|---|
| [pdos-next 执行方案](2026-10-02-pdos-next-execution-plan.md) | 建设阶段与加速规则（阶段名已按 v1.1 改为 S0–S5） |
| [S0 整体重构计划](2026-10-08-pdos-next-s0-refactoring-plan.md) | 已批准；迁移链一次性重置（P1）、B0–B8 分批 |
| [小Pai 产品执行计划](2026-10-07-xiaopai-product-execution-plan.md) | M0–M3 的依赖与顺序，已按 v1.1 同步 |
| [M3 实施合同](2026-10-08-pdos-next-m3-implementation-contract.md) | 品类到立项闭环 |
| [S2 多运行合同](2026-10-17-pdos-next-s2-multi-run-contract.md) / [S2 项目工作台合同](2026-10-17-pdos-next-s2-project-workbench-contract.md) | S2 项目工作 |
| [S3 品质续接合同](2026-10-17-pdos-next-s3-quality-continuation-contract.md) | 失败 → 问题 → 双线变更 → 复验 |
| [S4 制造交付合同](2026-10-17-pdos-next-s4-manufacturing-delivery-contract.md) | 制造基线、试产与发布包 |
| [S5 关注合同](2026-10-18-pdos-next-s5-attention-contract.md) / [S5 G0 工作合同](2026-10-18-pdos-next-s5-g0-work-contract.md) / [S5 项目工作合同](2026-10-18-pdos-next-s5-project-work-contract.md) | 我的工作、G0 评审与项目工作 |
| [立项前改造](2026-10-05-preproject-redesign.md) | 品类、活提案、AI 先起草与小Pai 入口 |

## 三、小Pai 与模型

| 文档 | 状态 |
|---|---|
| [日常问答与企业检索](2026-10-27-xiaopai-daily-assistant-enterprise-rag-design.md) | 实施设计 v0.4；P30–P32 已确认；切片 A–G 已实施（10-28/10-30），余项见[清单 W1](../../tasks/ai-native-integrated-todo.md#debt-board) |
| [上下文设计](2026-10-28-xiaopai-context-design.md) | v0.2；§13 已确认为 P32；X1–X3 已实施（10-28/10-30），余项见[清单 W1](../../tasks/ai-native-integrated-todo.md#debt-board) |
| [切片 A / X1 实施交接](2026-10-28-slice-a-x1-implementation-handoff.md) | 已实施（10-28）；代码路径已按 2026-11-01 新目录更新 |
| [M2 工具面决定](2026-10-17-m2-tool-surface-decision.md) | 方案 C 已实施；T2 门禁与方案 B 待定 |
| [M2 工具下发审查](2026-10-08-m2-skill-tool-delivery-proposal.md) | 待评审；载荷数字已被上一行取代 |
| [本地开发 MiniMax 策略](2026-10-23-local-development-minimax-policy.md) | 用户批准的本地开发不限额策略 |

## 四、界面

| 文档 | 状态 |
|---|---|
| [v1.1 UI 重设计稿](2026-10-13-pdos-v1.1-ui-mockup.html) | 多轮迭代至 v4.1，演示数据 |
| [UI 契约补遗](2026-10-17-pdos-v1.1-ui-contract-addendum.md) | A/B/C 三类界面决定，B/C 已并入 v1.1 |
| [完整体验候选](2026-10-23-pdos-full-product-ui-candidate.md) | 供预览选择的本地合成原型 |

## 五、待用户裁决

| 文档 | 状态 |
|---|---|
| [NPI 框架与 Agent 任务规划](2026-11-01-npi-framework-agent-task-planning-design.md) | 设计草案 v0.2；P33 已确认，未实施 |
| [项目协作、驾驶舱与提及](2026-11-01-project-team-cockpit-mentions-design.md) | 设计草案 v0.1；P34 已确认，未实施 |
| [小Pai 记忆层优化](2026-11-05-xiaopai-memory-layer-design.md) | v0.4 已确认（用户 2026-11-07，Q1–Q19，[P84–P90](2026-10-08-pdos-next-design-confirmation.md#p84)）；含业务场景记忆、具体架构、节点衔接与评测方案、语言习惯；其中 9 处由 [P121](2026-10-08-pdos-next-design-confirmation.md#p121) 修订（2026-11-12）；M1、M2a 已实施并合入（11-08、11-09），M2b、M3、M4 未实施，按 §13 分期交清单 W8 D45 |
| [小Pai 记忆系统评估与目标架构](2026-11-12-xiaopai-memory-system-assessment-and-target-architecture.md) | v0.1；与 v0.4 和 P84–P94 不同的 9 处已由用户 2026-11-12 逐条确认（[P121](2026-10-08-pdos-next-design-confirmation.md#p121)）；含现状证据、目标架构、数据契约、评测方案；未实施，开工时间未定（清单 D473） |
| [v1.1 缺口与竞品对照](2026-10-22-pdos-v1.1-gap-analysis-and-competitive-review.md) | 分析稿，不构成合同；改变范围的条目须先有决策记录 |

## 六、资料与相邻目录

- [category-seeds/](category-seeds/README.md)：品类种子资料（轮胎充气泵、自行车打气筒）。
- [../runbooks/](../runbooks/)：pdos-next 运维与使用手册，以及原生产下线手册。试点上线：[备份与恢复](../runbooks/backup-and-restore.md)、[发布与回滚](../runbooks/release-and-rollback.md)、[监控告警与值班](../runbooks/monitoring-and-on-call.md)。
- [../evaluations/xiaopai-v0/](../evaluations/xiaopai-v0/README.md)：小Pai 评测题集。
- [../evaluations/xiaopai-memory-v0/](../evaluations/xiaopai-memory-v0/README.md)：小Pai 记忆评测的时间线候选（8 条，未经确认）。
- [../research/](../research/report.md)：早期市场与产品调研综合报告。
- [../reports/](../reports/)：评审报告与 `evidence/` 验证证据。
