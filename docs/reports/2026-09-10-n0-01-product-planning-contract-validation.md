# N0-01 产品与计划衔接合同验证

日期：2026-09-10，版本：`1.0.0-draft.2`。延续用户“按照新的设计开始执行”的目标，完成立项前对象、正式计划衔接、资源预约和首批逻辑操作的可执行合同。N0-01仍为部分完成；本文不是接口上线、数据库验收或正式冻结记录。

## 本轮交付

- [产品字段合同](../../server/app/contracts/product_records.py)：Line→Family→Platform→Series→Model→Variant、MarketSpace、ResearchTask、DesiredOutcome、Opportunity/Solution、VUVF Experiment、九区StrategyCanvas/ProductStrategy、SpecificationItem/ProductDefinition。
- [计划衔接合同](../../server/app/contracts/planning_records.py)：ProjectRoleAssignment、CaseProjectConversion、WorkItemTransfer、InitialPlanApplication、ProjectContractAdoption、ResourceIdentity/Reservation。兼容现有Task、七态Project和Role。
- [逻辑操作合同](../../server/app/contracts/object_operations.py)：8个命令，6种严格事件载荷、7套目标状态转换、9种命令错误；请求没有租户/人工操作者/已批准布尔值等授权自报字段。实际handler须由后续领域服务加载真实身份、范围、来源、版本与批准。
- [对象归属字典](../contracts/pdos-v1/object-ownership.json)：32个共同业务/运行对象的SoR、Owner、namespace、旧实现复用、键/FK/并发与兼容要求；内嵌值对象在组件schema表达。现有97表仍以静态盘点复用。
- [66个组件OpenAPI](../contracts/pdos-v1/common-objects.openapi.json)、[逻辑操作/事件与状态导出](../contracts/pdos-v1/logical-operations.json)及[来源manifest](../contracts/pdos-v1/manifest.json)。均有candidate标签，未登记生产API、事件或模型工具。

同时修正第一片一个实际表达缺口：将工程单位从标识符Key分离，保留`°C`、`%`、`m³/s`、`kg/m^3`原值，避免正确单位在schema校验时被拒绝；单位换算及同口径计算仍属于领域引擎。

## 验证

执行环境为现有`server/.venv`，测试只使用内存合成对象。未连接任何数据库、未读取试点原件、未调用模型或网络；无需以数据库schema迁移证明本片纯字段合同。

| 项 | 实际结果 |
|---|---|
| 新增产品/计划与边界测试 | 28 passed |
| 两片共同合同 | 58 passed |
| 加旧Context/RBAC/项目权限/导入映射兼容回归 | 101 passed |
| Ruff check/format | passed |
| Mypy | 9 source files passed |
| 导出与`--check` | 4 artifacts一致；临时副本注入版本漂移后被拒绝，目录内全部文件字节保持不变 |
| 产物与链接 | 66组件、32对象；3份说明文档21个本地链接有效，清单diff格式通过 |

实际测试命令：

```sh
.venv/bin/pytest -q tests/test_product_planning_contracts.py tests/test_common_object_contracts.py tests/test_agent_runtime_contract.py tests/test_project_access_policy.py tests/test_rbac_policy.py tests/test_test_report_mapping.py
.venv/bin/ruff check app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py
.venv/bin/mypy app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py
.venv/bin/python -m scripts.export_common_contracts
.venv/bin/python -m scripts.export_common_contracts --check
```

正反例证明范围：完整产品层级和跨租户/错误父级拒绝；合法无命中研究与无源断言区别；已批准假设仍为假设；选型前3个不同ID的候选；四维实验的方案/执行/结论分离；九区策略缺区拒绝、未完成草稿可保留；规格unknown可暂存但当前必需未确认不能发布；完成历史不能通过转项目重开；初始计划摘要匹配批准、转换映射不重复；active项目只做兼容记录不回退；资源情景不占容量、实际预约和释放保留回执；跳态事件、伪造身份参数拒绝；工程单位原值保真；七角色枚举与专业职责分开。

状态转换检查只验证允许边，引用字段校验只验证输入一致性。它们不证明真实授权、当前来源、并发容量、数据库不可变或实际发生过人审双动作。操作合同列出的所有policy_checks均须在相应真实handler验证，不得把本片的101项单元/兼容测试称为这些业务路径的端到端通过。

## 当前证据与剩余

本地基础Git HEAD仍为`8d2ec5c75b9296b86e552582cdc44e69e9bc7d68`；大量前序未提交修改继续保留。当前候选由manifest内实际文件摘要定位，不用HEAD声称全部变更已提交。

继续N0-01收口：发布后有效性/替代控制字段、其余共同操作及严格事件、字段到物理约束的最终对应与DC-01～05/09冻结记录；随后按N0-02统一逐能力授权/出口/预算/保留，再进入实际迁移与业务接线。该剩余未形成外部权限阻塞，不以正常工作尚未完成请求用户重复授权。

N0-01未勾选；未新建迁移，生产及P/Q出口不变。未启动前端/浏览器、未跑整库迁移或全部应用测试；这些不属于本次未接运行时的schema增量验证。主试点D14-04和历史回放D14-02业务结果没有改变。
