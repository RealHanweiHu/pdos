# LangGraph 插件迁移 · 阶段 1 试点证据（2026-11-12）

对应清单 D378、确认稿 P100、[决策记录](../../../design/2026-11-12-langgraph-temporal-plugin-migration-decision.md) §10。

## 候选

工作区未提交改动，基于 `c13c3fd6`。新增依赖 `temporalio-langgraph==0.1.0`；`temporalio 1.34.0`、`langgraph 1.2.12` 不变。

## 跑了什么

在 `server/` 下，本机 Temporal 开发服务（`.local/tools/temporal`，内存存储，每个用例独立启动），不连数据库、不调模型、无出站：

```bash
uv run pytest tests/workflows/test_graph_plugin_pilot.py -q -p no:cacheprovider
```

结果：7 通过，约 57 秒。连同原有工作流测试与回放检查工具测试：64 通过、3 跳过（跳过的 3 项是原有的、需要数据库的检查点用例）。

| 用例 | 证明 |
|---|---|
| `test_summary_completes_node_by_node_and_replays` | 个人摘要图两个节点各作为一个 Activity 完成；历史用 Replayer 回放通过；历史里有运行数据、没有凭据特征串 |
| `test_worker_killed_inside_a_node_does_not_rerun_the_finished_node` | worker 子进程在第二个节点执行中被 SIGKILL，新进程接手后第一个节点没有重跑（执行 1 次），第二个节点重试 1 次后完成 |
| `test_signals_are_deduplicated_and_consumed_in_arrival_order` | 重复、非法、乱序、提前到达的 `resume` 信号：去重，按到达顺序消费；不追问的摘要工作流不受影响 |
| `test_pending_question_is_queryable_until_answered` | 待答复内容可由 query 读到，答复后清空 |
| `test_timed_out_attempt_is_retried_without_rerunning_earlier_nodes` | 节点首次尝试超过 start-to-close 超时，重试成功；之前的节点不重跑 |
| `test_stopped_node_closes_the_run_with_its_code_and_is_not_retried` | 节点以领域错误停止：不重试，Workflow 带错误码调用收尾 Activity |
| `test_workflow_rejects_anything_but_the_fixed_reference` | 信封多带一个字段即拒绝，任何 Activity 都没有执行 |

## 范围与替身

- 真实：个人摘要图（`summary_plugin_graph`）、节点外壳（`graph_nodes`）、Workflow（`PersonalSummaryGraphWork`）、驱动与信号队列（`graph_runtime`）、插件本身、Temporal 服务。
- 替身：摘要的数据库读写（`runtime.generate` / `persist` 和 scope 重建）、`open` / `close` / `reconcile` 三个图外 Activity。
- 个人摘要没有模型调用，“已完成节点不重跑”用节点执行次数证明，不是模型调用次数。

## 真实数据库端到端（同日补做）

用户选择另建隔离库。新建带身份标记的合成库：容器 `pdos-next-test-20261002-de9db19e`，`127.0.0.1:49789/pdos_test`，状态文件 `.local/graph-plugin-runtime-20261112.json`，迁移 up/down/up 通过（[日志](pdos-next-bootstrap-de9db19e/migration-roundtrip.log)）。原有的 `pdos_test`（f117bb5b，预览在用）没有动。新路径不使用检查点库。

```bash
uv run pytest tests/automations/pg/test_personal_summary_graph_plugin_pg.py -q -p no:cacheprovider
```

结果：4 通过。真实的有：经原生命令建立的私有项目与来源、已受理的自动化运行、worker 的插件接线（`graph_plugin`）、open/close Activity、每个节点从数据库重建 scope、摘要自身的读取与落库、本机 Temporal。

| 用例 | 证明 |
|---|---|
| `test_summary_runs_node_by_node_and_a_second_start_does_not_repeat_it` | 运行完成，结果与本人可读校验一致，无账本调用、无 token；`versions.execution_engine` 已记；对已终态的运行再启动一个工作流，只执行 open，不跑任何节点；历史里有运行数据，没有数据库连接串和密码 |
| `test_run_cancelled_between_nodes_stops_before_persisting` | 两个节点之间取消运行：第二个节点重建 scope 时停下，不重试，不落结果 |
| `test_node_failure_is_recorded_once_without_a_retry` | 节点以领域错误停止：只执行 1 次，运行记为 `failed` 并带错误码 |
| `test_envelope_of_another_requester_is_refused_and_the_run_is_untouched` | 伪造请求人的信封在 open 被拒，工作流失败，运行保持 `queued`、未被改写 |

