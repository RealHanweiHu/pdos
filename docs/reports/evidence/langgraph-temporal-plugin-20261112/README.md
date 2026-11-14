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

## 阶段 3：合成租户打开开关，真实模型试运行（同日）

用户 2026-11-12 授权阶段 3，并选择“在隔离库新建合成租户、真实调用 MiniMax”。综合预览库没有动。

**环境**：隔离库 `de9db19e`；每轮新建一个合成租户（测试夹具生成的人员、品类、型号，4 小时成员资格）；模型为本机已配置的 MiniMax-M3，按[本地开发 MiniMax 策略](../../../design/2026-10-23-local-development-minimax-policy.md)运行。做法是把本机模型运行时元数据里的服务商条目复制一份、改绑到合成租户，放在测试临时目录；API Key 仍在本机安全存储里，脚本不读取也不打印。模型配置、本人预算都经真实的 T1 命令保存。`PDOS_XIAOPAI_GRAPH_TENANTS` 只含该合成租户。Temporal 为每轮独立启动的本机开发服务。

```bash
PDOS_GRAPH_PLUGIN_REAL_TRIAL=<本机模型运行时元数据文件的绝对路径> \
  uv run pytest tests/agent/kernel/test_xiaopai_graph_plugin_real_trial.py -q -s
```

不设置该环境变量时这个文件整体跳过，不会在常规测试里调用真实模型。

**三个合成问题**：不查资料的简单问答（个人入口）；针对一份已登记的合成试产记录提问（品类入口）；一个范围含糊的请求（品类入口）。

**结果**（三轮，共 9 次运行，全部走 `XiaopaiGraphWork`；每条历史都用 Replayer 回放通过；结束时没有占用中的 token）：

| 轮次 | 问题 | 状态 | 用时 | token | 执行次数 | 历史事件 | 历史 JSON 字节 | 最大单个 payload |
|---|---|---|---|---|---|---|---|---|
| 1 | 简单问答 | completed | 7.6 s | 14,989 | 1 | 35 | 56,861 | 4,517 |
| 1 | 资料提问 | partial | 73.4 s | 152,690 | 2 | 47 / 89 | 385,377 / 392,563 | 22,711 |
| 1 | 含糊请求 | partial | 113.9 s | 193,870 | 1 | 119 | 974,565 | 28,745 |
| 2 | 简单问答 | completed | 6.6 s | 14,963 | 1 | 35 | 57,037 | 4,534 |
| 2 | 资料提问 | partial | 89.1 s | 227,435 | 2 | 95 / 89 | 941,019 / 399,279 | 28,701 |
| 2 | 含糊请求 | partial | 97.3 s | 190,596 | 2 | 47 / 89 | 449,974 / 515,968 | 23,545 |
| 3 | 简单问答 | completed | 7.7 s | 15,014 | 1 | 35 | 54,721 | 4,307 |
| 3 | 资料提问 | completed | 165.6 s | 164,313 | 1 | 95 | 464,719 | 23,900 |
| 3 | 含糊请求 | partial | 109.4 s | 249,598 | 2 | 95 / 89 | 1,234,808 / 517,600 | 36,385 |

原始记录：[第 1 轮](stage3-trial-round1.jsonl)、[第 2 轮](stage3-trial-round2.jsonl)、[第 3 轮](stage3-trial-round3.jsonl)（只含计数、体积和错误码，不含对话内容）。

**观察**：

- 真实运行里 continue-as-new 实际发生了 4 次（满 6 轮模型调用触发）。续接前后 `open` 和 `prepare_context` 各只执行 1 次，模型节点数与账本里的主图模型调用数对得上，没有重跑。
- 第 3 轮的资料提问给出了与登记材料一致、带依据的答案；其间隔离抽取子任务在 `tools` 节点内运行了 5 次。
- 最大单个 payload 36 KB，离 2 MB 上限很远；单次执行的历史最大约 1.2 MB。这个合成租户几乎没有历史上下文，体积比 W1 评测租户小得多，不能代表有长会话历史的真实使用。
- partial 的原因都记录了错误码和出处，全部来自合成租户自身或模型输出，与执行路径无关：
  - 第 1、2 轮：单次运行的 token 额度（默认值）用完。第 3 轮按评测的做法放宽到 200 万后，资料提问得以完成。
  - 合成租户没有启用技能包、没有基线型号，相关读取被拒绝。
  - 含糊请求：模型返回的追问里 `options` 不是数组，结构核对三次不通过，之后模型轮次预算用完。因此**真实模型下的“追问 → 答复 → 恢复”这次没有走到**；这条路径的验证仍然只有阶段 2 的合成模型用例。

**Temporal 库的访问权限和历史保留期**（Q4，本机开发环境）：

