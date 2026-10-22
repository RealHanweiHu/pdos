# N0-02 政策合同第一片验证

日期2026-09-10，候选`1.0.0-draft.1`；前置共同合同`1.0.0`已冻结。N0-02仍部分完成；本次未冻结DC-06/07/08、未改实际Gateway/权限/模型注册或数据库。

## 交付和验证范围

- [政策字段及跨登记校验](../../server/app/contracts/runtime_policy.py)：范围/ACL、Capability/Tool/Engine/HumanAction分离、版本引用、预算profile/价目/账本、保留/出站/讨论。
- [32项正反例](../../server/tests/test_runtime_policy_contracts.py)：五个撤权边界不得省略、persona/代理不扩权、资格窗口不足拒绝、恢复/席位不重置额度、未知费用null、超时不释放预留、证据链保留、模型工具拒绝业务写、只读无审批及候选双动作、跨登记错版/错scope/人工入口混入拒绝、D25/D26已批准默认继承。
- [独立导出器](../../server/scripts/export_runtime_policy_contracts.py)：OpenAPI组件、三运行/三保留候选参数、来源/产物摘要。独立目录避免将未批政策合并进已冻结N0-01。

本轮使用现有`server/.venv`，纯内存合成对象，未连接数据库、未执行网络/模型调用、未读取凭据。Pydantic参数完整性和字段间一致性不证明当前ACL、真实人审、预算原子性或引用的handler/资格确实存在。尚未应用运行时的候选不以UI/整库迁移测试代替政策审阅。

| 检查 | 结果 |
|---|---|
| 本片政策测试 | 32 passed |
| 加三片共同对象回归 | 109 passed |
| Ruff check/format | 通过 |
| Mypy | 政策/测试/导出器通过 |
| 政策导出与只读`--check` | 3产物一致 |
| 冻结N0-01 `--check` | 不受本片新增模块影响 |

复现命令（`server`目录）：

```sh
.venv/bin/pytest -q tests/test_runtime_policy_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/ruff check app/contracts/runtime_policy.py tests/test_runtime_policy_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/ruff format --check app/contracts/runtime_policy.py tests/test_runtime_policy_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/mypy app/contracts/runtime_policy.py tests/test_runtime_policy_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/python -m scripts.export_runtime_policy_contracts
.venv/bin/python -m scripts.export_runtime_policy_contracts --check
.venv/bin/python -m scripts.export_common_contracts --check
```

初始mypy发现跨循环变量重复导致的类型收窄冲突，已改用独立名称，未改变校验语义。未扩成运行时授权修复；本片尚无真实业务行为变化。

## 剩余施工

继续按[候选入口](../contracts/pdos-runtime-v1/README.md)列出的逐能力矩阵、硬闸/Brief、工具schema/示例及DC-06/07/08收口；真实原子账本与handler循环归N0-03，专业功能随所属领域N项。没有新增用户权限阻塞，未申请不完整政策批准。

N0-01保持完成、N0-02部分完成；其他65项编号/依赖与P/Q出口保持。未push/部署/外发，未改golden集或生产配置。
