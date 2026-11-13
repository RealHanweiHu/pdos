# W11：D346 / D347 / D348 / D349 / D221 本地证据（2026-11-09 至 11-10）

只在本 worktree 带标记的隔离合成环境里做；没有云上操作、没有调用真实模型、没有真实外发。

- D346：`tools/tests/test_agent_runtime_environment.py` 3 项；把 realm 改回 `pdos` 时其中 2 项失败。
- D348：`server/tests/workflows/test_worker_shutdown.py` 13 项（含 3 项用本地 Temporal 二进制的真实 Worker：在途 Activity 跑完且不再取新任务；超过宽限期的 Activity 被取消；不响应取消的在上限内放弃并返回非干净退出；重复信号只停一次）。
- D349：`server/tests/ops/test_worker_metrics.py` 9 项，原 `test_metrics_and_alerts.py` 10 项、`test_worker_threads.py` 照常通过。
- D221：
  - 规则 29 项、PG 8 项（`server/tests/work_calendar/`），在 `local_environment.py create` 新建的库上跑（head→base→head 往返含 `s0_0910`，通过；11-10 第五轮集成改号为 `s0_0870`）。
  - 全表守卫：ORM 与迁移一致、定义者函数属主、AI 角色无业务 DML、RLS 与权限，以及账户 PG，共 17 项通过。
  - 前端：typecheck、lint（0 错误，4 条旧警告）、相关 node 测试 54 项通过；合同只增加 3 个接口，校验通过。
  - 浏览器走查截图 `d221-01`–`d221-06`：
    - 管理员亮色：草稿检查、保存、试算 2027-01-29 10:00 加 1 个工作日 → 2027-02-22 周一 10:00；
    - 暗色；
    - 375px 暗色和编辑表单，无整页横向滚动；
    - 非管理员只读。
  - 走查中发现并修好：试算起点原先按浏览器时区读取。
- D221 决定：用户 11-09 定为租户管理设置、不进附录 A，工厂与供应商日历分开且带版本（[P117](../../../design/2026-10-08-pdos-next-design-confirmation.md#p117)）。11-10 结果回执加上日历名称（`calendar_name`），日历与运维 PG 用例 40 项通过。
- D347（11-10）：AT-47 演练链补上测试结果一环，`server/tests/ops/test_restore_drill_pg.py` 在干净环境上通过（约 4 分钟）。
  - 环境：新建测试库、检查点库、原生 Temporal，以及运行时状态库。其中运行时状态库由修好的 `agent_runtime_environment.py start` 直接装好 schema，这也是 D346 的端到端验证。
  - 链：工程配置 → 测试结果（上传报告，`test.results.import` 按已接受的计划判定为通过；运行状态是 `results_pending`）→ 制造发布 → 固定该测试运行的发布包 → 两项具名决定 → 交接。
  - 恢复后：
    - 七个存储全部一致；
    - 补回主机配置后，测试结果页和其余 6 个页面读取都与备份时刻完全一致；
    - 重放不写入，投递意图只有 1 个；
    - Temporal 两种情形下，每个工作流 ID 都只运行一次；
    - 回放检查 20 条历史全部通过。
  - 未补回签发方配置时的差异全部写在 `at47-unconfigured-differences.json`：
    - 当前性由“当前有效”变成“需要重新核对”；
    - 测试结果页上 4 个专业权威变成“签发方不可用”：没有事实引用和来源读取，原因加 `TRUSTED_ISSUER_UNAVAILABLE`、`SYNTHETIC_AUTHORITY_NOT_ALLOWED`；
    - 运行的读集只少掉权威来源。
  - 演练按这条规则逐项断言。
  - 证据：`at47-drill.json`、`at47-backup-manifest.json`、`at47-unconfigured-differences.json`。
- 测试库、检查点库、两个 Temporal 开发服务、运行时状态库、本地备份与恢复目录、API 和 Web 预览都已销毁或停止。
