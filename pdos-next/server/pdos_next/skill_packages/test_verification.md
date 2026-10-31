---
key: test_verification
version: 0.1.1-draft
purpose: 办理验证准备与试模后交接：形成验证请求与方法可用性、提出与承诺时段、逐项记录交样/接收/退回、计划并开始测试 Run、导入实测结果并交确定性工具判定，为专业复核与处置准备具名决定材料；接收、承诺与结论本身由各方本人作出。
input_schema:
  type: object
  required: [instruction]
  properties:
    instruction: {type: string, description: "用户本轮要求，如“这轮样件交品质”“把 A 项结果导进来”"}
    request_ref: {type: [object, "null"], description: "页面给定的 request_id 与 expected_request_revision"}
    run_ref: {type: [object, "null"], description: "run_id 与 expected_run_revision；计划阶段只需 run_id"}
    build_ref: {type: [object, "null"], description: "准备阶段必需的 build_id 与 expected_build_revision"}
    sample_refs: {type: array, items: string, description: "本次交样或测试的样件 id，逐件给出"}
output_schema:
  type: object
  required: [bound_objects, prepared, coverage, unknowns]
  properties:
    bound_objects: {type: array, items: {object_type: string, id: string, revision: integer, basis: "page|trigger|user_message|domain_read"}}
    prepared: {type: array, items: {operation: string, tier: string, payload_summary: string, sources: "Citation[]"}}
    handoff_events: {type: array, items: {event: "request_created|sample_ready|documents_complete|offered|accepted|promised_start|actual_start|preliminary_result|final_result|disposed", at: string, timezone: string, actor: string, basis: string}, description: "各事件分别记录，缺的留空不补"}
    coverage: {type: object, description: "本次覆盖的测试项/模穴/样件与未完成项"}
    time_facts: {type: object, description: "承诺、预计与实际分列；暂定时段标 tentative"}
    unknowns: {type: array, items: {field: string, reason: string}}
    blocking: {type: array, items: {item: string, rule_or_evidence: string, responsible: string}}
context_schema: {$ref: "context-schemas.json#/profiles/project"}
context_requirements:
  - 项目、型号与品类范围（服务器绑定）
  - 页面给定的 VerificationRequest、TestRun、Build 与样件的精确 id 与版本
  - 判据与测试方法来源（已发布定义、规格字典参数版本、客户或法规要求）
  - 设备、工装与人员资格的可用性依据（如页面已给出）
allowed_operations:
  - {tool: conversation.history, tier: READ}
  - {tool: build.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: build.lot.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: build.sample.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: test.run.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: evidence.search, tier: READ, note: "已登记的方法文件、校准记录、原始结果"}
  - {tool: evidence.extract, tier: READ, note: "从已登记原件定位读数位置"}
  - {tool: product.baseline.read, tier: READ, note: "判据、关键特性与认证要求"}
  - {tool: calc.spec_compare, tier: READ, kind: compute, note: "读数与判据比较"}
  - {tool: skill.load, tier: READ, note: "失败处置加载 quality_issue；需要新一轮实物加载 build_execution"}
  - {tool: verification.request.create, tier: T0, note: "按已固定的准备记录与其摘要建立请求"}
  - {tool: verification.schedule.propose, tier: T0, note: "提出暂定时段；暂定不是已接受"}
  - {tool: test.result.compute, tier: T0, note: "按固定依据摘要算判定，结论由代码给出"}
  - {tool: verification.preparation.record, tier: T1, note: "图纸/特征、判据、数量/模穴、材料、规程、设备、预期时点与返回形式"}
  - {tool: verification.method.prepare, tier: T1, note: "方法可用性评估（计划方法）"}
  - {tool: verification.actual_method.prepare, tier: T1, note: "实际方法评估；与计划方法分别保留"}
  - {tool: verification.handoff.offer, tier: T1, note: "生产/技术提出交样，带样件与覆盖范围"}
  - {tool: verification.handoff.accept, tier: T1, note: "品质本人接收；可部分接收，覆盖范围写明"}
  - {tool: verification.handoff.return, tier: T1, note: "退回缺项，须写原因与下一责任人"}
  - {tool: verification.schedule.promise, tier: T1, note: "对接收者的承诺窗口；与预测分开"}
  - {tool: test.run.plan, tier: T1, note: "固定覆盖范围与执行计划"}
  - {tool: test.run.start, tier: T1, note: "须带计划摘要与真实开始时点"}
  - {tool: test.results.import, tier: T1, note: "导入实测读数；部分结果写明未完成项与下一责任人"}
  - {tool: test.run.review, tier: T2-prepare-only, note: "只准备专业复核材料"}
  - {tool: test.disposition.decide, tier: T2-prepare-only, note: "只准备处置材料；处置由专业具名作出"}
evidence_policy: |
  实测读数只能来自真实记录（仪器报告、测量原件、页面录入）并带来源与定位；模型不填造读数，也不把摘要当读数。
  合格/不合格由 test.result.compute 按固定依据摘要给出；模型不自判、不改判据。
  计划方法与实际方法、暂定时段与已接受交样、承诺与预测、初步结果与最终结果，一律分别记录。
  原始执行时间不可被迟到的报告改写；原时区与日历引用保留。
failure_policy: |
  缺 run 精确版本先用 test.run.read 核对；缺请求当前版本只提问该项，其余只读工作继续；不猜测版本号。
  资料不齐：只阻断受其影响的验证项，其他并行准备继续，覆盖范围显式记录。
  部分结果：按测试项/模穴/样件写明覆盖与未完成项，不以部分结果充当最终结论。
  判定工具不可用：只给读数与判据清单，结论写"待计算"。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 8
  tool_calls: 20
  tokens: 约 50k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#test_verification", case_types: [试模后交接, 部分接收与退回, 分批结果导入], min_cases: 10}
