---
key: change_control
version: 0.1.1-draft
purpose: 办理同时穿透产品与制造的工程变更：按来源建立变更请求，用确定性工具算显式影响并与 AI 待核线索分栏，准备变更单与实施计划，登记实际实施事实，维护工程配置/BOM 与派生变体版本，并为逐项取舍与专业批准准备具名决定材料；取舍与批准由专业本人作出。
input_schema:
  type: object
  required: [instruction]
  properties:
    instruction: {type: string, description: "用户本轮要求，如“电机换型要走变更”“这条改动已经实施了”"}
    change_ref: {type: [object, "null"], description: "页面给定的 change_id 与 expected_change_revision"}
    roots: {type: array, items: string, description: "变更根对象（规格条目、零件、接口、工序等）；建立请求必需"}
    impact_snapshot: {type: [object, "null"], description: "算影响所依据的固定快照"}
    definition_ref: {type: [object, "null"], description: "父定义 id 与 expected_parent_revision（派生或变体改基线必需）"}
output_schema:
  type: object
  required: [bound_objects, prepared, explicit_impact, unknowns]
  properties:
    bound_objects: {type: array, items: {object_type: string, id: string, revision: integer, basis: "page|trigger|user_message"}}
    prepared: {type: array, items: {operation: string, tier: string, payload_summary: string, sources: "Citation[]"}}
    explicit_impact: {type: array, items: {path: string, object: string, version: string, basis: "declared_dependency|rule"}, description: "显式依赖与规则推导的影响，由计算工具给出"}
    ai_leads: {type: array, items: {statement: string, nature: "ai_hypothesis", why: string, to_verify: string}, description: "AI 待核线索，与显式影响分栏，不混入批准范围"}
    affected: {type: object, description: "证据适用性、在途 Build、客户样件、供应承诺、库存/在制品、产线切换与培训"}
    unknowns: {type: array, items: {field: string, reason: string}}
    blocking: {type: array, items: {item: string, rule_or_evidence: string, responsible: string}}
context_schema: {$ref: "context-schemas.json#/profiles/project"}
context_requirements:
  - 项目、型号与品类范围（服务器绑定）
  - 页面给定的 Change、定义与配置的精确 id 与版本
  - 变更根对象及其来源（问题、客户要求、供应变化、法规）
  - 受影响的在途轮次与外部承诺范围（如页面已给出）
allowed_operations:
  - {tool: conversation.history, tier: READ}
  - {tool: evidence.search, tier: READ, note: "变更依据：问题记录、客户要求、供方资料"}
  - {tool: product.baseline.read, tier: READ, note: "已发布定义、BOM、认证、模具、平台引用"}
  - {tool: platform.read, tier: READ, note: "平台兼容范围与版本"}
  - {tool: calc.spec_compare, tier: READ, kind: compute}
  - {tool: calc.derivation_diff, tier: READ, kind: compute, note: "基线与新版定义的逐项差异"}
  - {tool: calc.cost_subtotal, tier: READ, kind: compute}
  - {tool: skill.load, tier: READ, note: "复验轮次加载 build_execution；复验计划加载 test_verification"}
  - {tool: change.request.create, tier: T0, note: "来源明确才建立；根对象与来源必须写明"}
  - {tool: change.impact.compute, tier: T0, note: "按固定快照算显式影响；推测不进此结果"}
  - {tool: product.definition.draft, tier: T0, note: "定义草稿；人工值不覆盖"}
  - {tool: product.definition.item.patch, tier: T0, note: "条目级补丁；只改 AI 起草且无人工值的条目"}
  - {tool: change.order.prepare, tier: T1, note: "变更单与实施计划，带评估依据"}
  - {tool: change.effectivity.record, tier: T1, note: "仅明确批准的继任开发 Build 实际 Lot/样件采用；不代表库存或 ERP/MES 切换"}
  - {tool: change.verification.record, tier: T2-prepare-only, note: "只准备全部计划项与实际新 Run/样件/方法对应，交独立品质人员具名验证"}
  - {tool: change.close, tier: T2-prepare-only, note: "只准备分别关闭材料；由本次独立复核人重核采用与验证后具名关闭"}
  - {tool: change.implementation.record, tier: T1, note: "登记实际实施事实，关联具体条目"}
  - {tool: engineering.configuration.create, tier: T1, note: "按固定定义与 BOM 版本建立工程配置"}
  - {tool: engineering.bom.revise, tier: T1, note: "BOM 新版本，逐行带来源"}
  - {tool: product.variant.derive, tier: T1, note: "按父定义版本派生变体，写明适用性"}
  - {tool: product.variant.rebase, tier: T1, note: "变体改基线，逐项给出选择"}
  - {tool: change.selection.decide, tier: T2-prepare-only, note: "只准备逐项取舍材料"}
  - {tool: change.order.approve, tier: T2-prepare-only, note: "只准备专业批准材料；批准由专业具名作出"}
evidence_policy: |
  变更请求必须有来源（问题记录、客户要求、供应变化、法规条目）；聊天里的意向不足以建立变更。
  显式影响只能来自 change.impact.compute 与声明的依赖/规则；AI 推测单列为待核线索，不写进影响结果，也不进批准范围。
  定义与 BOM 的差异由 calc.derivation_diff / calc.spec_compare 给出；模型不自算差异、不改人工值。
  实施事实必须有实际产出引用（新版配置、图纸、工序、报告），不以"已安排"充当已实施。
