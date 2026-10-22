# PDOS

本分支是用户批准的清理后快照，仅有一个无父提交，不发布原开发分支的历史提交或旧工程归档标签。原八批本地提交仍保留于开发机器；本快照的出处、验证与发布边界见[快照说明](docs/reports/evidence/repository-sync-20261022/snapshot-publication.md)。

当前主线是 **[pdos-next/](pdos-next/README.md)**：Next.js + FastAPI + PostgreSQL + LangGraph + Temporal，按[完整目标架构 v1.1](docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md)建设。

开发前阅读 [AGENTS.md](AGENTS.md)；可用能力、验证证据与剩余缺口以[唯一活动清单](tasks/ai-native-integrated-todo.md#current-queue)为准。安装与本地运行见 [PDOS Next 说明](pdos-next/README.md#独立安装和检查)。

## 目录

- `pdos-next/`：现行应用、迁移、契约、测试与本地工具。
- `packages/pdos-agent-runtime/`：共用 Agent 持久运行框架。
- `server/scripts/agent_runtime_environment.py`：共用状态库和 Temporal 开发服务管理；`server/golden/` 保留原资格证据，不授予新工程资格。
- `infra/`、`assets/`、`certs/`：仍需保留的运行设施及复用资产。
- `docs/`、`tasks/`：设计合同、决策、验证证据与活动状态。

## 原工程归档

原 `server/` + `web/` 已于 2026-10-08 停用，业务源码、旧迁移、旧测试、旧开发入口和旧 CI 已从当前目录清理。完整原工程仅保存在开发机器的本地 Git 标签 `original-final-2026-10-08`，没有随本快照上传；需要恢复时由持有本地归档者单独导出，不覆盖现行工作目录。旧版依赖缓存和私有环境文件未纳入此次源码删除。

旧生产环境下线尚待用户按[下线手册](docs/runbooks/original-production-decommission.md)执行。根目录生产 compose、部署与发布核对脚本为此保留；旧版构建须在归档标签的独立检出中运行。此次仓库清理不操作生产、数据库、存储或历史备份。

旧 CI 随原工程移除；当前分支的本地检查结果和原有未验收项见唯一活动清单。
