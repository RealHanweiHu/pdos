# Agent模型结果checkpoint与过期恢复

2026-09-10，N0-03，本地候选migration `0073_agent_result_checkpoints`～`0074_checkpoint_scope_keys`。本片覆盖现有事件Agent完成模型调用后、发布Finding及终结运行之间的恢复。所有操作仍是运行元数据服务；模型工具列表没有新增写入口，Finding仍需原来的人工接受与独立应用。

## 保存与恢复

实际受限执行器在Gateway返回后、创建Finding之前保存`agent-result.v1` checkpoint：冻结上下文、模型结果/错误、关联invocation、最近事件、已用知识及专业域观察，以及prompt/工具定义/输出与上下文schema/preflight版本摘要。数据库验证当前lease、tenant/project/run/Agent、实际trace，计算正文摘要。模型trace、checkpoint、恢复记录与Finding之间还通过tenant/run/id复合外键限制同租户同运行引用。每个run只有一份该阶段记录，相同正文幂等复用，冲突或直接覆盖/删除均拒绝。

dispatcher每次循环先扫描最多100个已过期的事件run；只有拥有到期字段和token的运行适用，主动用户请求及旧无期限运行不被猜测回收。行锁和`SKIP LOCKED`允许多个监督进程并发，原lease只有一条恢复记录。

| 现场证据 | 处理 |
|---|---|
| 已有该run的Finding回执 | 记录`receipt_completed`并终结run，不新增Finding/action/event，不改变人的review/apply状态 |
| 模型会话open/unknown或预算仍持有 | 记录`AGENT_RECOVERY_RECEIPT_UNKNOWN`并停止；不释放预留、不重发模型请求 |
| 没有完整结果checkpoint | 记录`AGENT_CHECKPOINT_MISSING`并停止；不能从只有用量的trace编造模型结果 |
| 订阅暂停、恢复次数或活动/绝对期限耗尽 | 保存具体停止原因，不扩大权限或重开额度 |
| 有完整checkpoint且允许继续 | 同一run重新排队，新worker领取新lease后只读复核并复用结果，不执行模型节点 |

重新排队保留原预算lineage、期限、token记录和活动区间。已批准的`transient_attempt_limit=2`在这里限制同run最多一次自动恢复排队；这不增加模型调用次数。旧worker无法使用旧token保存checkpoint或Finding。恢复动作与运行状态变更同事务提交，记录保存在`agent_run_recoveries`。

## 恢复时的复查

新执行器重新检查capability启用状态、当前订阅、SQL活动/绝对期限，以及保存的runtime摘要。摘要具体覆盖prompt正文、静态工具定义、指令、输出schema、上下文/观察schema和preflight版本，不等同于已经实现全部部署版本束。

恢复通过当前受限数据库投影重建上下文进行比对，不把旧`get_project_context`返回的冻结对象当成实时鉴权。项目/触发来源、业务执行数据、Multimodal与User信息发生变化时停止；仅排除已被原调用改变的两个运行计数：`remaining_tokens_today`和`agent_runs_today`。实际预算仍在SQL单独检查。冻结正文保持原样。

最近事件和专业域观察也重新只读核对；已用知识按保存的ID读取当前可见投影，核对状态、内容摘要、标题、正文、适用范围、标签和来源引用。不会再次调用嵌入模型计算相似度；保存的相似度只属于旧检索观察。来源变化返回`AGENT_CHECKPOINT_SOURCES_CHANGED`，不静默改写原结果。Finding仍经过当前确定性预检、质量控制、lease及活动额度写入检查。

`no_action`和已完成的degraded模型结果可沿同一路径收口；degraded不会触发新的schema修复。缺失/未知回执的运行被标为明确失败，费用未决状态仍保留。已有Finding回执的收口只证明已产生候选，不证明业务应用完成或所有费用已对账。

## 权限与运行

Agent只有保存/读取自己当前租约checkpoint的两个函数权限；没有checkpoint/恢复表直接读写权限，也不能调用恢复监督函数。Worker只有扫描过期运行的窄函数权限，不能读取模型结果正文。DBA模板与迁移内定义一致；执行器、dispatcher、迁移和模板须采用同一候选版本。生产部署仍遵循原逐次批准关卡，本次未执行。

dispatcher日志新增`recovered`/`stopped`数量，原run查询可见queued/failed及具体错误码。迁移遇到checkpoint或恢复历史时拒绝降级；空测试历史往返有证据，不代表生产历史允许删除。

## 继续建设的范围

这是模型完成阶段的恢复点，不是完整LangGraph持久checkpointer。模型执行中断且结果尚未保存、工具逐步checkpoint、waiting_input/人工恢复、主动请求Owner lease、完整generation/运行版本束、在途请求取消和全部领域的衍生来源ACL仍需继续接入。结果保存失败不会自动重新调用模型；未知外部回执仍需查询或有据对账。

默认预算仍legacy；本片在受限事件执行器中保存结果，但没有自动开启真实租户完整预算、发布真实计量资格或修改原P/Q/Sprint出口。

验证见[验收记录](../reports/2026-09-10-n0-03-agent-checkpoint-recovery-validation.md)。
