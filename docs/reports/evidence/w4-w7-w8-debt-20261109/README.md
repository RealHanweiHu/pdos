# W4 D286–D288、W7 D274、W8 D303 与 D358（2026-11-09/10）

分支 `claude/gracious-ptolemy-3b2f0d`，基于 `pdos-next/design-v1.1` 的 `c13c3fd6`（迁移真实 head `s0_0869`；开工前用 `merge-base --is-ancestor` 核对）。只做本地提交，未推送。

测试都在 `tools/local_environment.py create` 新建的隔离 `pdos_test` 上运行（`create` 自带的 head→base→head 往返和 seed 通过），`TEST_DATABASE_URL` 显式指向它，没用 `.env`。检查点库由 `tools/workflow_environment.py create-db` 在同一标记下新建，只用于 `test_activity.py`。没有调用真实模型，没有联网，没有下载镜像（`postgres:16`、`pgvector` 镜像都已在本机）。基点对照用 `git archive c13c3fd6` 的副本，连同一个测试库。

## 结论

| 项 | 判断 | 处理 | 证明 |
|---|---|---|---|
| D286 共享资产栅栏多一个产品时钟 | 夹具过时 | 只改测试：时钟正好对应租户的全部产品 | 单跑通过（13 秒）；基点同一用例失败 |
| D287 部分观察被拒 | 产品缺陷（两处） | ① 观察：事实 owner 收集来源时遍历正文的 JSON 形式，覆盖来源不再漏掉；② 复核：按你选的 A（P119）补齐命令回执与仪器报告的核对，参与者与复核把内嵌原行的来源纳入闭包（D463） | 新回归与闭包用例在基点失败、修复后通过；整链通过（22.8 分钟） |
| D288 外部交接投影不带开关时失败 | 测试缺跳过 | 模块级 `skipif`，用例内的开关断言保留 | 不带开关 1 跳过；带 `PDOS_EXTERNAL_HANDOFF_LINK=1` 1 通过（3 分钟） |
| D274 生命周期图看不到个人运行 | 产品缺口 | 迁移 `s0_0915`（占位号）：个人运行按来源回执的品类进各品类图 | 新 PG 用例 2 个；退到 `s0_0869` 时都失败；[往返与对照](d274-migration-roundtrip.txt) |
| D303 `kernel.models` 单独导入循环 | 产品缺陷 | `KernelRow` 挪出；登记期间不再要求内核模块完整 | 6 个模块各在全新解释器里先导入，DDL 指纹与登记入口一致；基点 6 个失败 |
| D358 租约连接断开不被发现 | 产品缺陷 | 心跳探测租约，失去时按 superseded 停下 | PG 用例真实终止租约后端；反证 2 组 |

## D286

10-11 起项目创建经签核的 G0（`964def44`），G0 给项目另建产品。所以 `operational_work` 的租户里有三个产品：共用夹具 `setup` 的基础产品、G0 建的项目产品、测试自己加的对照产品。每个产品插入时由触发器（`s0_0001`）建一个依赖时钟。测试写于 10-10（`0eccfe03`），仍断言只有项目产品和对照产品两个时钟。

改为：先读租户的全部产品，断言 `{项目产品, 对照产品} ⊆ 产品集合`，且时钟集合恰好等于产品集合。仍是精确断言：多一个或少一个时钟都会失败。后面用 `before` 的断言（锁本产品的时钟不改其他产品的时钟；资产占用加一只推进本产品的时钟）自然覆盖了第三个产品，也更严。原先因这里失败而跑不到的权限断言（`lock_change_dependency_clock` 对 `pdos_agent`、`pdos_next_auth` 和 PUBLIC 都不可执行）这次跑到并通过。

## D288

`tests/ui/test_project_external_handoffs_projection_pg.py` 加模块级 `pytestmark = pytest.mark.skipif(os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") != "1", …)`，写法同 `tests/ops/test_restore_drill_pg.py`。用例里原有的 `assert os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") == "1"` 保留。跳过时不建夹具。导出只在设了 `PDOS_UI_PROJECT_EXTERNAL_HANDOFFS_EXPORT` 时发生，本次没设，没有写文件。

