# 受限 Agent 模型预算预留与显式运行接入

N0-03 / DC-07。0067 将原子预算预留和旧用量对账下沉为共同数据库函数；Owner `BudgetLedger` 和租约绑定的 `RestrictedBudgetLedger` 复用相同计算。它补齐0066的转换接口，但不自动启用默认工厂，也不发布模型计量资格。

## 接入前提

1. 服务端已经为真实 run 创建不可变 lineage 或绑定到授权的既有 lineage，冻结预算 profile 和绝对期限。Agent 不能创建/更换 lineage，也不能把关联 run 变成新额度。
2. 租户已有数据库模型设置，包含明确的 provider/model 和每日 token 上限。受限预留缺少此记录时返回 `BUDGET_TENANT_POLICY_REQUIRED`，不由请求或模型给出替代限额。
3. 服务端已核验当前模型的 golden 资格与输入计量发布包，显式装配 `ModelBudgetController`，同时提供稳定业务 run/model_call_id。测试中的合成资格不能用于真实服务。
4. 运行经 `RestrictedAgentRunStore` claim 并进入有效租约 scope；数据库使用 `pdos_agent`，没有 Owner 数据库凭据。

`RestrictedBudgetLedger.open_lineage` 为控制器保留同名接口，但只读取并核对既有 profile，不创建 lineage。缺失返回 `BUDGET_RUN_UNBOUND`；本地配置与冻结 profile 不一致返回 `BUDGET_PROFILE_CONFLICT`。

## 数据库接口和准入依据

| 接口 | 输入及职责 |
|---|---|
| `agent_budget_profile()` | 从有效租约派生 tenant/project/run/Agent，只返回该 run 的冻结预算 |
| `agent_reserve_model_budget(attempt_id, measured_input, binding)` | 按数据库冻结 profile、当前租户模型和每日限额决定是否预留，不接受 tenant/run/限额/策略参数 |
| `agent_open_budgeted_model_call()` | 要求已有预算绑定与租户设置，再进入既有 budgeted 调用会话及排空保护 |
| `agent_transition_model_budget(...)` | 复用0066的唯一派发、未知持有、派发前取消和有据结算 |

`ModelBudgetController` 使用结构化预算端口，可接 Owner 或受限实现。两端公共参数中的 `tenant_daily_token_limit` 在受限实现里不作为授权依据，也不发送给受限 SQL；数据库的当前租户设置决定每日额度。租户/运行参数则与租约作用域核对，不能把合法租约指向另一运行。

输入 token 数由受信运行代码的计量器计算，binding 来自固定的模型/计量配置和实际请求摘要，不是模型生成的政策事实。SQL 再次校验 binding 的字段、类型、结构化尝试编号、摘要及输出上限；受限路径还比对数据库的当前 provider/model。任意工具请求、未绑定模型预留或伪造配置不得混入此入口。

共同预留函数在租户事务锁内读取最新预算 revision，保证：

- 同 lineage 只允许一个未决调用；租户并行上限同时受已占用 lineage 的更严格 profile 约束。
- 模型/工具次数、单次 token、累计 lineage token 和租户每日 token 上限同时成立。
- 已登记 legacy 在途调用拦住预留；draining 拒绝新预留，已有预留的相同内容重放仍返回原记录，不获得新派发权。
- unknown 不因跨日清零；结算和取消后的旧 reserved revision 不重复计入余额。
- 取得运行与租户设置行锁之后再读取数据库时间，防止等锁期间过期或跨日后沿用旧时刻。

## 旧用量共同对账

`unbound_model_usage` 从数据库读取所有相关最新 journal/trace/人工对账记录；不接受 Agent 的汇总数字或由调用方删减过的 journal。Owner 的既有对账查询也复用此函数。

同一 run/call 的 trace 与预留/结算按实际绑定去重；已知超出未决预留的差额跨日继续占用额度，迟到的汇总 trace 不重复收取昨日已结算用量。未知且未绑定的旧用量必须先人工核实，不能以零代替。函数仅供受信服务和安全包装函数调用，Agent 不能直接读取其他运行的 journal、trace 汇总或未决 ID。

费用未知和货币限额未接通的保护保持；本接口不从 token 推造货币价格。活动时间租约、恢复策略和工具循环另按 N0-03 交付。

## 权限、验证与采用

Alembic 0067 先安装私有共同函数，再按现有 DBA 流程幂等应用 `infra/postgres/security/agent-runtime.sql`。权限脚本只向 `pdos_agent` 授予租约绑定包装接口；通用函数不授予 PUBLIC、Agent 或 worker，预算表和业务表权限不扩大。生产执行仍须逐次明确授权。

0067 不新增表或列。已有预算记录时拒绝 downgrade；空历史往返会删除新包装函数，恢复迁移后须重新应用权限脚本。不能只回退代码或权限脚本而假定活动调用已排空。

后续0070已将新事件run创建时冻结和独立Agent工厂接入，见[事件预算采用](event-budget-adoption.md)。已有五处StructuredGateway入口均有稳定调用身份，应用工厂也可显式装配；默认模式仍legacy。应用创建时冻结、关联run实际接线、真实计量资格发布、版本采用及旧进程排空继续。真实模型计量请求待明确授权；此前HTTP验证只连接本机模拟供应商。
