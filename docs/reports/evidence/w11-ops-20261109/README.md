# W11：D346 / D348 / D349 / D221 本地证据（2026-11-09）

只在本 worktree 带标记的隔离合成环境里做；没有云上操作、没有调用真实模型、没有真实外发。

- D346：`tools/tests/test_agent_runtime_environment.py` 3 项；把 realm 改回 `pdos` 时其中 2 项失败。
- D348：`server/tests/workflows/test_worker_shutdown.py` 13 项（含 3 项用本地 Temporal 二进制的真实 Worker：在途 Activity 跑完且不再取新任务；超过宽限期的 Activity 被取消；不响应取消的在上限内放弃并返回非干净退出；重复信号只停一次）。
- D349：`server/tests/ops/test_worker_metrics.py` 9 项，原 `test_metrics_and_alerts.py` 10 项、`test_worker_threads.py` 照常通过。
- D221：
  - 规则 29 项、PG 8 项（`server/tests/work_calendar/`），在 `local_environment.py create` 新建的库上跑（head→base→head 往返含 `s0_0910`，通过）。
  - 全表守卫：ORM 与迁移一致、定义者函数属主、AI 角色无业务 DML、RLS 与权限，以及账户 PG，共 17 项通过。
  - 前端：typecheck、lint（0 错误，4 条旧警告）、相关 node 测试 54 项通过；合同只增加 3 个接口，校验通过。
  - 浏览器走查截图 `d221-01`–`d221-06`：
    - 管理员亮色：草稿检查、保存、试算 2027-01-29 10:00 加 1 个工作日 → 2027-02-22 周一 10:00；
    - 暗色；
    - 375px 暗色和编辑表单，无整页横向滚动；
    - 非管理员只读。
  - 走查中发现并修好：试算起点原先按浏览器时区读取。
- 测试库、API 和 Web 预览都已销毁或停止。
