---
key: price_band
version: 0.2.0-draft
purpose: 在统一价格口径（币种、日期、地区、渠道、零售或促销、含税运、配置）下整理竞品与我方价格点，用 calc.price_band 得到价格带分布与目标价位置；分组、分档、分位和换汇都交计算工具。
input_schema:
  type: object
  properties:
    caliber: {type: object, description: "币种、地区、渠道、日期窗口、零售/促销、含税运；未给时用显式假设"}
    competitor_refs: {type: array, items: string}
    target_price_item: {type: [string, "null"], description: 提案 commercial_target 条目 ID（取 target_price）}
    segment: {type: [string, "null"], description: 细分（来自品类用户与场景）}
output_schema:
  type: object
  required: [caliber_used, price_points, groups, target_position]
  properties:
    caliber_used: {type: object, description: 实际采用的口径；假设项标 assumption=true}
    price_points:
      type: array
      items: {brand: string, model: string, amount: number, currency: string, observed_at: date, region: string, channel: string, price_type: "list|retail|promo|unknown", tax_included: "bool|unknown", shipping_included: "bool|unknown", bundle: string, seller_type: "brand_store|marketplace_3p|retailer|unknown", citation: Citation}
    groups: {type: array, items: {caliber_key: string, point_ids: "string[]", calc_ref: "calc.price_band 结果 ID | 待计算", sample_note: string}, description: 分组与档位以 calc.price_band 返回为准}
    excluded: {type: array, items: {point: string, reason: string}}
    target_position: {type: object, description: "目标价所在档位（calc_ref）；目标价未定则 unknown"}
    observations: {type: array, maxItems: 5, items: {statement: string, basis: "calc_ref|Citation[]"}}
context_requirements:
  - 品类：地区、渠道、细分
  - 竞品库价格观察（含口径字段与日期）
  - 提案 commercial_target（target_price、cost 的 amount、currency、basis、as_of、来源）及是否人工值
  - 我方现款目标价与目标细分（型号）
allowed_operations:
  - {tool: category.read, tier: READ}
  - {tool: category.competitors.list, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: product.baseline.read, tier: READ}
  - {tool: evidence.search, tier: READ}
  - {tool: research.fanout, tier: READ, kind: research, note: 零售页价格，按地区/渠道拆子任务}
  - {tool: calc.price_band, tier: READ, kind: compute, note: 按口径分组、按显式档位或分位点统计、按传入汇率换算}
  - {tool: skill.load, tier: READ}
  - {tool: category.knowledge.add, tier: T0, note: 仅品类上下文；公开价格观察（kind=competitor 的 prices），ai_draft}
  - {tool: evidence.claim.record, tier: T0, note: 私有提案运行中（不能写品类知识时）新的价格观察登记为 Claim（来源为快照），记录随提案保持私有}
  - {tool: proposal.item.patch, tier: T0, note: 只写 section（key=worth_it）中的价格带结论；不改 commercial_target 人工值}
evidence_policy: |
  每个价格点必须有零售/官网页面的 Citation 与采集日期；搜索摘要里的价格不算。
  价格带边界、分位、均值、汇率换算一律来自 calc.price_band（含汇率日期与来源）；模型不报这些数。
failure_policy: |
  calc.price_band 不可用或拒绝：只输出按口径分组的价格点清单，档位写"待计算"，不由模型划档、算分位或换汇；样本量仍由代码回填。
  某地区/渠道价格取不到：照实列缺口，不用其他地区价格替代。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 6
  tool_calls: 16
  tokens: 约 40k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#price_band", case_types: [自主新品, 派生（换价位）], min_cases: 10}
owner: 待定
preload_when:
  - 自主新品提案起草或定位方案阶段
  - 用户问"价格带/定价/卖多少钱合适"
  - 提案定位图（价格 × 关键性能）视图打开
---

# price_band · 价格带

## 工具

