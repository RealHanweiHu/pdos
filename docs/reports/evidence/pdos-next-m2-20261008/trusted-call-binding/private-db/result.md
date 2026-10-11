# 0716 私有 PostgreSQL 端口验证

仅使用 `127.0.0.1:51698/pdos_test`，marker `3749a9d8-a9de-4544-87c7-6766338a73a8`。运行前核对现有容器 ID、标签、绑定端口、实际数据库与 environment_guard；各 Session 入口再次 verify_test_target，显式 TEST_DATABASE_URL，无 `.env` 后备。主库操作与真实模型调用均为 0。

## 已完成

- 实际初始 head 为 s0_0715；显式 upgrade s0_0716 成功。确认没有任何新可信 binding 后，仅往返 s0_0716 → s0_0715 → s0_0716；随后才创建本轮合成调用。没有重定位私有链，也没有升级公共分支或重跑整个旧链。当前实际 head、结构与角色证据见 `environment-schema.json`。Alembic 没有配置控制台输出，三个迁移 log 为空；wrapper exit 0、明确目标以及最终实际 schema 核对是其证据，不把空日志当成 SQL 执行记录。
- 实际 execution_binding NOT NULL、无 server default、结构 CHECK validated、未完成 Call 的 binding 不可变；真实 SQL 的 NULL/JSON null/缺键/已完成 T0 缺 Receipt/修改 binding 均被拒绝。12 张 M2 自持表 compare_metadata 差异 []。pdos_agent 对 agent_tool_calls 的 INSERT/UPDATE/DELETE 权限均为 false。
- 普通 pdos_next_app、actor=实际 Run.writer(agent)、requester=实际 human、产品范围：prepare 与 finish 运行在同一个 tenant_session；构造的合成 Receipt/Audit/Outbox 与 Call 一起提交。准备后、回执/Outbox 后、finish 后注入失败时，Call/Receipt/Audit/Outbox 全回滚，Product.lifecycle_epoch 的触发器更新也回滚。
- 已完成结果在 can_write 撤销、技能停用、资格撤销之后，仍由普通 app + 实际 RLS 当前读取检查恢复原 Call/Receipt。running/completed/partial/failed Run 均覆盖；记录 SQL，恢复过程没有 INSERT/UPDATE/DELETE。当前读取授权到期后拒绝恢复，原已完成事实仍保留。不同参数/命令摘要、缺读取 callback、旧 epoch 拒绝。
- 新调用读取真实持久 model Call 的回复参数/index，核对实际加载 AgentEvent 的 Run 归属；参数/index、跨 Run model Call、跨 Run load Event、旋转 route、撤销 qualification 均拒绝且无新领域 Call。
- 实库负例暴露预加载 Run 的 SQLAlchemy identity map 旧 epoch：另一事务更新 epoch 后，原 FOR UPDATE 没有刷新缓存（`stale-epoch-before-fix.log` 为 1 failed / 1 passed）。独占 execution.py 的 Run/Call 锁查询已增加 populate_existing=True，保留锁序；最终候选覆盖准备前预缓存旧 epoch，以及同 UOW SQL 改 epoch 后 finish 拒绝并全回滚。另只读恢复补 partial 终态，未放开新写。

## 最终选择与可复现入口

`final-private-candidate.log`：**76 passed / 12.87s**，其中 29 项使用实际 PostgreSQL，47 项为已有可信绑定纯端口测试。选择是：

```sh
python -m pytest -q tests/agent_kernel/postgres_execution_binding_cases.py tests/agent_kernel/test_execution_binding.py --tb=short
```

须由现有 tools/m2_verify.py wrapper 设置显式私库环境，并在 wrapper 前核对上述固定 port/marker。独立 PostgreSQL 文件使用 `*_cases.py` 命名，只能显式选择，避免普通 B7 主库全套自动收集这份固定 51698 的私有检查。

按 root 后续核对，graph.py 原 Command 是 langgraph.types 的 resume 控制指令，AST 同名识别为领域 Command 是误报。已改别名 GraphCommand；追加实际 interrupt/resume 中伪造 category/run/tenant/writer 的 answer 不改变服务器 Scope。该低影响修正单独受影响纯检查 **11 passed / 1.90s**，见 `graph-resume-pure.log`。与 76 项分开记录，不相加宣称统一候选或 M2 全套。当前独占 lint 通过。

前面的 19 项、中间 75 项以及缺 AgentEvent 测试 import 的失败，均为过程记录；本轮不重跑无变化的历史 217 项或此前 85 项纯选择。

## 明确未完成

- 合成的模型回复、加载 Event、资格行和 Receipt/Audit/Outbox 前置由测试 fixture 构造；真实 PostgreSQL 端口通过不等于真实模型资格。route callback 也只是本地合成配置，不是公共模型配置 head owner。
- 没有 service.execute、真实 Claim/Artifact 写入、公共 Context.agent_call_id、最终公共资格/执行权、公共 HTTP→Temporal、真实配置/SecretPort、并发整链或模型出站。仍由 root 在 B7 接线与验证。
- 私库公共 fixture 止于此前授权同步的 0404–0409：category-only actor=agent 构造合成 Receipt 时，lifecycle_reference_gate 更新 categories.lifecycle_epoch 被既有 Category UPDATE RLS 拒绝（42501），且整个 Call/Receipt UOW 回滚。已保留拒绝检查，没有修改公共守卫或授予 AI Category DML。root 应先对照其实际公共 head 是否已有修正；这里不能推断主库存在同样缺陷。主库 s0_0416 仅为 root 报告，M2 未访问。
- 往返发生于新 binding fixture 之前；目前保存了本轮不可变合成账本，不再删除数据或降级 0716。环境与历史证据保留。

当前源码冻结清单见 `source-manifest.json`；上层 `trusted-call-binding/source-manifest.json` 是此前 85 项纯检查点的历史快照。
