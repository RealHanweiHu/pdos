---
key: jtbd
version: 0.2.0-draft
purpose: 从用户声音、场景与研究证据中整理目标用户要完成的工作（JTBD）、完整使用路径与购买标准，区分有证据的发现和待验证假设。
input_schema:
  type: object
  properties:
    segment: {type: [string, "null"], description: 关注的细分；为空时按品类用户群逐个处理}
    sources: {type: array, items: string, description: 已有证据、用户声音归类、访谈记录的引用}
    scope: {enum: [category, proposal], description: 写回品类知识（kind=segment）还是提案 section}
output_schema:
  type: object
  required: [jobs, usage_path, buying_criteria, hypotheses]
  properties:
    jobs:
      type: array
      items: {statement: "当……时，我想……，以便……", segment: string, situation: string, dimension: "functional|emotional|social", status: "evidenced|hypothesis", citations: "Citation[]（evidenced 时必填）"}
    usage_path:
      type: array
      items: {step: string, current_solution: string, pain_refs: "cluster_id[] 或 Citation[]", parameter_refs: "{parameter_id, version}[]", status: "evidenced|hypothesis"}
    buying_criteria: {type: array, items: {criterion: string, nature: "claimed|inferred|unknown", citations: "Citation[]"}}
    switching_forces: {type: [object, "null"], description: "可选：推力/拉力/顾虑/习惯，各条带依据或标假设"}
    hypotheses: {type: array, items: {hypothesis: string, how_to_validate: string, would_falsify: string}}
context_requirements:
  - 品类：用户群、场景、地区、渠道
  - 用户声音归类结果（cluster 与代表引文）
  - 已有品类知识中的 JTBD 与购买标准（避免重复与漂移）
  - 参数版本清单（把使用路径步骤关联到参数）
allowed_operations:
  - {tool: category.read, tier: READ}
  - {tool: category.knowledge.list, tier: READ}
  - {tool: category.parameters.list, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: evidence.search, tier: READ}
  - {tool: research.fanout, tier: READ, kind: research, note: 论坛问答、评测中的使用场景描述}
  - {tool: skill.load, tier: READ, note: 用户声音未归类时先加载 review_pain_clustering}
  - {tool: category.knowledge.add, tier: T0, note: 仅品类上下文；kind=segment（细分、JTBD、购买标准、渠道、地区），ai_draft}
  - {tool: evidence.claim.record, tier: T0, note: 私有提案运行中（不能写品类知识时）新的公开观察（论坛问答、评测中的使用描述）登记为 Claim，记录随提案保持私有}
  - {tool: proposal.item.patch, tier: T0, note: 只写 section（key=target_customer_market_channel）与对应的 assumption 条目}
evidence_policy: |
  status=evidenced 的工作、路径步骤必须有用户原话或研究片段支撑；没有的标 hypothesis，并给验证方法。
  不编造用户原话、人群比例、人口统计或"典型用户画像"细节。
failure_policy: |
  证据不足以支撑任何工作：仍可列假设清单（全部 hypothesis）并给验证方法，reply 明说"均为待验证假设"。
  细分规模、渗透率等数值不在本技能处理，转 opportunity_scoring。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 5
  tool_calls: 10
  tokens: 约 40k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#jtbd", case_types: [自主新品, 品类建立后补用户与场景], min_cases: 10}
owner: 待定
preload_when:
  - 品类页"用户与场景"区域编辑或补全
  - 自主新品提案起草"目标客户/市场/渠道"段落
  - 用户问"用户为什么买/在什么场景用"
---

# jtbd · 用户要完成的工作

## 工具

1. `category.read`、`category.knowledge.list` 读用户群、场景、已有 JTBD 与购买标准。
2. 用户声音还没归类时，先 `skill.load("review_pain_clustering")`；已归类就直接用其 cluster 和引文。
3. 证据不够时用 `research.fanout` 读论坛问答、评测中的使用描述（按 public_research 原则）。
4. `category.parameters.list` 把路径步骤关联到参数版本。
5. 写回：品类范围 `category.knowledge.add`（T0，kind=segment，ai_draft）；私有提案运行中品类知识写不了，fanout 取得的新观察用 `evidence.claim.record`（T0）登记为 Claim（来源为快照与定位；用户原话 nature=extracted、不标厂商宣称；可读范围 = 提案受众，随提案保持私有，合同 §2.14），evidenced 的依据引用这些 Claim；提案范围写 section `target_customer_market_channel`（`proposal.item.patch`，T0，op=upsert）；待验证假设写成 assumption 条目（statement=假设，basis=依据或"无证据"，validation=验证方法与证伪条件，related_item_ids 指向该 section），不在正文里冒充发现。

## 数据语义

- **工作（Job）**：用户在某个情境下想取得的进展，与具体产品形态无关。写法"当……时，我想……，以便……"。例如（示例，auto-tire-inflator）"当长途出发前，我想确认四个轮胎气压正常且不弄脏手，以便安心上路"，而不是"我想要一个无线充气泵"；路径步骤"出发前补气"可关联本品类的 `fill_time_topup@1`、`pressure_accuracy@1`。
- **维度**：功能性（完成任务）、情感性（安心、省事）、社会性（在他人面前的形象）。
- **完整使用路径**：从意识到需要、准备、使用、收纳到维护的步骤；每步记当前解决办法与痛点。立项前改造方案要求自主新品按完整使用路径比较竞品，本技能提供路径骨架。
- **购买标准**：用户选购时比较的维度；来自评论、问答、零售页筛选项等，标性质。
- **证据与假设**：有用户原话或研究片段支撑的是 evidenced；其余是 hypothesis，必须带验证方法与证伪条件。原工程的"实验设计"方法并入此处的 hypotheses。

## 使用原则

**适用**：建立或补全品类"用户与场景"；自主新品提案的目标客户与场景段落；为方案对比提供"为谁、解决什么"的依据。

**方法**：
1. 按细分逐个处理；每个细分 2–4 个工作，总数 3–7 个。
2. 每个工作写清情境与期望进展，标维度与状态，附依据。
3. 画使用路径 5–8 步，把痛点（cluster 或引文）挂到对应步骤，并关联参数版本。
4. 列购买标准，区分用户自述（claimed）与推断。
5. 可选：转换动力（推力/拉力/顾虑/习惯），每条带依据或标假设。
6. 列待验证假设：怎么验证（访谈、问卷、小样测试、数据分析），什么结果会推翻它。

**边界与禁止**：
- 不编造用户原话、访谈或人群比例；不写虚构的人物画像（姓名、年龄、收入）。
- 不把假设写成发现；不把卖点文案当用户需求。
- 不估算细分规模（交 opportunity_scoring 与 calc.market_size）。
- 品类范围内只用公开或内部非客户资料；客户访谈或客户需求留在对应私有提案。

**失败时**：证据不足就交假设清单与验证计划，不硬凑 evidenced。

**输出要求**：
- reply 第一句给最核心的一个工作及其证据状态（≤60 字）。
- 工作列表 3–7 条，每条一句；路径表 5–8 行（步骤、当前办法、痛点、关联参数）。
- 购买标准 ≤8 条；假设 ≤5 条，每条带验证方法；全文表外说明 ≤200 字。
