# Implementation Plan: PDOS Preview 全量建设

## Overview

本文件是执行控制视图，不是第二份产品计划。产品范围、Sprint 工作项与验收只以 `docs/design/2026-08-09-preview-execution-plan.md` 为准；这里负责把当前工作项拆成单次可实现、可验证的小任务，并在每次交接后保持唯一当前指针。

当前唯一指针：**Sprint 2 Exit Gate**。S0～S2 已实现，Sprint 2 生产部署与人工 smoke 已通过；进入 S3-1 前仍需选择或建立 1–2 个真实双跑项目，并获得人的明确出口确认。

## Architecture Decisions

- 保持 Next.js + FastAPI + PostgreSQL 10 schema + LangGraph(Python) + shadcn/ui 的既定栈。
- 业务写必须同事务产出事件与审计；Alembic 是 schema 变更唯一入口。
- Agent 只创建 finding；接受与应用是两个人工动作，apply 由服务端真值守门。
- `pdos_agent` 与 `pdos_worker` 对业务表零写权限；AI executor 不持应用角色。
- 测试只允许连接 `pdos_test`，保护失败时直接终止。

## Dependency Graph

```text
人确认结构校准
  → 首次本地 commit
  → S0-1 本地脚手架与 CI
      ├─ web 基线壳
      ├─ server /healthz
      └─ pgvector + MinIO + pdos_test 隔离
  → S0-2 migration 0001
  → S0-3 Auth/Tenant
  → S0-4 RBAC
  → S0-5 Event/Audit
  → Sprint 0 人工出口
```

RDS/pgvector/OSS 人工准备可与 S0-1 并行，但 ECS/Nginx/DNS smoke 必须单独授权，且只要求在 Sprint 0 出口前完成。

## Task List

### Phase 0: Baseline Freeze

- [x] 确认设计六层结构与六 Sprint 依赖链
- [x] 补齐 S0-1、DoR/DoD、状态与人工轨
- [x] 校准 finding 双动作、数据库角色和文档漂移
- [x] 人审本次校准并完成首次本地 commit（`d28d984`，未 push）

### Checkpoint: Baseline

- [x] 唯一执行计划、AGENTS、README、UI 基线口径一致
- [x] 仓库不含真实凭据
- [x] 首次 commit 已创建但未 push

### Phase 1: S0-1 Scaffold

- [x] S0-1a：建立根目录命令契约与环境校验
- [x] S0-1b：建立 FastAPI `/healthz`、Python 工具链与空 Alembic 环境
- [x] S0-1c：建立 Next.js 应用壳与 UI token 基础
- [x] S0-1d：建立 pgvector/MinIO、本地 `pdos`/`pdos_test` 与测试 fail-close 保护
- [x] S0-1e：建立 CI，跑 web/server lint、type、test、build 与 test DB migration smoke

### Checkpoint: S0-1

- [x] 无 LLM key 时本地依赖与空应用可运行
- [x] `/healthz` 与 web 首页运行时可访问（`make smoke-app`）
- [x] `pdos_test` migration smoke、完整测试、类型检查、构建全绿
- [x] 生产模板无密钥，未执行未经授权的外部操作
- [x] 唯一执行计划将 S0-1 标记为 `[x]`

### Phase 2: S0-2 Initial Schema

- [x] Alembic `0001_initial_entities` 创建 10 个冻结 namespace
- [x] `cehub_core` 建立 Tenant/User/Customer
- [x] `cehub_project` 建立首批 10 个项目域实体
- [x] composite tenant FK、状态、唯一性、索引与时间戳约束落库
- [x] downgrade→upgrade、metadata drift、隔离与完整门禁全绿

### Phase 3+: Canonical Sprint Sequence

S0-3～S2-7 已按唯一执行计划完成。当前执行 Sprint 2 出口：真实项目双跑选择与人工确认；出口通过后再按 S3-1→S3-7、Sprint 4、Sprint 5 与切换退役的 canonical 顺序展开。开始每个工作项时，在 `tasks/todo.md` 写入该项的 3–5 个实现切片，不提前复制后续 Sprint 细节。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 文档与执行状态再次漂移 | High | canonical checkbox + 单一 `tasks/todo.md` 当前指针 |
| 测试误连开发/生产库 | High | 库名 fail-close + CI 独立 `pdos_test` migration smoke |
| AI 进程取得业务写凭据 | High | 分角色/分进程注入 + migration 权限测试 + 红队测试 |
| 外部控制台动作阻塞开发 | Medium | 人工轨与本地轨并行，Sprint 出口前汇合 |
| S0-1 变成大而全平台搭建 | Medium | 子任务仅覆盖可启动空应用、依赖、隔离与 CI |

## Open Questions

- Sprint 2 试点需要哪 1–2 个真实 Project？当前生产 PDOS 库在 2026-08-12 部署抽查时 Project 数为 0；对现役 CEHub 的只读盘点已记录 4 个候选，推荐人工评估 `C4s 手持充气泵` + `S18-01 便携户外充气泵`。候选不等于选定，仍需人确认负责人、reviewer、观察窗口与退出条件；迁移留待 canonical S3-7。
