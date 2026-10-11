# B7 root 实施交接（0421 源码只读快照）

本轮不连接数据库、不调用模型、不修改冻结候选或公共实现。主库 `s0_0421` 及 0420/0421 成员资料/来源栅栏实证由 root 提供；旧私库 Category clock 拒绝不再列为主线未修问题。B7 汇合时应使用届时 B6 的实际 head，不能把这里的 0421 当最终汇合点。

代码路径以下均以 `pdos-next/server/` 为根；精确源码哈希与函数行号在 `b7-root-handoff-0421-source.json`。这是接线清单，未执行其中的修改/迁移/测试。

## 1. 公共 Context、Run 与资格

| 接线处 | 现在可直接复用 | root 必须补齐 |
| --- | --- | --- |
| `pdos_next/service.py:60 Context` | actual tenant/actor/requester/category、cancel_epoch、agent_run_id 已存在；frozen dataclass | 末尾追加内部可选 `agent_call_id: UUID | None = None`，保留现有位置参数导入；run_id/agent_run_id 互斥，agent_call_id 必须属于 actual agent_run_id。HTTP Command/模型 payload 不新增这些权限字段。 |
| `service.py:465 check_run` | 现有公共新写位置与持锁事务 | 新 Agent 分支读取并刷新实际 AgentRun、AgentToolCall；目前 ctx.run_id=None 直接返回 None，忽略 agent_run_id。禁止把 AgentRun 伪装旧 Run；旧来源技术记录不得继续作为另一条 AI 领域执行链。 |
| `service.py:483 check_qualification` | 公共 T2 具名本人入口、操作档位注册与当前授权 | 对 Agent 新写改为实际 Call 的 DomainBinding → actual skill load Event / skill version+digest → actual model Call+reply index/model_version/route digest；基于 actual TenantSkillEnablement 的租户×技能×模型审阅事实作最终 T0 判断。当前只允许旧 source_claim+Qualification/provider_version，不能直接适用单小Pai。 |
| `service.py:416 append_receipt` | 已写 ctx.agent_run_id，和 ctx.run_id 分列；已有 Receipt/Audit/Outbox 与 request_digest | 保持 Receipt 来自共同命令；Call UUID 属执行账本，不另造业务回执。Outbox correlation 目前 `ctx.run_id or command.command_id`，root 可在现有消费者合同允许下纳入 actual agent_run_id；不能把 AgentRun 当业务 subject 或修改业务事件类型。 |
| `agent_kernel/execution.py:23 check_run_binding`、`:106 verify_source` | actual Run 信封、取消/撤回 epoch、actual ModelCall、skill Event、reply args/index、当前工具/技能一致性；均可在现有 Session 复用 | 公共执行必须仍验证命令 category/product 与 actual Run 一致（NULL 也精确），actor=Run.writer、requester=Run.requester，actual Principal/Grant 当前授权与业务 owner 权限。prepared Call 必须 started、domain_t0、同 operation/命令摘要，不能凭任意已完成 Call 获得新写权。 |

内部 adapter 的 Context 应由 actual Run/Call 构造：

```python
Context(
    tenant_id=scope.tenant_id,
    actor_id=scope.writer_id,
    requester_id=scope.requester_id,
    run_id=None,
    category_id=scope.category_id,
    agent_run_id=scope.run_id,
    cancel_epoch=scope.cancel_epoch,
    agent_call_id=actual_call.id,  # root 待追加字段
)
```

不需把 selected_skill/model_version/route/model_call_id 再复制为可传入的 Context 政策字段：以实际 agent_call_id 查询不可变 DomainBinding 即可。`bindings.py` 已提供 SkillBinding/WriteSource/ModelBinding/DomainBinding；native tool call.id 不作身份。`policy.qualified(...,lock=True)` 已刷新并锁 TenantSkillEnablement，核对实际版本、模型、审阅者/时间/至少10个不同案例及撤销状态；公共 owner 可复用该事实判断，但仍负责当前操作档位和领域执行权。合成 fixture 的审阅行不是实际资格授予。