## D274

`m3_lifecycle_nodes` 在品类表扫描和钉钉两段之间加一段：

- 取租户内 `category_id IS NULL`、`versions.personal_sources` 是数组、且至少一条回执的 `category_id` 是 c 的运行；
- 节点是 `('agent_runs', run.id)`，载荷只含 `id` 和回执是 c 的那部分来源（作为 `read_sources`），链接由已有的 `kernel_lifecycle_links` 取 `artifact_id`；
- 只在构建全图时加入，按标识的根查找不加，与品类运行相同（品类运行也只在全图的表清单里）。

函数是 `SECURITY DEFINER`，属主 `pdos_next_owner` 在 `agent_runs` 上有 `owner_internal` 策略，所以别的成员的个人运行也会被计入，这正是清除规划需要的；节点只进生命周期图，不返回给请求者。生命周期时钟早由 `s0_0860` 的 `kernel_source_reference_clock` 推进。

迁移 `s0_0915_personal_run_lifecycle`（占位号，down `s0_0869`）：`ordinary_owner()` 下执行；升级前核对现定义与 `s0_0852` 逐字一致，升级后核对新定义；降级反向。新定义由 `s0_0852` 的定义在固定锚点前插入新段得到，锚点不唯一时模块直接报错。

用例 `server/tests/agent/kernel/test_personal_run_lifecycle_pg.py`：

- 一个个人运行带两个品类的来源：两个品类图里各有这个运行，链接只含本品类的来源；无关品类和按标识查找里没有它；不带来源的个人运行不进图。
- 本人上传并解析一份 DOCX 原件，个人运行携带它：清除规划读的 `lifecycle_reference_summary`（`originals.lifecycle.access.References`）对该原件的引用数加一。对照（同库，把节点断言改成打印）：`s0_0869` 时 19→19，`s0_0915` 时 19→20。

## D303

原因：`pdos_next.core.models` 是模型登记的入口，末尾按固定顺序导入各表模块。先导入 `pdos_next.agent.kernel.models` 时，它的第一件事是导入 `core.models`，于是整个登记在内核表还没定义时就跑完，期间：

- `session_presentation_models`、`work_state_models`、`memory.models` 要 `KernelRow`；
- `domain/categories/preproject/models.py` 要 `AgentRun`，模块末尾还逐条解析外键（`referred_table`），需要 `agent_runs` 表已登记。

改法：

- `KernelRow` 挪到 `agent/kernel/kernel_row.py`，`models.py` 从那里导入（`from pdos_next.agent.kernel.models import KernelRow` 仍可用），三个使用者改为从 `kernel_row` 导入；
- `preproject/models.py` 改为 `import pdos_next.agent.kernel.models`（只为外键元数据），末尾按外键的目标名判断是否指向 `action_receipts`，不再解析外键，结果相同；
- `project_work_task_context.py` 把 `core.models` 的两行导入挪到领域模块之前，与文件里“公共登记先于领域子模块”的注释一致。

没有采用的做法：把 `Base` 挪到独立模块、让内核表先定义。`core.models` 里有一段循环给“当时已登记、有 `category_id` 的表”补品类外键；内核表若先登记，会多拿到 7 条库里没有的外键（`fk_agent_runs_category` 等），DDL 指纹与登记入口不同，所以放弃。

验证：

- 新用例 `server/tests/agent/kernel/test_standalone_import.py`：在全新解释器里分别先导入原先失败的 6 个模块（`models`、`api`、`context_observability`、`policy`、`project_work_task_context`、`session_bindings`），对全部 272 张表编译 PostgreSQL DDL（含索引）并取哈希，都与先导入 `pdos_next.core.models` 的一致；这个哈希也与基点相同，说明正常导入顺序下的结构没变。基点上 6 个全失败。
- `pdos_next/agent/kernel` 下 114 个模块各自单独导入：全部成功；原先轻量、不加载登记的 30 个仍不加载（多一个新的 `kernel_row`）。
- 无库全量（不设任何数据库变量）：10816 通过、0 失败、112 跳过，1985 个错误全是 `KeyError: 'TEST_DATABASE_URL'`。第四轮集成记录的无库全量是 10808 通过，多出的 8 个是本次新增的用例。