owner: 待定
preload_when:
  - 项目工作区验证/测试入口打开且已选定请求或 Run
  - 样件就绪后发起交接
  - 用户问"交品质/什么时候出结果/这批测了哪些项"
---

# test_verification · 验证准备、交接与测试

## 工具

1. 固定对象：`request_ref`、`run_ref`、`build_ref`、`sample_refs` 来自页面、触发对象、用户消息或领域读取。用 `build.read`、`build.lot.read`、`build.sample.read`、`test.run.read` 读取当前项目精确 id 与 revision；测试 Run 选择参数为 `test_run_id`，返回 `id` 是测试对象，不是小Pai运行。请求读取仍须页面给出或核对 Run 的固定请求引用，固定请求版本不当作请求最新版。
2. 准备：`verification.preparation.record`（T1）固定图纸/特征、判据、数量与模穴、材料、规程、设备、预期时点与返回形式 → `verification.request.create`（T0）按该记录与摘要建立请求。
3. 方法与时段：`verification.method.prepare` / `verification.actual_method.prepare`（T1）分别评估计划与实际方法；`verification.schedule.propose`（T0）给暂定时段，`verification.schedule.promise`（T1）才是对接收者的承诺。
4. 交接：`verification.handoff.offer` → `accept`（可部分）→ 必要时 `return`（写原因与下一责任人）。
5. 测试：`test.run.plan` → `test.run.start` → `test.results.import` → `test.result.compute`（判定）；复核与处置只准备材料。
6. 失败后加载 `quality_issue`；需要新一轮实物加载 `build_execution`。

## 数据语义

- **十个交接事件分别记录**：request_created、sample_ready、documents_complete、offered、accepted、promised_start、actual_start、preliminary_result、final_result、disposed。AI 检查差异、整理交接包、提示阻塞与跟进，**不代替任何一个真实事件**。
- **暂定 ≠ 已接受**：品质可提前确认方法可用性与暂定时段；暂定预约不同于已接受实际交样，正式资源占用按资料/样件准备与约束政策确定。
- **四种时间**：Baseline（批准计划）、Forecast（按当前输入预计，可自动更新）、Commitment（对某接收者的承诺及范围）、Actual（真实事件与来源）分开版本化。**预测滑期不自动改变承诺**；无送达证据不能认定对方已开始承担响应时钟。
- **TestRun 固定实际测试对象、规程与条件**：样件与配置、规程、设备/校准引用、执行者、环境、实际起止、读数、附件、异常、确定性判定与专业结论。
- **测试中途关键变化**：按规程允许的分段记录，或中止并新建 Run；**不静默改变原 Run 代表的整体配置**。没有明确分段规则时选新 Run。
- **部分结果**：返回部分结果时明确测试项/模穴/样件覆盖与未完成项；品质可退回缺项或只接收部分明确样件，系统记录原因与下一责任人。
- **资源**：设备/工装实体是否存在与是否适合本轮验证是两件事；预约要校验设备、人员资格、工装与样件可用性。**破坏性测试消耗实际样件**。
- **成熟度与适用性**：产品验证成熟度、制造成熟度、交付适用性独立；必需证据过期或方法无效时不用其他高分抵消。

## 使用原则

**适用**：验证请求与准备、方法与时段、交样与接收/退回、测试计划与执行、结果导入与判定、复核与处置材料准备。

**方法**：
1. **固定范围与判据**：确认请求、Build、样件与本轮测试项；判据取已发布定义或参数版本，缺判据就标未知并提问。
2. **准备齐套**：逐项核对样件数量/模穴、材料、规程、设备与资料；资料不齐只阻断受影响项，其余继续并写明覆盖。
3. **方法与时段**：方法可用性由品质评估；先给暂定时段，正式承诺单独办理并写明接收者与范围。
4. **交接**：交样写明样件与覆盖；接收按本人办理，部分接收要列出未接收项；退回写缺项、原因与下一责任人。
5. **测试**：计划固定覆盖与执行安排；开始带真实时点；结果逐项导入并保留原值、单位与工况；判定交计算工具。
6. **收尾**：初步结果与最终结果分别写；未完成项与下一责任人显式列出；失败转 `quality_issue`。

**边界与禁止**：
- 不代替生产的实物就绪、资料 owner 的齐备、品质的接收与承诺。
- 不填造读数、不改判据、不自判合格，不把初步结果当最终结果。
- 不把不同规程、工况或设备的结果合并比较。
- 不用"测试任务还在列表"证明样件仍可用（破坏性消耗已不可用）。
- 不替专业作复核结论或处置决定。

**失败时**：缺版本或缺齐套时交回具体缺项与责任人；判定工具不可用时只给读数与判据清单。

**输出要求**：
- reply 第一句给交接或测试的当前位置（例如"已按该请求准备交样，两项资料缺失只影响 B 项"——示意）。
- 交接事件表按已发生的事件列出，未发生的留空；覆盖、时间事实、未知与阻塞各一列表。

读取边界：`build.read`、`build.lot.read`、`build.sample.read`、`quality.issue.read`、`test.run.read` 返回 `structural_metadata/v1`，只读记录身份、当前指针和固定关系；`basis_status=not_assessed`。不从记录状态、存在的样件身份或计划摘要推断已就绪、未消耗、依据仍有效、专业批准或可执行；来源与当前适用性由领域命令重新核对。私有元数据须已由服务器在受理本运行时绑定当前项目和内部资料类别，当前 RLS 逐次重验；旧运行缺绑定时发起新运行。无 id 时分页读取 `next_cursor`，多对象匹配时由用户明确目标，不取第一条代替选择。
