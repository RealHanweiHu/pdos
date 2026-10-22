# N0-02 能力矩阵与工具载荷验证

日期2026-09-10；政策候选`1.0.0-draft.2`。N0-02部分完成，DC-06/07/08未冻结；N0-01合同及批准快照保持。

## 本轮交付

- [逐能力与工具政策](../../server/app/contracts/capability_matrix.py)：27项原能力逐项对应scope、触发、上下文字段、工具、读/候选出口、Finding类型、review/apply、预算/保留、过期/幂等、人工替代和领域归属。13个现有key独立保留实际声明及迁入差异；部分复用不等于已实现所有新语义。
- [模型可见工具载荷](../../server/app/contracts/tool_payloads.py)：14类输入、严格结果信封及领域结果形状，版本化范围句柄代替模型自报tenant/project/身份。定义/计划/测试/CAPA/变更候选不接受人工批准或实绩字段。
- [14个输入示例](../contracts/pdos-runtime-v1/tool-examples.json)：全部为合成例子，句柄不是有效授权。保留缺工期/责任/判据，不以占位人员或虚构日期冒充完整结果。
- DecisionBrief保留来源、共识、方案/收益/代价/异议、建议/未决和停止原因；只读直接展示，业务提案必须关联Finding。建议不是正式Decision或专业批准。
- 硬闸封闭表覆盖设计§2的14种逻辑动作（把Baseline/Commitment、Gate/DCP/TR分别展开）；原值导入与模型映射分轴，研究GET和只读POST不新增业务审批。

产物见[能力矩阵](../contracts/pdos-runtime-v1/capability-policy-matrix.json)、[字段OpenAPI](../contracts/pdos-runtime-v1/runtime-policy.openapi.json)及[源文件摘要](../contracts/pdos-runtime-v1/runtime-policy-manifest.json)。新能力与工具均disabled/planned、model qualification为空；它们是新版本候选，不改变旧13项运行注册或生产状态。

## 验证

环境为现有`server/.venv`，无数据库、网络、模型或外部操作，仅合同/静态定义读取。声明不自动证明运行代码和资格内容。

| 项 | 结果 |
|---|---|
| 本轮工具、Brief和矩阵测试 | 23 passed |
| 含上一片政策 | 55 passed |
| 加已冻结共同对象测试 | 132 passed |
| Ruff check/format、Mypy | 通过 |
| 导出与只读漂移 | 4政策产物一致；N0-01产物仍一致 |

从`server`执行：

```sh
.venv/bin/pytest -q tests/test_tool_payload_contracts.py tests/test_runtime_policy_contracts.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/ruff check app/contracts/tool_payloads.py app/contracts/capability_matrix.py tests/test_tool_payload_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/ruff format --check app/contracts/tool_payloads.py app/contracts/capability_matrix.py tests/test_tool_payload_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/mypy app/contracts/tool_payloads.py app/contracts/capability_matrix.py tests/test_tool_payload_contracts.py scripts/export_runtime_policy_contracts.py
.venv/bin/python -m scripts.export_runtime_policy_contracts
.venv/bin/python -m scripts.export_runtime_policy_contracts --check
.venv/bin/python -m scripts.export_common_contracts --check
```

正反例：逐工具合法示例与额外租户/项目/批准/主体字段拒绝；版本化句柄/事实引用；候选不能塞批准、实际测试结果或新建导入指令；计划孤儿/循环/无依据工期拒绝；搜索不可用与零命中分离、snippet不能直接引用；unknown费用不变0、不可计算情景不造日期；原始单元格空串、0、N/A、单位、前后空白及换行保真；Brief只读与业务Finding分流；27语义与设计附录实际集合一致；跨登记版本、scope和预算引用一致。

本轮修正原值预览的候选问题：公用Contract默认去首尾空白，RawCell必须覆盖为保留原始字符串，否则改变原件内容。该规则只适用于原始单元格；普通文本沿现有规范。公开URL禁止内嵌凭据，真正每跳DNS/IP/重定向安全仍由reach运行验收，不将URL校验称为SSRF防护完成。

## 剩余与下一步

矩阵里的新context/prompt/专业output/quality pin是规划标识，除已导出的工具/Brief字段外，其内容和真实模型资格须随N0-03公共适配及对应领域N项落实；不能凭pin字符串live。既有13项声明按真实代码对账，风险API旧confirm标签须接回现有Finding双动作；报告导入确认继续独立的确定性原值通道。

下一步将矩阵落实为采用清单：逐项注明已有/规划schema和context/prompt来源、真实人工action/Engine/权限映射、立即请求与事件合并/SLA的触发政策，汇总DC-06/07/08的具体批准包。缺真实费率、模型窗口/专业阈值保持具名待配置，不杜撰、不自动启用。N0-03才实际接通当前ACL、预算原子预留、handler循环与回执，领域能力随后验收。

未新增迁移、改golden、部署、push或外发，原P/Q出口不变。当前无外部权限阻塞，不把正常未完成工作伪称受阻。
