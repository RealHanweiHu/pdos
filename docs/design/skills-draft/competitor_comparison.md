---
key: competitor_comparison
version: 0.2.0-draft
purpose: 按规格字典参数版本做竞品与我方现款/目标的同口径对比，区分实测、宣传、推断、未知，口径不同就分组标注，数值比较交给 calc.spec_compare。
input_schema:
  type: object
  properties:
    competitor_refs: {type: array, items: string, description: 竞品记录 ID；为空时用品类竞品库}
    parameter_refs: {type: array, items: {parameter_id: string, version: integer}, description: 为空时取提案关键规格或字典中方向明确的参数}
    ours: {type: [object, "null"], description: 我方现款（型号+定义版本）或提案目标（提案 spec 条目）}
    region: {type: [string, "null"]}
output_schema:
  type: object
  required: [groups, not_comparable, observations]
  properties:
    groups:
      type: array
      items:
        caliber: "{parameter_ref, unit, condition}"
        rows: "{brand, model, value, nature: measured|claimed|inferred|unknown, citation, observed_at, region}[]"
        calc_ref: "calc.spec_compare 结果 ID"
        sample_note: "可比样本数（代码回填）与'样本少'标记"
    not_comparable: {type: array, items: {brand_model: string, parameter_ref: string, reason: "单位/工况/版本/配置不同或未知"}}
    unknown_summary: {type: array, items: {parameter_ref: string, reason: string}, description: 条数由代码计算}
    observations: {type: array, maxItems: 6, items: {statement: string, nature: string, basis: "calc_ref 或 Citation[]"}}
    research_gaps: {type: array, items: string}
    parameter_drafts: {type: array, items: {key: string, name: string, value_type: string, unit: string, direction: "higher|lower|target|neutral", standard_condition: "string|null", method: "string|null", acceptance_criterion: "string|null", change_note: string, basis: "Citation[]（多款竞品的标注，建议 ≥2）"}, description: 字典缺参数时的通用新参数草稿（category.parameter.publish 的字段）；T1 由人确认}
context_requirements:
  - 品类竞品库条目：品牌、型号、地区版本、各参数值及性质、来源、日期
  - 参数版本：单位、方向、标准工况
  - 我方现款已发布定义或提案目标 spec 条目（含 item_status）
  - 提案可见性（私有提案的对比结果不进品类共享；私有运行不能写品类知识）
allowed_operations:
  - {tool: category.competitors.list, tier: READ}
  - {tool: category.parameters.list, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: product.baseline.read, tier: READ}
  - {tool: evidence.search, tier: READ, note: 查已登记的竞品 Claim 与定位；对快照不返回正文}
  - {tool: research.fanout, tier: READ, kind: research, note: 补缺口，按 public_research 原则}
  - {tool: calc.spec_compare, tier: READ, kind: compute}
  - {tool: skill.load, tier: READ}
  - {tool: category.knowledge.add, tier: T0, note: 仅品类上下文中新的公开竞品观察（kind=competitor 的 metrics/features），ai_draft}
  - {tool: evidence.claim.record, tier: T0, note: 提案运行中（不能写品类知识时）新的公开竞品观察登记为 Claim；私有提案运行中登记的只给提案受众读（合同 §2.14）}
  - {tool: proposal.item.patch, tier: T0, note: 只写 section（key=worth_it）中的竞品对比结论；对比表是规格对标视图，不存条目}
  - {tool: category.parameter.publish, tier: T1, note: 竞品普遍标注而字典缺少的参数，起草通用新参数；私有提案运行中准备的候选由服务器做身份检查（identity_not_removed）}
evidence_policy: |
  每个竞品值带 Citation 和性质；官网值是 claimed；有测量方与工况的才是 measured。
  比较结论只能引用 calc_ref；模型不做差值、百分比、排序或单位换算。
failure_policy: |
  某参数可比样本不足或全部未知：照实输出，标"样本少"或"未知"，把补证列入 research_gaps。
  calc.spec_compare 拒绝（口径不一致）：把相关行移入 not_comparable，不绕过。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 6
  tool_calls: 16
  tokens: 约 50k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#competitor_comparison", case_types: [自主新品, 客户RFQ（对标现款）, 派生], min_cases: 10}
owner: 待定
preload_when:
  - 提案页打开竞品对比或规格对标视图
  - 用户要求"对比/对标/和某某比"
  - proposal_drafting 在自主新品入口加载
---

# competitor_comparison · 竞品同口径对比

## 工具