T2 必须同时拒绝 agent_run_id/agent_call_id 的执行身份；Human T1 ai.run.revert 的 payload.run_id 仅是目标，ctx 两种 Run 与 Call 字段均为空。个人 Run category=None 不能伪造必填 category 的公共 Command；个人读取/研究与后续具名归入品类由实际 owner 接入。G0 product_manager 消费属于 M3，不在 B7 补做领域动作。

## 2. 同 UOW 的 prepare / execute / finish 位置

实际调用路径已有：`graph.py tools/call_tool → BoundHost.write → KernelAdapters.execute_command`。待 root 注册的签名保持：

```python
execute_command(scope, operation, arguments, intent_key, *, source: WriteSource) -> dict
```

`operation` 必须来自实际注册 ToolSpec；source 来自 graph 的 actual ModelTurn.ledger_call_id、reply index 和实际加载 skill Event。adapter 只组装业务 payload 与服务器 Command envelope，不能接受模型交付的完整 Command、Context 或资格。

1. **先做已完成结果恢复探测**，见下一节；miss 结束其 UOW。
2. 新写开现有 tenant_session / category_transaction，actor=writer、requester=human；用公共 PAYLOADS 规范化 payload，建立 actual category/product、expected_revision、actual source_read_set。命令摘要必须与 `service.execute:780` 完全相同：operation/category/product/expected_revision/source_read_set/payload；command_id、意图 key 不纳入摘要。宜由公共 owner 提取一个共用纯规范化函数，避免两份摘要漂移。
3. 在 `command_scope(lock=True)` 所在公共锁阶段先持 Principal/Grant 与实际领域 root/object 锁，再调用 `prepare_domain_call`。当前产品消费品类来源已由 command_scope 获取 Category→Product；CategoryScope 本身仍只锁授权行，B7 品类级路径须在 Run 前取得实际 Category 锁。不要在持 Run/Call 后才让末尾 trigger 取得 Category；不要任意重复查询或新增期限规则。
4. `prepare_domain_call(session,scope,spec,arguments,source,catalog=...,registry=...,route=current_route_in_session,command_digest=...,read_receipt=...)` 领取 Call；返回 `(actual_call,None)`。`route(session,scope)` 必须刷新并锁实际 ModelConfigurationHead 后取实际版本/SecretPort route。SessionConfigurationStore.current 当前不锁 head；这段锁回调由 root 接入。返回 prior_result 时直接恢复，不进入新写。
5. 将 actual_call.id 注入内部 Context。共同 `execute` 的 **新写分支**（当前 require_access/check_run/check_qualification/prove_sources 在 `:869–872`）核对上述 actual AgentRun/Call 与公共最终资格，再办理领域动作、Receipt、Audit、Outbox、RequestKey。
6. 公共 execute 返回 actual Receipt 后，在 **同 Session、外层 commit 前** 调用 `finish_domain_call(session,scope,call.id,receipt.id)`；它核对 Receipt 的实际 tenant/category/Run/writer/requester/operation/request_digest，并完成 Call。返回公共 receipt_view 加 server-only agent_call_id。Call.started 不单独提前提交。

最小公共结构可由 root 拆成“既有恢复前半段 + 新写核心”，或在公共 execute 新写锁段挂受控 prepare/finish hook；不要为了外部 adapter 先执行 KernelStore.claim 再锁业务对象。`KernelStore.claim/settle/reconcile` 明确禁止 domain_t0 使用独立 Session，不能用它们完成领域动作。公共 check_run 不应在 Run/Call 后重新获取更早的 scope/object 锁；沿已有 request proof 复用本事务事实。

同 UOW 锁顺序为当前公共 scope/领域锁 → AgentRun → AgentToolCall → current configuration head → TenantSkillEnablement → 原来源/领域动作所需后续锁；统一与撤回 owner 的 scope→Run 顺序。Run/Call 端口已有 populate_existing，避免旧 identity map 的 epoch；root 新查询同样保持刷新。没有新外部发送，不使用 unknown-send 重试逻辑为领域 Call 占位；模型未知费用原占额不由这些端口释放。

## 3. 恢复早退与语义复用的剩余缺口

