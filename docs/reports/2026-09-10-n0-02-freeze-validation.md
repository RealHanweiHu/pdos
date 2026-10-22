# N0-02 共同政策冻结候选验证

日期2026-09-10，候选`1.0.0-draft.3`。N0-01六项共同决定已批准；N0-02等待DC-06/07/08集中裁决。所有结果是本地合同与静态对账，无模型、网络、数据库或生产操作。

## 本轮收口

1. [采用/触发校验](../../server/app/contracts/runtime_adoption.py)：组件存在须有路径/digest，规划项不得伪装文件证据；live采用必须组件、capability资格、回归与批准齐全；用户/控制立即处理，里程碑不能先把180秒耗在合并/排队上，错误清理零模型。
2. [真实组件盘点生成器](../../server/scripts/runtime_adoption_inventory.py)：13能力逐项读取实际prompt并核对注册版本，AST验证context/model output/handler/权限/API符号和行号；不调用这些函数。27新语义明确标注规划组件与领域归属，不能把provider通用资格扩大为全新能力资格。
3. 全部69现有事件按当前route/no-route逐项对应milestone、frequent_edit、control或no_model_route及理由；未知有路由事件缺政策时导出失败。没有增改当前dispatcher路由。
4. 9个真实人工动作与Role/Action/API合同、3个真实Finding应用适配器、3个现有确定性组件及4组规划引擎已有来源定位。新专业候选不能套Risk载荷宣称应用完成。
5. [权限/采用合同](../contracts/pdos-runtime-v1/authorization-and-adoption.md)补七类scope、主体/委托交集、产品/专业工作项和Quality窄动作权限、时钟/预算、14硬闸、导入/Brief、旧新组件采用及回退；[三组冻结提案](../contracts/pdos-runtime-v1/n0-02-freeze-proposal.md)已具体可审阅。

## 验证结果

| 检查 | 结果 |
|---|---|
| 本轮采用/触发/实际来源校验测试 | 7 passed |
| 三片N0-02政策测试 | 62 passed |
| 含已冻结共同对象合同 | 139 passed |
| Ruff check/format、Mypy | 通过 |
| 独立政策导出与只读漂移 | 5产物一致 |
| N0-01冻结产物漂移 | 仍一致，批准快照未变 |

在`server`执行：

```sh
.venv/bin/pytest -q tests/test_runtime_adoption_contracts.py tests/test_tool_payload_contracts.py tests/test_runtime_policy_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/ruff check app/contracts/runtime_adoption.py scripts/runtime_adoption_inventory.py tests/test_runtime_adoption_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/mypy app/contracts/runtime_adoption.py scripts/runtime_adoption_inventory.py tests/test_runtime_adoption_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/python -m scripts.export_runtime_policy_contracts
.venv/bin/python -m scripts.export_runtime_policy_contracts --check
.venv/bin/python -m scripts.export_common_contracts --check
```

发现并保留的真实差异：FindingService当前仅直接成员，通用ProjectAccess支持代理；逐次Run/导入使用PRODUCT_ENGINEERING_EDIT使Quality缺窄权限；事件dispatcher全部15分钟且要求project_id；ProviderRateCard未知记0；真实应用只有Risk/Memory/TestPlan三载荷；通用资格未覆盖27新能力。均已在采用合同列为N0-03/N0-04或领域实现条件，本次没有偷偷修权限、启用能力或删历史。

测试及AST不能证明接口可用、当前ACL、数据库原子预留、部署状态、真实模型资格或员工收益。所有source-present记录标为静态证据；待领域实现的prompt/output/quality/engine不写虚假路径或模型样本。golden只读引用、未修改。

## 状态

N0-02共用政策与采用合同已具备冻结审阅材料；未收到明确裁决前仍为部分完成。审批后登记生效版本，N0-03才推进实际运行loop/handler/授权/预算/恢复；领域能力和真实用户效果按原所属N项取得，不反向等待全域才搭公共基础。

未新增迁移、push、部署、外发、清理或关闭P/Q/Sprint出口。批准N0-02不授权这些独立操作。当前需用户裁决的是已具体化的三项政策差异，其余已授权独立准备可继续。
