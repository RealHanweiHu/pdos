# LangGraph 执行迁移到 Temporal 官方插件 · 决策记录（用户 2026-11-12 确认）

- 状态：**已确认**。用户 2026-11-12 对 §9 的 Q1–Q8 答复“全部按推荐”，登记为确认稿 [P100](2026-10-08-pdos-next-design-confirmation.md#p100)；AGENTS.md 第 6 条和[运行架构收口合同](2026-10-07-agent-runtime-convergence.md)已同步修订。阶段 3 切换仍需另行授权。
- 起因：用户 2026-11-12 的任务书，要求把小Pai 从“一个大 Activity 里跑整张图 + PostgresSaver”迁到 Temporal 官方 LangGraph 插件：图在 Workflow 中运行，有 I/O 的节点各自成为 Activity。
- 清单条目：[D378](../../tasks/ai-native-integrated-todo.md#debt-board)。

## 0. 本次变更改动的冻结条款

| 现行条款 | 现行内容 | 变更后 |
|---|---|---|
| AGENTS.md 第 6 条 | LangGraph 管理能力内执行和检查点，Temporal 管理持久任务、等待、取消和恢复 | LangGraph 只定义图的结构、状态和路由；节点执行、检查点、等待、取消、恢复全部由 Temporal 承担。图内只用 `InMemorySaver`，持久性来自 Workflow 历史 |
| 收口合同表第 1 行、v1.1 第 964 行（“执行结构”图） | Workflow 历史只存固定工作引用 | 消息、模型输出、业务状态可以进入历史（用户 2026-11-12：数据隐私不再是约束）。密钥、凭据、令牌、签名 URL 仍然不得进入 graph state、runtime context、Activity 参数或返回值 |
| 收口合同“独立 PostgreSQL 检查点” | 主图检查点存 `pdos_checkpoints` | 新路径的主图不再写该库；旧 run 和隔离子任务继续使用，见 §4.4 和问题 Q2 |

不变的条款：唯一 Agent 小Pai；模型网关拒绝登记图之外的调用；AI 写入分级；模型传参不作为政策事实；worker 错误路径零 LLM；固定技术栈（插件属于 Temporal 与 LangGraph 的官方接法，不是新栈）。

## 1. 插件事实（2026-11-12 核对官方文档、PyPI 和示例）

| 项 | 事实 |
|---|---|
| 包 | `temporalio-langgraph` 0.1.0，2026-10-07 发布，仅此一个版本；导入路径 `temporalio.langgraph`；状态 Public Preview |
| 依赖 | 已发布的 0.1.0 实际要求 `temporalio>=1.34.0,<2`、`langgraph>=1.2.0`、Python ≥3.10（以安装包的元数据为准；仓库主干的 `>=1.36.0` 是未发布版本的要求）。仓库现锁 `temporalio 1.34.0`、`langgraph 1.2.12`、Python 3.12，**不需要升级 temporalio**（阶段 1 核实，草案原写“需要升级”有误） |
| 注册 | `LangGraphPlugin(graphs={...}, default_activity_options=...)` 传给 `Worker(plugins=[...])`；Workflow 内 `graph("name").compile(checkpointer=InMemorySaver()).ainvoke(...)` |
| 节点归属 | `add_node(..., metadata={"execute_in": "activity" \| "workflow", ...})`，必填；同一个 metadata 里放 `start_to_close_timeout`、`retry_policy`、`heartbeat_timeout` 等，原样传给 `execute_activity`。不能用 LangGraph 自带的 `retry_policy=` |
| 条件边 | 一律在 Workflow 内执行，必须是 `async def` |
| interrupt | 示例在 activity 节点内调用 `interrupt()`；Workflow 用 `ainvoke(..., version="v2")` 取 `result.interrupts`，query 暴露，signal 收答复，`Command(resume=...)` 恢复 |
| continue-as-new | `cache()` 导出已完成任务的结果缓存，`graph(name, cache=...)` 在新一轮恢复 |
| context | `context_schema` 在 Activity 侧重建，须能被 Temporal payload converter 序列化 |
| 不支持 | LangGraph Store（节点内 `runtime.store` 为 None） |
| 流式 | 仅 `stream_mode="custom"`，经 `WorkflowStream`，按 Activity 尝试至少一次投递 |

**文档没有写明、须在阶段 1 试点中实测的项**（下文以 V 编号引用，任何一项不成立都按所列退路处理）：

| 编号 | 待验证 | 不成立时的退路 |
|---|---|---|
| V1 | 同步节点函数（现有节点全是同步、基于线程和 contextvars）能否作为 Activity 节点 | 节点改 `async def`，内部 `asyncio.to_thread` 调现有同步实现 |
| V2 | Activity 节点内 `activity.heartbeat()`、`activity.is_cancelled()` 可用 | 无退路：长节点没有心跳就无法及时发现 worker 死亡，此项不成立则停止迁移 |
| V3 | 节点 Activity 抛出的 `ApplicationError(non_retryable=True)` 以 `ActivityError` 形式从 `ainvoke` 传到 Workflow，类型码可读 | 节点不抛错，改为把错误码写进 state 的 `fault` 字段，由条件边转到收尾节点 |
| V4 | `cache()` 对**循环图**有效：同一节点多次执行（model→tools→model）的每次结果都能在 continue-as-new 后命中，重放到原位置 | 改用显式续接：continue-as-new 的参数直接带 state，图入口加一条按 `resume_at` 字段跳转的确定性条件边 |
| V5 | execute_in=workflow 的节点内可以调用 `interrupt()`（文档只说需要 `asyncio.create_task(context=)` 支持，Python 3.12 满足） | 滚动检查并入 `tools` 节点末尾，由它返回 `rollover` 标记 |
| V6 | 图模块导入了 SQLAlchemy 等重模块；Workflow 沙箱中只按名字取图、只执行条件边，不会重新导入这些模块 | 条件边和状态类型拆到无第三方依赖的独立模块 |
| V7 | interrupt 恢复时，节点从头重新执行（与现在 PostgresSaver 下的行为一致），且重新执行的那次是新的 Activity | 无需退路，只影响 §4 的去重设计 |
| V8 | Activity 节点收到的输入是完整 state 还是该节点订阅的通道 | 只影响 §6 的体积估算 |

## 2. 节点归属

所有现有节点都调用 ports（数据库）、模型、工具或 emit，因此**全部归 activity**。Workflow 侧只剩条件边，以及一个新增的纯判断节点 `rollover_gate`。

节点 Activity 的公共外壳（一个装饰器，Activity 侧执行）：按 §3 重建 scope 和 kernel → 进入 `registered_graph_context("xiaopai")` → 取 run 租约（`run_lease`，D243）→ 起心跳线程，心跳发现取消即置 `superseded` → 执行节点 → 按 §5.1 映射错误。

### 2.1 小Pai 主图

| 节点 | 归属 | 做什么 I/O | start_to_close | heartbeat | 重试 | 说明 |
|---|---|---|---|---|---|---|
| `prepare_context` | activity | `ports.current`、技能预载、`emit(skill_loaded)`、上下文读取 | 5 分钟 | 45 秒 | 3 次 | 只读加事件；重试会多发一条 `skill_loaded` 事件，失败那次的绑定不进 state，无害 |
| `model` | activity | 网关调用模型、账本 claim/settle、`emit(model_started)` 和 token 流 | 20 分钟 | 45 秒 | 3 次，但见 §5.2：结果未知一律 non-retryable | 评测中单次调用中位约 20 秒；20 分钟覆盖慢模型和限流排队 |
| `route` | activity | `emit(needs_input)`、`interrupt()`、按 answer_ref 读答复、写 `waiting_input` | 1 分钟 | 无 | 3 次 | 无追问时不进入本节点（见 §3.3 的 `choose`） |
| `tools` | activity | 读、准备、T0 写、隔离子任务（研究/抽取/MCP）、`emit(tool_*)` | 60 分钟 | 45 秒 | 3 次 | 与现 `advance_xiaopai_run` 相同的上限；W1 实测一轮 10–30 分钟（D243）。重试安全性来自现有账本：每个调用按 `execution_key` 认领，已完成的重放结果，T0 走 `recover`，`started` 抛结果未知 |
| `rollover_gate`（新） | workflow | 无；只读 `workflow.info()` 的历史体积 | — | — | — | §6 |
| `await_category_adoption` | activity | `interrupt()`、按 answer_ref 核对采用回执 | 1 分钟 | 无 | 3 次 | §4.3 |
| `verify` | activity | `ports.verify`（只读核对） | 5 分钟 | 45 秒 | 3 次 | 幂等 |
| `finalize` | activity | `ports.finish`、`emit(finished)` | 1 分钟 | 无 | 不限次，间隔上限 1 分钟 | 技术收尾须熬过数据库短暂不可用；实现前核对 `finish` 重复调用幂等 |

新增两个**图外** Activity（普通 `@activity.defn`，零 LLM）：

- `open_xiaopai_run`：承接现 `advance` 的前置检查。校验固定信封与归属；已撤回返回 `cancelled+reverted`；已终态直接返回；判定是否个人摘要运行；适配器缺失时置 `waiting_input / SOURCE_UNAVAILABLE`；否则置 `running`，返回 `{kind, goal}`（goal 含自动化规则的用途和停止条件后缀）。
- `close_xiaopai_run`：承接现 `advance` 的 `except` 分支。按错误码写 `failed`，或 `waiting_input` + `mark_required`，返回状态。不限次重试。

`reconcile_xiaopai_run` 原样复用，不改。

### 2.2 试点图

| 图 | 节点 | 归属 | start_to_close | 重试 |
|---|---|---|---|---|
| 个人摘要 | `read_personal_summary`（读本人来源快照） | activity | 2 分钟 | 3 次 |
| 个人摘要 | `persist_personal_summary`（复核来源权限后落结果） | activity | 1 分钟 | 不限次，间隔上限 1 分钟 |
| 钉钉投递 | `deliver_dingtalk`、`deliver_fixed_summary`（各一个节点） | 不迁移 | — | — |

**试点选个人摘要图**。钉钉两张图都只有一个节点、无检查点，迁过去只是把一个 Activity 换成另一个 Activity，验证不了“已完成节点不重跑”。个人摘要有两个节点、有“快照后再落库”的恢复语义，且全程无模型、无外发，风险最低。

任务书要求用 fake provider 统计模型调用次数，而个人摘要没有模型调用。试点改为统计 `runtime.generate` 的执行次数来证明已完成节点不重跑；模型调用次数的证明放到阶段 2 的小Pai 主图测试。

钉钉两张图和 `packages/pdos-agent-runtime` 的 `AgentWork` / `pdos_execute_agent_graph`（原工程用，pdos-next 的 worker 没有注册）**不在本次范围**，保持现状。`registered_graph_context` 继续使用。

## 3. 构图方式改造

### 3.1 Worker 启动时注册

`AgentKernel.compile(scope, ...)` 现在按 run 用闭包构图，捕获 `scope`、`ports`、`preload`、`trusted_adoption`。改为模块级 `build_xiaopai_graph()`，在 worker 启动时构造一次，经 `LangGraphPlugin(graphs={"xiaopai": ..., "personal-summary": ...})` 注册。节点是模块级函数，签名 `(state, runtime)`。

原 `compile()` / `execute()` 不动，旧路径继续用。节点主体逻辑抽成两条路径共用的函数，旧闭包改为调用它们；这一步是纯重构，阶段 2 用现有内核测试全量回归。

### 3.2 run 级信息与活对象

| 原闭包捕获 | 新来源 |
|---|---|
| `scope`（RunScope，含品类、数据类别、客户身份等政策事实） | runtime context 只带 5 个字符串 ID：`tenant_id`、`category_id`、`actor_id`、`requester_id`、`run_id`，与现有 Temporal 固定信封相同。每个节点 Activity 内用 `KernelStore.scope(...)` **从数据库重建**完整 scope。政策事实不经过 context 或 state，符合不可协商项 2 |
| `ports`（BoundHost）、gateway | 节点外壳每次用 worker 级依赖新建 `BoundHost(store, adapters)`，结束时 `gateway.close()` |
| engine、adapters、tool registry、skill catalog | worker 启动时写入一个进程级依赖登记（沿用现有 `configure_agent_kernel(engine, adapters)` 的做法），节点外壳从中读取。不进 state，不进 context |
| `preload` | `prepare_context` 节点内按现有 `KernelActivities.preload` 从数据库算出 |
| `trusted_adoption`（内存见证对象） | `await_category_adoption` 节点内用 answer_ref 调 `category_adoption.resolve` 现场核对得到，见 §4.3 |
| 系统提示词、工具定义 | 每个节点 Activity 新建 `AgentKernel` 时组合。跨节点一致性由现有的 `prompt_identity` 校验和技能绑定的 `VERSION_CONFLICT` 检查保证 |

密钥约束：模型凭据、MCP 令牌、签名 URL 只存在于 adapters 和 gateway 内部。需在阶段 2 加一条测试，扫描一次完整 run 的 Workflow 历史，断言不含凭据特征串和签名 URL 参数（`Signature=`、`X-Amz-`、`Expires=` 等）。`provider_continuation`（服务商私有续接数据，现在已在检查点里）进历史前要逐个服务商确认不含令牌，见问题 Q5。

### 3.3 条件边

全部改为模块级 `async def`，只读 state，不做 I/O，不读时钟、随机数或环境变量。

| 函数 | 起点 | 读取字段 | 返回 |
|---|---|---|---|
| `choose` | `model` 之后 | `calls`、`output`（是否为空、`status`） | 有调用 → `tools`；`output` 为空 → `model`；`status == "needs_input"` → `route`；其余 → `verify` |
| `after_route`（新） | `route` 之后 | `output` | 已收到答复（`output` 被清空）→ `model`；追问格式不合法、未中断 → `verify`（保留现有“格式错误走核对修复”的行为） |
| `after_tools` | `tools`、`await_category_adoption` 之后 | `pending_categories`、`rollover` | 有待采用候选 → `await_category_adoption`；否则 → `rollover_gate` |
| `after_gate`（新） | `rollover_gate` 之后 | 无 | 恒为 `model`（写成固定边即可） |
| `after_verify` | `verify` 之后（原 lambda） | `output` | 非空 → `finalize`；空 → `model` |

与现图的差别：现在 `model → route` 是固定边，`route` 在无追问时空转。新图把这个判断前移到 `choose`，无追问时省一次 Activity。`choose` 只按 `status` 字符串分支，问题列表的 pydantic 校验留在 `route` 节点内。

## 4. interrupt 与人工确认

### 4.1 新模型

- `route` 和 `await_category_adoption` 在 activity 节点内调用 `interrupt()`。
- `XiaopaiGraphWork` 用 `InMemorySaver`，`thread_id` 取 workflow id。
- `ainvoke(..., version="v2")` 返回 interrupts 时，Workflow 记下待确认内容，`@workflow.query pending_input` 暴露它，然后 `wait_condition` 等待答复队列。
- 答复经 `@workflow.signal resume(answer_ref: str)` 进入。信号名、UUID 规范化、`seen_answer_refs` 去重、先进先出队列与现 `XiaopaiWork` 完全一致，所以 `TemporalPort.signal` 和 Outbox 不用改（信号按 workflow id 投递，不关心工作流类型）。
- 恢复时 `Command(resume={"answer_ref": <uuid>})`。**进历史的只有引用**；节点在 Activity 内按引用从数据库读答复正文或采用回执。
- `waiting_input` / `running` 的状态写入并入这两个节点：`interrupt()` 之前写 `waiting_input`，恢复后写 `running`。

用 signal 不用 update：调用方是事务性 Outbox，只需要“至少一次、可乱序”的投递，不需要同步返回值。

### 4.2 `route` 的重复执行

恢复时节点从头执行（V7），`emit(needs_input)` 会再发一次。现在 PostgresSaver 下也是这样，行为不变；阶段 2 顺带核对过程视图对重复 `needs_input` 的显示。

### 4.3 品类采用

现在 Activity 先把 answer_ref 解析成 `VerifiedCategoryAdoption` 内存见证，再经闭包交给节点；节点比对 `interrupt()` 返回值与见证的信封。新路径中节点恢复后拿到 answer_ref，在同一个 Activity 内调 `resolve()` 得到见证，再做同样的检查：见证类型、`consumed_input_refs` 去重、`_adoption_index` 按候选匹配（任意顺序）。“普通答复不能代替采用回执”的保证不变：见证仍然只能由服务器端 `resolve()` 构造，Workflow 历史里的 answer_ref 只是一个 UUID，不携带授权。

### 4.4 `execute()` 现有恢复分支的去向

| # | 现有分支（graph.py 716–798 行） | 新路径 |
|---|---|---|
| 1 | 检查点 `run_id` 与 scope 不符 → `FORBIDDEN_SCOPE` | **不再需要**。检查点在 Workflow 内存里，workflow id 由租户和 run 决定；每个节点仍用数据库重建 scope 并 `ports.current` |
| 2 | `restore_checkpoint` 钩子（只有研究子图实现） | 主图不涉及；子任务保持旧机制 |
| 3 | 检查点已到终点 → 直接返回已存结果 | **由 Temporal 覆盖**。Workflow 完成后不会重跑；重复启动被 `REJECT_DUPLICATE` 拦下；`open_xiaopai_run` 对终态 run 直接返回 |
| 4 | 有中断但没有答复，或答复重复 → 原样返回中断 | **由 Workflow 覆盖**：`wait_condition` 加 `seen_answer_refs`。`consumed_input_refs` 检查保留在节点里作第二层 |
| 5 | 有待采用候选时收到普通答复 → `FORBIDDEN_SCOPE` | **保留**，移到 `await_category_adoption` 节点（`resolve` 结果不是见证即拒绝） |
| 6 | 当前等的是追问，却收到采用见证 → `FORBIDDEN_SCOPE` | **保留**，移到 `route` 节点 |
| 7 | 有答复但检查点没有中断（上一个 Activity 中途崩溃）→ 先空载恢复跑到中断 | **不再需要**。Temporal 重放把图恢复到崩溃点，答复留在 Workflow 队列里，只在图确实停在中断时才取出 |
| 8 | 采用确认在 tools 检查点之后、interrupt 保存之前提交 → 空载推进到等待，再用同一见证恢复 | **不再需要**，原因同 7：早到的 answer_ref 在队列里等，图走到 `await_category_adoption` 中断后再消费 |
| 9 | 没有检查点却带答复 → `SOURCE_UNAVAILABLE` | **不可能出现**：只有 `ainvoke` 返回中断后才会 `Command(resume=...)` |
| 10 | 隔离子任务的 `thread_id` 加 `execution_key` 摘要 | **保持旧机制**，见下 |
| 11 | 会话布局 `SessionRunSaver`（一个会话线程、按 run 分命名空间） | 新路径不需要。新 run 在 `versions` 记 `execution_engine: "temporal-langgraph/v1"`。`checkpoint_layout` 是建运行记录时写入的（阶段 1 核实），新路径上仍然存在但不被读取；隔离子任务继续用它 |

**隔离子任务**（research、extract、mcp、assistant_extract、assistant_compare）是在 `tools` 节点内嵌套执行的另一张 `AgentKernel` 图，各有自己的 PostgresSaver 检查点和账本。本次**不迁移**：它们留在 `tools` 这个 Activity 内，继续用现有检查点库。理由是它们的并行、截断续读和账本接续逻辑量大，与主图迁移相互独立，放在一起会让阶段 2 的回归面翻倍。代价是 `tools` 仍可能是 10–30 分钟的长 Activity，检查点库也不能随主图迁移下线。是否后续把子任务改成插件子图，见问题 Q2。

## 5. 账本、对账、取消、撤回、预算

### 5.1 错误映射（节点外壳）

| 节点内发生 | 外壳行为 | Workflow 行为 |
|---|---|---|
| 正常返回 | 返回 state 更新 | 继续 |
| `DomainError(EXTERNAL_OUTCOME_UNKNOWN)` | `ApplicationError(type=code, non_retryable=True)` | `close_xiaopai_run` → `needs_reconciliation` → 等 5 分钟 → `reconcile_xiaopai_run` |
| `DomainError(CANCELLED_RUN)` | 同上，non-retryable | 返回 `cancelled`，不写状态（`cancel_run` 已写） |
| 其他 `DomainError` | non-retryable | `close_xiaopai_run` 写 `failed` |
| 非预期异常 | 记日志（只记类型和栈帧，不记值），转 `INTERNAL_ERROR`，non-retryable | 同上。与现在一致：意外失败不触发重试，更不会从这里重发模型 |
| 数据库连接类 `OperationalError`，且发生在账本认领之前 | 原样抛出，可重试 | Temporal 按节点重试策略重试 |
| `AttemptSuperseded` / Temporal 取消 | `CancelledError` | 见 §5.4 |
| Activity 超时、心跳超时、重试耗尽 | — | `close_xiaopai_run`（标记待对账）→ `reconcile_xiaopai_run(activity_exhausted=True)`，与现 `xiaopai-reconciliation-v1` 分支相同 |

### 5.2 模型调用不盲目重发

现有账本已经提供主要保证：`gateway.turn` 用请求摘要作 `call_key` 认领；同一 key 已 `completed` 时重放已记账的结果、不出站；处于 `started` 或 `unknown` 时抛 `EXTERNAL_OUTCOME_UNKNOWN`。新路径下重试拿到的是同一份输入 state，摘要相同，所以这条保证直接生效。

新路径再加一道与摘要无关的前置检查，防止重试时请求摘要因路由或校准变化而对不上：`model` 节点认领前查询本 run 主图是否存在 `started` 或 `unknown` 的模型调用，存在即抛 `EXTERNAL_OUTCOME_UNKNOWN`（non-retryable）。主图同一时刻只会有一个在途模型调用，所以这个检查不会误伤。

| 场景 | 结果 |
|---|---|
| 请求发出前失败（路由未配置、数据库不可用、认领前被取代） | 无账本行或已释放 → 可重试 |
| 请求已发出，worker 在记账前崩溃 | 心跳超时 → 重试的那次认领时发现 `started` → 结果未知 → 对账，不重发 |
| 模型已返回并记账，Activity 结果没能交回 Temporal | 重试时命中 `completed` → 重放账本结果，零出站 |
| 服务商返回错误且网关判定结果未知 | 网关已置 `unknown` → 对账 |

### 5.3 各项落点

| 项 | 落点 |
|---|---|
| 调用账本（started/completed/unknown） | 不变，仍在 `KernelStore.claim/settle/release_call`，由 `model` 和 `tools` 节点 Activity 调用 |
| 对账 | `reconcile_xiaopai_run` 原样复用；`mark_required` 由 `close_xiaopai_run` 调用；人工对账入口不变 |
| 预算耗尽返回 partial | 不变，仍在图内：`model` 节点返回 `partial` 输出 → `verify` → `finalize`。`RATE_LIMITED`、`CONTEXT_INCOMPLETE`、会话资料被撤回三种情况同理 |
| 核对失败修复 | 不变，`verify` 节点内计数，超过 `validation_retries` 转 partial |
| 运行状态写入 | `running`：`open`；`waiting_input`：两个中断节点；终态：`finalize` 或 `close` |

### 5.4 取消与撤回

- **取消**：API 的 `cancel_run` 先在数据库置 `cancelled`、`cancel_epoch + 1`，再调 `temporal_port.cancel`（按 workflow id，不用改）。Workflow 取消传到在途节点 Activity 的心跳，外壳置 `superseded`，节点在下一个安全点（认领模型或工具调用之前）抛 `AttemptSuperseded`。即使 Temporal 取消没送达，每个节点开头的 `ports.current` 也会因 `cancel_epoch` 变化而抛 `CANCELLED_RUN`。Workflow 以 Cancelled 结束，不再写业务状态。
- **撤回**（`reverted_at`）：`open_xiaopai_run` 对已撤回的 run 直接返回 `cancelled + reverted`。运行中被撤回时，应在下一个节点入口停下：阶段 2 开工时先核对 `KernelStore.authority` 是否检查 `reverted_at`（或撤回流程是否递增 `cancel_epoch`），缺则在节点外壳补一次显式检查。
- **run 租约**（D243）保留，粒度从“整轮”变为“每个节点 Activity”：超时被放弃的旧尝试可能还在线程里跑，新尝试要等它在安全点停下。

## 6. 历史体积

### 6.1 实测基数

取自 [W1 真实评测](../reports/evidence/pdos-next-real-eval-20261101/result.md)的 244 个运行记录：

| 指标 | p50 | p90 | 最大 |
|---|---|---|---|
| 模型调用次数（含子任务） | 5 | 17 | 46 |
| 账本调用数 | 10 | 29 | 93 |
| 账本结果总字节 | 85 KB | 295 KB | 968 KB |
| 运行事件数 | 30 | 73 | 217 |

主图单次模型调用的输入约 4.5 万 token，上下文焦点上限 6.4 万 token，折合 `messages` 约 150–260 KB。主图预算为 12 次模型轮、40 次工具调用。

### 6.2 估算

记 S 为一次节点 Activity 携带的 state 大小。现在的 state 有两个大字段：`messages`（受焦点上限约束，≤ 约 260 KB）和 `tool_results`（每个工具结果的**完整值**，只增不减，对应上表“账本结果总字节”）。节点返回的是整个 `messages` 列表（模型节点会用准入后的消息整体替换历史，不是追加），所以输入和输出都接近 S。

| 情形 | S | 每轮（model + tools 两个 Activity，各一进一出） | 12 轮 |
|---|---|---|---|
| 不改 state，典型 | 150 KB + 85 KB | 约 0.9 MB | 约 11 MB |
| 不改 state，偏大 | 260 KB + 300 KB | 约 2.2 MB | 约 27 MB |
| 不改 state，最坏 | 260 KB + 968 KB | 单个 payload 1.2 MB | 逼近单 payload 2 MB 上限 |
| `tool_results` 改引用后 | ≤ 260 KB | ≤ 约 1 MB | ≤ 约 12 MB |

Temporal 的界限：单 payload 2 MB，单个历史 50 MB 或 51,200 个事件，10 MB 或 10,240 个事件起告警。事件数不是问题（每轮约 15–20 个事件，12 轮不到 300 个）；体积是问题。以上估算假设 Activity 输入是完整 state（V8），阶段 1 记录实际值后修正。

### 6.3 决定

1. **`tool_results` 的值改存引用**（必须做，否则最坏情况会撞单 payload 上限）：state 中每项只留 `tool`、`tier`、`taint`、账本 `call_id` 和现有的 `model_view`；`verify`、`finalize`、partial 输出在 Activity 内按 `call_id` 从账本读结果。工具结果给模型看的那一份已经有截断和 `result_handle` 机制，留在 `messages` 里不变。
2. **文档、检索结果等大内容**：现状已是引用（原件 ID、引用 ID、`result_handle`），正文不进 state。新路径加一条断言：单条工具消息超过现有截断阈值时必须带 `result_handle`。
3. **`messages` 先保持内联**。它有上限，且用户已允许消息进历史。如果阶段 1、2 的实测显示常见 run 超过 10 MB，再改为按内容摘要存引用（问题 Q3）。
4. **continue-as-new 触发条件**，由 `rollover_gate`（workflow 侧，位于 `tools` 之后、下一次 `model` 之前）判断，满足任一即触发：
   - `workflow.info().is_continue_as_new_suggested()` 为真；
   - 当前历史体积 ≥ 8 MB；
   - 本轮 Workflow 执行内已完成 6 次模型轮。
   
   触发方式：`rollover_gate` 调 `interrupt({"type": "rollover"})`，`ainvoke` 返回后 Workflow 执行 `continue_as_new`，参数为固定信封、未消费的 answer_ref 队列、`seen_answer_refs`、`cache()`。新一轮用 `graph("xiaopai", cache=...)` 重入，已完成节点从缓存取结果，不重跑。等待人工答复期间不触发（等待不增加体积）。
5. 这条设计依赖 V4 和 V5。任一不成立，按 §1 的退路改为显式带 state 续接；两种做法对外行为相同，阶段 2 的测试“长对话触发 continue-as-new，已完成节点不重跑”都适用。

## 7. Store、流式、LangSmith

| 项 | 结论 |
|---|---|
| Store | 没有用到。全库无 `BaseStore`、`InMemoryStore`、`PostgresStore`；记忆层设计（D253）已明确不用 LangGraph 自带 Store。插件不支持 Store 对本项目无影响 |
| 流式 | 不需要 `WorkflowStream`。现在的 token 流和过程事件走 `gateway.turn(emit=...)` → `agent_events` 表 → 前端按序号读取，全程在 `model` 节点 Activity 内完成，迁移后原样保留。图本身没有用 `stream()`、`astream()` 或 `get_stream_writer` |
| LangSmith | 现在没有接入，本次也不接。接入意味着把提示词和模型输出发给新的外部服务商，按 P26 须由服务器判定并记入运行回执，属于另一项决定 |

## 8. 迁移计划、开关、回退、风险

### 8.1 版本锁定

- `temporalio-langgraph==0.1.0`（精确）。
- `temporalio` 保持已锁的 1.34.0，`langgraph` 保持 1.2.12，都满足 0.1.0 的要求，`uv.lock` 只新增插件一个包。
- 以后升级插件时，如果新版本抬高 temporalio 下限，先用 `tools/workflow_replay_check.py`（D212）对全部工作流的未结束历史做回放，通过后才升级。

### 8.2 阶段

| 阶段 | 内容 | 生产路径影响 |
|---|---|---|
| 1 试点 | 新建 `PersonalSummaryGraphWork`；Worker 注册 `LangGraphPlugin`；验证 V1–V8；测试正常完成、节点中途杀 worker、重复与乱序信号、超时重试；记录历史事件数和体积 | 试点工作流**只由测试和评测工具启动**，不接生产派发。生产的个人摘要仍走 `XiaopaiWork` |
| 2 主内核 | 节点主体抽成共用函数；`build_xiaopai_graph()`；`XiaopaiGraphWork`、`open` / `close` 两个 Activity；`tool_results` 改引用；任务书列出的全部测试 | 开关默认关，生产零变化 |
| 3 切换 | 先合成租户，后试点租户 | 需另行授权 |

### 8.3 开关

- 环境变量 `PDOS_XIAOPAI_GRAPH_TENANTS`：逗号分隔的租户 UUID 列表，默认空。只在 `TemporalPort.start` 读取：租户在列表内，新 run 以 `XiaopaiGraphWork` 启动，否则以 `XiaopaiWork` 启动。
- 两种类型共用同一个 workflow id 规则（`pdos-next:xiaopai:<租户>:<run>`）和同一个 `resume` 信号名，所以 signal、cancel、Outbox、派发恢复函数都不用区分类型，也不需要数据库迁移。
- 类型只在启动时决定，之后不变。旧 run 留在 `XiaopaiWork` 上自然跑完。
- `open_xiaopai_run` 在 `run.versions` 记下 `execution_engine`，供运行详情和排障辨认。
- `XiaopaiWork`、`advance_xiaopai_run`、`reconcile_xiaopai_run`、检查点库、检查点保留清理（D58）在阶段 3 结束前一律不动。

### 8.4 回退

- **关开关**：从列表移除租户，新 run 立即回到旧路径。已在新路径上的 run 继续在 `XiaopaiGraphWork` 跑完，所以回退期间 worker 仍须保留插件和新工作流的注册。
- **在途 run 出问题**：取消该 run（现有取消链路），用户重新发起，新 run 走旧路径。账本和对账机制与路径无关，结果未知的调用照常进入对账。
- **插件升级破坏回放**：插件精确锁版本；升级前对 `XiaopaiGraphWork` 的未结束历史做回放检查（纳入 D212 的发布检查）。回放不过就不升级，或等在途 run 结束后再升级。
- **彻底放弃插件**：新路径只新增类型和文件，旧路径原封未动；关开关、等新路径 run 结束、去掉插件注册即可。数据层只多了 `versions.execution_engine` 一个标记。

### 8.5 风险

| # | 风险 | 影响 | 应对 |
|---|---|---|---|
| R1 | 插件是 Public Preview，只有 0.1.0 一个版本 | API 可能改；历史格式可能不兼容 | 精确锁版本；升级前回放；新旧并存；试点先验证 V1–V8 |
| R2 | ~~temporalio 1.34 → ≥1.36~~ | 不成立：0.1.0 在 1.34.0 上可用（阶段 1 核实） | 以后升级插件时再评估 |
| R3 | 现有节点全是同步、依赖线程和 contextvars（`attempt_scope`、`registered_graph_context`、并行读的线程池） | 插件可能只适配 async 节点 | V1；退路是 async 外壳加 `to_thread`，contextvars 用 `copy_context` 传递（现有并行读已是这个做法） |
| R4 | 历史体积超限 | run 被 Temporal 终止 | §6：`tool_results` 改引用、continue-as-new、阶段 1/2 实测 |
| R5 | `cache()` 对循环图的行为未见文档 | continue-as-new 后节点重跑 | V4；显式带 state 续接的退路；账本是最后一道防线（重跑的模型或工具调用命中 `completed` 时重放结果，不出站） |
| R6 | 每个节点 Activity 都新建 host、gateway 并重建 scope | 每个节点多几次数据库往返 | 一次 run 约 30–50 个节点，相对模型耗时可忽略；阶段 2 记录 p95 |
| R7 | 重试导致过程事件重复（`skill_loaded`、`model_started`、`tool_started`） | 过程视图多出重复步骤 | 现在 Activity 重试时已有同样现象；阶段 2 核对过程视图按调用 ID 去重 |
| R8 | 隔离子任务不迁移 | `tools` 仍是长 Activity；检查点库不能下线 | 明确为本次范围外（Q2） |
| R9 | 消息、模型输出进入 Temporal 历史 | Temporal 库的访问控制、备份、保留期此前按“只有引用”设计 | 用户已放开隐私约束；仍建议阶段 3 前核对 Temporal 库的访问权限和历史保留期（Q4） |
| R10 | `provider_continuation` 进入历史 | 若某服务商在其中放了令牌类内容，会违反密钥约束 | 阶段 2 逐服务商核对；有疑问的不进 state，改为按账本 `call_id` 取（Q5） |

## 9. 确认的问题（用户 2026-11-12：全部按推荐）

| # | 问题 | 推荐 |
|---|---|---|
| Q1 | 是否批准 §0 的三处条款变更，并登记为 P100（P92–P99 已被占用） | 批准 |
| Q2 | 隔离子任务（研究、抽取、MCP 等）本次不迁移，继续在 `tools` Activity 内用 PostgresSaver。这与“checkpointer 只用 InMemorySaver”在字面上不完全一致：主图满足，子任务不满足 | 同意本次不迁移；主图稳定后另开一项评估子任务改插件子图 |
| Q3 | `messages` 先内联进历史，实测超 10 MB 再改引用 | 同意 |
| Q4 | 阶段 3 前是否要核对 Temporal 库的访问权限和历史保留期 | 要，列入阶段 3 的前置检查 |
| Q5 | `provider_continuation` 在核对清楚之前，是否一律不进 state、改按账本引用取 | 是，直接按引用取，省掉逐服务商核对 |
| Q6 | 试点选个人摘要图，且阶段 1 的试点工作流不接生产派发 | 同意 |
| Q7 | 开关用环境变量租户列表，不做数据库配置和管理界面 | 同意；下线旧路径时一并删除 |
| Q8 | 钉钉两张单节点图和 `pdos-agent-runtime` 的 `AgentWork` 不迁移 | 同意 |

## 10. 阶段 1 实测结果（2026-11-12）

证据：[langgraph-temporal-plugin-20261112](../reports/evidence/langgraph-temporal-plugin-20261112/README.md)。

### 10.1 V1–V8

| 编号 | 结论 | 依据 | 对设计的影响 |
|---|---|---|---|
| V1 | 同步节点可以注册，插件用 `asyncio.to_thread` 执行；但那个线程里没有事件循环，`activity.heartbeat()` 会抛错 | 插件源码 `_activity.py`；实测 | 采用退路：节点统一包一层异步外壳 `workflows/graph_nodes.py::activity_node`，外壳在事件循环上发心跳，现有同步节点体在线程里执行并带上调用方的 contextvars |
| V2 | 外壳里的心跳有效 | “杀掉 worker”测试：被杀进程的节点由 45 秒心跳超时发现并重试 | 无 |
| V3 | 成立：节点抛的 `ApplicationError(non_retryable=True)` 以 `ActivityError` 传到 Workflow，`cause.type` 是错误码 | 测试 `test_stopped_node_closes_the_run_with_its_code_and_is_not_retried` | §5.1 按原设计 |
| V4 | 成立：循环图在 continue-as-new 后不重跑已完成的节点。缓存键是（节点标识、完整输入 state、context）的摘要 | 一次性实测（3 轮循环，续接后节点执行总数不变），尚未写成正式测试 | 缓存里存的是**每个节点的完整输出**，体积等于历次输出之和。小Pai 主图带着它续接会超过单 payload 2 MB，所以阶段 2 改用 §1 的退路：续接参数只带当前 state，图入口按 `resume_at` 跳转。`cache()` 只用于个人摘要这类小图 |
| V5 | 成立：workflow 侧节点可以 `interrupt()` | 同上一次性实测 | `rollover_gate` 按原设计 |
| V6 | 部分成立：图对象由插件按名字交给 Workflow，条件边不会触发重导入；但 **Workflow 所在模块本身**会在沙箱里重新导入，不能导入数据库或领域模块 | 测试夹具最初把 Workflow 与领域夹具放在一个模块，沙箱校验失败 | 规则：Workflow 文件只导入 `workflows/graph_runtime.py`；图和节点放在别的模块 |
| V7 | 成立：恢复时被中断的节点从头再执行一次，是新的 Activity | 两次追问对应 4 次节点进入、2 次答复 | §4.2 按原设计 |
| V8 | 成立：Activity 输入是完整 state 加一份可序列化的 LangGraph 配置（含 context） | 插件源码 | §6.2 的估算口径不变 |

### 10.2 文档没写、实测或读源码才知道的三点

1. **节点标识是“模块名.函数限定名”**，闭包和 lambda 会被拒绝。所以节点必须是模块级函数；外壳保留了节点体的模块名和限定名。
2. **同一次 Workflow 执行内，对同一节点用完全相同的 state 和 context 再次调用，会直接返回缓存结果，不执行节点**。被中断的那次不进缓存，所以追问恢复不受影响。阶段 2 要逐条确认主图的每条回边都会改变 state（现有的 model、tools、verify 回边都会递增计数或追加消息）。
3. **注册时插件会改写图对象**，同一个图对象不能交给两个插件实例；`build()` 每次返回新图。

### 10.3 历史事件数与体积

| 用例 | 节点 Activity 数 | 历史事件数 | 历史 JSON 字节 |
|---|---|---|---|
| 个人摘要，正常完成 | 2（另有 1 个 open） | 23 | 19,903 |
| 个人摘要，worker 在第二个节点内被杀后恢复 | 2（第二个节点 2 次尝试） | 23 | 20,115 |
| 测试图，两次追问（共 6 次节点执行） | 6 | 52 | 44,178 |

每个节点 Activity 约占 6–7 个历史事件；每次追问往返另加约 6 个。上表是合成小载荷；真实数据库上的体积见 §10.4。

### 10.4 真实数据库端到端（同日补做）

另建隔离库 `de9db19e` 后，`open_xiaopai_graph_run`、`close_xiaopai_graph_run`、节点内的 scope 重建和真实摘要读写都已在真实数据库上验证（4 项通过，见证据）：正常完成且重复启动不重跑、节点之间取消后不落结果、节点失败只记一次、伪造信封被拒且运行不被改写。真实数据上的一次个人摘要占 23 个历史事件、32,403 字节。

对设计的一处细化：open 拒绝的信封（不属于该运行，或该运行不是已登记的图）让工作流直接失败，**不调用 close**，避免把一个走错路径的运行写成失败。只有图执行中的失败才进入 close 或对账。

### 10.5 尚未验证

- V4、V5 只做过一次性实测，没有进测试套件；阶段 2 的“长对话触发 continue-as-new”测试覆盖。
- 个人摘要没有模型调用和人工追问，账本防重发和答复解析的真实路径在阶段 2 验证。

## 11. 阶段 2 实现与实测（2026-11-12）

证据：[langgraph-temporal-plugin-20261112](../reports/evidence/langgraph-temporal-plugin-20261112/README.md) 的“阶段 2”一节。开关默认关，生产路径没有变化。

### 11.1 与前文设计的对应和细化

| 项 | 实现 | 相对前文的变化 |
|---|---|---|
| 节点主体共用（§3.1） | `AgentKernel.nodes(scope, ...)` 返回按节点名取用的节点体，`compile()` 改为调用它装图。两条路径的差异收在 `NodeHooks` 的 7 个钩子里，旧路径用默认实现 | 没有照草案把节点体搬成模块级函数，而是保留原闭包、只拆“构节点”和“装图”，`graph.py` 净改动约 60 行 |
| 主图（§2.1、§3.3） | `agent/kernel/plugin_graph.py`：7 个 activity 节点、1 个 workflow 节点 `rollover_gate`、4 个 `async def` 条件边 | 按设计 |
| runtime context（§3.2） | 固定信封的 5 个 ID，加 open 返回的 `writer_id`，共 6 个 ID | 多一个 `writer_id`：对话运行的执行身份不在信封里，节点重建 scope 需要它。仍然只是 ID，scope 的其余字段都从数据库读 |
| 答复与采用（§4） | 恢复值只接受 `{"answer_ref": <uuid>}`，节点在 Activity 内 `resolve`；等待和恢复时的 `waiting_input` / `running` 由钩子写 | 按设计 |
| `tool_results` 存引用（§6.3 第 1 项） | 带 `execution_ref` 的 READ 结果存 `{ledger_ref, result_digest}`，使用前从账本取回并校验摘要 | **范围收窄**：回执、错误、技能正文没有读取账本行，仍然内联。它们体积小；大结果都属于 READ |
| `provider_continuation`（Q5） | state 里只存 `provider_continuation_ref`（模型调用的账本 ID），调用模型前取回，返回前再换成引用 | 按 Q5 |
| 模型不重发（§5.2） | 网关原有保证不变；`model` 节点认领前另查本运行主图是否有 `started` / `unknown` 的模型调用，有则释放预约并抛结果未知 | 按设计 |
| continue-as-new（§6.3 第 4 项） | `rollover_gate` 触发后，Workflow 取当前 state，`continue_as_new` 时只带 state、未消费的答复引用和已见集合；新一轮用 `aupdate_state(..., as_node="tools")` 接上 | 按 §10.1 V4 的结论，不用 `cache()` |
| 对账等待时长 | open 返回 `reconcile_after_seconds`（默认 300），Workflow 只用历史里记下的值 | 新增：让测试不必真等 5 分钟，且不引入 Workflow 侧的非确定性 |
| 工作流类型 | `XiaopaiGraphWork` 同时承接主图和个人摘要：open 判定类型并返回 | `PersonalSummaryGraphWork` 保留为试点类型，仍不接生产派发 |
| 开关（§8.3） | `PDOS_XIAOPAI_GRAPH_TENANTS`，只在 `TemporalPort.start` 读取；列表里出现非 UUID 即报错，不静默选路 | 按设计 |

### 11.2 测试结果

| 任务书要求 | 用例 | 结果 |
|---|---|---|
| completed 端到端 | `test_completed_run_executes_node_by_node_with_one_request_per_turn` | 通过 |
| partial | `test_partial_when_the_run_budget_cannot_cover_a_model_request`、`test_partial_result_lists_full_actions_restored_from_the_ledger` | 通过 |
| cancelled | `test_cancelled_while_the_model_is_answering_stops_without_another_request` | 通过 |
| failed | `test_failed_when_the_provider_refuses_and_the_request_is_not_repeated` | 通过 |
| needs_reconciliation | `test_unknown_provider_outcome_goes_to_reconciliation_not_a_second_request` | 通过 |
| interrupt 后 signal 恢复，含重复 | `test_question_waits_for_a_committed_answer_and_ignores_duplicates`；采用与追问的引用恢复见 `test_plugin_graph_waits.py`（10 项） | 通过 |
| 模型请求已发出、未记账时 worker 崩溃：不重发，进对账 | `test_worker_lost_after_the_request_was_sent_is_reconciled_not_resent` | 通过：模型只被请求 1 次，重试的那次在网关之前停下 |
| （补充）已记账、结果没交回：重放账本 | `test_completed_request_is_replayed_from_the_ledger_when_its_result_was_lost` | 通过：模型只被请求 1 次 |
| 长对话触发 continue-as-new，已完成节点不重跑 | `test_long_run_continues_as_new_without_rerunning_finished_nodes` | 通过：3 次执行串起 9 个 Activity，无重复 |
| Replayer 回放现有 `XiaopaiWork` 历史 | `test_original_workflow_histories_replay_on_the_plugin_worker` | 通过：5 条历史（完成、partial、取消、两次追问含重复与非法信号、Activity 失败转对账）在装了插件的完整注册表上回放无差异。`xiaopai.py` 与 `activities.py` 没有任何改动 |
| 条件边和 workflow 侧节点的确定性 | `test_routing_is_a_pure_function_of_state` 等 15 项；新路径各用例的历史也都用 Replayer 回放过 | 通过 |
| 开关 | `test_switch_off_keeps_new_runs_on_the_original_workflow`、`test_switch_lists_only_tenant_ids` | 通过 |
| 密钥不进历史 | 完成用例断言历史中没有合成凭据；续接数据用例断言历史中只有引用 | 通过 |

旧路径回归：检查点、品类采用、对账、真实 Temporal、个人摘要等 128 项通过。

### 11.3 实测体积

合成小运行（消息约 25 KB，主要是预载的技能正文）：

| 用例 | 执行次数 | 节点 Activity | 历史事件 | 历史 JSON 字节 |
|---|---|---|---|---|
| 一轮工具后完成 | 1 | 7 | 47 | 349,514 |
| 两次追问 | 1 | 11 | 91 | 577,381 |
| 两轮工具，每轮后续接 | 3 | 9 | 29 / 17 / 23 | 228,930 / 230,196 / 204,714 |

每个节点 Activity 的进出合计约 50 KB（JSON 形式，含 base64 膨胀），约为 state 的 2 倍，与 §6.2 的估算口径一致。按真实运行 150–260 KB 的消息推算，每轮工具约 1–2 MB，6 轮续接一次时单次历史在 10 MB 上下。真实体积要等阶段 3 在合成租户上实测。

### 11.4 缺口 G1–G5（同日补完）

| # | 缺口 | 结果 | 用例 |
|---|---|---|---|
| G1 | 品类采用在真实数据库上的全链路 | 通过。个人运行在候选处等待 → 本人确认创建（真实回执和 Outbox 事件）→ 元数据派发 → Temporal 信号 → 节点内核对采用证明 → 完成。Outbox 重复投递两次，图只恢复一次；小Pai 身份没有因此获得新品类的授权 | `test_category_adoption_graph_plugin_pg.py` |
| G2 | 隔离子任务在新路径 `tools` 节点内 | 通过。`assistant.extract` 的子图在 `tools` Activity 内运行，主图 3 次、子图 2 次模型请求，与旧路径的次数相同；子任务读到的原文没有进入主图 state 和 Workflow 历史 | `test_assistant_graph_plugin_pg.py` |
| G3 | 真实杀进程下主图的恢复 | 通过。独立的 worker 进程在模型请求发出后被 SIGKILL，账本行停在 `started`；新进程接手后没有重发请求，运行转入对账 | `test_worker_process_killed_after_the_request_was_sent_is_reconciled_not_resent` |
| G4 | `tools` 执行中取消、运行中撤回 | 通过。工具执行中取消：工具返回后不再请求模型，运行为 `cancelled`、无结果。模型应答期间走真实的整次撤回：撤回成功，迟到的模型应答不被采用，运行不进入核对和收尾；之后再为该运行启动工作流，只执行 open 就返回“已撤回” | `test_cancelled_while_a_tool_is_running_...`、`test_run_reverted_while_the_model_is_answering_...` |
| G5 | 重试造成的事件重复、每节点重建依赖的耗时 | 已测。节点重试时会多发一条 `model_started` 进度事件，过程视图因此多一个步骤；账本调用、出站检查事件、调用计数都不重复。每个节点重建 scope、host、内核并取租约，中位约 60–70 毫秒，6 个节点合计约 0.37 秒 | `test_retried_node_repeats_its_progress_event_but_no_ledger_call`、`test_rebuilding_scope_and_ports_for_each_node_is_cheap` |

两点说明：

- **撤回**：草案 §5.4 写的是“运行中被撤回时下一个节点即停”。实测真实撤回流程在模型请求进行中可以成功（它先把进行中的调用标为结果未知，再盖撤回标记并递增 `cancel_epoch`），新路径的表现与设计一致。
- **重复的进度事件**是已知的显示层现象，旧路径在 Activity 重试时也有。没有修，登记为 D381；要修的话应在过程视图按“轮次”去重，而不是在执行路径里抑制事件。

### 11.5 仍然留到阶段 3 的部分

- 真实模型、真实消息体积、长时间运行下的历史大小和 continue-as-new 频率。
- 研究、MCP 两类隔离子任务没有单独的新路径用例（抽取类已测）；它们与抽取共用同一套嵌套执行方式。
- Temporal 库的访问权限和历史保留期核对（Q4）。

## 12. 阶段 3：合成租户试运行（2026-11-12）

用户 2026-11-12 授权阶段 3，先在合成租户打开开关；并选择在隔离库新建合成租户、真实调用 MiniMax。证据见[证据说明](../reports/evidence/langgraph-temporal-plugin-20261112/README.md)的“阶段 3”一节。

### 12.1 结论

- 三轮共 9 次真实模型运行全部走新路径，状态为 completed 或 partial，没有失败、没有待对账、没有残留的 token 占用；每条历史回放通过。
- continue-as-new 在真实运行中发生 4 次，续接后没有节点重跑。
- partial 的原因全部来自合成租户的配置（默认的单次运行额度、未启用技能包、无基线型号）或模型输出格式，没有一条指向执行路径。
- 没有发现需要修改新路径代码的问题。本阶段没有改生产代码，只新增了一个需显式开启的试运行脚本。

### 12.2 对前文估算的修正

| 项 | 前文估算 | 实测（合成租户，短上下文） |
|---|---|---|
| 最大单个 payload | 最坏逼近 2 MB（§6.2） | 36 KB |
| 6 轮模型调用的单次历史 | 约 10 MB（§11.3） | 0.4–1.2 MB |
| 简单问答整次历史 | — | 35 个事件、约 55 KB |

实测远小于估算，原因是这个合成租户没有会话历史和大量资料，消息只有 20–40 KB。W1 评测租户的单次模型输入约 4.5 万 token，仍应按 §6.2 的口径看待；要得到有代表性的体积，需要在带真实规模资料和长会话的租户上再测。

### 12.3 仍未覆盖

- 真实模型下的追问恢复：模型返回的追问格式不合规，没有进入等待。
- 有长会话历史、大量资料的租户上的体积与续接频率。
- 研究、MCP 两类隔离子任务。
- 部署环境的 Temporal 持久库访问控制、备份与保留期（本机开发环境的现状见证据说明）。

### 12.4 下一步需要用户决定的

- 是否在试点租户打开开关。前提是先有部署环境及其 Temporal 持久库的访问控制与保留期决定；目前仓库里没有试点部署（清单 D210）。
- 旧路径（`XiaopaiWork`、`advance_xiaopai_run`、主图检查点）的下线时间，按任务书另行确认。
