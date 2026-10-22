# 事件运行服务授权

2026-09-11，N0-03，本地候选 migration `0079_event_authorization`。本片接入预算绑定事件运行的 AuthorizationEnvelope；完整 ContextManifest、用户委托授权和全量版本束仍待建设。

## 签发与主体

Agent 领取新事件运行时，数据库在同一事务内建立租约并签发授权。只有受限 claim 端口能够触发签发，模型与 Agent 不能传入主体、授权范围或期限。一个订阅对应一个具名服务主体，名称为 `event-agent:<agent_key>`，主体 UUID 使用订阅 UUID。主体状态和 revision 随订阅暂停/启用更新；已有主体身份不能直接改写。

授权采用已冻结 AuthorizationEnvelope DTO，记录 tenant、run、原预算 lineage、项目 scope、服务主体、订阅策略来源、签发时间和期限。`trigger_actor_user_id` 从对应事件的审计记录取唯一明确作者；无作者或多作者歧义保留空值。作者只是触发来源，不继承作者角色或委托权限。

本片服务策略版本为 `event-service-project.v1`；`capability_version=<agent_key>.event.v1` 和 `toolset_version=internal-read-tools.v1` 标识本片的事件 Agent / 内部读取策略。它们不是完整的部署版本束或真实模型用途资格。现有 Agent 工具白名单、rollout 约束、模型资格、预算和循环发布件继续独立执行。

授权范围收窄到触发项目；来源中保存项目锚点以及订阅/主体 revision 的摘要，描述授权依据，不冒充完整业务内容快照。供应商和组合视图在返回行及聚合前执行项目锚点过滤，同租户其他项目不自动可读。显式多项目/产品锚点集合的管理与授权尚待实现。

## 当前权限与历史

`event_authorization_is_current` 与数据库租约共同约束读取、工具登记/派发、模型出口、上下文收据和 Finding 写入口。每次受限操作都要求订阅及服务主体仍有效、主体 revision 与原授权相同、未过期且项目匹配。

暂停订阅立即使在途授权失效。再次启用会递增 revision，不恢复旧授权。Worker 可以在租约尚未到期时收回这些运行，并记录 `AGENT_AUTHORIZATION_CHANGED`；尚未开始的队列运行直接失败，`started_at` 保留空值。已存在 Finding 回执的恢复只确认历史成功，不重复写业务结果。

授权期限取原 lineage 绝对期限与适用的事件 dispatch deadline 的较早者。恢复只复用原授权，不延长期限、不换主体、不重新分配预算。未知模型回执和已持有的预算原样保留，撤权不是费用归零或退款。

每个新工具 Observation 和 ContextReceipt 由数据库自动关联同一授权 ID，并通过 tenant/run 复合外键保持范围一致。执行器经租约读取并验证 Envelope；授权主体和事件作者不放入模型可见上下文。ContextReceipt 是已投影请求收据，仍不能当作完整 ContextManifest。

旧的未绑定预算运行继续原兼容路径，不补造 Envelope。迁移前已执行但没有 Envelope 的预算运行在恢复时停止；已有工具、模型或恢复历史的队列也不能补发授权。未开始、没有执行历史的预算事件可以首次签发。暂停/过期的排队运行在领取前清理。

## 数据库安装与撤回

新增 `agent_service_principals`、`agent_authorizations`，并为工具观察/上下文收据新增可空授权外键。运行账号没有这两张表的直接读写权限。只有当前 Agent 租约可调用 `read_agent_authorization`；私有签发端口与底层授权检查不授予 Agent/Worker。

Alembic 只替换已经安装的受限投影视图；全新库由 DBA 模板安装视图，避免迁移依赖尚未安装的角色边界。DBA 模板在全部定义和授权之后统一提交，重复安装幂等。撤销脚本撤销角色权限并删除公开读取端口，保留审计数据。

没有授权历史且没有新策略停止状态时允许降回 0078；存在授权历史时拒绝降级，已有新停止状态也不能通过回退旧CHECK约束丢失语义。生产部署、真实用途资格发布及各阶段出口仍需原有审批。

## 后续

继续完整 ContextManifest、精确 capability/toolset/deployment bundle 绑定、多锚点授权、用户/委托/Owner 运行、衍生来源 ACL、持久等待与逐步恢复、收费工具费用与未知用量对账。N0-03 保持部分完成。
