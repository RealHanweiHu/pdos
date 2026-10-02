# 排程资源调整：真实 PostgreSQL 最小集成测试交接

2026-09-30。新增 `server/tests/test_resource_reallocations_postgres.py`，7 个测试函数、13 个参数化场景。本轮仅编写测试及运行静态检查，**没有连接数据库、执行 pytest、迁移或运行浏览器**。真实执行由协调会话分配并核对隔离环境后统一进行；57440 只是候选，本文不将其记作已核对地址。

## 运行条件与命令

1. 协调会话明确核对独立临时 PostgreSQL 16 `pdos_test`，并将完整连接串显式设为进程环境变量 `TEST_DATABASE_URL`。测试不读取 `.env`，不使用存续联验库。
2. 在协调会话核对过的隔离库迁移到执行时真实 Alembic head。测试自身不建库、迁移或调整 schema。需有当前资源容量、优先级、预约、调整、审计表及对应 SQL 守卫/函数。
3. 只接受 localhost、127.0.0.1 或 ::1 及显式端口；在创建 engine/连接前调用 `require_test_database_url`，并额外拒绝 **57432、57433、57434、57439**、任何 URL 查询参数及未声明隔离的环境。缺少 URL 或 `PDOS_SCHEDULE_TEST_ISOLATED=1` 会直接失败，不跳过或回退地址。
4. 测试账号需要该隔离库内种子和真实领域写入权限、相应函数执行权限，以及 `session_replication_role` 的 SET 权限。后者仅用于本例专属租户的清理，不用于业务执行。所有并发会话使用同一数据库账号，以便观察自己的 `pg_stat_activity` 锁等待。

以下命令仅由协调会话在完成环境核对后执行。`TEST_DATABASE_URL` 必须已经显式注入，不能拿占位文本或候选端口替代核对。

```sh
cd "/Users/huhanwei/Documents/ai-native-R&D-platform/server"
: "${TEST_DATABASE_URL:?须先由协调会话核对并显式设置隔离测试连接串}"
PDOS_SCHEDULE_TEST_ISOLATED=1 TEST_DATABASE_URL="$TEST_DATABASE_URL" \
  .venv/bin/pytest -q tests/test_resource_reallocations_postgres.py \
  > ../output/parallel-schedule-20260930/postgres-test-pytest.log 2>&1
```

不要并入调用全局 `clear_test_tenants` 的测试组合。此文件没有引用该辅助函数；并发在用例内部完成，无需额外并行测试插件。若预检、种子、清理或用例失败，保留原日志并回传具体失败；不关闭原 N/P/Q 条目，不用静态通过替代真实事务证据。

## 每例种子与清理边界

每例生成随机专属租户 `schedule-pg-<UUID>`，创建真实资源管理员（OWNER）、两个不同项目的具名 PM 和一个无项目权限的 PM。只为最小项目边界直接插入租户、用户、工作流、项目及成员；每个项目使用自己的工作流。项目采用既有兼容的 active 边界，这不构成 G1 或初版计划批准的验证。

通过真实领域服务依次发布全天 UTC 日历、单单位 bench 容量、有效优先级政策，创建两个任务、登记关联真实任务的 ScheduleNode，提出并按场景正式确认预约。原预约窗口相隔一小时，调整后的正式预约窗口整体延后一天，容量版本覆盖全部窗口。待确认分支保持原预约请求不变。

业务路径保留 SQL 触发器、外键、权限核对、事件及审计写入；预检、读取和各并发连接均核对 `session_replication_role=origin`。只有两个故障注入点使用 monkeypatch，并且先调用真实实现或核对真实 SQL 写入，其他 SQL、授权、快照、容量和领域动作不 mock。

清理只按本例 tenant_id 删除显式表清单内的种子和衍生记录，再删除该租户。由于回执/审计/版本为不可变记录，清理事务内使用 `SET LOCAL session_replication_role=replica`；退出事务后核对恢复为 origin、租户已删除。不执行 TRUNCATE、全租户清理、序列重置、DDL，也不触碰 golden-case。清理失败作为测试失败报告，不自动扩大删除范围。协调会话可在全部验证结束后统一处置专属临时实例。