- 本机共用的 Temporal 开发服务只监听 `127.0.0.1:61596`，没有认证；历史存在 `.local/agent-runtime/temporal.sqlite`，文件权限 0644，所在目录权限 0700，只有本机当前用户能读。
- 各命名空间的历史保留期：`pdos-next-comprehensive-20261023` 为 7 天，`pdos-agent-local`、`default` 为 1 天。
- 新路径上历史里会有消息和模型输出，保留期内都留在这个 sqlite 文件里。本机合成数据可以接受；**任何部署环境在打开开关前，都要先定 Temporal 持久库的访问控制、备份和保留期**，这属于部署决定，本次没有涉及。
- 本次试运行用的是每轮独立启动、内存存储的开发服务，结束即销毁，没有往共用服务里写历史。

## 阶段 3 补充：三项未覆盖内容（同日）

### 研究、MCP 两类隔离子任务

- **研究**：`tests/agent/kernel/test_research_graph_plugin_process.py`（2 项）。把现有的“默认 API/Worker 研究”用例原样放到开关打开的条件下运行：worker 是生产入口 `pdos_next.workflows.worker.main` 的真实子进程，模型、搜索、网页为离线替身。`restart` 一项在研究子任务进行中两次杀掉 worker 并重启。结果：运行完成，主图走 `XiaopaiGraphWork`，主图没有写检查点，研究子任务的检查点线程只有 1 个，搜索和网页请求各只发出 1 次。需要显式的进程级测试环境（`PDOS_WORKER_PROCESS_CHECK=verified-local-synthetic` 和一个本机 Temporal 服务）。
- **MCP**：`tests/agent/kernel/test_mcp_graph_plugin_pg.py`（1 项）。沿用现有 MCP 夹具（真实的连接器准入与授权、网关、账本、隔离子图，模型为脚本，传输层为记录替身）。结果：运行完成，连接器只被调用 1 次，子图的读取记在 `mcp` 隔离下；**交给传输层的凭据和回复里的注入指令都没有出现在 Workflow 历史里**，历史里只有核对过的结果行。
- 顺带修了一条过时断言：`test_research_runtime_process.py` 末尾假定主图检查点线程名是旧格式，主图早已改为按会话分命名空间，所以这个需要显式开启的用例在旧路径上也会失败。现在改成对两条路径都成立的断言，旧路径 `api`、`restart` 两项通过。

### 真实模型下的追问恢复

`PDOS_GRAPH_PLUGIN_REAL_TRIAL_CASES=ask`。问题要求模型先问清目标市场再继续。结果：模型前两次给出的追问格式不合规，被核对环节打回；第三次合规后运行进入等待，脚本经真实接口提交答复“欧盟”，运行恢复并给出针对欧盟的答案。completed，93.7 秒，4 次模型调用，`route` 节点执行 4 次（两次不合规、一次等待、一次恢复）。[记录](stage3-trial-ask.jsonl)

### 长会话下的历史体积

`PDOS_GRAPH_PLUGIN_REAL_TRIAL_CASES=long`。登记 8 份各数千字的合成试产记录，在同一会话里连续 5 轮追问，每轮接续上一轮。[记录](stage3-trial-long.jsonl)

| 轮 | 状态 | 用时 | token | 执行次数 | 历史事件 | 历史 JSON 字节 | 最大单个 payload | 模型调用（含子任务） |
|---|---|---|---|---|---|---|---|---|
| 1 | partial | 237.8 s | 345,072 | 2 | 83 / 89 | 1,677,116 / 770,074 | 59,384 | 20 |
| 2 | failed（结果未知，已对账） | 424.1 s | 176,729 | 1 | 64 | 352,326 | 23,383 | 9 完成、1 失败 |
| 3 | partial | 242.5 s | 274,288 | 1 | 95 | 1,014,947 | 27,956 | 21 |
| 4 | partial | 429.9 s | 475,330 | 2 | 83 / 89 | 2,259,699 / 1,118,612 | 52,547 | 27 |
| 5 | partial | 284.9 s | 194,109 | 1 | 83 | 718,111 | 34,903 | 18 |

- **体积**：最大单个 payload 59 KB；单次执行的历史最大 2.26 MB（JSON 形式，含 base64 膨胀），发生在满 6 轮模型调用、即将续接的那次执行。续接发生 2 次，没有重跑。
- **第 2 轮**是一次真实发生的“结果未知”：服务商对一次主图模型请求没有返回可用结果。运行没有重发请求，按设计走了收尾 → 等待 300 秒 → 自动对账，最终状态 failed，对账说明为“保留 0 条已提交动作，1 次不确定调用已结束等待”。服务商一侧的具体原因脚本没有记录。
- 其余 partial 的原因：本轮查找预算用完（每轮都有）、模型返回的追问格式不合规导致核对不通过（第 3、4 轮）、合成租户未启用技能包。都与执行路径无关。
- 5 轮里只有第 5 轮给出了成形的汇报，前几轮多数资料没读完就用尽了查找预算。所以这组数据说明的是**体积和路径行为**，不说明答案质量。

### 合并复跑

