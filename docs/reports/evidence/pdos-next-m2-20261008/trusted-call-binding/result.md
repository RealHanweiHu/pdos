# M2 可信 T0 调用增量候选

2026-10-08。本增量只修改 M2 自有运行模块、独立测试与迁移号段。原 217 项候选是历史检查点，不能作为此次新代码的完整出口证明。后续授权的 0716 私库实际验证、实证修复与当前冻结源码见 [private-db/result](private-db/result.md)；下述 85 项保留为先前纯检查点。

## 实际改动

- Gateway 将实际 model Call UUID 写入 server-only `ModelTurn.ledger_call_id`；正常返回及已存回复恢复一致。协议中的 native call ID 仅用于模型协议关联，工具幂等键改为实际 model Call UUID + 回复索引。
- SkillBinding 固定 key/version/完整配置和正文 digest/实际加载 Event UUID。checkpoint 保存完整绑定；恢复时比较版本、正文与允许操作。Gateway 的 model Call 同时保存该次实际使用的技能集合，随后加载的技能不能授权此前生成的输出。
- AgentToolCall 增加 `execution_binding`。模型绑定保存实际模型版本、route digest、提示/工具定义摘要、隔离范围及取消 epoch；领域绑定增加实际结果索引、选中技能、operation 与共同命令摘要。旧未绑定调用明确为 `unbound`，不能作为 T0 模型来源。
- BoundHost.write 核对实际持久模型回复的工具名/arguments/index、加载 Event、Run envelope、当前模型和登记工具；向领域 adapter 传递 server-only `WriteSource`。回执读取还须与实际已完成 Call 一致。
- prepare_domain_call / finish_domain_call 只操作调用账本，在调用者领域 Session 内运行，无独立 commit。通用 KernelStore.claim/settle/reconcile 拒绝接管 domain_t0 的独立事务领取、完成或对账。
- 已完成结果恢复有独立 recover_domain_call 端口，并由 root 的同 Session read_receipt 检查当前读取权限。相同输入直接返回已绑定 Call/Receipt，不重核当前来源、模型配置、技能启用、写权限或 T0 资格，不新增 Call、预算、业务或 Outbox 写入。取消/整次撤回 epoch 与实际 Run 归属仍保留；completed/failed Run 可恢复原结果。新写入才走当前资格及来源守卫，符合 v1.1 §08.3/§08.11。
- s0_0716 从私有链 s0_0715 单调追加：NOT NULL JSON envelope、通用结构 CHECK、binding 不可变守卫。CHECK 未包含任何具体提示、技能或工具版本值；缺键/NULL 显式失败。模型 metadata 与冻结迁移保留同一结构定义。

## 验证范围

最终受影响纯测试 85 passed / 7.45s，ruff 通过，见 `affected-pure.log`。此选择是在完成结果恢复合同调整后统一运行。先前的 74 项、36 项针对性复验以及中间 76 项检查仅保留为过程证据，不能拼接计数或代替最终选择。包括实际运行的 LangGraph、内存 checkpoint、原生 OpenAI 兼容请求解析与 MockTransport、模拟的 Session/ledger 端口。没有连接 PostgreSQL、真实 Temporal 或外部模型。现有 runtime/agent_execution/worker/xiaopai 及 M2 模块导入通过；冻结迁移 SHAPE 与 metadata SHAPE 静态一致。

负例包括：模型回复参数/索引变更、跨 tenant/Run、错误加载 Event、同回复先加载后写、技能恢复漂移、缺少真实 model Call、重复协议 ID、新写资格撤销、准备后取消/整次撤回 epoch、旧运行回执重新挂接、不同命令摘要重放、恢复缺少当前读取检查/读取被拒、通用 Store 越过同 Session 完成边界。正例另覆盖当前技能停用/资格撤销后与 completed/failed Run 的原结果只读恢复，且无 flush、不调用当前模型 route。

LedgerSession/GatewayStore 是明确的内存端口替身；这些检查没有授予或证明任何真实模型资格，也没有证明 PostgreSQL 约束、事务回滚或实际公共命令整链。

## 当前未决

- 先前纯检查点未应用迁移。后续 root 已授权仅在原 51698 marked 私库应用并往返 0716，实际当前 head 为 s0_0716，见 private-db/result.md。公共汇合仍待 B7；主库最新 s0_0416 仅由 root 报告，未由 M2 操作。
- root 在 B7 接公共 Context.agent_call_id、AgentRun/check_run、当前资格与配置 head 锁、领域 execute adapter、公共 HTTP→Temporal 和迁移汇合。
- root 同时接完成结果恢复的当前读取 callback；先恢复原回执，只有缺少完成结果时才进入新写事务。BoundHost/图中的当前技能与资格 preflight 属于新 T0 执行，不能代替该只读入口；B7 的 Worker/HTTP 恢复必须显式使用共同恢复 owner，防止重新加载技能或预算失效阻断原回执读取。
- finish 仅接受本 Run 真实新写的 Receipt。跨 Run 的品类语义去重须由 root 公共 owner 明确返回「复用已有结果引用」，不能改旧回执归属；本端口对此拒绝并要求整个领域 UOW 回滚。
- 真正资格判断和最终执行权仍属于 root 共同命令；M2 内核不创建资格或直接写业务表。实际模型、主库和公共验证仍待授权/接线，不计入本增量。

事务前置、端口签名、锁序和返回形式见 `b7-port-contract.md`。
