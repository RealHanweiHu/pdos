# 事件 Agent 预算创建与独立工厂采用

2026-09-10，N0-03，迁移0070。新事件运行可以在创建事务内冻结已批准预算，独立Agent工厂可以装配受限预算控制器。当前默认仍legacy；本次未启用真实环境模式、发布真实计量资格或变更生产。

## 配置与接线

| 服务端变量 | dispatcher | executor |
|---|---|---|
| `PDOS_AGENT_MODEL_BUDGET_MODE` | 默认legacy；显式budgeted | 相同模式 |
| `PDOS_AGENT_MODEL_BUDGET_PROFILE` | budgeted须为short/work_package/research_discussion | 与创建端一致，执行时核对已冻结值 |
| `PDOS_AGENT_MODEL_METER_PATH` | 不读取、不传入容器 | 真实计量发布包在容器内的绝对路径 |
| `PDOS_AGENT_MODEL_METER_SHA256` | 不需要 | 独立可信配置的发布包SHA-256 |

应用侧`PDOS_APPLICATION_*`不能启用Agent预算。dispatcher无模型密钥、无计量客户端，也不加载计量资产；它只读取获批档位。executor缺配置或计量包失效时拒绝构造预算运行环境，不回退legacy。生产Compose模板已传递分离的配置，默认legacy；真实采用还需按部署授权提供只读计量包及配套tokenizer/模板挂载，不能仅填路径就认为文件已部署。

`run_dispatcher`将固定profile交给AgentDispatcher。每个租户派发事务都显式设置事务局部`pdos.event_budget_profile`，legacy也显式清空，避免连接池遗留配置。该参数是服务控制平面的选择，不是模型可调用的工具或用户请求字段。

数据库AFTER INSERT触发器只处理该参数已设置的新debouncing事件运行，使用迁移中固定的三份获批profile及对应摘要，创建不可变lineage/run link。绝对期限从数据库实际创建时刻计算；事件发生时间、去抖窗口及将来的claim时刻不能延长它。运行、预算和cursor在同一事务提交；任一步失败一起回滚。错误profile或主动Chat/映射形状不能借此创建事件预算。

重新派发、合并事件、seal入队或新进程切换档位均不改已有预算。旧未绑定运行不因重放或seal而自动分配新额度。未来关联run必须显式继承原lineage；本片没有新增关联run创建能力，也不能把关联任务视为新额度。

## 受限执行与切换

真实`configured_agent_runtime`使用`pdos_agent`和运行租约，经`RestrictedBudgetLedger`读取冻结profile，再用受信计量发布包计数、预留、唯一派发、未知持有和有据结算。Agent不能创建/更换lineage；worker和Agent都没有预算表INSERT权限，也无触发器函数的直接EXECUTE权限。触发器由数据库在合法新运行INSERT时执行，不开放额外写业务表的入口。

预算已绑定的运行即使被legacy执行器claim，`open_model_call`也返回`MODEL_CALL_BUDGET_REQUIRED`，零模型请求。该保护同时适用于已有应用侧绑定运行，防止改进程环境后绕开冻结预算。budgeted执行器遇到旧未绑定运行返回`BUDGET_RUN_UNBOUND`；遇到不一致profile返回`BUDGET_PROFILE_CONFLICT`或更早的计量资格拒绝，均不得新建额度或回退调用。

正式采用仍需真实计量资格、当前租户provider/model及每日限额、可信版本配置、旧进程排空与租户draining切换。已有运行的恢复/迁移必须沿后续恢复合同保留原期限和累计用量，不清库绕过；本片没有自动补旧账或重新派发失败运行的操作。合成测试发布包不可部署。

## 迁移和剩余

0070不新增表、列或数据库角色权限。数据库历史中已有budget run link时拒绝downgrade；禁止删除记录绕过。空历史迁移往返已验证。权限脚本重放保留迁移安装的触发器和共同准入函数；部署仍先执行迁移再启用对应进程。

事件运行创建时冻结及独立工厂装配已接通。后续四个应用主动入口的创建时冻结与测试计划续写共账已接通，见[创建与续写手册](application-run-budget-creation.md)。其他领域关联run实际采用、活动时间租约、checkpoint恢复、工具循环和真实计量仍按N0-03继续，不能以局部通过代替完整出口。
