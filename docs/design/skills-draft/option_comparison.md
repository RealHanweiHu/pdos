---
key: option_comparison
version: 0.2.0-draft
purpose: 为立项提案起草 2–3 个在决策上真正不同的方案（可含"沿用现款"或"不做"），按同一组维度写定位、关键差异、大致成本与周期和取舍；成本由计算工具给出，选择留给人。
input_schema:
  type: object
  properties:
    proposal_id: {type: string, description: 服务器绑定}
    seed_options: {type: array, items: string, description: 用户已提出的方案思路（可空）}
    dimensions: {type: array, items: string, description: 用户指定的比较维度；为空用默认维度}
output_schema:
  type: object
  required: [options, comparison_dimensions]
  properties:
    options:
      type: array
      items:
        option_id: "A|B|C"
        kind: "new|status_quo|do_nothing（option 条目的 kind）"
        route: "new_development|derive_from_model|platform_reuse|null（kind=new 时必填，写入 summary）"
        name: string
        positioning: "{segment, price_band_ref, channel}（写入 summary）"
        key_spec_deltas: "{parameter_ref, value, unit, item_status, citation}[]（写入 summary 与 sources）"
        reuse: "string[]（型号/平台/模块，需有基线或平台记录引用，写入 sources）"
        rough_cost: "{low, high, currency, calc_refs, assumptions: string[], complete: bool} | null"
        cycle: "{low, high, unit, basis: Citation|record} | null（写缺什么）"
        risks: "string[]（另写 risk 条目）"
        tradeoffs: "string[]"
        unknowns: "string[]"
    comparison_dimensions: {type: array, items: string}
    fewer_than_two_reason: {type: [string, "null"], description: 方案少于 2 个时必填；作为 G0 提交 no_alternative_reason 的候选材料（只准备），不写条目}
    recommendation: {type: [object, "null"], description: "仅在用户要求时给：{option_id, conditions, reason}；不代表选定，不写 decision_note"}
context_requirements:
  - 提案：目标、关键 spec 条目（含 item_status）、commercial_target、已有 option 条目及是否人工值
  - 品类竞品与价格带结果（calc_ref）、用户工作与痛点
  - 可复用基线：型号已发布定义及其平台引用（product.baseline.read）、平台兼容范围与版本（platform.read）
  - 参数版本清单
allowed_operations:
  - {tool: proposal.read, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: category.competitors.list, tier: READ}
  - {tool: category.parameters.list, tier: READ}
  - {tool: product.baseline.read, tier: READ}
  - {tool: platform.read, tier: READ, note: 平台复用方案的兼容范围与版本}
  - {tool: evidence.search, tier: READ}
  - {tool: calc.cost_subtotal, tier: READ, kind: compute}
  - {tool: calc.spec_compare, tier: READ, kind: compute}
  - {tool: skill.load, tier: READ, note: price_band、competitor_comparison、opportunity_scoring、derivative_diff}
  - {tool: proposal.item.patch, tier: T0, note: 只写 option 与 risk 条目（op=upsert）；不改、不删人工方案}
evidence_policy: |
  每个方案的定位、复用和规格差异要有来源（提案条目、基线定义、竞品 calc_ref 或研究片段），写入 option 的 sources；没有来源的在 summary 中标"假设"。
  成本只引用 calc.cost_subtotal 结果；周期只引用有来源的范围（历史项目记录、供应商声明），否则 unknown。
failure_policy: |
  只能形成 1 个可行方案：写 fewer_than_two_reason（例如客户已指定方案），不凑数。
  成本输入缺项：calc 返回部分结果时照实标"不完整"，列出缺项；不由模型补价格。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 6（不含子技能）
  tool_calls: 16
  tokens: 约 50k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#option_comparison", case_types: [自主新品, 客户RFQ, 派生], min_cases: 10}
owner: 待定
preload_when:
  - 提案方案对比视图打开或该节为空
  - 用户要求"给几个方案/比较方案"
  - proposal_drafting 在自主新品入口起草定位方案
---

# option_comparison · 方案对比

## 工具

1. `proposal.read`、`proposal.items.read` 读目标、关键规格与已有方案；人工写的方案只读不改。
2. 依据不足时先加载子技能：价位 `price_band`，竞品差距 `competitor_comparison`，复用基线 `derivative_diff`，吸引力 `opportunity_scoring`。
3. `product.baseline.read` 核对"沿用现款"方案的基线；`platform.read` 核对"平台复用"方案的兼容范围与版本；`calc.spec_compare` 算方案间规格差异。
4. `calc.cost_subtotal` 对每个方案的成本假设求合计；假设逐项写来源。
5. `proposal.item.patch`（T0，op=upsert）写 option 条目（name、summary、rough_cost、cycle、tradeoffs、kind、sources）及对应 risk 条目；选择与 decision_note 由人在提案中完成。

## 数据语义

- **方案（option）**是提案"走哪条路"的回答，不是独立对象。v1.1 规则：至少 2 个方案，可包括"沿用现款"或"不做"；少于 2 个必须由负责人在 G0 提交时写理由（no_alternative_reason），否则不能提交。
- **方案类型**：条目 kind 只有 `new`（全新开发、从某型号派生、基于平台复用，路线写在 summary）、`status_quo`（沿用现款）、`do_nothing`（不做）。
- **平台复用**：只在 `platform.read` 给出的兼容范围内才算复用；目标规格超出范围或平台版本不明时，写入 risks 或 unknowns，不当作已可复用。
- **大致成本**：BOM/模具/认证/开发费用等按项列假设（数量、单价、币种、时点、来源），合计由计算工具给出；rough_cost 的 low/high 取自低/高两组假设的计算结果（只有一组时相同），不同币种不合并；缺项时为 NULL 或标"不完整"。
- **周期**：cycle{low, high, unit} 只写有依据的范围（例如同类历史项目记录、供应商交期声明）；没有依据为 NULL，并说明需要谁提供。
- **规格差异**：引用参数版本；方案间只比同口径值。
- **推荐 ≠ 选定**：选择是人的取舍，记录在 decision_note 中；G0 决定时选定方案是 T2。

## 使用原则

**适用**：自主新品的 2–3 个定位方向；客户需求的实现路线（新开 vs 基于现款改）；派生的改动幅度选择。

**方法**：
1. 先定比较维度，所有方案用同一组：目标细分与价位、关键规格差异、复用、成本、周期、主要风险、取舍、未知。用户指定维度优先。
2. 方案之间要在决策上真正不同（定位、路线或投入不同），不做只差颜色或名称的方案。
3. 每个方案写清"得到什么、放弃什么"。
4. "不做"或"沿用现款"方案写清后果，依据证据（例如竞品动向、客户要求），不夸大。
5. 用户要求时可给推荐，写成"在…条件下倾向 B，因为…"，并说明哪个未知会改变结论；不标记选定。

**边界与禁止**：
- 不由模型估算成本、周期、销量或回收期。
- 不把周期写成承诺日期；不编造供应商报价。
- 不覆盖人工方案；不删除用户提出的方案。
- 不替用户选择，不写 decision_note。

**失败时**：依据不够的方案保留但在 unknowns 里写清缺什么；子技能失败时在 reply 中说明哪一维是空的。

**输出要求**：
- reply 第一句说方案间最大的差别（≤60 字，例如"A 走高压快充高价位，B 沿用现款降本，差别在电机与电池"——示意）。
- 对比表：方案为列（≤3 列，另可加"沿用/不做"），维度为行（6–9 行），每格 ≤40 字。
- 表后取舍要点 ≤5 条；若有推荐，单独一段 ≤100 字并写明条件。
