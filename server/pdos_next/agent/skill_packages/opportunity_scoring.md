---
key: opportunity_scoring
version: 0.2.1-draft
purpose: 收集机会评分与市场规模所需的输入并逐项注明来源、区间和性质，调用计算工具得到结果，再解释驱动因素与不确定性；模型不自报任何规模或分数。
input_schema:
  type: object
  properties:
    question: {type: string, description: 例如"这个细分值不值得做""欧洲无线款市场有多大"}
    segment: {type: [string, "null"]}
    region: {type: [string, "null"]}
    option_ids: {type: array, items: string, description: 对多个方案分别评分时给出}
output_schema:
  type: object
  required: [inputs, results]
  properties:
    inputs:
      type: array
      items: {name: "以 calc 工具输入 schema 的字段名为准", value: "number|{low, high}|unknown", unit: string, as_of: date, region: string, nature: "measured|claimed|inferred|unknown", citation: "Citation|record|null", note: string}
    results: {type: array, items: {tool: "calc.market_size|calc.opportunity_score", calc_ref: string, scope: "细分/地区/方案", completeness: "complete|partial|blocked"}}
    drivers: {type: array, maxItems: 4, items: {statement: string, basis: "calc_ref + input name"}}
    uncertainties: {type: array, items: {input: string, why: string, how_to_reduce: string}}
  note: 结果数值只出现在计算工具回执中，由界面按 calc_ref 显示；模型文本引用时原样照抄，不改写或四舍五入
context_schema: {$ref: "context-schemas.json#/profiles/proposal"}
context_requirements:
  - 品类：细分、地区、渠道
  - 已有证据与品类知识中的市场数据（来源、日期、口径）
  - 价格带与竞品结果的 calc_ref
  - 计算工具的输入 schema 与版本（由服务器提供）
allowed_operations:
  - {tool: category.read, tier: READ}
  - {tool: category.knowledge.list, tier: READ}
  - {tool: category.competitors.list, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: evidence.search, tier: READ}
  - {tool: research.fanout, tier: READ, kind: research, note: 公开统计、行业报告摘要、渠道数据}
  - {tool: calc.market_size, tier: READ, kind: compute}
  - {tool: calc.opportunity_score, tier: READ, kind: compute}
  - {tool: skill.load, tier: READ}
  - {tool: proposal.item.patch, tier: T0, note: 只写 section（key=worth_it），数值以 calc_ref 引用}
evidence_policy: |
  每个输入要么有 Citation/记录引用，要么标 inferred 并写推断链，要么 unknown。来源之间不一致时用区间并列出各自来源。
  结果只来自计算工具；模型不给 TAM/SAM/SOM、份额、销量、评分或其近似值。
failure_policy: |
  关键输入未知：照样调用计算工具，让它返回 partial/blocked 并列出缺项；不补零、不填行业默认值。
  计算工具拒绝输入（单位或口径不符）：修正为同口径或标 unknown，不绕过。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 6
  tool_calls: 14
  tokens: 约 40k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#opportunity_scoring", case_types: [自主新品, 派生（新地区/新价位）], min_cases: 10}
owner: 待定
preload_when:
  - 提案"值不值得做"段落起草
  - 用户问市场规模、机会大小、评分
  - option_comparison 需要比较方案吸引力
---

# opportunity_scoring · 机会评分与市场规模

## 工具

1. 先读计算工具的输入 schema（服务器在上下文中给出），按字段清单收集输入。
2. `category.knowledge.list`、`evidence.search` 找已有数据；`category.competitors.list` 与价格带结果提供价格、竞品密度类输入。
3. 缺的公开输入用 `research.fanout` 找（公开统计、渠道数据）；找不到就 unknown。
4. 调用 `calc.market_size`、`calc.opportunity_score`。来源分歧大时用低/高两组输入各算一次，结果都列出。
5. `proposal.item.patch`（T0，op=upsert）把解释写进提案 section `worth_it` 的规模与评分部分（保留其他部分），数值以 calc_ref 引用。

## 数据语义

- **输入**：每个输入有值或区间、单位、时点、地区、性质和来源。常见输入（示例，以计算工具 schema 为准）：目标人群或保有量、年需求频次或替换周期、渗透率、价格、可触达渠道比例、竞争强度、痛点强度与满足度。
- **口径**：地区、年份、币种、单位必须一致；不同年份或地区的数据不直接拼接。
- **性质**：公开统计或报告原文是 claimed（发布方声称）；我方销售数据可以是 measured；由其他数推出的是 inferred，必须写推断链。
- **结果**：是计算视图，不是事实，不是决定。分数高不能抵消硬性风险（认证、专利、客户约束等），也不等于建议立项。
- **版本**：结果绑定计算工具版本与输入快照；不同版本或不同输入口径的分数不互相比较。

## 使用原则

**适用**：自主新品回答"值不值得做"；方案对比中的吸引力维度；派生到新地区或新价位。

**方法**：
1. 把用户问题对应到计算工具（规模、评分或两者）和范围（细分/地区/方案）。
2. 按输入 schema 逐项收集；每项写来源或标 inferred/unknown。
3. 来源冲突用区间；明显过时（建议超过 3 年）的数据标注时点，不默认采用。
4. 调用计算工具；结果不完整时照实标注。
5. 解释：≤4 条主要驱动因素（哪个输入影响最大，依据计算工具给出的分解或高低两组对比）；列出最大的不确定项及如何降低。

**边界与禁止**：
- 不输出模型自己估的规模、份额、销量、分数或"约 X 亿"。
- 不把缺失输入补零或填行业经验值。
- 不把评分写成"建议立项/不立项"；立项是 G0 的具名决定。
- 不在文本里改写计算结果（不换单位、不四舍五入、不换算币种）。

**失败时**：关键输入缺失时交出"输入清单 + 缺口 + 补数建议"，结果标 blocked；研究失败按 public_research 处理。

**输出要求**：
- reply 第一句：结果引用（calc_ref）+ 完整性 + 最大不确定项（≤60 字，例如"规模结果见计算 #ref，部分输入缺失；最大不确定是渗透率"——示意）。
- 输入表：名称、值/区间、单位、时点、性质、来源，每行一项。
- 驱动因素 ≤4 条、不确定项 ≤4 条，每条 ≤60 字。
