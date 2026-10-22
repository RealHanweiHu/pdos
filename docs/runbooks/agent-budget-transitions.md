# Agent 运行租约预算转换接口

N0-03 / DC-07。`0066_bound_budget_transition` 为已有、已绑定请求摘要的模型预算预留提供共同数据库状态机。Owner `BudgetLedger.transition` 和受限 `RestrictedBudgetTransitions` 复用此函数，避免两个入口的派发和结算语义分叉。

## 允许的操作与数据来源

服务端仍负责创建 lineage、冻结预算策略、绑定运行、核验模型计量并原子预留。Agent 窄接口只有 `attempt_id`、`action` 和可选回执三个参数；没有租户、运行、额度、策略、价格或模型资格参数。它不能创建新预留、修改预算上限或拓展作用域，也不是注册给模型调用的工具。

`RestrictedBudgetTransitions` 从当前 `RestrictedAgentRunStore` 绑定的 claim 取得租约。数据库安全包装函数再次检查当前运行、租约、租户、项目和 Agent 键。转换期间共享锁定运行行，防止运行在权限校验后先被终止或换租约。预算转换和 Owner 预留/派发继续使用同一租户事务锁。若派发等待了运行行锁，取得锁后重新读取数据库时间，再判断绝对截止时间，不能沿用等待前的有效时刻。

| action | 条件与结果 |
|---|---|
| `dispatch` | 仅 reserved 且尚未派发；运行仍 running、lineage 未超过绝对期限；成功者获得一次派发权 |
| `unknown` | 已派发但供应商用量未知；保留全部预留，不计成零、不因超时释放 |
| `cancel` | 仅派发前 reserved；释放预留，已派发或 unknown 不可取消 |
| `settle` | 已派发的 reserved/unknown，提供与原请求摘要绑定的回执；按实际输入加输出入账，包括超过原预留的真实用量 |

重复转换返回原结果，重复 dispatch 没有派发权；重复 settle 的证据须一致。运行结束或租约失效后 Agent 不能再转换预算，未完成项继续持有；受信 Owner 服务可根据真实供应商证据对账，不需要恢复旧租约。

## 回执与权限

Python 客户端将 `BudgetUsageEvidence` 规范序列化；数据库再次校验字段集合、请求摘要、严格非负整数、缓存为总输入的子项，以及请求 ID 等字段类型。回执正文限制 64 KB，正文摘要生成 `provider-usage.v1:sha256:` 留痕。费用未知继续保留 unknown；本接口不从 token 数虚构币值。

本函数确认回执结构及其与请求的绑定，不独立证明供应商回执的真实性。回执来自受信运行代码的供应商适配器，不接受模型生成的“实际用量”。Owner 对账仍须核对供应商来源。

权限脚本 `infra/postgres/security/agent-runtime.sql` 仅给 `pdos_agent` 授予安全包装函数 EXECUTE；通用转换函数不授予 PUBLIC/Agent/worker。Agent 对预算表仍无 SELECT/INSERT/UPDATE/DELETE，对业务表继续零写。没有新增凭据或宽表权限。

## 安装、回退与采用范围

先运行 Alembic，再按既有 DBA 流程幂等应用运行权限脚本。生产安装仍需用户逐次授权，本轮仅在独立本机 `pdos_test` 集群验证。

安全回退脚本删除包装函数并撤销运行权限。0066 的 Alembic downgrade 在已有绑定预算转换历史时拒绝回退，保留可对账证据；空历史往返可移除并恢复通用函数。downgrade 移除包装函数后，再次部署运行时须重新应用权限脚本。

0067已补齐受限预留和预算模式的租约调用登记，见[后续接入手册](agent-budget-reservations.md)。当前显式路径要求服务端已冻结运行预算及租户模型设置；默认工厂仍未启用。真实计量资格、自动预算冻结与稳定业务身份、版本采用及排空，以及活动时间租约、checkpoint和无trace恢复继续按N0-03推进。
