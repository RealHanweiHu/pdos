---
key: derivative_diff
version: 0.2.0-draft
purpose: 以原型号已发布定义为基线，把改动说明拆成规格、BOM、认证、模具、成本及其他差异，区分直接差异与推断的传导影响，写明沿用范围和待专家项，作为派生提案的立项版定义草稿。
input_schema:
  type: object
  required: [change_description]
  properties:
    base_ref: {type: object, description: "原型号/变体 ID；服务器解析为其当前已发布定义版本"}
    change_description: {type: string, description: 用户的改动说明}
    target_kind: {enum: [new_product, new_variant], description: 派生出新型号还是新变体}
    proposal_id: {type: string, description: 服务器绑定（派生入口提案）}
output_schema:
  type: object
  required: [base_version, diffs, inherited, expert_pending]
  properties:
    base_version: {type: object, description: "{product_id, definition_revision}，回复中必须写明"}
    atomic_changes: {type: array, items: {change: string, source_quote: "用户说明原文片段"}}
    diffs:
      type: array
      items: {area: "specification|bom|certification|tooling|cost|other（difference 条目的 area）", item_ref: "覆盖路径：parameter_id@version / BOM 行 / 认证项 / 模具 ID / 成本项", baseline: "值或 unknown", proposed: "值或 unknown", change: "added|removed|changed", propagation: "direct（用户说明或计算工具直接给出）|inferred（传导推断）", impact: "影响说明；inferred 项写推断链", calc_ref: "前四类 direct 项为 calc.derivation_diff 结果 ID，cost 为 calc.cost_subtotal 结果 ID；其余为 null", sources: "Citation[] 或记录引用"}
    inherited: {type: array, items: string, description: 明确沿用不变的范围}
    version_notes: {type: array, items: {parameter_ref: string, note: "calc.derivation_diff 标出的跨版本参数，需人工映射"}}
    platform_fit: {type: array, items: {platform_ref: string, within_compatibility: "within|exceeds|unknown（候选判断，待专家确认）", basis: "platform.read 记录引用"}}
    expert_pending: {type: array, items: {item: string, role: string, question: string}, description: 经 proposal.question.create 起草；角色写在问题正文}
    redirect: {type: [string, "null"], description: "若属于同一型号在项目内的修改，写'应走变更'并停止"}
context_requirements:
  - 原型号基线（product.baseline.read）：已发布定义（规格条目及参数版本）、BOM、认证、模具、平台引用
  - 基线引用平台的兼容范围与版本（platform.read）
  - 品类当前参数版本
  - 派生提案已有条目与人工值
allowed_operations:
  - {tool: product.baseline.read, tier: READ, note: 返回已发布定义、BOM、认证、模具、平台引用}
  - {tool: platform.read, tier: READ, note: 平台兼容范围与版本}
  - {tool: category.parameters.list, tier: READ}
  - {tool: proposal.read, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: evidence.search, tier: READ, note: 认证报告、模具记录等已登记资料}
  - {tool: calc.derivation_diff, tier: READ, kind: compute, note: 规格/BOM/认证/模具逐项差异}
  - {tool: calc.cost_subtotal, tier: READ, kind: compute}
  - {tool: proposal.item.patch, tier: T0, note: op=upsert；spec 条目写新值，difference 条目写各类差异（含 area、item_ref、change、propagation）}
  - {tool: proposal.question.create, tier: T1}
  - {tool: platform.link.create, tier: T1, note: 仅当用户明确说明已存在型号应关联某平台而基线缺此关联}
evidence_policy: |
  baseline 值只来自基线记录（引用对象 ID + 版本）；基线没有的写 unknown，不从记忆或竞品补。
  规格/BOM/认证/模具的直接差异只引用 calc.derivation_diff 的结果（calc_ref），成本差只引用 calc.cost_subtotal，模型不自行比对父值与新值、不估算成本。
  传导影响一律 propagation=inferred，写清推断链（例如电池容量变化 → 可能影响运输与认证），由专家确认。
failure_policy: |
  基线没有已发布定义（工具返回草稿并标明，或 baseline_unreadable）：停止起草差异，告诉用户需先导入或发布基线（可标"导入，未复核"），只列改动清单。
  基线缺 BOM/认证/模具数据：对应 area 全部 unknown，列入 expert_pending，不跳过该 area。
  calc.derivation_diff 不可用或拒绝：只交原子改动清单与父值引用，差异写"待计算"，不手工比对。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 6
  tool_calls: 18
  tokens: 约 50k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#derivative_diff", case_types: [派生（新型号/新变体）, 片段级小案例], min_cases: 10}
owner: 待定
preload_when:
  - 提案 entry_kind=derivative
  - 型号页点"发起派生提案"
  - 用户说"在某型号基础上改…/出一个某某版"
---

# derivative_diff · 派生差异

## 工具

1. `product.baseline.read` 读原型号基线：当前已发布定义（规格条目及参数版本）、BOM、认证、模具、平台引用；在 reply 中写明基线版本。
2. `category.parameters.list` 对照当前参数版本。
3. `platform.read` 读基线引用平台的兼容范围与版本：改动是否仍在兼容范围内，决定"平台沿用"是候选还是需扩展平台（都待专家确认）。
4. `evidence.search` 找已登记的认证报告、模具与供应资料，用于判断沿用范围；它对原件和网页快照只返回定位与已登记 Claim，不返回正文，没有 Claim 覆盖的内容按未知处理。
5. `calc.derivation_diff`：传入基线版本与派生方（提案当前修订，含本轮写入的改动条目），得到规格/BOM/认证/模具逐项差异与不可比原因（含跨版本参数）；`calc.cost_subtotal` 对 BOM 增减项求成本差。
6. `proposal.item.patch`（T0，op=upsert）写条目：规格改动写 spec 条目（新值，item_status ai_draft/expert_pending），差异写 difference 条目（area、item_ref、change、baseline、proposed、propagation、impact、sources）；`proposal.question.create`（T1）建专家问题，所需角色写在问题正文，负责人只能是提案负责人或评审人。
7. `platform.link.create`（T1）只在用户明确要求、且对象是已存在型号时使用；派生出的新型号在 G0 前还不存在，不能关联。