合并复跑（数据库端到端 + 试点 + 原有工作流测试 + 回放检查工具）：68 通过、3 跳过。

## 历史体积

见 [pilot-history.jsonl](pilot-history.jsonl)。真实数据库上的一次个人摘要（1 个关注项目、1 条条目）：23 个事件，历史 JSON 32,403 字节；合成小载荷为 19,903 字节。

## 没有覆盖

- continue-as-new 与 workflow 侧节点中断只做过一次性实测，未入测试套件（阶段 2 的主图测试覆盖）。
- 个人摘要没有模型调用和人工追问；这两类行为的真实路径留给阶段 2。
- 隔离库 `de9db19e` 保留，供阶段 2 继续使用；清理放在检查点集中做。

## 阶段 2：小Pai 主内核（同日）

候选：工作区未提交改动，基于 `c13c3fd6`。隔离库同上（`de9db19e`）；为了回归旧路径，另在同一标记下建了独立检查点库（`127.0.0.1:52001`，状态文件 `.local/graph-plugin-workflows-20261112.json`）。新路径不使用检查点库。

```bash
uv run pytest tests/agent/kernel/test_xiaopai_graph_plugin_pg.py \
  tests/agent/kernel/test_plugin_graph_waits.py \
  tests/workflows/test_xiaopai_graph_determinism.py -q -p no:cacheprovider
```

结果：39 通过，约 97 秒。

- `test_xiaopai_graph_plugin_pg.py`（13 项）：经认证的 API → Temporal → 插件执行的主图 → 真实数据库。只有模型服务商是合成的脚本客户端，它统计收到的每一次请求。覆盖 completed、partial（两种）、cancelled、failed、needs_reconciliation、追问恢复与重复信号、请求发出后尝试丢失、已记账结果丢失后重放、continue-as-new、读取结果与续接数据存引用、开关。
- `test_plugin_graph_waits.py`（10 项）：进程内按 Workflow 的方式驱动主图的节点体和条件边，验证采用与追问都按引用恢复，以及各种不合法恢复被拒绝。
- `test_xiaopai_graph_determinism.py`（16 项）：未装插件的 worker 上录制 5 条 `XiaopaiWork` 历史，在装了插件的完整注册表上回放；条件边是 state 的纯函数；每个节点声明了归属。

旧路径回归（需要检查点库）：`test_graph`、`test_checkpoint`、`test_category_adoption`、`test_category_wait`、`test_public_temporal_domain`、`test_run_reconciliation_temporal`、`test_activity`、`test_run_continuation`、`test_session_checkpoints`、个人摘要两个文件，共 128 通过、3 跳过。

`graph.py` 重构的回归：对所有直接构造内核或执行内核图的测试文件（171 个）整批运行，3630 通过、14 跳过、1 失败，用时约 44 分钟。失败项是 `tests/knowledge/pg/test_answer_footprint_pg.py::test_uncited_private_parent_footprint_remains_when_only_public_source_is_requeried`（模型节点内报“当前身份没有这个品类的操作权限”）。单独运行时，它在改动后的 `graph.py` 和原始 `graph.py` 上都通过，因此判断为整批运行下的偶发失败，原因没有查明，已登记 D380。

历史体积见 [stage2-history.jsonl](stage2-history.jsonl)。

### 缺口 G1–G5（同日补完）

```bash
uv run pytest tests/agent/kernel/test_xiaopai_graph_plugin_pg.py \
  tests/agent/kernel/test_category_adoption_graph_plugin_pg.py \
  tests/agent/enterprise_search/test_assistant_graph_plugin_pg.py -q -p no:cacheprovider
```

- G1 品类采用真实全链路：`test_category_adoption_graph_plugin_pg.py`（1 项）。
- G2 隔离抽取子任务在 `tools` 节点内：`test_assistant_graph_plugin_pg.py`（1 项，需要检查点库）。
- G3 真实 worker 进程被 SIGKILL：主图文件内 1 项，子进程 worker 是 `xiaopai_graph_plugin_worker.py`。
- G4 工具执行中取消、模型应答期间真实撤回：主图文件内 2 项。
- G5 重试的进度事件、每节点重建耗时：主图文件内 2 项。

主图文件现在共 18 项。合并复跑（全部新路径用例 + 试点 + 工作流与回放 + 旧路径的图、采用、真实 Temporal、对账、撤回）：153 通过、2 跳过，约 6.5 分钟。

结论和两点说明见决策记录 §11.4；留到阶段 3 的部分见 §11.5。
