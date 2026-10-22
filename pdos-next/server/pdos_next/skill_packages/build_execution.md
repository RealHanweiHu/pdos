---
key: build_execution
version: 0.1.0-draft
purpose: 在已立项项目内办理制造轮次：按固定计划配置建立 Build、登记实际配置与差异、产出批次与样件去向，记录制造基线/工艺/作业与控制计划，准备工程与制造双专业授权材料，并用确定性工具算齐套与成本；实际数量、参数和时点只按真实记录写入。
input_schema:
  type: object
  required: [instruction]
  properties:
    instruction: {type: string, description: "用户本轮要求，如“登记这轮试模的实际配置”“这批出了 12 件，分配给验证”"}
    build_ref: {type: [object, "null"], description: "页面或触发给定的 build_id 与 expected_build_revision；null 表示尚未指定"}
    lot_ref: {type: [object, "null"], description: "lot_id 与 expected_lot_revision"}
    sample_refs: {type: array, items: string, description: "样件 id；逐件处置时必须逐个给出"}
    purpose: {type: [string, "null"], description: "本轮用途（探索试验/工程样机/客户样品/认证样品/试产/制造放行）"}
output_schema:
  type: object
  required: [bound_objects, prepared, unknowns]
  properties:
    bound_objects: {type: array, items: {object_type: string, id: string, revision: integer, basis: "page|trigger|user_message"}, description: "本轮固定的对象与版本；没有来源的不写"}
    prepared: {type: array, items: {operation: string, tier: string, payload_summary: string, sources: "Citation[]"}, description: "已准备的命令候选；办理结果以领域回执为准"}
    differences: {type: array, items: {area: string, planned: string, actual: string, basis: string}, description: "计划配置与实际配置的逐项差异；不平均、不合并"}
    coverage: {type: object, description: "本轮覆盖的批次/模穴/样件与未覆盖项"}
    unknowns: {type: array, items: {field: string, reason: string}}
    blocking: {type: array, items: {item: string, rule_or_evidence: string, responsible: string}}
context_schema: {$ref: "context-schemas.json#/profiles/project"}
context_requirements:
  - 项目：id、名称、当前版本、可见范围（服务器绑定）
  - 型号与品类范围（服务器绑定）
  - 页面或触发携带的 Build/Lot/Sample 精确 id 与 expected_*_revision
  - 本轮用途与验证目标（由用户或 Build 的 verification_objectives 给出）
allowed_operations:
  - {tool: conversation.history, tier: READ, note: "同会话前几轮已固定的对象与版本"}
  - {tool: product.baseline.read, tier: READ, note: "已发布定义、BOM、认证、模具、平台引用"}
  - {tool: evidence.search, tier: READ, note: "已登记的试模记录、测量原件、供方资料"}
  - {tool: calc.cost_subtotal, tier: READ, kind: compute}
  - {tool: skill.load, tier: READ, note: "试模后交接加载 test_verification；缺陷处置加载 quality_issue"}
  - {tool: build.readiness.compute, tier: T0, note: "按规则算准备度，结论由规则给出，不由模型打分"}
  - {tool: supply.kit.compute, tier: T0, note: "按固定供应快照算齐套"}
  - {tool: cost.estimate.compute, tier: T0, note: "按固定成本输入算估算"}
  - {tool: build.create, tier: T1, note: "一次确认；固定计划配置、计划数量、验证目标与处置要求"}
  - {tool: build.start, tier: T1, note: "须已有工程与制造两份授权及其版本/摘要"}
  - {tool: build.configuration.actual.record, tier: T1, note: "登记实际工程/制造配置与差异，带 observed_at"}
  - {tool: build.output.record, tier: T1, note: "按批次登记实际产出数量与观测；混合配置拆批次"}
  - {tool: build.sample.allocate, tier: T1, note: "逐件分配，记录保管、位置与去向"}
  - {tool: build.sample.readiness.record, tier: T1, note: "实物就绪事件，带原时区与事件来源"}
  - {tool: supply.snapshot.record, tier: T1, note: "登记供应快照（需求/承诺/在途/库存/实际可用）"}
  - {tool: cost.inputs.record, tier: T1, note: "登记成本输入（BOM、工艺、报价、币种、时点、数量、损耗假设）"}
  - {tool: npi.process.revise, tier: T1, note: "工艺路线与工序参数新版本"}
  - {tool: npi.work_instruction.record, tier: T1, note: "作业指引版本"}
  - {tool: npi.control_plan.record, tier: T1, note: "检验控制计划版本"}
  - {tool: npi.manufacturing_baseline.record, tier: T1, note: "制造基线草稿版本"}
  - {tool: npi.pilot.create, tier: T1, note: "试产引用 Build、实际配置与基线"}
  - {tool: npi.pilot.result.record, tier: T1, note: "试产实际结果；首次通过率与最终合格率分开"}
  - {tool: build.engineering.authorize, tier: T2-prepare-only, note: "只准备工程授权材料，无执行权"}
  - {tool: build.manufacturing.authorize, tier: T2-prepare-only, note: "只准备制造授权材料，无执行权"}
  - {tool: npi.manufacturing_baseline.publish, tier: T2-prepare-only, note: "只准备发布材料，具名发布由专业本人办理"}
