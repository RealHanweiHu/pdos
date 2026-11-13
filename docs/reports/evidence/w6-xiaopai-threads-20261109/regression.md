# 受影响范围回归（2026-11-10）

新建隔离库：`tools/local_environment.py create`（端口 56726，已于收尾 destroy）。`create` 的 head→base→head 与 seed 通过，其中含最终版 `s0_0880`。显式 `TEST_DATABASE_URL`，未用 `.env`。

范围：`tests/projects/discussions_pg`、`team_pg`、`work`、`work_pg`，`tests/my_work`，`tests/exports`，`agent/kernel` 的上下文投影与会话依赖（`test_context_projection*.py`、`test_conversation_acl*.py`），`agent/memory/test_memory_recall_pg.py`，`core/test_trusted_source_work.py::test_migration_matches_orm_and_test_guard`、`core/test_public_api.py`、`core/command_catalog`，表目录（`test_m3_lifecycle_catalog.py`、`test_combined_registries.py`），`tests/workflows`，`tools/tests/test_workflow_replay_check.py`。

| 结果 | 个数 | 说明 |
|---|---|---|
| 通过 | 608 | 含 ORM 与迁移比对、`test_agent_thread.py` 11 例 |
| 失败 | 3 | 表目录用例：`discussion_agent_requests` 新增的 `notified_wait` 未登记进 `COVERED_COLUMNS`。补登后两个文件 75 例全过 |
| 跳过 | 7 | 3 个检查点保留用例需独立检查点库（与本项无关）；4 个回放检查缺本地 Temporal 二进制。软链主仓库已有的二进制后补跑 4 例通过（注册 18 个工作流） |

另跑：`test_agent_thread_temporal.py` 1 例通过（投递工作流经本地 Temporal）；前端 `tsc --noEmit`、改动文件 eslint、`.mjs` 1942 项、`[...path]/route.test.ts` 90 项通过；`tools/validate_contracts.py` 通过。