## D358

- `run_lease` 交出 `RunLease`。`held()` 在租约自己的连接上查 `pg_locks`：本后端（`pg_backend_pid()`）是否仍持有本运行的咨询锁（64 位键按高低 32 位分在 `classid`、`objid`）。驱动在断线后可能悄悄重连到新会话，查询成功不说明锁还在，所以看锁本身。查询出错或锁不在都算失去，之后一直算失去。探测有锁保护，心跳线程和别处同时调用也安全。
- `KernelActivities._advance_owned` 的心跳线程每 `HEARTBEAT_SECONDS`（10 秒）心跳一次，`activity.is_cancelled()` 或 `not lease.held()` 时置停止信号。之后的处理全是 D243 已有的：下一个安全点抛 `AttemptSuperseded`，转成 `CancelledError("小Pai attempt superseded")`，运行状态不动，交给下一尝试。
- 租约连接加 TCP keepalive（空闲 10 秒起探测，5 秒一次，3 次失败断开；`tcp_user_timeout` 30 秒，只在 Linux 生效），对端失联时探测会报错，不会无限挂住心跳线程。

用例：

- `test_run_lease_pg.py` 新增 4 个：键的高位为 0 和为 1 的运行都能被认出持有；用管理连接 `pg_terminate_backend` 终止租约后端后，另一个租约立刻能拿到同一运行（即重叠风险真实存在），`held()` 为假且之后一直为假，探测没有把锁拿回来；不持锁的新会话不算租约；Activity 在执行中租约被终止，心跳发现，在下一个安全点抛 `CancelledError`，运行仍为 running。
- `test_run_attempts.py` 新增 2 个：租约失去时心跳置信号并按 superseded 停下；租约一直持有时心跳多次探测、照常完成。

反证（临时改代码再跑，跑完恢复）：

- 心跳不探测租约：3 个失败（Activity 的 PG 用例和 2 个单元用例）。
- 探测只看查询是否成功：1 个失败（不持锁的会话被当成租约）。
- 去掉“一直算失去”：全部通过。重连后的新会话本来就不持锁，探测照样为假；保留它只是避免失去后每次心跳都去重连。

受影响范围：`test_run_lease_pg`、`test_run_attempts`、`test_child_attempt_stop_pg`、`test_personal_summary_runtime`、`test_assistant_fanout`、`test_assistant_extract_concurrency_pg`、`test_category_adoption`、`test_activity`，共 162 个通过。`test_activity.py` 的 3 个需要检查点库，第一次缺库失败，建检查点库后通过。

<a id="d287"></a>

## D287

判断：产品缺陷，不是夹具过时。

定位（两轮诊断，都在基点副本上整链运行，约 35 分钟一轮；诊断插件只记录，不改行为）：

1. 第一轮记录每次产生 `MISSING_REQUIRED_EVIDENCE` 的调用栈：拒绝出在 `fact_write._check_material` 第 453 行，即“事实正文里出现的每个来源，都必须在 `body.sources` 里”。
2. 第二轮在该处记下缺了哪些来源、在正文的什么位置（[d287-missing-refs.json](d287-missing-refs.json)）：缺 2 个，是 `coverage_sources[0]` 和 `coverage_sources[2]`，即新运行的开始事实与测量值的来源。

原因：`ActualFactOwner._read` 组装 `body.sources` 时，把起源、规则、请求、资格、政策的来源和“新正文字段里出现的全部来源”（`_all_source_refs(body_extra)`）合在一起，再逐个过 `evidence.check_source`（权限与精确原文行）。但 `body_extra["coverage_sources"]` 是 `anchor.json_value(payload.coverage_sources)`，`json_value` 只序列化本身是模型的值，模型组成的元组原样深拷贝；`_all_source_refs` 只遍历字典和列表，看不到元组里的模型，于是覆盖来源整组漏掉：既没进 `body.sources`，也没被逐个核对。随后的材料核对看的是正文序列化后的形式，看得到它们，就按规则拒绝（失败是闭合的，没有越权）。