**可复用端口**：`recover_domain_call(session,scope,spec,args,source,command_digest=原摘要,read_receipt=callback)` 返回 `(actual_call,prior_result)` 或 None。完成恢复不需要 catalog/route/技能启用/资格/写授权/来源/预算，不创建 Call、Receipt、Outbox，也不 flush；actual cancellation/revert epoch、Run/Call 所属和当前读取仍核对。callback 必须由公共 owner 检查当前 Receipt/实际 subject 可读范围，成功时返回值忽略。先锁读取所需身份/Grant，再 Run→Call，不加写对象锁；miss 后结束该 UOW，再开新写 UOW。

**尚未接入**：冻结 graph `tools` 一开始 `restore_loaded`，随后 registry.authorize/ports.qualified；BoundHost.write 也先 verify_source。故仅在 execute_command 内加 recover 太晚：技能停用/更版或资格撤销后旧 checkpoint 会先失败。root 必须接一个 server-only 完成 Call 读取入口（Worker/HTTP 或约定的 host recover port），在这些 **新推理/新写** preflight 之前按实际 checkpoint/已固定 Call 恢复；返回历史结果不触发新模型调用。需要改 graph/host 时另交给相应文件 owner，不能以“已有 recover helper”宣称该路径已通。

原摘要取实际固定请求/checkpoint/DomainBinding，不能用当前来源水位重新拼摘要。不同 args/index/operation/来源 envelope 仍冲突。已完成/partial/failed Run 可读原 Call/Receipt；cancelled/reverted/旧 epoch 拒绝继续执行，历史事实仍保留并由普通历史读取呈现。

公共 execute 目前同请求/同语义会早退旧 Receipt；**跨 Run 或跨 Call 的旧回执不能 finish 到新 Call**，否则整次撤回会错误认领历史。root 需定义服务器明确的“复用已有结果” outcome，保持旧 Receipt/旧 Run 归属与当前读取、零新业务事实；现有 BoundHost.receipt 只认当前 Run 完成 Call，必须对应调整该 outcome 的核对。没有这个接线时新 UOW 应回滚；不得将旧回执重挂、另补 AgentRun 外键或提交 started Call。本交接不另创建未批准的业务操作。

## 4. HTTP → Temporal → worker → 注册图

| 入口 | 可直接复用 | root 装配项/实际缺口 |
| --- | --- | --- |
| `agent_kernel/api.py:53 router`、`:35 ApiPorts` | category/personal start/read/events/answers/cancel/stream；提交 actual Run/accepted Event 后再 start，稳定 queued 恢复、无同步推理 fallback | `api.create_app` 在实际 authenticated 函数定义后 include_router，传 `context_dependency=authenticated`（传函数，不传已构造 Depends）；app 尚未挂该 router。ApiPorts writer_for 取租户已登记单小Pai Principal；binding_for 解析 actual Product/Proposal/来源受众、private taint、资料类别、客户标识、read_sources/预算。不存在的 Proposal 领域能力不假设可用。 |
| `api.py:305 authenticated` | 实际 LoginSession→Human Context、URL category、active/RLS 校验；personal category=None | HTTP 不接受 writer/Run/Call/qualification 等权限字段；真实 start 的目标/source proof 由服务器绑定。当前 binding_for 在 create_run UOW 外调用，如需锁住来源到 Run 创建须协调增加 caller-Session port/挪入该 UOW；独立 callback 读到事实不等于已保持创建事务锁。 |
| `agent_kernel/temporal_port.py:15 TemporalPort` | 固定 reference keys；workflow_id=`pdos-next:xiaopai:{tenant}:{run}`；start/signal/cancel；重复 start不重建Run | **队列必须显式一致**：TemporalPort 默认 `pdos-next`；当前 worker 监听 TemporalSender 默认 `pdos-next-domain-v1`。直接实例化 `TemporalPort(client,task_queue=同一服务器队列)`，将 start/signal/cancel 传 ApiPorts。API lifespan 管理实际 Client/关闭；配置/队列不可由模型请求决定。 |
| `workflows/xiaopai.py:10 XiaopaiWork` | 单工作流 run；固定信封，signal 仅已提交 answer_ref；Activity `advance_xiaopai_run`，等待/取消/重试 | 保留，仅注入统一队列；Temporal history 只放UUID信封与技术状态，不塞 goal/全文/模型/Secret。 |
| `workflows/worker.py:161 main` | 已注册 XiaopaiWork 和 KernelActivities.advance；technical_engine=dispatch_engine；原件/安全/生命周期技术工作流可继续 | CLI `main()` 目前未装配实际 agent_kernel_adapters，缺 adapters 会进入 waiting_input/SOURCE_UNAVAILABLE。实际 bootstrap 必须构造 KernelAdapters 并传入 main；不能仅启动 Worker 就宣称Agent已可执行。 |
| `agent_kernel/activities.py:53 advance` | actual Run → KernelStore.scope → BoundHost → AgentKernel.execute；actual AgentInput归属；真实 PostgresSaver；失权由受控 dispatch 技术收尾 | 使用 actual配置/SecretPort/provider/领域ports；显式 PDOS_CHECKPOINT_DATABASE_URL、PDOS_STATE_DB_PORT/MARKER，verified_checkpoint_url；独立 pdos_checkpoints，缺配置无内存fallback。不得拿主业务库做 checkpoint。 |
| `agent_kernel/graph.py:394 execute`、`packages/pdos-agent-runtime/src/pdos_agent_runtime/graph.py` | registered_graph_context("xiaopai")，gateway只认该注册图；thread=`xiaopai:{tenant}:{session}:{run}`；Skill Event/version/digest与actualModelCall/index/checkpoint绑定 | 重装本地运行包使现有导入可用；完整 Agent 只经上述 Activity/图，不经通用 execute_graph 包一个 provider。缺真实适配时保留可见失能，不造回执。 |

