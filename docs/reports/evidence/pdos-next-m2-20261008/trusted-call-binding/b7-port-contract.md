# B7 领域事务接线合同

## 入口与事实来源

实际入口：`agent_kernel/graph.py` HostPorts.write → `host.py` BoundHost.write → KernelAdapters.execute_command。

新 adapter 签名：

```python
execute_command(scope, operation, arguments, intent_key, *, source: WriteSource) -> dict
```

`source` 为服务器内部对象，含 SkillBinding(key/version/digest/load_event_id)、model_call_id、response_index。它不来自模型 payload，不出现在 provider tool JSON，也不是可由 HTTP 调用者提交的执行资格。

Gateway 将实际 AgentToolCall.id 作为 `ModelTurn.ledger_call_id` 返回。图绑定该实际 model Call 的回复序号；工具 native call.id 不影响权限、幂等或 Call UUID。Skill Loaded 不是独立表，复用 `AgentEvent`；事件完整 body 为 type/key/version/digest/isolation，且必须属于同一实际 Run。

## 同 Session 前置

调用者使用现有 tenant_session，并保持 actor=Run.writer_id、requester=Run.requester_id、实际 tenant/category。scope 从实际 Run 读取，包含实际 session、product/proposal、资料性质与取消 epoch。

对于新写入，adapter 构造服务器共同 Command，绑定实际业务对象、版本与来源 read set；不接受模型提供的 Context、执行权限或完整服务器 Command envelope。command_digest 使用公共 service.execute 的 request_digest 规范（已规范化 payload + operation/category/product/expected_revision/source_read_set）。

同一调用必须按下面顺序办理：

1. 沿现有 command_scope 锁排序后的 Principal/Grant 与实际业务对象，保持普通 NULL Grant 不设到期及实际 can_write 守卫。
2. prepare_domain_call 锁实际 AgentRun，再锁该幂等键的领域 Call。
3. 对新 Call，prepare 调用 root 提供的 `route(session, scope)` 内部回调，在该 Session 锁当前模型配置 head 并返回当前 route；资格输入来自实际 DomainBinding/Run/model Call。prepare 自有资格预检查也锁 TenantSkillEnablement 并 populate_existing；最终资格、档位和执行权仍由 root 公共 check_qualification 判定。
4. 公共 Context 注入实际 agent_run_id/cancel_epoch/agent_call_id；调用共同 service.execute，持有来源与领域所需锁。
5. finish_domain_call 核对实际 Receipt，并完成 Call。业务对象、Receipt、Audit、Outbox 与 Call 一次提交；任何失败全部回滚。

`route` 推荐传服务器回调 `(session, scope) -> current_route`，在 Run/Call 锁后取得实际配置 head 锁。也支持 route 对象，但调用者必须此前已持有本 Session 当前配置锁，且统一该路径的锁序；不能传入未经当前 owner 核对的旧 route。现有 SessionConfigurationStore.current 不会锁 head；回调由 root B7 接线。

不要先调用 KernelStore 的独立 transaction/claim 来占 Call，再进入共同业务对象锁；否则锁序与公共撤回相反。不要在领域 UOW 中调用 KernelStore.settle/reconcile；它们会另开 Session，新 domain_t0 明确拒绝此用途。

## 领取、重放与完成

```python
prepare_domain_call(
    session, scope, spec, arguments, source,
    *, catalog, registry, route, command_digest, read_receipt=None,
) -> (AgentToolCall, prior_result_or_none)

recover_domain_call(
    session, scope, spec, arguments, source,
    *, command_digest, read_receipt,
) -> (AgentToolCall, prior_result) | None

finish_domain_call(
    session, scope, call_id, receipt_id,
    *, replay=False, read_receipt=None,
) -> dict
```

首次领取返回实际 Call + None；Call UUID 已 flush，可直接交给公共 Context。prepare 不自行提交，不写业务事实；CALL.started 不得单独提前 commit。

同键已完成返回原实际 Call 与原结果；核对已固定的载荷、binding、实际 Receipt 和取消/撤回 epoch，再调用 root 提供的 `read_receipt(session, scope, receipt)` 检查当前读取权限。callback 在无当前读取权限时抛公共 DomainError，成功时返回值忽略；缺 callback 明确失败。不得重核当前来源、route、技能启用、写权限、T0 资格或预算。结果为公共 receipt_view 加 server-only agent_call_id；该 UUID 对应实际账本完成事实。不同模型结果索引、参数、命令摘要或 binding 不可占用原键。

独立 recover_domain_call 不需要 catalog/registry/route，且无新增 Call、flush、业务或 Outbox 写入。completed/partial/failed Run 保留历史执行结果；cancelled/reverted/旧 epoch 不能以恢复启动原执行。root 应在新写入的 command_scope/can_write/来源/资格之前先提供当前读取恢复入口，遵守 v1.1 §08.3/§08.11；只读取原回执不能进入 BoundHost.write/graph 当前技能资格 preflight。Run/Call 锁查询须显式刷新已加载的 identity map；自有端口已用 populate_existing=True，实际 SQL 旧 epoch 负例见 private-db/result.md。

恢复的调用者先锁当前读取所需 Principal/Grant，再由 helper 锁 Run → Call；read_receipt 只检查当前可读性，不在 Run/Call 后引入写入对象锁或新的写资格。恢复 miss 返回 None 后应结束该只读 UOW，再按上节新写锁序开新的事务，不能持 Run 锁后才取得新写的 Product/领域对象锁。新 Call 的 claim、业务、Receipt、Outbox 与 finish 始终在同一新写 Session；只读探测不占 Call。

恢复使用原请求/检查点固定的 command_digest，或由 root 从实际已绑定 Call 取得该原摘要；不得把当前来源水位重新聚合成新的摘要并伪称同意图恢复。新请求/新命令的不同摘要仍返回冲突。

finish 仅接受同 tenant/category/实际 Run/writer/requester/operation/request_digest 的真实 Receipt；绑定 Product 的 Run 还须同一 Product。它不生成领域回执，不调用模型，不改业务表。

跨 Run 语义去重返回的旧回执不能通过 finish，也不能伪造成新写。root 应明确实现已有结果引用的独立 outcome，保持旧回执和整次撤回归属；当前缺少该 outcome 时须回滚，不能部分完成。

## root 最小接线与受影响出口

- Context 增 agent_call_id，仅内部 adapter 注入；HTTP/model payload 不接受该字段。
- check_run/check_qualification 对新写读取实际 AgentRun + AgentToolCall + DomainBinding，核对 operation、Run/model/skill/epoch/当前授权；完成结果早退只核当前读权限与已固定身份/意图，不重新要求写资格。
- 注册 execute_command adapter，并让 Claim/Artifact 等领域动作走上述 Session。不能启用另一个旧 Agent 或直接业务 DML。
- 接入恢复 owner 与 read_receipt callback，供 HTTP/Worker 在新写 preflight 前恢复实际完成结果；图恢复后的新推理/新动作继续核对当前技能/资格，不能把恢复旧结果当新执行。
- 主库汇合 s0_0716 后核对 metadata、RLS、结构 CHECK、binding 不可变、回执实际归属与升级/降级。
- 公共实库测试：Claim/Artifact 真正 T0 命令→Call/Receipt/Outbox一次提交；末尾失败全回滚；跨 Run/取消/撤回 epoch/新写撤权/模型旋转拒绝；只剩当前读权限或技能/资格撤销后恢复原 Call/Receipt，零新增写入；重复 Activity 恢复同 Call 与 Receipt。纯内存端口通过不能代替这些出口。