1. `category.parameters.list` 确定要比的参数版本；`category.competitors.list` 取竞品值；`product.baseline.read` 或 `proposal.items.read` 取我方现款或目标。
2. 竞品库缺值或过旧时，用 `research.fanout` 补（或 `skill.load("public_research")` 后按其原则执行），按参数版本抽取。
3. 按口径分组后，每组调用 `calc.spec_compare`；结论只依据其结果。
4. 新取得的公开竞品观察：品类上下文用 `category.knowledge.add`（T0，ai_draft）；提案运行中用 `evidence.claim.record`（T0）登记为 Claim（来源为快照；性质按 README §6 映射，官网与零售页标称为 extracted 并标 `vendor_claimed: true`，有测量方与工况的评测为 observed）。运行接触过私有资料（例如在私有提案中运行）时，这些 Claim 即使来源是公开快照，也只给提案受众读，不当作品类可读，也不能关联到品类知识（合同 §2.14）。对比结论写入提案 section `worth_it` 的竞品部分（`proposal.item.patch`，T0，op=upsert，保留其他部分），source_refs 引用这些 Claim 或知识条目；没有竞品行条目，对比表由提案的规格对标视图按 `calc.spec_compare` 显示。
5. 多款竞品都标注、字典里却没有的参数，起草通用新参数，用 `category.parameter.publish`（T1）请人确认。私有提案运行中准备的候选，服务器在预览与确认时做与去标识沉淀相同的身份检查：含客户名、该提案原件文件名或来源链接即被拒（identity_not_removed），预览列出命中项；被拒后去掉命中内容重拟，不绕过。
6. 需要价格维度时加载 `price_band`，不在本技能里处理价格口径。

## 数据语义

- **竞品库**：每个值区分实测、宣传、推断、未知，带来源与日期。同名型号在不同地区可能是不同配置，按地区版本区分。
- **同口径**：参数 ID + 版本相同、单位相同、测试工况相同、配置相同（例如是否含配件、供电方式）。任何一项不同或未知，就不是同口径。参数 ID 只在品类内唯一，跨品类同名参数不是同一参数。
- **工况举例（取自品类种子）**：auto-tire-inflator 的 `fill_time_full@1` 为 205/55 R16、0→36 psi，`fill_time_topup@1` 为同胎 26→36 psi；bicycle-pump 的 `fill_time_road@1` 为 700×25C、0→100 psi。`noise_level@1` 两个品类都按 1 m、前后左右 4 点测，但负载不同（汽车胎 26→36 psi 补气 / 700×25C 60→80 psi）；`max_pressure@1` 的密封容器分别为 ≤0.5 L 与 ≤0.1 L。这些同名参数不跨品类比较。
- **方向**：参数版本的"越大/越小越好"决定优劣表述；没有方向的参数只描述差异，不评优劣。
- **我方值**：现款已发布定义是基线；提案目标 spec 若 item_status=ai_draft，对比中标"目标（AI起草）"，不当作已确认指标。
- **字典缺参数**：新参数草稿只写键、名称、值类型、单位、方向；标准工况、方法、判据未知为空，需专家确认的另列，不照搬某品牌的宣传工况。回执到达前，该参数的值进 `not_comparable`（原因：未映射），不进对比组。
- **私有边界**：在私有提案里做的对比只写回该提案；客户值不进品类竞品库、品类知识或新参数草稿。

## 使用原则

**适用**：规格对标、定位图（价格 × 关键性能）的数据准备、功能配置对比。

**方法**：
1. 选 5–8 个关键参数：优先提案关键规格，其次字典里方向明确的参数。
2. 收集每个竞品每个参数的值和性质；同一型号多来源冲突时都保留，标 conflicted。
3. 按口径分组：同口径一组；不同口径另组或进 `not_comparable`，写具体原因。
4. 每组调用 `calc.spec_compare`；样本数由代码回填，少于 3 个可比样本标"样本少"（建议阈值）。
5. 观察（≤6 条）：我方在哪些参数领先/落后，依据 calc_ref；宣传值之间的比较要写明"均为标称值"。
6. 缺口转为研究问题，不用推断值补满表格。

**边界与禁止**：
- 不把宣传值写成实测，不把实测和宣传混在一组平均或排名。
- 不换算单位、不推算工况，例如不把不同轮胎规格的充气时间折算成同一规格。
- 未知不画点、不填中位数，只写数量和原因。
- 多个网址或型号不等于多个品牌；同一产品的多个零售链接只算一个型号。
- 不编造竞品型号或参数。

**失败时**：可比样本不足时照实给出现有组，结论写"不足以判断"；研究补证失败按 public_research 处理。

**输出要求**：
- reply 第一句给定位结论并带口径限定（例如"在标称最大压力上处于中上，噪音缺同工况数据无法比较"）。
- 对比表：每行一个型号，只列所选参数，单元格写值+单位+性质标记，≤12 行；我方行在首行。
- `not_comparable` 与未知汇总放表后；观察 ≤6 条，每条 ≤60 字。
- 视图规则（§05.8）：实测/宣传/推断/未知分开显示；口径不同分组；每个点可追溯来源；样本量可见；我方用强调色、竞品灰色（由前端执行，本技能提供分组与性质）。

## 示例（示意，非真实数据）

品类 `auto-tire-inflator`，比较 `fill_time_full@1`（205/55 R16，0→36 psi）。A 官网按该工况标称（宣传）；B 为评测按同工况实测；C 官网写"0–35 psi，195/65 R15"；D 只写"3 分钟充满"无工况。
→ A、B 同口径：同组展示、分别标"宣传""实测"，calc 只在同性质内排序；C 工况不同，单列一组或进 `not_comparable`（原因"轮胎规格与目标压力不同"），不折算；D 进 `not_comparable`，原因"工况未知"。
→ 某款两用泵在 bicycle-pump 竞品库中的 `fill_time_road@1` 值不进入本对比：跨品类同名或相近参数不是同一参数。
