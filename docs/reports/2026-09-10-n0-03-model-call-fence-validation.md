# N0-03 模型调用在途切换验证

2026-09-10。继续已批准 DC-07，补齐默认 Gateway 的在途登记、追加状态和安全切换基础。N0-03 保持部分完成；本片没有启用真实租户的完整预算模式。

## 实际变更

- 0064 新增 model_call_sessions、model_call_events、model_call_mode_events 三张追加表，model_invocations 通过租户复合外键关联调用会话。会话只保存范围、执行模式、时间和 trace 关联，不复制 prompt、响应正文或密钥。SQL 禁止更新/删除历史，存在会话或模式历史时拒绝降级。
- StructuredModelGateway 默认在发出 provider 请求前登记整个逻辑调用，结构化重试共用该会话；trace 成功提交后才能关闭。ContextVar 隔离同一 Gateway 的并发会话。登记失败不回退发出请求；异常、进程中断或 trace 写入失败保留 open/unknown，未知状态写入失败也保留原 open。trace 已提交而关闭失败时，可使用原 trace 做幂等恢复，无须重调模型。
- 默认 compatibility 允许旧计量调用及显式预算候选路径。当前有效 Owner/Admin 使用带 expected_revision 和证据引用的内部服务发起切换，先进入 draining；新调用被拒绝，已登记调用可完成其既定的有限重试。只有会话全部关闭、预算账本没有 reserved/unknown、旧用量没有未核实记录，才能完成切换。反向切回 compatibility 也经过 draining；取消尚未完成的切换只恢复先前准入模式，不删除在途或账本历史。
- 调用登记、模式变更、预算预留及旧用量对账使用相同租户事务锁。并发登记和进入 draining 只有一个先获得锁；不存在“看到已排空后又插入旧调用”的空隙。没有超时自动放行或跨日清零。
- 普通路径在 draining 返回 MODEL_CALL_DRAINING，在 budgeted 模式下未配置预算控制器返回 MODEL_CALL_BUDGET_REQUIRED，均为零 provider 调用及 not_invoked trace。持久模式不改变现有 capability rollout；shadow 能力仍在执行器入口被拒绝。
- 更新 Agent 安全模板，增加三个绑定当前运行租约的窄接口。Agent 不传租户、项目、Agent 类型或预算模式；数据库从有效 run 派生范围。底层通用函数撤销 PUBLIC 执行权限，Agent 没有会话/模式/预算表读写或策略变更权限。受限预算控制器尚未接线时明确拒绝 BUDGET_AGENT_ADMISSION_UNAVAILABLE。

这里的切换服务是 owner/service 内部端口，尚未提供员工 API、操作界面或自动部署开关。证据引用记录操作依据，不会自行验证部署覆盖或真实模型资格。closed 表示调用 trace 已登记，不代表用量已知；未知 legacy 用量仍单独阻止完成切换。

## 验证

| 检查 | 结果 |
|---|---|
| 调用切换、账本/对账、逐次控制器、Gateway、Schema/迁移、默认工厂 | 116 个不同测试通过；Schema 列集合补入新关联列后复验通过 |
| 真实受限 Agent/worker 与新增会话接口 | 16 个不同测试通过 |
| 共同对象、产品计划、版本时间、运行政策/采用、工具载荷与日历 | 160 passed |
| 不重复合计 | **292 个不同测试通过** |
| Ruff / 格式 | 12 个本片相关文件通过 |
| Mypy | model_call_fence、gateway、schema 三个文件通过 |
| 当前合同导出 | 共同合同四产物、运行政策五产物检查通过，获批原件摘要未变 |

常规数据库测试仅使用 `127.0.0.1:57432/pdos_test`，head 为 `0064_model_call_fence`。受限角色测试另建临时容器 `pdos-fence-security-test`，地址 `127.0.0.1:57433/pdos_test`、PostgreSQL 16.14；角色与密码调整只发生在该独立集群，结束后已关闭并自动删除临时数据。未连接开发/生产数据库，未调用真实模型。测试使用合成 Provider 和资格，不构成真实模型评测通过。

新增测试覆盖在途重试与切换并发、切换后预算路径、未知用量与未结算账本阻塞、反向切换、取消不清理历史、trace 失败与事后幂等恢复、实际中断及恢复写入失败、登记失败零调用、并发 ContextVar 绑定、旧版本与无效角色拒绝、错误会话/trace/Agent/租户关闭拒绝、追加历史和迁移往返。实库安全测试覆盖伪造 run/tenant/project/lease、过期租约、跨租户会话、通用函数与表访问拒绝，以及受限 Gateway 登记—trace—关闭—draining 拒绝。

旧安全测试中 supplier_intelligence / executive_intelligence 仍预期普通路径成功，与已冻结 shadow 策略不符；现改为断言 CAPABILITY_SHADOW、零模型调用、零会话和零 Finding。其余 live 能力保留完整受限执行验收；没有修改运行策略来迎合测试。新增 Owner 夹具补齐 username，Schema 断言同步新增列；失败原因及修复没有扩大实现范围。

机器摘要与源文件摘要见[证据](evidence/2026-09-10-n0-03-model-call-fence.json)。

## 采用剩余与边界

1. 本片可以协调**已使用新 Gateway 的进程**。旧版本二进制、不经过 Gateway 的入口及此前未登记的在途请求无法被这三张表追溯发现。真实切换必须先具备部署覆盖和旧进程排空证据；不能仅凭空会话表声明全租户安全切换。
2. compatibility 不为 legacy 调用提供逐次 token 原子预留。真实模型输入计量/窗口/输出能力资格加载、业务入口固定 run/call_id、受限角色预算预留与结算端口，以及完整默认工厂装配继续完成。当前默认只接入会话保护。
3. open/unknown 不自动到期。已有匹配 trace 可以恢复关闭；没有 trace 的崩溃调用仍需受信来源核实与正式操作恢复入口。本片未提供凭空关闭、伪造零用量或清除审计的接口。
4. 安全模板新增函数依赖 0064，获批部署时须先迁移再应用幂等安全模板；只升级应用而未装安全函数将拒绝发出模型请求。部署及生产模式切换仍需逐次明确授权，本片未执行。
5. 活动预算租约、checkpoint/resume、对账来源核实与统一可见状态、工具预算/循环、持久 rollout/bundle 与当前来源 ACL 等继续归 N0-03。N0-06/N2-01、P/Q/Sprint 出口保持，没有 git push、生产切换或 golden 集修改。