为什么只有这条链路失败：其他观察用例的覆盖来源（例如 `test_capa_fact_flow` 用问题的根来源）恰好也在起源来源里，从别的路径进了 `body.sources`；部分观察链路的覆盖来源是新运行的事实来源，只出现在 `coverage_sources` 里。规则分支的 `failures`、`actions` 也是模型元组，写法相同。

修法（`domain/quality/capa/fact_owner.py` 一行）：收集来源时遍历 `body_extra` 的 JSON 形式（`fact_write._json`，它就是为“模型元组”写的），即 `_all_source_refs(_json(body_extra))`。正文本身不变。

- 现在能通过的写入不受影响：第 453 行的核对保证这些写入的正文来源本来就都在 `body.sources` 里，多收集一次是重复项。
- 原来被拒的写入：覆盖来源进入 `body.sources`，并且逐个过 `evidence.check_source`（权限、精确版本、整行原文摘要）与读集。核对比以前多，没有放宽任何守卫、权限或断言。
- 测试 payload 不需要改：`coverage_sources` 不必另抄进 `sources`，`test_capa_fact_flow` 原本就这样写，`ObservationPayload` 也没有这条要求。

回归用例：`server/tests/quality/followup_transactions/test_capa_fact_flow.py` 的观察多带一个只出现在 `coverage_sources` 里的来源，并断言准备好的命令的读集包含它。基点上该用例失败，报的正是 D287 的 409 `MISSING_REQUIRED_EVIDENCE`；修复后 2 个用例通过（约 5 分钟）。

### 修复后的整链：复核一步仍被拒（D463）

在本分支（含上述修复）上单独跑整链（约 18–21 分钟）：部分观察已能记录，链路走到下一步“独立具名复核，结论 unknown”，又在 `fact_write.py:453` 以同一个码被拒。第三轮诊断（[d287-review-missing-refs.json](d287-review-missing-refs.json)）显示，缺的 7 个来源全在复核正文内嵌的 `participant_owner_material` 里，也就是参与者 owner 读到并原样放进正文的原行：

| 来源 | 所在原行 | 能否过现有闭包 |
|---|---|---|
| 2 个 `command` / `receipt` | 启动事实 `kernel_event.at.source` | 不能：`read_source_closure` 对非 artifact 的领域来源一律记 `DOMAIN_SOURCE_OWNER_REQUIRED`，注明“owner 接上前一律记为缺失” |
| 2 个 `artifact` / `measurement-report` | 测量导入的 `report_binding.report` | 不能：`evidence.check_source` 只认 `line:N;quote_sha256:…`，其余报 422；正文来源里只有同一报告的整行引用 |
| 3 个整行引用（artifact、line、quote） | 原行 `sources`，资源依赖证明里的决定来源 | 能；但复核 owner 只并入各参与者的 `owner_sources` 和参与者读集，没并入参与者来源集 |

所以在现有设计下，只要参与者里有真实的验证运行（启动事实、测量导入），具名复核就记不下来。这几处 10-08 首次导入时就有，用例 10-22 加入（`1583fab1`），没有找到它通过过的记录。修法要么新增来源核对 owner，要么收窄守卫。11-10 把三个选项发给协调会话，你 11-11 选 A，见下一节。

<a id="d463"></a>

### 复核一步的修复（D463，你 11-11 选 A，P119）

守卫“正文里的全部来源须在 `sources` 内并经过闭包核对”不变，补齐核对：

- `fact_sources_owner.read_source_closure`：
  - `command`/`receipt` 来源：须在本型号恰有一条该命令编号的回执（当前会话可读，受 RLS 约束），版本须为 1；私有回执不能进入品类可见的事实。
  - `artifact`/`measurement-report` 来源：经 `source_for` 核对可读、精确版本、有效，且须是已上传原件（原生文本永远不是仪器报告）；原件字节与安全状态由闭包原有的读集循环核对；私有报告不能进入品类可见的事实。
  - 其他领域来源（如 `kind: domain`）仍记 `DOMAIN_SOURCE_OWNER_REQUIRED`，原有用例不变。
