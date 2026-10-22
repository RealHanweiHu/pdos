# N0-03 新旧模型调用准入互斥验证

2026-09-10。继续 DC-07 原子预算接线，修复 compatibility 中已登记旧调用与显式预算路径的并发窗口。本片不把旧路径改称完整预算路径，N0-03 仍部分完成。

## 问题与修复

0064 已支持排空后切换，但 compatibility 允许新旧调用同时在途。旧调用的 usage 只有在返回并写入 trace 后才可见；新路径若在此前按账本和历史 trace 计算余额，就会遗漏这笔尚未返回的用量。反向也一样：新路径已有预留时，旧路径仍可能依据未结算的 trace 汇总发出请求。

0065 为数据库 open_model_call 加入双向互斥，使用同一租户事务锁：

- 存在 open/unknown 的 legacy 会话时，budgeted 会话返回 MODEL_CALL_LEGACY_IN_FLIGHT。
- 存在 open/unknown 的 budgeted 会话，或最新预算记录仍为 reserved/unknown 时，legacy 会话返回 MODEL_CALL_BUDGET_IN_FLIGHT。没有 Gateway 会话的直接预算预留也参与拦截。
- BudgetLedger.reserve 在其同一事务内检查未关闭的 legacy 会话；存在时返回 BUDGET_LEGACY_CALL_IN_FLIGHT，防止直接使用账本绕过会话入口。原预留的幂等重放仍保留；重放不产生新的派发权。
- 未关闭会话即使已有 trace 也继续阻塞，直到其完成状态落库；关闭后，旧用量按 0063 的对账规则参与预算计算。预算状态先取每个 attempt 的最新 revision，再检查未决状态，不能把已取消或已结算记录的历史预留重复算作在途。
- 不同租户互不阻塞。相同模式继续遵守自身已有规则：legacy 保留兼容行为，budgeted 继续使用账本并行数、调用数、token 和未知用量检查。本片没有声明 legacy 与 legacy 之间具备逐次原子预留。

新增查询函数使用固定 search_path、租户条件并撤销 PUBLIC 执行权限。Agent 继续通过既有 run 租约窄接口进入，不能调用查询其他租户状态的通用函数。没有新增表、schema、配置开关或员工操作入口；0064 安全包装函数通过原函数名继承新约束，不须扩大权限。0065 保留旧函数正文供空历史往返验证，有会话历史时拒绝撤去保护。

## 验证

| 检查 | 结果 |
|---|---|
| 新旧互斥、原会话、账本/对账、控制器、Gateway、Schema/迁移、工厂 | 129 passed |
| 独立 PostgreSQL 的真实 Agent/worker 权限及调用会话 | 17 passed |
| 共同合同、版本时间、运行政策/采用、工具载荷与日历 | 160 passed |
| 不重复合计 | **306 个不同测试通过** |
| 本片新增 | 14 个测试，其中 2 个穿过实际本机 HTTP socket |
| Ruff / 格式 | 10 个相关文件通过 |
| Mypy | budget_ledger、model_call_fence 通过 |
| 导出 | 共同合同四产物、运行政策五产物通过，获批原件未改 |

真实 HTTP 用例把第一个 provider 请求保持在途，再从另一 Gateway 发起另一计量模式的请求。验证两种方向都只有第一笔请求到达 Provider。旧请求返回 10 tokens 后，再申请 30 tokens、租户限额 35 时会被账本拒绝，没有第二次 HTTP；反向在新预算调用已结算后可以继续兼容调用。拒绝 trace 明确为 not_invoked，未生成会话或模型请求。

其他新增用例覆盖直接账本与 legacy 并发只有一个获准、两种会话并发只有一个获准、open/unknown 拦截、trace 已提交但尚未关闭、无会话的 reserved/unknown 预留、已取消/已结算最新状态放行、不同租户与相同模式独立、空历史迁移往返和有历史时降级保护。受限角色用例证明 Owner 账本预留会拦住真实 pdos_agent 的 legacy 准入，取消预留后恢复，且 Agent 无法直接调用状态查询函数。

常规数据库测试只连接 `127.0.0.1:57432/pdos_test`；角色测试使用本轮独立临时容器 `pdos-mixed-admission-test`，`127.0.0.1:57433/pdos_test`，PostgreSQL 16.14。两个测试库 head 均为 `0065_mixed_call_admission`。独立集群已关闭并自动清理，未修改开发集群角色密码。Provider、资格与用量均为合成测试数据，没有真实模型调用、生产操作或 golden 发布。

机器摘要见[证据](evidence/2026-09-10-n0-03-mixed-call-admission.json)。

## 尚未完成

- 互斥只覆盖已登记的 Gateway 会话和已有预算预留，不能发现旧版本二进制或绕开准入的请求。真实采用仍需部署覆盖、旧进程停止与在途排空证据。
- 完整预算默认装配仍待真实计量/窗口/输出能力资格、服务端稳定 run/call_id 和受限预算预留/结算接口。本片没有将 compatibility 自动切成 budgeted。
- 没有 trace 的崩溃恢复、受信来源对账、活动租约、checkpoint/resume、统一可见预算状态、工具循环/预算及持久权限和 rollout 继续按 N0-03 推进。
- N0-06/N2-01、P/Q/Sprint 状态保持。没有 git push、生产部署、真实外发或新增人工出口结论。
