# LangGraph + Temporal 执行边界收口

用户要求所有 Agent 使用 LangGraph + Temporal。此前原工程的应用能力分别运行、普通会话以进程后台任务执行；新工程 Worker 固定传入空 provider，API 默认关闭队列。因此 Next 的局部底座没有成为全部执行入口的约束。

本次落地共同纯运行包、原工程 31 个入口及网关绕行拒绝、普通对话判断/研究图、委托持久定时器、开发启动链；Next API/ASGI 默认使用持久队列，Worker 使用独立模型工厂并保存具体缺失条件。业务服务、身份、资格和写入分级保持。[执行合同](../../../design/2026-10-07-agent-runtime-convergence.md)列明责任、当前恢复能力与余项。

已执行的受影响验证：

- [原会话、研究、委托和核心恢复检查](original-final.log)：36 项通过。包含真实本地 Temporal + PostgreSQL、Worker 强制终止后原 Workflow 的 Activity 自动重试、完整检查点恢复零重复效果、无检查点等待对账、Temporal 定时器持久化、业务对话实际网关/授权/租约/计量链。供应商 HTTP 与资格样本为合成，未真实调用模型。
- [事件与租约](events-leases-v2.log)：22 项通过后，历史降级检查因专用临时 PG 的锁容量失败；仅将自有测试实例的容量调至 1024 后，[9 项定向复查](events-leases-final-v3.log)通过，包含降级守卫、schema 对照及框架编码病例。随后[独立门禁检查](architecture-entry.log)为 8 项通过，包含固定入口覆盖、真实网关绕行拒绝、事件声明与结构化结果往返、当前身份复核。
- [Next 检查](next-regression-final.log)：166 项通过，覆盖队列默认、请求防重、禁用队列拒绝正式直执行、真实 PG 的失能状态记录、受控 provider 工厂、原资格/出站/预算网关回归。Next 独立临时库进行了真实 head/base/head 初始化。
- 新增四个运行适配器的聚焦严格类型检查（导入模块 silent）、两端受影响 Python 规范/编译、启动脚本语法检查通过；全依赖类型展开报告 12 文件 115 项错误，未宣称全后端类型通过。Next 仅变更失能提示展示；受影响前端类型与规范检查通过，见[收尾记录](closeout.md)，无新的全前端构建或 GUI 验收声明。

失败与恢复保留：初次原库缺少迁移前置角色，补齐后核心检查通过；一次实际对话链首次合成计量输入上限不足，修正独立测试计量样本后通过，[原失败](domain-temporal.log)与[复查](domain-temporal-v2.log)保留。事件结果的 dataclass 编码错误已修复并经事件执行及往返检查验证。现存产品影子评测旧用例在“品类内创建产品线”处被当前合同拒绝，未进入 Agent，本轮未将其计作框架或八能力资格通过。[旧用例失败](original-regression-recheck.log)保留。

独立原测试库为 58949/pdos_test，Next 测试目标为 61762/pdos_test，私有备份/停止记录见[收尾记录](closeout.md)；未对 57432、62513、62158 或其他会话测试库执行 repo 测试。公开日志已移除连接凭据。新增开发状态服务使用 61595/pdos_agent_runtime、Temporal 61596/pdos-agent-local，Workflow/Activity poller 均已在线；检查时未发起真实业务动作。开发状态与测试状态分离。

未完成项：Next 的独立真实模型配置/资格/出站接口与真实资格证据、生产 Temporal PG、G5 完整主协调器/Skills/长期记忆及正式人工出口。当前未知动作仍须业务回执对账，不能宣称全部能力已具备逐工具自动恢复。本次未生产启用、外发、push 或改变人工批准状态。