1. `category.read` 取地区、渠道、细分；`proposal.items.read` 取目标售价（及状态）；`product.baseline.read` 取我方现款目标价。
2. `category.competitors.list`、`evidence.search` 取已有价格观察（`evidence.search` 只返回定位与已登记 Claim，不返回网页正文）；缺的地区/渠道用 `research.fanout` 读零售页补（按地区、渠道拆子任务）。
3. 先定口径，再把价格点（或竞品记录引用）连同口径字段、分档方式和带来源的汇率传给 `calc.price_band`，由它按口径分组、统计档位或分位并换算；样本量由代码回填。
4. 新价格观察在品类上下文用 `category.knowledge.add`（T0，kind=competitor 的 prices）；私有提案运行中品类知识写不了，改用 `evidence.claim.record`（T0）登记为 Claim（来源为快照与定位，nature=extracted，页面所列价格不标厂商宣称；可读范围 = 提案受众，随提案保持私有，合同 §2.14），价格带结论的 source_refs 引用这些 Claim。价格带结论写入提案 section `worth_it` 的价格带部分（`proposal.item.patch`，T0，op=upsert，保留其他部分）。
5. 需要"价格 × 性能"定位时加载 `competitor_comparison`，两者的口径各自独立。

## 数据语义

- **价格是带时间的观察**，不是型号属性：同一型号不同日期、地区、渠道、卖家的价格都是不同观察。
- **口径字段**：金额、币种、采集日期、地区、渠道、价格类型（标价/零售/促销/未知）、是否含税、是否含运费、套装配置（是否含配件或多件装）、卖家类型（品牌店/平台第三方/零售商）。缺的字段写 unknown。
- **同口径**：币种、地区、渠道、价格类型、含税运、配置都一致，日期在同一窗口内。不同口径分组，不硬比。
- **汇率**：跨币种比较只能由 `calc.price_band` 按传入的汇率换算；每个汇率要有来源和日期，价格日期与汇率日期分别保留。没有可核汇率就按币种分组，不换算。
- **分档方式**：默认传分位点（建议四分位）；用户指定或品类已有价格档定义时传显式档位并注明来源。不凭看到的价格点自拟档位边界。
- **目标价**：取提案 commercial_target.target_price；若是 AI 起草（未经人确认），定位结论写"目标（AI起草）"；其 basis（retail/promo）、币种、含税与所比口径不一致时不定位，写原因；没有目标价就不做定位，只给分布。
- **样本量**：每档的样本数由代码回填（verify 节点）；样本少（建议 <5）要标出。

## 使用原则

**适用**：自主新品定位、派生换价位、方案对比中的价位维度。

**方法**：
1. **定口径**：用户指定的优先；未指定时按品类主地区与主渠道、零售价、近 90 天（建议值）作为显式假设写入 `caliber_used`。
2. **收集**：每款至少一个同口径价格点；促销价单独记，不与零售价混组。
3. **清洗**：配件套装、多件装、翻新品、二手单独分组或排除，写原因。
4. **计算**：调用 `calc.price_band`；读取各组档位、分位与 calc_ref，样本量看代码回填结果。
5. **定位**：目标价落在哪一档（calc_ref）；同时说明该档主要竞品与关键性能差异（来自 competitor_comparison 的 calc_ref）。
6. **观察**（≤5 条）：例如某档样本稀疏、某品牌长期促销；每条带依据。

**边界与禁止**：
- 不混币种、不混零售与促销、不混含税与不含税。
- 不由模型划档、算均价、算中位数或换汇。
- 单一第三方卖家的价格不代表品牌定价，要标卖家类型。
- 搜索排名或"热卖"字样不是销量；不推断销量或市场份额。
- 不修改人工设定的目标价；有冲突写问题。

**失败时**：取不到的口径照实列为缺口；`calc.price_band` 不可用时只给按口径分组的清单，档位写"待计算"。

**输出要求**：
- reply 第一句给分布结论与口径（例如"欧盟主流电商零售价，近 90 天，主要集中在两档；目标价位于较高一档，样本 7 款"——示意）。
- 价格点表：品牌、型号、金额+币种、日期、渠道、类型、卖家类型，≤15 行；超出折叠。
- 排除项与缺口各一列表；观察 ≤5 条，每条 ≤60 字。