KernelAdapters 已有必需 `route_for/project_context/verify_result/prepare_candidate/execute_command`；可选 read_tools/provider_client/provider_for/preload/rate_card_for/catalog/registry。root 应提供实际 RLS 数据投影、领域回执核对、T1候选和受控读取/研究工具；T1仅预填，Human实际鉴权后再预览/确认；T2只准备材料。实际模型调用 cost_required=True，rate_card_for 与实际验证钱包/保守预约配置齐全才启用；未知发送费继续保留。本轮不提出或使用新真实出站授权。

**旧路径退出点**（保持必要可导入接口不等于继续启用）：`api.py:1343 resume_work` 的 synthetic execute_graph fallback；`workflows/transport.py:44` 将 ai.work_* 送 SourceWork；`workflows/definitions.py:8 SourceWork`；`worker.py:40 Activities.advance` 的 selected_provider/runtime.resume；`runtime.py:227 resume` 的旧 Run/Invocation/来源抽取与 `agent_execution.py` 旧 ClaimGateway组合。B7 取消它们的完整 AI 派发/模型生成入口，来源解析技术记录和 ParseOriginal/安全/生命周期 Worker 保留。旧 Run 不能继续为另一 Agent 取得 T0；新 ai.run.cancel 的事件 subject 也须按 actual AgentRun 区分，不能继续落 SourceWork 的 work_id 信封。

当前新 Run API 是“提交后直接 start Temporal，再由同键重试恢复 queued”，没有 AgentRun 专用 Outbox 定时补派发器；若 root 要保证客户端不重试也能补送，需增加实际 queued Run 扫描/受控派发并保持同 workflow_id，不能假称原业务 Outbox 已承接新入口。

## 5. 0700 重接主线的执行步骤（本轮未执行）