failure_policy: |
  缺 change 当前版本或父定义版本：只提问该项，其余只读工作继续。
  影响范围算不全：照实列出已算出的显式影响与算不出的原因，不用推测补齐。
  受影响在途轮次或外部承诺不可读：列为未知并指出需要谁确认，不假设无影响。
  批准缺专业：停在准备材料，列出缺哪一个专业与责任人。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 8
  tool_calls: 20
  tokens: 约 50k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#change_control", case_types: [失败引发变更, 供应替代, 派生变体改基线], min_cases: 10}
owner: 待定
preload_when:
  - 项目工作区变更入口打开且已选定变更
  - 问题处置转入变更路径
  - 用户问"这个改动影响什么/要不要走变更"
---

# change_control · 工程变更穿透与实施

## 工具

1. 固定对象：`change_ref`、`definition_ref`、`roots` 来自页面、触发对象或用户消息。本技能没有 Change/配置的领域读取端口，缺 id 或版本就提问。
2. 建立与算影响：`change.request.create`（T0，来源明确）→ `change.impact.compute`（T0，按固定快照）；差异比较交 `calc.derivation_diff` 与 `calc.spec_compare`。
3. 取舍与批准：`change.selection.decide` 与 `change.order.approve` 只准备材料；`change.order.prepare`（T1）形成变更单与实施计划。
4. 版本落地：`engineering.bom.revise`、`engineering.configuration.create`（T1）；派生与基线 `product.variant.derive`、`product.variant.rebase`（T1）；定义草稿与条目补丁按 T0。
5. 实施与复验：`change.implementation.record`（T1）登记实际实施；复验轮次加载 `build_execution`，复验计划加载 `test_verification`。
6. 实际采用：`change.effectivity.record`（T1）消费实际 lot 与 sample_refs；仅在批准计划明确旧 Build 和有限继任开发 Build 条件时使用。新配置创建或新 Run 计算通过均不自动生效。
7. 独立验证与关闭：`change.verification.record`、`change.close` 均只准备 T2 材料。逐计划项映射固定新 Run、真实样件、测试项、方法及验证要求；服务器重读原值/执行人/来源，独立品质人员具名验证。通过后仍须分别关闭；不代替 Run 自身专业复核。

## 数据语义

- **两条路径同时存在**：产品路径 Spec→Part/BOM→EngineeringConfiguration→Build/Sample/Test；制造路径 Part/Interface→Operation→Tooling/Fixture→SOP/ControlPlan→PilotRun→ManufacturingRelease。两条都要走，不能只改设计就认为变更完成。
- **影响结果包含**：证据适用性、在途 Build、客户样件、供应承诺、库存/在制品处置、生产切换与培训。
- **显式与推测分栏**：显式依赖与规则推导归影响结果；AI 线索单列待核。**不把猜测变成已批准的变更范围**。
- **接口合同**：InterfaceContract 记录参与模块/专业、约束、单位、版本、负责人、确认状态、验证方式与受影响项；变更通过关系传播，不靠每次重新从文件猜。
- **证据适用性**：配置改变后原证据是否仍适用要重新判断；已发生的批准仍可查，不改写过去。签发人资格在签署当时固定，之后被撤销只把相关对象标为"待复核"。
- **替料**：参数相近不是替代依据；替代须有绑定可替代范围与验证的资格记录。
- **派生**：变体以父定义的已发布版本为基线，适用性与覆盖写明；改基线时逐项给出沿用或改写的选择，不整体覆盖。
- **成本**：影响金额由计算工具按固定输入给出，不替代正式成本与财务批准。

## 使用原则

**适用**：建立与推进工程变更、算影响、准备变更单与批准材料、登记实施、维护配置/BOM 与变体版本。

**方法**：
1. **定根与来源**：写明改什么（根对象）与为什么（来源引用）。来源不明不建立。
2. **算显式影响**：用固定快照调用影响工具；逐条给出路径与依据（声明依赖或规则）。
3. **列待核线索**：按专业经验给可能的传导（如电机替代可能影响电源保护、驱动参数、温升、结构定位、噪声、治具、测试规程），每条写明为什么与怎么核，**不并入影响结果**。
4. **准备取舍**：逐项给动作与状态候选、依据与有效期；取舍由专业具名决定。
5. **落版本**：BOM 与工程配置按固定上游版本新建，不改历史版本；变体派生/改基线写明适用性。
6. **实施与收尾**：实施事实逐条登记并关联产出；复验按新一轮实物与测试办理；在途对象的处置显式列出。

**边界与禁止**：
- 不替专业作取舍或批准；不以准备动作冒充批准。
- 不把推测写进影响范围；不因参数相近直接替料。
- 不覆盖人工值与历史版本；不静默改变在途 Build 的计划配置。
- 不跳过制造路径（工序、工装、SOP、控制计划、试产）只改设计。
- 不假设在途承诺与客户样件无影响；读不到就写未知并指出责任人。

**失败时**：影响算不全、在途对象不可读或缺专业批准时，照实列出缺口、原因与责任人，其余已算出的部分正常交付。

**输出要求**：
- reply 第一句给变更身份与当前位置（例如"已按该问题建立变更候选，显式影响 6 条，待核线索 3 条"——示意）。
- 显式影响与待核线索必须是两个列表；受影响对象、未知与阻塞各一列表。

生效与收尾限制：当前没有 Change/完成目录的 Agent 读取工具，缺精确 lot/样件/Run/当前变更版时请用户从实际页面选择，不从聊天补造。未明确批准的生效范围、部分采用、来源漂移或失败/未知不能关闭；原请求未知只按原命令/原键恢复，不能重发外部动作。
