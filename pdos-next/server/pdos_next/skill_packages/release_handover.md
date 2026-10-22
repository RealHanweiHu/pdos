---
key: release_handover
version: 0.1.1-draft
purpose: 组装放行包并办理对外移交：按固定主体配置与放行范围收集定义、双配置、验证结果、试产、遗留与例外，为工程发布、制造放行、有限例外及其撤回准备具名决定材料，准备 ERP/MES 移交授权，并登记外部回执；四类决定与移交授权由各专业本人作出。
input_schema:
  type: object
  required: [instruction]
  properties:
    instruction: {type: string, description: "用户本轮要求，如“准备这批的放行包”“移交结果回来了”"}
    subject_config: {type: [object, "null"], description: "主体配置（工程与制造配置及版本）；组包必需"}
    release_scope: {type: [object, "null"], description: "适用数量/批次/产线/地区范围"}
    purpose: {type: [string, "null"], description: "用途（客户样品/认证/试产/量产等）"}
    package_ref: {type: [object, "null"], description: "已组装放行包的 id 与版本"}
    handoff_ref: {type: [object, "null"], description: "已授权移交的 id 与外部 ID"}
output_schema:
  type: object
  required: [bound_objects, prepared, scope_and_limits, unknowns]
  properties:
    bound_objects: {type: array, items: {object_type: string, id: string, revision: integer, basis: "page|trigger|user_message"}}
    prepared: {type: array, items: {operation: string, tier: string, payload_summary: string, sources: "Citation[]"}}
    scope_and_limits: {type: object, description: "subject_config、release_scope、purpose、limits、expiry 与依据摘要"}
    evidence_inventory: {type: array, items: {item: string, version: string, applicable: "yes|no|unknown|expired", basis: string}, description: "逐项证据与当前适用性"}
    residuals: {type: array, items: {item: string, kind: "residual|exception", basis: string, controls: string}}
    external_facts: {type: object, description: "发送成功、对方接收、实际生效分别记录；未知转对账"}
    unknowns: {type: array, items: {field: string, reason: string}}
    blocking: {type: array, items: {item: string, rule_or_evidence: string, responsible: string}}
context_schema: {$ref: "context-schemas.json#/profiles/project"}
context_requirements:
  - 项目、型号与品类范围（服务器绑定）
  - 页面给定的主体配置、放行包、移交记录的精确 id 与版本
  - 本次放行范围与用途（数量/批次/产线/地区）
  - 验证结果、试产记录与制造基线的版本引用
allowed_operations:
  - {tool: conversation.history, tier: READ}
  - {tool: evidence.search, tier: READ, note: "验证报告、认证证据、试产记录"}
  - {tool: product.baseline.read, tier: READ, note: "定义、BOM、认证、模具与平台引用"}
  - {tool: calc.spec_compare, tier: READ, kind: compute, note: "放行范围与证据覆盖的逐项比较"}
  - {tool: skill.load, tier: READ, note: "缺证据时加载 test_verification；范围变化加载 change_control"}
  - {tool: release.package.assemble, tier: T0, note: "按固定主体配置与范围组包；缺项如实留空"}
  - {tool: integration.receipt.record, tier: T0, note: "登记外部回执；结果未知转对账"}
  - {tool: release.engineering.approve, tier: T2-prepare-only, note: "只准备工程发布材料"}
  - {tool: release.manufacturing.approve, tier: T2-prepare-only, note: "只准备制造放行材料"}
  - {tool: release.exception.decide, tier: T2-prepare-only, note: "只准备有限例外材料，含检查项、限制与风险控制"}
  - {tool: release.exception.withdraw, tier: T2-prepare-only, note: "只准备例外撤回材料"}
  - {tool: integration.handoff.authorize, tier: T2-prepare-only, note: "只准备移交授权材料；外发由具名决定办理"}
evidence_policy: |
  放行包只收录有版本引用的真实证据；缺的项如实留空并列为缺口，不用相邻批次或其他项目的结果补位。
  每项证据的当前适用性（适用/不适用/未知/已过期）必须有依据；来源撤回或配置改变后重新判断。
  发送成功、对方接收、实际生效是三个事实，分别登记；结果未知先对账，不盲目重发。
  决定材料必须带 subject_config、release_scope、purpose、limits、证据摘要与有效期；范围之外的用途不写进本次决定。
failure_policy: |
  缺主体配置或范围：只提问该项，其余只读工作继续；不按"全部批次"默认放行范围。
  证据缺失或过期：组包仍可进行，但缺口与过期项显式列出，并指出需要谁补；不降低判定规则。
  外部接口超时或结果未知：登记为待对账并给出对账出口，不重复发送。
  缺专业决定：停在准备材料，列出缺工程还是制造、责任人与依据缺口。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 7
  tool_calls: 16
  tokens: 约 45k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#release_handover", case_types: [试产放行, 有限例外, ERP 移交回执], min_cases: 10}
