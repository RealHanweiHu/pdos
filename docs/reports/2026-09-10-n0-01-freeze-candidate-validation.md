# N0-01 共同合同冻结候选验证

日期：2026-09-10；合同版本：`1.0.0-draft.3`；N0-01状态：部分完成，等待共同差异裁决。延续用户“按照新的设计开始执行”，本轮完成版本有效性、四时间操作和物理映射候选；未把测试通过当人工冻结或业务上线。

## 已交付

- [版本生命周期合同](../../server/app/contracts/version_lifecycle.py)：独立有效性控制修订、替代/撤回/失效，固定运行release bundle，旧Context v2只读兼容。
- [时间与查询合同](../../server/app/contracts/time_operations.py)：基线应用、预测重算、承诺确认、实绩记录/更正、供给捕获、有效性变更；计划验证/情景计算的输入及结果。预测日期由后续确定性引擎生成，缺输入不能用假日期掩盖。
- [物理字段与兼容映射](../contracts/pdos-v1/physical-contract-map.md)：对应对象模型、拟用列、tenant/project复合FK、版本/并发与历史迁入约束；不是DDL或数据库验证。
- [六项冻结提案](../contracts/pdos-v1/n0-freeze-proposal.md)：DC-01～05及DC-09共同部分；未填写批准人/时间，不越过显式差异裁决。
- [当前候选入口](../contracts/pdos-v1/README.md)：累计31条合同追溯、88个OpenAPI组件、35个对象归属、15个共同变更命令、12种事件payload、2查询、7套目标状态机。候选没有注册运行API、工具或Event生产者/消费者。

## 本轮修正的实际兼容问题

当前[事件写入器](../../server/app/events/writer.py)的`WrittenEventAudit`返回`event_row_id/audit_row_id: int`，metadata对应BIGINT；外部`event_id`是字符串。第一/二片候选曾把回执ID当UUID，与真实实现不符。

已将OperationReceipt、CommandResult、CaseProjectConversion的回执字段与因果事件字段统一为正整数行号。SourceRef仅kind=event接受整数，业务对象仍UUID；布尔值拒绝。用真实WrittenEventAudit类型构造结果完成回归。旧外部事件引用需按tenant/project/source受权解析后转换，歧义不得任选；本片只规定后续适配要求，没有更改当前业务引用或数据库。

## 验证结果

环境：仓库现有`server/.venv`；纯内存合成数据。未连接开发、测试或生产库，未调用网络/模型，未读试点原件。静态盘点仍为97表、11namespace、69事件、215 API操作，含0000共59迁移，单一head=`0058_ai_test_plan_changes`；只代表本地工作树。

| 验证项 | 结果 |
|---|---|
| 第三片版本/时间/事件兼容/缺失输入测试 | 19 passed |
| 三片候选合同测试合计 | 77 passed |
| 加现有Context、项目权限、RBAC、报告映射回归 | 120 passed |
| Ruff check / format --check | 12 files通过 |
| Mypy | 12 source files通过 |
| 导出及只读漂移检查 | 4个产物一致 |

从`server`执行：

```sh
.venv/bin/pytest -q tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py tests/test_agent_runtime_contract.py tests/test_project_access_policy.py tests/test_rbac_policy.py tests/test_test_report_mapping.py
.venv/bin/ruff check app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/ruff format --check app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/mypy app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/python -m scripts.export_common_contracts
.venv/bin/python -m scripts.export_common_contracts --check
```

本轮正反例验证：独立控制修订不改原模型；替代不得跨租户/项目/种类或倒退版本；固定bundle必需组件齐全且不重复；旧v2适配拒绝伪造可执行授权；重算请求拒绝自报日期或批准；承诺需要明确结束时点与唯一节点；实绩更正必须指向原实绩版本并有新证据；控制事件形状与替代状态一致；事件/audit标识兼容现有写入器；无法计算情景保留缺项而非生成日期。

这些只证明结构和跨字段一致性。真正同逻辑对象、当前来源有效性、已授权审批、同事务写入、原子容量、lineage预算、旧事件解析及数据不可变仍须在所属领域handler/迁移/受限账号测试验证。候选的`policy_checks`是待实施的要求，不是执行了对应政策的证据。

## 当前状态及后续

第一、二片报告保留各自历史计数，以本报告及当前manifest为最新候选依据。本地基础HEAD=`8d2ec5c75b9296b86e552582cdc44e69e9bc7d68`；前序未提交修改保留，候选用[manifest](../contracts/pdos-v1/manifest.json)文件摘要定位。未commit/push，未新建迁移、启动前端、部署或改变生产delivery及P/Q出口。

N0-01保持`[~]`：共同技术选择已具体可评审，剩余为清单指定的实质差异裁决及生效版本记录。N0-02可先盘点已有能力/权限/参数，依赖差异的变更在裁决后开始。批准本合同不自动批准真实外发、golden发布、生产或Sprint/Phase出口；完整业务验收仍按原65项工作与依赖推进。
