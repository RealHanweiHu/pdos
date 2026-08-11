# PDOS · AI-native 产品开发操作系统（工作名）

制造业产品开发的过程记录与 AI 装配层：事件驱动 Agent 产出发现，人审裁决落库。
按 [preview.zip 规格](docs/specs/cehub-v3.2-preview/) 全量建设；老 CEHub 为可选代码复用源，最终由本系统替换。

## 文档索引

| 文档 | 内容 |
|---|---|
| [执行计划](docs/design/2026-08-09-preview-execution-plan.md) | 六 Sprint 工作项与验收、基础设施复用参数、方法论审查纪律（§11） |
| [汇合决策](docs/design/2026-08-09-cehub-v32-convergence.md) | 规格地位、CEHub 角色、切换策略 |
| [UI 基线](docs/design/2026-08-09-ui-baseline.md) | 设计系统 token、信息架构、三承重界面交互（已拍板） |
| [结构与实施校准](docs/design/2026-08-10-structure-and-delivery-review.md) | 六层结构确认、已收口冲突、进入 S0-1 的条件 |
| [当前执行队列](tasks/todo.md) | 当前工作项的可验证切片；不替代唯一执行计划 |
| [产品提案 v0.3](docs/design/proposal.md) / [M0 计划](docs/design/m0-plan.md) | 历史工程参考（连接器/检查项导入/LLM trace 纪律仍取用） |
| [调研报告](docs/research/report.md) | 11-agent 全网调研（Attio/Lightfield 等） |

## 快速开始（开发）

```bash
cp .env.example .env        # Sprint 0/1 无需 LLM key；Sprint 2 前填写所选供应商凭据
docker compose up -d        # PostgreSQL(pgvector) + MinIO
# 脚手架就绪后: 迁移 + 启动命令见执行计划 S0-1
```

## 不可协商项（摘要）

1. AI-native：Sprint 2 起 AI 在关键路径，拆除测试为验收判据
2. AI 输出人审：Agent 唯一写出口 = finding；`pdos_agent` 数据库角色零业务表写权限
3. 不替代 ERP/MES/PLM；SoR 边界见规格
4. Alembic 迁移与 schema 永不脱节；测试库独立隔离