## 覆盖与可观察判据

| 测试函数 / 参数 | 场景数 | 真实断言 |
| --- | ---: | --- |
| `test_two_projects_save_named_approve_and_apply_real_reservations`：confirmed=true/false | 2 | 一份方案、两项目；缺少全部具名同意拒绝应用；无项目权限者拒绝确认；保存和批准不改变预约；项目 PM 仅看到本项目部分；正式预约分支释放旧预约、建立替换并确认新预约，待确认分支确认原预约；两活动区间不重叠；单应用回执；baseline/commitments 不变；应用事件/审计增量为 8 或 4。 |
| `test_waiting_two_connection_submit_and_approval_are_idempotent` | 1 | 两独立后端 PID 对同一提交 request_id 同时等待真实 advisory lock；只保存一次，事件和审计各增加 2；同一具名批准 request_id 同时等待项目锁，只写一次决定及一次事件/审计；相同编号换内容拒绝。 |
| `test_drift_refuses_saved_approved_content_without_partial_application`：original_release、priority_version、priority_suspended、capacity_version、competing_occupancy | 5 | 分别由真实服务释放原预约、发布新政策、暂停政策、发布新容量、确认目标窗口内第三笔真实占用；管理员复核失败，项目 PM 收到不泄漏另一项目细节的通用阻塞；应用拒绝，拒绝前后本租户表快照完全一致。 |
| `test_ended_actual_task_source_refuses_application_and_keeps_original_reservations` | 1 | 真实任务 transition 到 skipped 后，应用由实际来源守卫拒绝；即便应用已开始释放/提出替换，事务结束后仍保留原预约、回执和审计快照。该用例验证应用时的执行资格，未宣称静态预览已覆盖任务状态。 |
| `test_two_connection_application_race_has_one_receipt_and_no_double_occupancy` | 1 | 两独立连接同时等待同一项目锁后应用同一请求；取得同一应用回执，仅一笔应用及两笔活动预约，事件/审计只增加 8；再次重试无新写入。 |
| `test_application_and_withdrawal_race_have_exactly_one_terminal_winner` | 1 | 应用与提出人撤回同时等待项目锁，恰好一个终态生效；应用赢则没有撤回，撤回赢则零应用且原正式预约保持。 |
| `test_real_transaction_rolls_back_all_reservations_receipts_and_audits_then_recovers`：second_confirmation、application_audit | 2 | 第二次确认前已在真实事务内确认第一笔新预约；或真实应用行、事件、审计 SQL 写入后注入异常。原预约/区间、预约回执、优先级绑定、替换映射、应用回执及全部事件/审计的拒绝前后快照严格相等；解除故障后用原 request_id 成功应用，再重试无新增写入。 |

并发观察使用 AUTOCOMMIT 监测连接避免活动视图快照缓存，确认两个后端均处于 `wait_event_type=Lock` 后才放开控制锁。等待设有上限：连接 statement_timeout 15 秒、lock_timeout 10 秒，观测 6 秒、同步 8 秒、结果 20 秒。未实际进入锁等待会失败，不能把两个顺序调用记作并发通过。

## 本轮已验证与尚未验证

- AST 解析及 compile 通过；模块未执行，数据库连接数为零。记录：[语法日志](../../../../output/parallel-schedule-20260930/postgres-test-syntax.log)。
- 新文件 Ruff 通过。记录：[静态检查日志](../../../../output/parallel-schedule-20260930/postgres-test-lint.log)。
- 新文件严格 mypy（`--follow-imports=silent`）通过。记录：[类型日志](../../../../output/parallel-schedule-20260930/postgres-test-types.log)。
- 本次测试文件 SHA256：`bafc42366994a833a756b53731b761638f37065a2c962104e3bd398a2df4d0d1`。

真实种子与当前迁移相容性、事务/触发器行为、锁等待及回滚判据均待协调会话在核对过的环境执行。HTTP、浏览器、联合构建和人工出口不在本次测试文件的验证范围内。没有重跑首轮已通过的纯单元/前端检查，没有改 schema、迁移、公共文件或活动清单。