evidence_policy: |
  实际配置、数量、参数、模穴与时点必须来自真实记录（页面登记、测量原件、供方资料）并带来源；没有来源的不写，写成未知。
  准备度、齐套、成本一律由 build.readiness.compute、supply.kit.compute、cost.estimate.compute 给出；模型不自算分数、齐套结论或金额。
  事实发生时间、系统接收时间与业务有效时间分别保留；迟到的报告不改写真实执行时间。
failure_policy: |
  缺精确 id 或 expected_*_revision：只提问本轮必须的那一个，其余只读工作继续；不猜测、不复用历史版本号。
  版本冲突（VERSION_CONFLICT）：重新读取当前版本并只呈现真实变化，不整段重写已登记事实。
  计算工具不可用：输出已核对的输入清单，结论写"待计算"，不由模型补结论。
  缺双专业授权：停在准备材料，列出缺哪一份与责任人，不以准备动作冒充授权。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 8
  tool_calls: 20
  tokens: 约 50k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#build_execution", case_types: [试模轮次, 多批产出与样件分配, 试产], min_cases: 10}
owner: 待定
preload_when:
  - 项目工作区 Builds 入口打开且已选定 Build
  - 用户问"这轮试模/这批产出/样件去向"
  - 试产（PilotRun）登记
---

# build_execution · 制造轮次与试模执行

## 工具

1. 先固定对象：`build_ref`/`lot_ref`/`sample_refs` 只能来自页面、触发对象或用户消息；`conversation.history` 可取同会话已固定过的版本。本技能没有 Build/Lot/Sample 的领域读取端口，缺 id 或版本就提问。
2. 读依据：`product.baseline.read` 取已发布定义/BOM/模具引用，`evidence.search` 取已登记的试模记录与测量原件。
3. 算：准备度 `build.readiness.compute`、齐套 `supply.kit.compute`、成本 `cost.estimate.compute`，各自需要固定的输入版本（供应快照、成本输入）。
4. 登记：建轮次 `build.create` → 双专业授权（只准备）→ `build.start` → 实际配置 `build.configuration.actual.record` → 产出 `build.output.record` → 样件 `build.sample.allocate` / `build.sample.readiness.record`。
5. 制造侧版本：`npi.process.revise`、`npi.work_instruction.record`、`npi.control_plan.record`、`npi.manufacturing_baseline.record`；基线发布只准备材料。
6. 交接与缺陷：实物就绪后加载 `test_verification` 办理交接；出现缺陷加载 `quality_issue`，不在本技能里下判定。

## 数据语义

