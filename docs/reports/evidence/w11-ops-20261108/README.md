# W11 运维：D211 / D212 / D213 本地证据（2026-11-08）

只在本 worktree 带标记的隔离合成环境里做；没有云上操作、没有调用真实模型、没有真实外发。

- `at47-drill.json`：AT-47 演练结果（`server/tests/ops/test_restore_drill_pg.py`，干净环境上的最终一次）。在交接“发送结果未知”时备份业务库、检查点库、运行时状态库、Temporal 历史和原件；恢复到新标记环境后全表行数与内容摘要、原件 sha256 一致；链路读取与备份时刻一致（未恢复签发方配置时只有适用性/来源状态降为“需要重新核对”）；重放原命令返回原回执、零写入；投递意图 1 个、`network_send=false`；Temporal 同点恢复与只恢复业务库两种情形下，每个工作流 ID 都只运行一次；在途维护工作流用当前代码回放通过。
- `at47-backup-manifest.json`：该次备份的清单（不含角色文件与口令）。
- 同一检查点：`tests/ops/` 14 项通过（指标与告警 10、聚合函数 PG 3、演练 1）；`tools/tests/test_workflow_replay_check.py` 4 项通过；迁移 `s0_0861 ↔ s0_0879` 单步往返通过（分支上的占位号；11-09 集成时改为 `s0_0867`，down `s0_0866`。下面两份演练 JSON 里的 `alembic_version: s0_0879` 是当时的实际输出，未改）；探针在本地真实环境取到事件积压、Temporal 无 Worker / 积压年龄、API 计数与网页探活失败并按阈值报出。
- 无库全量回归：10766 通过、1 失败（D42 自带的过时测试 `test_source_views::test_get_only_router_uses_current_context_and_read_snapshot`，集成分支上同样失败）、1964 个 ERROR 为缺库的 PG 用例。
