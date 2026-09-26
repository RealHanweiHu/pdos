# N0-02 范围、工具与运行政策候选

版本`1.0.0-draft.3`，日期2026-09-10。前置[共同对象1.0.0](../pdos-v1/freeze-record.md)已获用户批准；本目录另存待收口的N0-02政策，不改写已冻结字段或批准快照，不启用任何运行配置。

## 已落地的合同

[runtime_policy.py](../../../server/app/contracts/runtime_policy.py)提供四类登记的可执行字段校验及共同政策：

| 合同 | 可验证约束 | 真实接线仍须完成 |
|---|---|---|
| ScopePolicy | 服务端run绑定主体，七类scope，职责不扩权；项目/租户及代理双方交集；五个ACL边界不可遗漏 | 用户/服务真实权限、引用存在及委托有效期、scope转换、每次撤权复核 |
| CapabilityPolicy | 只读无业务审批；模型候选必须Finding与独立review/apply；live声明须有实现/资格引用 | 当前13能力与27目标语义矩阵、资格/质量文件真实内容及场景效果 |
| ToolPolicy | 副作用仅read/simulate/record_observation/propose_finding；无隐藏模型调用；预算/保留/出站/超时/幂等引用 | 严格参数/结果schema实际内容、示例、handler代理、观察/取消与失败恢复 |
| EnginePolicy | 算法/输入快照/单位/日历/节点边数/时间上限；不模型调用、不写业务 | 具体领域算法、完整快照、日期/容量/成本计算及缺项行为 |
| HumanActionPolicy | 独立人工入口，apply必须已有review，不能标为模型可调用 | 操作者/当前来源/目标/批准/动作事实与事务回执 |
| PolicyCatalog | 精确版本引用，工具与人工动作key分离，scope覆盖、只读能力禁止Finding工具；live不能依赖未live工具 | 可信政策发布/加载、旧能力兼容、在调度/工具/披露/apply中一致强制 |
| RunBudgetProfile | 三profile字段、单次/lineage/活动/绝对期限、续租；恢复/重试/席位不重置；资格窗口计算 | 原子账本、token实际计数、模型资格窗口、跨worker并发和失联对账 |
| VersionedRateCard/BudgetEntry | 未知价目与费用null；已知价目具名来源/版本；响应未知保留全额token预留，结算有usage证据 | 实际费率、缓存/工具费策略、provider对账、状态迁移与防伪造/双结算 |
| RetentionPolicy | 临时7/90/365天；保护正文、Manifest、Observation、压缩索引、引用映射；清理初始关闭 | 引用分析、合法来源删除/失效映射、缓存撤权与真实删除预览/批准 |
| EgressPolicy/DebatePolicy | 已批准D25默认放行+blocklist/全席位GET/无首次域名审批；D26受权run内自主讨论/共享预算/无场景白名单 | 实际每跳解析、来源ACL/分类/用途、讨论handler和可见停止 |

[OpenAPI组件](runtime-policy.openapi.json)表达字段与枚举，`paths={}`；跨字段/跨登记约束必须执行Pydantic。`PolicyPin`只是待解析的版本引用，不证明所指schema、handler或资格真实存在。`ImplementationBinding`的字符串也不能作为授权或测试真值；发布门禁必须核对实际文件/资格/运行证据。

## 能力矩阵、工具与Brief

第二片见[能力矩阵](capability-policy-matrix.json)、[14个工具输入示例](tool-examples.json)和[验证记录](../../reports/2026-09-10-n0-02-capability-tool-validation.md)。27个目标语义逐项列scope/入口/上下文/工具/出口/预算/保留/过期/幂等和实施归属；13个旧key保留真实声明与迁入差异。新增14类工具输入和严格结果信封均可校验，范围句柄只能由服务端解析。

DecisionBrief区分只读建议与业务Finding，保留分歧/代价，不能自报批准。14项业务硬闸来自完整设计§2，不以HTTP方法或纯估算额外增加审批。原值导入独立办理，预览只读已有批次且保留每个原始字符；模型映射不等于原始数值。

矩阵中的目标context/prompt/专业output/quality版本仍明确是规划标识，不能凭字符串或候选disabled标记声明已有功能。新政策启用时，实际可用预算取能力/run/lineage/tenant及工具限制的交集，工具选择的profile不能扩大剩余额度。

## 具体候选参数

[参数文件](runtime-policy-defaults.json)直接按完整设计§18/20生成：short、work_package、research_discussion三组运行profile，以及minimal/standard/extended保留档。资格窗口、真实价目保持null，价目表空，金额硬限和purge均未启用；旧有效设置不被该文件覆盖。

输入限额按`min(profile输入上限, 资格窗口 − 输出预留 − 下一工具预留 − 安全余量)`计算，安全余量为`max(1024, ceil(资格窗口×5%))`；不足明确拒绝，不能猜模型窗口。此纯函数不计数实际token，也不等于预算预留事务。

预算账本结构允许结算实际消耗超过最初预估，避免丢失真实超额；此时执行层须记录超额并阻止继续。unknown记录保持预留，不能用重启或改状态释放；`cancelled_before_dispatch`只适用于服务可证明尚未发出的调用，字段为空本身不证明未发出。已确认免费的真实费率可以为0，但必须具名来源；未配置费率不能为0。

当前模型能力合同的zone仅free（只读）/hard_gate（候选）；旧confirm不是批量删除：风险API实际Finding回路归hard_gate；确定性原值导入是独立Engine/HumanAction业务路径，模型映射与原始数值分别溯源。该分类尚未改写现有注册或数据库。

## 真实组件与采用收口

第三片见[实际组件/权限/事件盘点](runtime-adoption-inventory.json)及[权限、触发与采用合同](authorization-and-adoption.md)。逐13旧能力核对真实prompt版本/符号/文件摘要，全部69事件已有候选策略；新能力待实现组件明确标记，不能借通用模型资格启用。9真实人工动作、3应用适配器及已有/规划引擎按职责复用。

N0-02共用政策与采用材料已收口为[DC-06/07/08冻结提案](n0-02-freeze-proposal.md)，待集中裁决。139项政策/共同对象测试通过，见[最新验证](../../reports/2026-09-10-n0-02-freeze-validation.md)。真实运行、数据库及领域闭环仍归N0-03/04和对应领域N项，不把静态来源存在当接线验收。

## 复现与剩余

从`server`执行：

```sh
.venv/bin/pytest -q tests/test_runtime_policy_contracts.py
.venv/bin/python -m scripts.export_runtime_policy_contracts
.venv/bin/python -m scripts.export_runtime_policy_contracts --check
```

验证见[第一片记录](../../reports/2026-09-10-n0-02-policy-contract-validation.md)，初始代码差异与27语义见[盘点](../../reports/2026-09-10-n0-02-runtime-policy-inventory.md)。[manifest](runtime-policy-manifest.json)绑定本片源码与产物；独立于N0-01 manifest。

N0-02保持部分完成。已补13现有能力和27目标语义矩阵、14工具输入/输出及示例、硬闸/Brief和导入分流。已有/规划组件来源及采用条件、HumanAction/Engine/权限映射和触发/SLA合同现已具体化；剩余为DC-06/07/08裁决及生效记录。N0-03才实际接线原子预算、运行循环与政策强制，领域工具随原N项验收。此前六项批准继续有效，不重问。