## 数据语义

- **基线**：原型号已发布定义，不可变（发布内容不可静默修改）。派生 = 固定父版本 + 显式覆盖（覆盖路径、原因、来源、适用范围），父版不受影响。
- **边界**：派生出**新型号或新变体**走立项提案（本技能）；**同一型号**在项目内的修改走变更（ChangeRequest），不用本技能。
- **差异类别**（difference 条目的 area：specification / bom / certification / tooling / cost / other；前四类逐项差异由 `calc.derivation_diff` 计算；模型负责拆改动、找传导影响、写沿用范围）：
  - 规格：引用参数版本；计算工具标出父定义用了旧版本参数时不跨版本比较，记入 version_notes 等人工映射。
  - BOM：内部研发编号、ERP 料号、客户料号分别记录，不互相替代。
  - 认证：按销售地区；电气、电池、无线、材料等变化可能影响认证，这是推断（propagation=inferred），交认证专家确认。
  - 模具：新开、修改、沿用三类；外观或结构变化通常牵动模具，同样标 inferred。
  - 成本（cost）：对 BOM 增减项用 `calc.cost_subtotal` 求差，写 area=cost 的条目（calc_ref 指向该结果）；所依据的 BOM 差异是推断时，成本条目也标 inferred。目标成本仍在 commercial_target。
  - 其他（other）：不属于以上五类的差异（例如包装、说明书、随附配件），只写用户说明的直接差异或标 inferred 的传导项，不计算。
- **直接与推断**：propagation=direct 指用户说明的改动及计算工具直接给出的差异；由此牵动的其他条目是传导影响，propagation=inferred，impact 写推断链，并列入待专家项。
- **平台兼容**：改动超出 `platform.read` 给出的兼容范围或版本不明时，不写"平台沿用"，记为差异或 unknown 并列入待专家项。
- **三方差异**：父版后来更新时的"旧父/新父/子版"差异用 `calc.derivation_diff` 的三方模式计算（包装派生引擎），双方都改的项列为冲突，不在本技能里手工做。

## 使用原则

**适用**：派生迭代入口的提案（新地区版、新配置版、降本版、升级版）。

**方法**：
1. 确认基线版本与派生对象类型（新型号/新变体）；如果用户说的是同一型号在项目内修改，填 `redirect` 并停止。
2. 把改动说明拆成原子改动，每条保留用户原话片段。
3. 每条改动先写成条目（规格改动写 spec 条目，BOM/认证/模具/其他改动写 difference 条目），再用 `calc.derivation_diff` 比较基线与提案当前修订，以其结果为直接差异（propagation=direct）并核对 difference 条目的 baseline 值；然后按"规格 → BOM → 认证 → 模具 → 成本"顺序找传导影响，每项写成 propagation=inferred 的 difference 条目（impact 写推断链）。
4. 明确写出沿用不变的范围（inherited），避免"没提到 = 不知道"。
5. 规格、BOM、认证、模具四类都要有结论：有差异、无差异（依据）、或未知（缺基线数据）；有 BOM 差异时给出 cost 结论（含"待计算"）。
6. 需要专业判断的项进入 expert_pending，按角色（结构、电子、认证、模具、采购）建问题。

**边界与禁止**：
- 不修改父版定义；不把派生差异写回原型号。
- 不编造父值；不编造认证要求、测试项目或模具费用。
- 不跨参数版本比较；不换算单位。
- 不宣称"认证可沿用""模具可沿用""平台可沿用"为结论，只能写"候选沿用，待专家确认"。

**失败时**：基线缺失就只交改动清单和缺口；某 area 数据缺失全部标 unknown 并建专家问题；计算工具不可用时差异写"待计算"。

**输出要求**：
- reply 第一句："基于 <型号> 定义 v<n>，共 N 项直接差异、M 项推断影响，K 项待专家"（≤60 字；数字由代码按 propagation 回填）。
- 差异表按 area 分组：项、基线值、新值、变化、直接/推断、影响；每组 ≤10 行，超出折叠。
- 沿用范围一段 ≤100 字；待专家列表每条 ≤50 字并写角色。

## 示例（示意，合成）

用户（品类 `auto-tire-inflator`，型号页"发起派生提案"）："出一个大电池版，电池容量翻倍，别的不变。"
→ 基线：该型号已发布定义 v<n>（`product.baseline.read`）。规格：`battery_capacity_mah@1` 写 spec 条目新值，`calc.derivation_diff` 给出 direct 差异；`endurance_tires@1`、`battery_energy_wh@1` 会随之变化，但没有计算或测试依据 → 只写 propagation=inferred 的 specification 差异，值 unknown。
→ BOM：电芯行由用户说明直接改动（direct，calc_ref）；认证：`battery_energy_wh@1` 变化可能需重做 UN 38.3 运输测试（inferred，待认证专家）；模具：电池仓尺寸可能变化（inferred，待结构/模具专家）；成本：对电芯增减行 `calc.cost_subtotal` 求差，写 area=cost（direct，calc_ref；若电芯单价未知则"待计算"）；包装与说明书的电池标识更新写 area=other（inferred）。
→ 只引用 auto-tire-inflator 的参数版本；bicycle-pump 的同名参数（如 `endurance_tires@1`，700×25C 每次 0→80 psi）不能作基线或比较对象。