1. B6结束/冻结接线候选后，由 root 在其独占隔离环境核对 marker/endpoint/actual alembic head、业务schema、必要备份。现主线0421只是起点；M2原私库0716及其0404–0409复制fixture是历史证据，不得用 stamp 冒充合流或拿已有不可变fixture降级。
2. 保存原 `s0_0700 down_revision=s0_0011, branch_labels=("m2",)` 的源快照与原候选。root 在**新 B7 汇合候选**中只将 0700 parent 重接为届时实际主线 head（0400–0699号段），保持0700–0716 revision与连续parent不变；不要本轮改冻结文件，也不要继续拿旧源码hash宣称合流候选。修改由 root 在接线阶段拥有。
3. 检查迁移图只有预期线性 head；0700先建10自持表/技术守卫，0703添加AgentInput、0707添加验证钱包，合计12表；0714在AgentRun存在后装 `uq_agent_runs_category_identity` 和公共 Receipt composite FK。root0405列/互斥check应已存在；公共 metadata 已登记 Agent models，不重复建旧schema/public列。0700–0716维护自身kernel函数，不应覆盖0420/0421公共来源guard。
4. 使用明确 MIGRATION_DATABASE_URL 和经过核对的隔离目标，显式 upgrade `s0_0716`，不对原双头盲目 upgrade head。结构核对后再创建新的可信binding fixture；0700→0716的往返到实际root基线放在**新fixture写入前、隔离演练库**，不用已保存M2账本或主库作破坏性降级。0716往返结构/check/权限以实际SQL核对，空Alembic日志不能代替证据。
5. 公共全metadata与FK/触发器/RLS比对；后续新增接线列/协议约束按汇合后的实际head单调新号分配，不在旧0716塞新行为。更新root的新候选manifest和选取日志；旧M2 manifest/私库保持历史可核验。

## 6. 必要最小实库/Temporal场景（root 串行）

| 受影响范围 | 必须用实际实现证明的结果 |
| --- | --- |
| 迁移/权限 | 公共head→0716→基线→0716（新fixture前）；全metadata、0714 FK、0716 NOT NULL/shape/immutable；app正常端口、pdos_agent业务/Call直接DML拒绝。 |
| 真公共T0事务 | actual AgentRun + fixed skill/model reply fixture，经公共 service.execute 实际 Claim 与独立 Artifact；Category-only Artifact正例、Product消费Category来源的Claim；Call/领域对象/Receipt/Audit/Outbox同commit，NULL ordinary Grant仍有效。不能用旧合成Receipt替代。 |
| 末尾失败 | 公共Outbox写/finish或commit注入失败，领域对象、Call、Receipt、RequestKey、水位全回滚；无模型或预算新副作用。 |
| 可信绑定/取消 | wrong model args/index、跨Run model/load event/Call、旧epoch（含提前载入identity map）、取消/整次撤回后新写、route/Secret配置旋转、当前资格或can_write撤销拒绝。比较实际写入集合无变化。 |
| 完成恢复 | 当前读保留而can_write/技能启用/资格撤销后，经实际恢复入口取原Call/Receipt；SQL记录零新Call/业务/预算/Outbox；当前读撤销拒绝但原事实保留。checkpoint和HTTP均不得先走新写preflight。 |
| 语义复用 | 同Activity重复同model reply恢复同Call/Receipt；跨Run同语义采用明确reused outcome，旧Receipt归属不变、新Run整次撤回不撤旧业务。 |
| 实际持久链 | 真实HTTP start→同队列真实Temporal→实际Worker→注册LangGraph→公共领域adapter（仅本地合成provider）；interrupt/answers仅已提交actualAgentInput、重复signal、Worker重启恢复同tenant/session/run；取消/撤回停止后续动作，停模型可见失能。 |
| 技术收尾 | actual失权仅dispatch worker收尾；app/Agent/跨tenant/健康Run拒绝技术函数；终态/撤回不反转，未知费用保留，业务零变化。 |

这里只安排受影响场景，不重跑无变化217/76项；B8集中完整候选与性能/恢复出口。实际Temporal+合成provider可以证明持久接线，不能证明真实协议/模型资格/DPA/真人验收；真实模型仍0次，另待root按具体可执行提案取得配置/调用授权。

## 冻结证据

冻结 `trusted-call-binding/private-db/source-manifest.json` 的34文件哈希复核一致，digest `701785a12e32c159e212a944c1c51e1a968cbc32b8acbda6f1de2b7536638a62`。`final-private-candidate.log` 是76（29实际PostgreSQL+47 pure），`graph-resume-pure.log`另11，未在本轮重跑或相加成统一出口。此前217与公共Human整次撤回6项的准确边界见 `candidate-boundaries.md`；当前整次撤回仅Claim与 original_id=NULL 的独立Artifact。公共主库迁移/实际Agent命令/真实资格/HTTP→Temporal尚待本交接实施。