全部新路径用例、进程级用例（新旧两条路径的研究用例）、试点、工作流与回放，加上旧路径的 MCP 与子任务停止用例：142 通过、1 跳过，约 18 分钟。跳过的是真实模型试运行，它在不设置环境变量时不运行。进程级用例用的本机 Temporal 开发服务是为这次复跑临时启动的内存实例，跑完已停止。

## 环境清理（同日）

用户要求清理后，删除了隔离库容器 `pdos-next-test-20261002-de9db19e`、检查点库容器 `pdos-next-state-de9db19e-pg`（连同各自的数据卷）、网络 `pdos-next-state-de9db19e`，以及 `.local/graph-plugin-runtime-20261112.json`、`.local/graph-plugin-workflows-20261112.json` 两个状态文件。删除前核对了容器 ID 和环境标记与创建时的记录一致。库里只有合成测试数据，没有备份。本页前文提到“隔离库保留”的说法以此为准。其他环境没有动。

## 下线原路径（同日，确认稿 P101）

用户要求直接下线原路径（尚未发布）。改动见决策记录 §13。因为之前的隔离库已按要求删除，这次为回归另建了一套同样的隔离环境（标记 `8be51288`，测试库与检查点库各一个容器），回归结束后已删除；预览库等其他环境没有动。

**第一批**（不需要外部 Temporal 地址）：全部插件路径用例、迁移过的内核测试、`tests/automations/pg`、`tests/my_work`、`tests/workflows`、`tests/integrations/dingtalk`、`tools/tests`。678 项中 668 通过、8 跳过、10 失败：

| 失败 | 数量 | 判断 |
|---|---|---|
| 已注册工作流数量的断言 | 1 | 这次下线造成，已改（19 → 17），改后通过 |
| `tools/tests/test_local_host_profiles.py` | 4 | 在上一个提交上同样失败，与本次无关（D384） |
| 自动化与钉钉的 5 个数据库用例 | 5 | 单独运行、按目录运行在改动前后都通过；只在排在某些内核测试之后时失败，同样的顺序在上一个提交上也失败。原有的测试顺序依赖，与本次无关（D383） |

**第二批**（需要外部 Temporal 地址和进程级环境的显式开启用例）：助手、嵌入查询、项目当前上下文、上下文清理、钉钉三组、worker 进程恢复、研究子任务进程用例，以及使用核对动作夹具的用例。34 项中 33 通过、1 失败。失败的是 `test_context_x3_temporal_pg.py`：一次结果续读在恢复“带观测时刻的列表”时报来源过期。它在上一个提交（原路径）上以完全相同的方式失败，是这个平时不跑的用例原有的问题（D384）。我只把它读取图状态的方式从主图检查点改成了 Workflow 历史。

对照方法：把上一个提交检出到临时目录，用同一个数据库运行同一组测试。

**没有覆盖**：没有再跑一次经过内核图的全部 171 个测试文件（阶段 2 那次约 44 分钟）；这次只跑了改动涉及的文件和上面列出的目录。真实模型试运行没有重跑。

## 清理主图检查点遗留代码（2026-11-13，D382）

改动见决策记录 §13.3。候选：提交 `74e4e745` 之上的未提交改动。为回归另建了一套隔离环境（标记 `ee1da33d`，测试库与检查点库各一个容器，另起一个内存态 Temporal 开发服务），回归结束后已全部删除；其他环境没有动。

**第一批**：`tests/agent/kernel`、`tests/agent/enterprise_search`、`tests/workflows`、`tests/my_work` 四个目录加 `tools/tests/test_workflow_replay_check.py`，共 3961 项，用时 1 小时 50 分：3900 通过、60 跳过（需要外部 Temporal 地址或真实模型的显式开启用例）、1 失败。

失败的是 `tests/agent/enterprise_search/test_recovery_pg.py::test_registered_family_search_and_authority_batch_stay_constant_sql_and_under_one_second`，断言“1 秒内”，实测 1.086 秒。对照：同一个库上单独再跑三次，当前代码 1 次失败、1 次通过，上一个提交 1 次失败（1.042 秒）。它不经过内核图，结果贴着阈值随机器负载波动，与本次清理无关（D385）。

**第二批**（显式开启，接临时 Temporal 服务）：worker 进程恢复、研究子任务进程用例、MiniMax 进程用例、品类采纳、MCP 子任务、检查点保留清理的数据库用例。13 项中 12 通过、1 失败；失败在 `test_worker_process_recovery.py`（等待 worker 状态超时），该文件随即单独重跑 3 项全部通过，属于整批负载下的等待超时（D385）。

**静态检查**：本次改动涉及的 Python 文件 ruff 全部通过。

**没有覆盖**：没有跑服务端全量；知识、自动化、钉钉等目录这次没有跑，它们不引用被删的名字（已用全仓搜索核对 `session_checkpoints`、`checkpoint_layout`、`execute(` 的 `answer` 参数）。真实模型试运行没有重跑。数据库函数 `automation_service_start` 仍写 `checkpoint_layout` 键，未改。