- `participants_owner.read_participants`：先组好内嵌材料，再按材料核对的同一识别方式收齐其中全部来源；整行引用经 `source_refs` 按实际整行换算定位；其中的原件同时进入读集。闭包和摘要按新的来源集计算。
- `named_review_owner`：来源闭包并入 `participants.sources`，与原来并入 `participants.required_source_read_set` 对称。

改动只在这三个文件，与 D47 分支（只改 `capa/paired.py`、新增 `capa_effectiveness/`、`execution/models.py`）没有文件重叠。无迁移，无接口变化。

## D287 验证

- 回归：`test_capa_fact_flow.py` 加覆盖来源后，基点副本上失败（409 `MISSING_REQUIRED_EVIDENCE`，与 D287 原报错相同），本分支 2 个通过（约 5 分钟）。
- 受影响范围（`tests/quality/capa`、`tests/quality/followup_transactions`、`test_action_fulfillment_owner`、`test_default_action_fulfillment_wiring`、`test_host_profile_choices`）：698 个通过，约 31 分钟。前一轮同一批在会话中断时被杀掉，杀掉前有 1 个错误，复跑没有再出现。
- 整链 `test_partial_observation_review_chain.py`：基点副本上失败于记录观察（36.8 分钟）；本分支上越过观察，失败于具名复核（18.4 分钟；带诊断插件那次 21.2 分钟），这是修 D463 之前；修 D463 后整链通过（22.8 分钟，新建的隔离库）。
- 修 D463 后：
  - 闭包单元用例新增 7 个（命令回执正例 1 个；未知回执、他型号回执、版本不为 1、私有回执 4 个负例；原生文本冒充报告 1 个；已上传原件的报告读字节 1 个）。基点副本上 6 个失败；原生文本那个在基点也通过，因为基点按位置格式同样拒绝，它守的是新路径。
  - CAPA 事实相关范围同上，705 个通过（约 30 分钟）。
  - 完成整改的整链 `test_completed_formal_fulfillment_chain.py` 通过（20.5 分钟）。
  - 复核页读取（`review_context.py` 也调 `read_participants`）没有端到端用例，未单独验证。

## 余项（已登记到清单）

- D460：D358 租约失去后到停下仍有窗口（最长一个心跳加上到下一个安全点）；落账时核对租约仍在本会话未做。
- D461：同类循环导入还在其他登记成员上（`preproject.models`、`projects.work.models` 单独先导入仍失败，基点相同）。
- D462：生命周期图每次构建都扫描租户内全部个人运行，没有按来源品类的索引。
- D463 ✅：具名复核记不下真实验证运行的参与者材料（D287 第二处），你选 A（P119），已修。

## 迁移

- 新增 `s0_0915_personal_run_lifecycle`（占位号区间 `s0_0915`–`s0_0919` 只用了这一个），down `s0_0869`，**集成时按真实 head 重排**（11-11 第五轮集成改为 `s0_0887`，接 `s0_0886`）：文件名、`revision`、`down_revision`、`schema_s0_0915.py` 模块名与导入一起改。
- 它在升级前要求 `m3_lifecycle_nodes` 与 `s0_0852` 的定义逐字一致。若集成分支上别的迁移在它之前改过 `m3_lifecycle_nodes`，须改为以那条迁移的定义为前驱、重新生成新定义。
- 往返：`s0_0869`↔`s0_0915` 通过（[记录](d274-migration-roundtrip.txt)）。测试库是 `create` 往返后的状态。

## 合同

没有改接口和操作，没有重导出 `openapi.json`；`tools/validate_contracts.py` 通过。确认稿新增 P119。

## 环境

隔离 `pdos_test`（127.0.0.1:54777，标记 b5fc3aa0）与同标记的检查点库（127.0.0.1:57452）11-10 已销毁。D463 的验证另用 `create` 新建的隔离 `pdos_test`（标记 11555722，同样经过 head→base→head 与 seed），11-11 收尾时销毁。草稿区的基点副本不在仓库里。
