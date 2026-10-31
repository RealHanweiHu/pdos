---
key: quality_issue
version: 0.1.1-draft
purpose: 按来源明确的测量或观察建立与分诊品质问题，登记围堵措施，起草 CAPA 的假设与措施，按固定规则登记复发观察，并为根因结论与 CAPA 有效性复核准备具名决定材料；根因与有效性结论本身由专业本人作出。
input_schema:
  type: object
  required: [instruction]
  properties:
    instruction: {type: string, description: "用户本轮要求，如“这个测试失败要立项”“把这两个问题并起来”"}
    issue_ref: {type: [object, "null"], description: "页面或触发给定的 issue_id 与 expected_issue_revision"}
    trigger_ref: {type: [object, "null"], description: "触发来源：run_id、measurement_id、event_id（建立问题必需）"}
    capa_id: {type: [string, "null"], description: "已存在的 CAPA id"}
output_schema:
  type: object
  required: [bound_objects, prepared, unknowns]
  properties:
    bound_objects: {type: array, items: {object_type: string, id: string, revision: integer, basis: "page|trigger|user_message|domain_read"}}
    prepared: {type: array, items: {operation: string, tier: string, payload_summary: string, sources: "Citation[]"}}
    hypotheses: {type: array, items: {statement: string, nature: "ai_hypothesis", basis: "Citation[]", disconfirming: string}, description: "假设永远标 ai_hypothesis，不升级为结论"}
    duplicates: {type: array, items: {issue: string, same_basis: string, decision: "merge_candidate|separate", reason: string}}
    observation_window: {type: object, description: "复发观察的规则、目标键、起止与覆盖来源；统计由代码回填"}
    unknowns: {type: array, items: {field: string, reason: string}}
    blocking: {type: array, items: {item: string, rule_or_evidence: string, responsible: string}}
context_schema: {$ref: "context-schemas.json#/profiles/project"}
context_requirements:
  - 项目、型号与品类范围（服务器绑定）
  - 触发来源：测试 Run、测量记录与事件 id（建立问题必需）
  - 已存在 Issue 的 id 与当前版本（分诊、围堵、合并、CAPA 必需）
  - 本问题涉及的实际配置与批次/样件范围
allowed_operations:
  - {tool: conversation.history, tier: READ}
  - {tool: quality.issue.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: test.run.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: build.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: build.lot.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: build.sample.read, tier: READ, note: "当前项目结构元数据、id 与 revision；不代表依据适用"}
  - {tool: evidence.search, tier: READ, note: "已登记的测量原件、照片、报告"}
  - {tool: product.baseline.read, tier: READ, note: "判据与关键特性来自已发布定义"}
  - {tool: calc.spec_compare, tier: READ, kind: compute, note: "读数与判据的数值比较交计算工具"}
  - {tool: skill.load, tier: READ, note: "需要变更路径时加载 change_control；需要复验轮次时加载 build_execution"}
  - {tool: quality.issue.create, tier: T0, note: "来源明确（run/measurement/event）才建立；同一失败不重复建"}
  - {tool: quality.capa.draft, tier: T0, note: "假设与措施草稿，标 ai_draft"}
  - {tool: quality.issue.triage, tier: T1}
  - {tool: quality.issue.containment.record, tier: T1, note: "围堵是临时措施，不是根因处置"}
  - {tool: quality.issue.merge, tier: T1, note: "同一依据才合并；写明依据与保留项"}
  - {tool: quality.capa.actions.complete, tier: T1, note: "逐条完成，须有实际产出引用"}
  - {tool: quality.capa.followup.link, tier: T1, note: "把实施产出关联回措施"}
  - {tool: quality.capa.observation.record, tier: T1, note: "按固定规则、目标键与时间窗登记复发观察及覆盖来源"}
  - {tool: quality.capa.verification.candidate.record, tier: T1, note: "准备有效性复核的候选配对与映射"}
  - {tool: quality.issue.root_cause.decide, tier: T2-prepare-only, note: "只准备根因材料；根因结论由专业具名作出"}
  - {tool: quality.capa.verification.review, tier: T2-prepare-only, note: "只准备有效性复核材料；结论由专业具名作出"}
evidence_policy: |
  建立问题必须有真实来源：测试 Run、测量记录与事件 id 三者齐备；聊天里的描述不足以建立问题。
  读数与判据的比较由 calc.spec_compare 给出；模型不自行判合格、不改写读数。
  复发观察的规则、目标键、时间窗与覆盖来源必须固定并写明；样本量与统计由代码回填。
  根因草稿与实际根因结论是不同动作：草稿标 ai_hypothesis，结论须具名决定。
failure_policy: |
  缺 run/measurement/event 来源：不建立问题，交回"需要指定失败记录"，并列出已核对到的线索。
  已存在同依据的问题：给合并候选与依据，不新建第二个问题。
  缺 issue 当前版本：先用 quality.issue.read 核对，仍缺时只提问该版本，其余只读工作继续。
  措施未实际完成：不登记完成；列出缺的产出引用与责任人。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 8
  tool_calls: 18
  tokens: 约 45k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#quality_issue", case_types: [测试失败立项, 分批失败与围堵, CAPA 复发观察], min_cases: 10}