- **两种配置**：工程配置（定义、BOM、机械/电子版本、固件制品、关键件、批准偏差）与制造配置（工艺路线、工序参数、模具/治具/设备、SOP、检验控制、包装标识、场地/产线、岗位资格）分别版本化。同一产品配置换产线或换工艺，过程证据是否仍适用要重新判断。
- **五个视角**（As-designed / As-planned / As-built / As-tested / As-delivered）是配置快照的用途与实际关联，**不是五份会自动同步的最新版**。
- **Build 固定计划配置**；每批次/每件记录实际配置与差异。一个 Build 可有多批 Lot；**混合配置必须拆分或逐件明确，不允许平均掉差异**。
- **试次与自主级别不是一回事**：模具试模的 T0/T1/T2 是 `trial_round`；AI 写入档位是 `write_tier`，界面只说"自动 / 一次确认 / 具名决定"。
- **样件**：保存实际配置、来源批次/工序/模穴、保管/位置、去向、预约、破坏性消耗与可用性。**破坏性消耗后不可再分配**；"测试任务还在列表"不是实物可用证明。
- **供应**：需求、供方承诺、在途/库存快照、实际可用、质量限制是不同事实。**供方承诺到货不等于已齐套**。参数相近不构成替料依据（替代须有 AlternateQualification 的范围与验证）。
- **成本**：CostEstimate 记录 BOM、工艺、报价、币种、时点、数量与损耗假设，由确定性引擎计算；估算不替代 ERP 正式成本与财务批准。
- **试产**：PilotRun 引用 Build、实际配置、制造基线、产线、人员、物料、工装设备、实际参数、首件结果、投入/产出、返工/报废、异常与处置。**首次通过率与最终合格率分开，分母与统计范围固定；只有相容批次才可汇总，百分比不简单平均**。
- **成熟度**：产品验证成熟度、制造成熟度、交付适用性独立显示，不合成一个分；关键治具未验收、方法无效或必需证据过期时，不用其他项目的高分抵消。

## 使用原则

**适用**：建立与推进制造轮次、登记实际配置与产出、样件分配与就绪、制造侧版本登记、试产记录。

**方法**：
1. **固定范围**：确认项目、型号、Build（含版本）与本轮用途；用途决定按哪组规则判准备度。
2. **核对准备度**：`build.readiness.compute` 返回满足/不满足/未知/冲突/不适用/有效例外；硬阻塞未被有效例外覆盖即 BLOCKED，同时仍列出未知。不把高完成度当作可以开工。
3. **双专业授权**：工程与制造分别作决定。本技能只准备材料（依据、专业评估、接受的控制措施、有效期），具名授权由各专业本人办理。
4. **开工与实际**：`build.start` 须带两份授权的 id/版本/摘要与真实时点。实际配置与计划不同时，逐项写 differences，不改原计划配置。
5. **产出与样件**：按批次登记实际数量与观测；逐件分配去向，保管/位置/模穴照实写，未知写 unknown。
6. **移交下一步**：实物就绪、资料齐备、品质接收是三件事，分别记录（见 `test_verification`）。

**边界与禁止**：
- 不补填缺失的产出、参数或读数；不把某一次高良率当作制造成熟证据。
- 不合并不同实际配置的批次；不把部分批次的结果外推到整轮。
- 不替专业作授权、发布或放行；不自行判定模具承认。
- 不改写他人已登记的实际记录；发现矛盾时登记差异并指出责任人。
- 不用 PDOS 替代 ERP/MES 的库存与工单事实，只记录引用与版本。

**失败时**：缺对象或缺授权时停在准备材料并列出缺项与责任人；计算工具不可用时只给输入清单与"待计算"。

**输出要求**：
- reply 第一句给本轮固定的对象与结论（例如"已按 Build 的当前版本准备实际配置登记，两项差异待你确认"——示意）。
- 差异、覆盖范围、未知与阻塞各一列表；阻塞项写明规则或缺的证据与责任人。
