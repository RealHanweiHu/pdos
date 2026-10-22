# 旧 SourceWork 执行路径归档

S0 / B7–B8 已将执行入口统一至小Pai。这里保存停用前的源码和合同测试，文件后缀为 `.py.txt`，不参与导入或 pytest 收集。

| 原路径 | 当前覆盖 |
|---|---|
| `pdos_next/runtime.py`、`agent_execution.py`、`test_agent_framework.py` | `pdos_next/agent_kernel/`、`workflows/xiaopai.py` 及 `tests/agent_kernel/` 的注册图、Temporal Activity、资格、撤权、取消与来源验证 |
| `test_checkpoint_recovery.py` 中的旧 WorkRequest 恢复案例 | `tests/agent_kernel/test_checkpoint.py` 与 Activity/持久运行恢复检查；当前同名测试保留独立状态库目标和标记守卫 |
| `test_trusted_source_work.py` 中的旧执行、资格和工具版本案例 | 小Pai注册调用与资格检查；当前同名测试保留原件、人工 Claim、回执、T1 撤回、RLS、幂等及 schema 比较 |
| `model_gateway/claim.py` 与 `providers/test_claim_gateway.py` | `providers/agent_client.py` 与 `tests/agent_kernel/` 的受控注册图调用；通用协议/错误/来源及成本检查保留 |
| `persistent_budget.py` 的旧 `DatabaseBudgetPort` 及其事务测试 | 小Pai成本预留/结算与网关事务检查；共同命令仍保留未知调用的人工 T1 记账及其原子性测试 |

WorkRequest/Run/Invocation/BudgetReservation 的技术记账表仍用于人工成本处理，不再创建或执行旧 SourceWork。档案中的旧顶层错误码、过期窗及执行接口不属于现行 v1.1 合同。