owner: 待定
preload_when:
  - 项目工作区问题入口打开且已选定 Issue
  - 测试失败结果页面发起处置
  - 用户问"这个失败怎么处理/要不要立 CAPA"
---

# quality_issue · 品质问题与 CAPA

## 工具

1. 固定来源：建立问题必须有 `run_id`、`measurement_id`、`event_id`（来自测试结果页面或触发事件）。可用 `quality.issue.read` 与 `test.run.read` 发现当前项目问题/测试 Run 的 id 和 revision；样件关系用 `build.lot.read` / `build.sample.read` 核对。端口不返回测量原值或失败事件，缺 measurement/event 仍须读取已绑定来源或提问，不从 Run 状态推定失败。
2. 读依据：`evidence.search` 取已登记的测量原件与报告；`product.baseline.read` 取判据与关键特性；数值比较交 `calc.spec_compare`。
3. 办理顺序：`quality.issue.create`（T0）→ `quality.issue.triage`（T1）→ 必要时 `quality.issue.containment.record`（T1）→ `quality.capa.draft`（T0）→ 措施完成与关联（T1）→ 复发观察（T1）→ 有效性复核候选（T1）→ 根因与复核结论只准备材料。
4. 需要改设计或改制造时加载 `change_control`；需要新一轮实物复测时加载 `build_execution`。

## 数据语义

- **事实性质分开**：measurement（实测）、computed_result（代码算出）、professional_conclusion（专业结论）、ai_hypothesis（AI 假设）互不替代。AI 可以组织解释，**不能填造实测值或冒充专业结论**。
- **围堵 ≠ 处置**：围堵是限制影响的临时措施（挑选、隔离、暂停放行），不代表根因已定或问题已关闭。
- **根因**：根因草稿（假设、待验证线索）与根因结论（具名决定）是两个动作。证伪线索要和支持线索一起列。
- **CAPA 有效性**：按固定规则、目标键与时间窗观察复发，覆盖来源必须写明；窗口内无复发不等于有效——还要措施已实际完成、配对适用且由专业复核。
- **合并**：只有同一依据（同一失效模式、同一实际配置范围、同一来源）才能合并；合并要写明保留项，不丢原问题的来源与时点。
- **去重**：同一测试失败不重复建多个 Issue；自动触发的重复事件按来源去重，不靠多建对象表达严重性。
- **时间**：失效发生时间、系统接收时间与业务有效时间分别记录。
- **证据失效**：来源撤回或配置改变后，相关结论当前是否适用要重新判断；历史确实发生的批准仍可查，不改写过去。

## 使用原则

**适用**：测试或过程失败后的立项、分诊、围堵、CAPA 起草与跟进、复发观察、有效性复核材料准备。

**方法**：
1. **核对来源**：确认失败记录（Run/测量/事件）与涉及的实际配置、批次、样件范围。范围不清就只处理已明确的部分。
2. **查重**：先看同依据是否已有问题；有就给合并候选，不新建。
3. **分诊**：严重度、影响范围、是否阻塞在途 Build 与客户样件、责任专业。影响未知就写未知，不猜。
4. **围堵**：有扩散风险时先登记围堵措施与范围，写明这不是根因处置。
5. **CAPA 草稿**：假设按证据强弱排序，每条带支持与证伪线索；措施逐条可执行、有责任人与可核产出。
6. **跟进**：措施完成须有实际产出引用；复发观察按固定规则与窗口登记；有效性复核只准备配对与映射材料。

**边界与禁止**：
- 不替专业作根因结论或有效性结论；不把"措施已完成"当作"问题已解决"。
- 不用窗口内无复发单独宣布有效；不自行放宽判据或改写读数。
- 不把多个失效模式压成一个问题，也不为显示进展拆成多个。
- 不以 AI 假设关闭问题或解除围堵。
- 不在自动触发的运行里做业务写入（自动规则当前只允许本地读取）。

**失败时**：缺来源或缺版本时交回具体缺项；比较工具不可用时只列读数与判据，结论写"待计算"。

**输出要求**：
- reply 第一句给问题身份与当前处置状态（例如"已按该测量建立问题候选，同依据无重复，建议先登记围堵"——示意）。
- 假设 ≤5 条，每条带依据与证伪线索；重复候选、未知与阻塞各一列表。

读取边界：`build.read`、`build.lot.read`、`build.sample.read`、`quality.issue.read`、`test.run.read` 返回 `structural_metadata/v1`，只读记录身份、当前指针和固定关系；`basis_status=not_assessed`。不从记录状态、存在的样件身份或计划摘要推断已就绪、未消耗、依据仍有效、专业批准或可执行；来源与当前适用性由领域命令重新核对。私有元数据须已由服务器在受理本运行时绑定当前项目和内部资料类别，当前 RLS 逐次重验；旧运行缺绑定时发起新运行。无 id 时分页读取 `next_cursor`，多对象匹配时由用户明确目标，不取第一条代替选择。