owner: 待定
preload_when:
  - 项目工作区放行/移交入口打开且已选定主体配置或放行包
  - 试产结果齐备后准备放行
  - 用户问"能不能放行/移交出去了吗"
---

# release_handover · 放行包与对外移交

## 工具

1. 固定对象与范围：`subject_config`、`release_scope`、`purpose` 来自页面或用户消息。本技能没有放行包/移交记录的领域读取端口，缺 id 或版本就提问；**范围不明时不默认"全部"**。
2. 组包：`release.package.assemble`（T0）固定定义、双配置、验证结果、试产、遗留与例外、文件与限制；缺项留空并列缺口。
3. 决定材料：工程发布、制造放行、有限例外与例外撤回都只准备材料（T2-prepare-only），由各专业本人具名办理。
4. 移交：`integration.handoff.authorize` 只准备授权材料；授权后用 `integration.receipt.record`（T0）登记外部回执。
5. 缺证据加载 `test_verification`；范围或配置要改加载 `change_control`。

## 数据语义

- **四类决定各自办理**：工程发布回答"设计可用于什么"；制造放行回答"哪个场地/产线可以在什么范围制造"；客户承认回答"客户接受了哪个版本及条件"；市场/认证适用性回答"要求与证据适用于哪个交付范围"。**客户接受外观不意味着性能/法规/制造全部通过**。
- **每个决定保存**：subject_config、release_scope、purpose、limits、evidence_digest、policy_version、signers 与 expiry。原件改变形成新候选，**不覆盖历史签核**。
- **有限例外**是受控放行，不是判定通过：必须写明检查项、限制、风险控制与有效期；撤回例外后原包与原决定仍保留，相关读取依据转"待复核"。
- **ERP/MES 接收与实际生效是外部执行事实**，独立于内部决定。移交包括编号映射、BOM/工艺版本、文件 manifest、内容摘要、外部 ID、发送意图与接收/生效回执。
- **三个外部事实分开**：发送成功、对方接收、实际生效。结果未知先对账；接口超时不盲目重发；外部暂未连接时允许受控人工交接证据，**不伪装实时集成**。
- **证据适用性**：验证与试产证据只在其固定范围内适用；换产线、换工艺或配置改变后要重新判断。必需证据过期时不用其他项目的高分抵消。
- **签发人资格在签署当时固定**：之后被撤销只把相关对象标为"待复核"并拦截基于它的新受约束动作，不实时级联。
- **外发边界**：每次出站的服务商与数据类别由服务器按当前 Run 判定并记入运行回执。登记了当前有效协议的服务商按“服务商 × 数据类别”限制执行，类别超出许可即拦截；未登记、已停用或已过期的协议不阻断出站（确认稿 P26，2026-10-18）。协议是可选治理工具，不是出站前置。

## 使用原则

**适用**：放行包组装、四类决定的材料准备、有限例外与撤回材料、对外移交授权材料与回执登记。

**方法**：
1. **固定主体与范围**：确认工程与制造配置版本、适用数量/批次/产线/地区与用途。范围决定需要哪些证据。
2. **逐项清点证据**：每项写版本与当前适用性（适用/不适用/未知/已过期）及依据；缺口单列。
3. **组包**：按固定主体与范围组装；遗留项与例外分别列出，例外要带检查项、限制与风险控制。
4. **准备决定**：工程与制造分别准备，各自带依据摘要与有效期；不把两者合成一份。
5. **移交**：准备编号映射、版本、manifest、摘要、外部 ID 与发送意图；授权由具名决定办理。
6. **回执**：发送、接收、生效分别登记；未知转对账并给出对账出口。

**边界与禁止**：
- 不替专业作发布、放行、例外或移交授权；不以组包冒充放行。
- 不用相邻批次或其他项目的证据补缺口；不降低判定规则让流程通过。
- 不默认放行范围，不把一次放行扩展到未经决定的产线、地区或数量。
- 不重复发送结果未知的外部动作；不以"接口已调用"当作对方已接收或已生效。
- 不自行判断某服务商可否接收客户资料：出站许可由服务器按当前 Run 判定，本技能不得以“未签约”自设闸门而拒绝合法外发。

**失败时**：缺范围、缺证据或缺专业决定时，照实列出缺口与责任人，已核对的部分正常交付。

**输出要求**：
- reply 第一句给放行范围与结论（例如"已按该配置与试产批次组包，两项认证证据过期，制造放行材料待你确认"——示意）。
- 证据清点表逐项带版本与适用性；遗留/例外、外部事实、未知与阻塞各一列表。
