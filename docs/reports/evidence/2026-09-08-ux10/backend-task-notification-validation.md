# UX10 Task / Notification 后端增量验证

日期：2026-09-08。范围为 Task 列表批量依赖读取与通知摘要 SQL 聚合，不代表全仓门禁、三页首屏性能或 V1 Phase Exit 通过。

本文记录本任务实际执行的命令与工具返回结果。测试 stdout 未另存为原始日志文件；下面的结果行是工具输出转录，不作为完整原始日志展示。

## 修改与查询预算

- `server/app/domain/tasks.py`：TaskService.list 从逐任务读取依赖改为一次任务查询、一次 tenant/project 限定的批量依赖查询；非空列表固定 2 个 SELECT，空列表 1 个 SELECT。两次读取使用同一 REPEATABLE READ 快照。单条 get 与写入路径仍使用原依赖读取逻辑。
- `server/app/domain/reminders.py`：通知列表与按 policy_key 的 SQL GROUP BY 共 2 个 SELECT；未读总数为分组计数之和，不再将全部未读 policy_key 逐行读取到 Python。列表与摘要共用 REPEATABLE READ 快照。
- 新增 `server/tests/test_task_list_query_budget.py`：1／500 个任务、500 任务场景的 1,494 条依赖、空列表、依赖 UUID 排序、全部 readiness 分支、get 返回一致性、租户/项目边界，以及前置任务在两次读取之间完成的快照一致性。
- 新增 `server/tests/test_notification_query_budget.py`：2／2,000 条未读，另有 50 条已确认通知、100 条其他收件人的未读通知与 1 条待发通知；检查 limit=50、完整分组计数、收件人隔离、跨租户空结果和两查询预算。

## 独立测试环境

- 工作目录：`/Users/huhanwei/Documents/ai-native-R&D-platform/server`。
- Python：`/private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python`，使用前序冻结升级依赖环境。
- 专用容器：`pdos-ux10-tasks-test`。
- 镜像：本机已缓存的 `pgvector/pgvector:0.8.6-pg16-bookworm`。
- 监听：仅 `127.0.0.1:58433` 映射至容器 PostgreSQL 5432。
- 数据库与用户：均为 `pdos_test`；密码为临时测试值 `pdos-test-only`。
- 无持久卷；容器使用 `--rm`。fixture 先校验测试数据库名称，再执行 Alembic head 迁移及租户表清理。
- 未使用 root 的 58432 测试实例，未连接开发或生产数据库，未修改 `/private/tmp/pdos-ux10-20260908` 冻结基线。
- 测试完成后实际执行 `docker stop pdos-ux10-tasks-test`，工具返回容器名称且退出码 0；容器随 `--rm` 自动删除。

启动命令：

```sh
docker run --pull=never --rm -d --name pdos-ux10-tasks-test \
  -e POSTGRES_DB=pdos_test -e POSTGRES_USER=pdos_test \
  -e POSTGRES_PASSWORD=pdos-test-only \
  -p 127.0.0.1:58433:5432 pgvector/pgvector:0.8.6-pg16-bookworm
```

首次尝试使用未缓存的 `0.8.6-pg16` 标签后客户端等待下载；随后改用上述已缓存标签启动成功，原下载客户端已定位并终止。该首次尝试不是测试通过证据。

## 58 项相关回归

以下两批测试互不重复，共 58 项；不是全仓测试。命令从上述 server 工作目录运行，本机 Docker/socket 访问使用经过工具审批的隔离测试执行权限。

```sh
TEST_DATABASE_URL=postgresql://pdos_test:pdos-test-only@127.0.0.1:58433/pdos_test \
  /private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python -m pytest \
  tests/test_task_list_query_budget.py tests/test_work_items_api.py \
  tests/test_notification_query_budget.py tests/test_reminders_api.py \
  tests/test_reminder_scheduler.py tests/test_reminder_delivery.py -q --tb=short
```

工具返回：退出码 0，`56 passed in 62.91s (0:01:02)`。

```sh
TEST_DATABASE_URL=postgresql://pdos_test:pdos-test-only@127.0.0.1:58433/pdos_test \
  /private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python -m pytest \
  tests/test_task_actions_api.py -q --tb=short
```

工具返回：退出码 0，`2 passed in 3.29s`。

在这两批之前还运行过 Task 查询预算与 work-items 的 7 项初验，返回 `7 passed in 16.86s`；其用例已包含于上述 56 项，不重复计入 58 项。

## 静态检查

```sh
/private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python -m ruff check \
  app/domain/tasks.py app/domain/reminders.py \
  tests/test_task_list_query_budget.py tests/test_notification_query_budget.py

/private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python -m ruff format --check \
  app/domain/tasks.py app/domain/reminders.py \
  tests/test_task_list_query_budget.py tests/test_notification_query_budget.py

/private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python -m mypy \
  --follow-imports=silent --cache-dir /private/tmp/pdos-task-list-mypy \
  app/domain/tasks.py app/domain/reminders.py \
  tests/test_task_list_query_budget.py tests/test_notification_query_budget.py

/private/tmp/pdos-v1-improvement-deps/server/.venv/bin/python -m compileall -q \
  app/domain/tasks.py app/domain/reminders.py \
  tests/test_task_list_query_budget.py tests/test_notification_query_budget.py
```

均退出码 0。工具结果分别为 `All checks passed!`、`4 files already formatted`、`Success: no issues found in 4 source files`；compileall 无错误输出。mypy 为这四个文件的定向检查，不是全仓类型检查。

## 追加只读审查

随后只读审查了新增 `server/app/api/review_candidates.py`、`RiskCandidateService.list_visible_candidates`、Task 与通知改动、相关权限入口及测试，未发现必须修复的权限、快照或连接资源问题；本轮未重跑候选聚合 API 测试，其运行结果应使用该功能负责人的独立记录。

- 候选聚合仅 GET，由 current_context 绑定 tenant；FINDING_VIEW 排除外部角色。只有 Owner/Admin 传入空成员过滤，其余内部角色按同 tenant 的直接项目成员关系限定；项目与风险通过 tenant/project 双条件关联，只返回 draft。浏览器传入的查询参数不参与权限范围计算，口径与 ProjectService.list、ReviewInboxService.digest 一致。
- Task 的 API 仍先执行 WORK_ITEM_VIEW 项目授权；两条领域查询均绑定 tenant/project，依赖关联也校验 tenant/project。预取结果和单条读取使用同一构造函数，空依赖元组不触发额外查询。
- 通知列表及摘要均按 tenant/recipient 过滤；已确认历史仍可在列表展示，未读计数仅包含 fired，未改变既有收件人授权语义。
- 所有查询结果在连接上下文内消费；成功、异常或空列表提前返回均退出上下文，释放只读事务与连接。Task 与通知两次查询使用同一快照，避免列表和派生状态取自不同提交版本。

候选聚合仍返回可见候选的完整列表，Task 列表仍返回项目全部任务；本轮没有新增分页或修改返回合同。是否达到 UX10 的导航至可操作内容 P95 <1.5s，须以 root 后续固定设备、网络与数据规模的浏览器测量裁决。
