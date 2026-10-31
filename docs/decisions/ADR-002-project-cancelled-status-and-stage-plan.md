# ADR-002: Project 增加"已取消"状态与阶段计划/实际日期

## Status

Proposed（分支 `claude/project-task-planning-ui`，待人审合并；未部署）

## Date

2026-10-31

## Context

S1-3 冻结的 Project 七态状态机（Draft/Proposed/Approved/Active/OnHold/Completed/Archived）没有"被砍项目"的出口：立项被否或客户撤回的项目只能长期挂在 OnHold，或被误标为 Completed。CEHub 迁移工具也只能把源系统的 `terminated` 映射为 `archived`，丢失了"未完成即终止"的语义。

同时，Stage 只有顺序没有日期：项目只有整体开始/目标日期，无法回答"当前阶段是否逾期""哪个阶段延期了多少天"。

## Decision

经人于 2026-10-31 授权（"做完剩下的"项目管理优化项），迁移 `0031_project_planning`：

1. `projects.status` 增加 `cancelled`。Draft/Proposed/Approved/Active/OnHold 均可转入 Cancelled；Cancelled 只能转 Archived，不可恢复。取消必须填写原因（API 校验），原因写入同事务审计 `context.reason`；事件仍为 `PROJECT_STATUS_CHANGED`，payload 结构不变。
2. `stages` 增加 `planned_start_date`、`planned_end_date`（计划基线）与 `entered_at`、`exited_at`（实际）。阶段推进在同一事务写入上一阶段 `exited_at` 与新阶段 `entered_at`；新建项目首阶段 `entered_at` = 创建时间。
3. 迁移按 `PROJECT_STAGE_CHANGED` 事件历史回填实际日期，首阶段缺失时取项目创建时间；无历史的导入项目保持 NULL，不推测。
4. `PUT /api/projects/{id}/stage-plan`（`project.edit`）在一个事务内更新多阶段计划，写 `PROJECT_UPDATED`（`changed_fields` 形如 `stage_plan.<code>`）与审计 `project.stage_plan.update`（前后快照）。Cancelled/Archived 项目计划锁定（409）。
5. 降级守卫：存在 `cancelled` 项目时拒绝降级到 0030。

## Consequences

- 不修改 CEHub 迁移工具的 `terminated → archived` 映射，保证已执行的生产迁移可同参数幂等重放。
- AI 工具的项目上下文查询只取 `approved/active/on_hold`，Cancelled 项目自动排除，无需改动 Agent 前缀。
- 执行计划 S1-3 的"7 态"描述保留为历史验收口径，现行状态机以本 ADR 为准。
- 上线需要一次生产迁移（0030 → 0031），按既有发布手册单独授权执行。
