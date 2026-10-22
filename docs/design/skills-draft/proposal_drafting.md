---
key: proposal_drafting
version: 0.2.0-draft
purpose: 在当前品类内按客户需求、自主新品、派生迭代三个入口起草或修订立项提案，以条目级补丁写入草稿，标明来源、状态与未知，并只提少量关键问题。
input_schema:
  type: object
  required: [instruction]
  properties:
    instruction: {type: string, description: 用户本轮要求，如"按 B 方案重写定义""续航改成 30 分钟"}
    entry_kind: {enum: [customer_request, new_product, derivative, null], description: 未知时由技能判断，判断不了就问}
    proposal_id: {type: [string, "null"], description: 服务器绑定；null 表示新建}
    base_ref: {type: [object, "null"], description: 参考型号/变体及定义版本（派生或对标基线）}
output_schema:
  type: object
  required: [patches, completed, needs_answers]
  properties:
    patches:
      type: array
      items: {op: "upsert|remove", item_id: "string|null（null=新增）", kind: "section|commercial_target|option|risk|difference|spec|assumption", base_version: "int|null", content: "按 kind 的结构（README 共用约定）；spec 含 item_status（ai_draft|expert_pending|unknown）与 availability；assumption 含 statement、basis、validation、related_item_ids", source_refs: "Citation[]", reason: "仅供说明，不进 payload"}
    completed: {type: array, items: string, description: 本轮实际完成的起草动作（有回执的）}
    needs_answers: {type: array, maxItems: 3, items: {question: string, why: string, options: "string[]", recommendation: string}}
    conflicts_with_human: {type: array, items: {item_id: string, human_value: string, proposed: string, question: string}, description: 触及人工值、已改出 T1 候选的条目}
context_requirements:
  - 品类：边界、用户与场景、地区法规摘要、参数版本（键、名称、单位、工况）
  - 提案：当前修订号、状态、各条目版本/值/状态/来源/负责人、是否人工值（origin=human 或 confirmed_by 非空）、有效可见性
  - 基线：参考型号已发布定义及平台引用（派生或对标时）；平台兼容范围与版本（平台复用或客户需求比对时）
  - 证据池：本会话与本提案已有引用与 Claim（ID 与定位，不含全文）
allowed_operations:
  - {tool: category.read, tier: READ}
  - {tool: category.knowledge.list, tier: READ}
  - {tool: category.parameters.list, tier: READ}
  - {tool: category.competitors.list, tier: READ}
  - {tool: proposal.read, tier: READ}
  - {tool: proposal.items.read, tier: READ}
  - {tool: product.baseline.read, tier: READ}
  - {tool: platform.read, tier: READ, note: 平台兼容范围与版本}
  - {tool: evidence.search, tier: READ, note: 查已有证据；对原件和网页快照只返回定位与已登记 Claim，不含正文}
  - {tool: calc.cost_subtotal, tier: READ, kind: compute}
  - {tool: skill.load, tier: READ}
  - {tool: proposal.create, tier: T1, note: 默认私有}
  - {tool: proposal.item.patch, tier: T0, note: op=upsert|remove；署 AI 名、可按运行撤回、不覆盖人工值（被拒改出 T1 候选）}
  - {tool: evidence.link.create, tier: T0, note: 把已登记的 Claim 关联到本轮写入或改写的条目}
  - {tool: proposal.question.create, tier: T1}
  - {tool: evidence.claim.withdraw, tier: T1, note: 单条撤回有误或含客户身份的 Claim；只预填候选，由负责人一次确认（P9）}
evidence_policy: |
  section 中的市场/客户信号、竞品、价格、用户声音必须带来源（source_refs）；规格值来自客户原件、基线定义或研究台账时引用之，AI 建议值 item_status=ai_draft 并在 reason 中说明。
  不编造来源、竞品、价格、评论、BOM、认证或模具事实；没有来源就写 unknown（规格条目 availability=unknown）并转为待决问题或研究问题。
  客户原件只经 rfq_extraction 的隔离抽取读取；本技能只引用其登记的 Claim，不读原文。
failure_policy: |
  补丁触及人工值被拒（human_value_protected）：不重试，改出 T1 候选并列入 conflicts_with_human；版本冲突（base_version_moved）：重读该条目再起草，不覆盖他人改动；提案已锁定（proposal_locked）：停止写入并说明。
  子技能失败或资料不足：先起草带 assumption 条目的版本（每条写依据与待验证方式），未知项保持 unknown，在 needs_answers 问最影响立项的问题。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 10（不含子技能）
  tool_calls: 40（条目补丁可批量）
  tokens: 约 80k
model_capability_requirements: [native_tool_calling, json_schema_output, parallel_tool_calls（只读）, 长上下文 ≥64k]
evaluation_suite: {rubric: "evaluation-rubric.md#proposal_drafting", case_types: [客户RFQ, 派生, 自主新品], min_cases: 12}
owner: 待定
preload_when:
  - 当前页面是立项提案页
  - 用户在品类页点"立项提案"打开的品类对话
  - 用户在任意对话中要求起草/修改提案
---

# proposal_drafting · 立项提案起草

## 工具

1. **读现状**：`category.read`、`category.parameters.list`（字典骨架与参数版本）、`category.knowledge.list`、`category.competitors.list`；有提案时 `proposal.read`、`proposal.items.read`，记下人工值、各条目 base_version 和已有待决问题。
2. **按入口加载子技能**（`skill.load`）：
   - 客户需求 → `rfq_extraction`（客户原件经其 `evidence.extract` 隔离读取；与现有型号的差距由其 `calc.spec_compare` 给出），平台候选用 `platform.read` 读兼容范围与版本；
   - 派生迭代 → `derivative_diff`（基线用 `product.baseline.read`）；
   - 自主新品 → `competitor_comparison`、`price_band`、`review_pain_clustering`、`jtbd`、`option_comparison`，需要时 `opportunity_scoring`。
   - 提交 G0 前或用户要求"查漏" → `gap_check`。
3. **无提案时** `proposal.create`（T1，默认私有）；从对话创建的提案一律私有，改共享只能由人操作。
4. **写条目**：`proposal.item.patch`（T0，op=upsert/remove，带 base_version）逐条写入，相关条目可同批；子技能已登记的 Claim 用 `evidence.link.create`（T0）关联到对应条目，不重复登记。目标成本合计用 `calc.cost_subtotal`，写入 commercial_target.cost。
5. **待决问题**：`proposal.question.create`（T1），owner_id 与 due_date 必填，由人一次确认；私有提案只能指派负责人或评审人，所需专业角色写在问题正文里。
6. `evidence.search` 只在本品类和本提案范围内找已有证据，不替代研究；它对客户原件和网页快照只返回定位与已登记 Claim，不返回正文；读原件原文只经 `evidence.extract`，读网页原文只经 `research.fanout`。
7. 共享提案、提交 G0、G0 决定（`proposal.share`、`proposal.g0.submit`、`proposal.g0.decide`）只能准备材料（例如提交说明），由人在界面办理。准备共享材料时说明：私有提案运行登记的 Claim 会随共享对新受众可见，服务器在共享预览中逐条列出并做身份检查，负责人确认后才共享。预览命中身份检查，或发现某条 Claim 登记有误时，用 `evidence.claim.withdraw`（T1）为命中的 Claim 预填撤回候选（列出命中内容与受影响条目），由负责人一次确认，不撤回整次运行；撤回后受影响条目标记"来源已撤回"，按需重新起草；已被签署 G0 决定消费的 Claim 不能撤回。

## 数据语义

- **立项提案回答四个问题**（对应条目）：值不值得做 → section `worth_it`（证据摘要：客户或市场信号、竞品与价格带、用户声音、主要风险）；做成什么样 → section `target_customer_market_channel`、`features_in_out`（含明确不做的）、`certification_regions`、`launch_window`，10–20 条 spec 条目，commercial_target（目标售价/成本/数量）；走哪条路 → ≥2 个 option 条目（可含 status_quo 或 do_nothing），少于 2 个的理由在 G0 提交时填写；还有什么不确定 → question（每条有负责人和期限）。另有 risk 条目和 decision_note（人的取舍记录，AI 不写）。
- **规格条目（SpecItem）**：引用本品类的 `parameter_id@version`（例如 auto-tire-inflator 的 `fill_time_topup@1`；参数 ID 只在品类内唯一，bicycle-pump 的同名参数是另一参数）；value/lower/upper、tolerance、unit（须等于字典单位）、condition_note、verification_method、acceptance_criterion、modality 与 exceptions（客户需求条目，由 rfq_extraction 按原文填写，本技能不改写）、source_refs、item_status、availability、owner_id。键、名称、单位、工况来自字典；字典没有的参数用自由 item_key 并标"未映射"，不自造参数版本；新参数由 rfq_extraction 或 competitor_comparison 依据来源起草（`category.parameter.publish`，T1）。
- **状态**：AI 只写 item_status `ai_draft` / `expert_pending` / `unknown`；`confirmed` 只能由具名的人设。人工值与已确认值不可被 AI 覆盖。
- **金额**：commercial_target 的 target_price、cost、volume 各自 amount、currency、basis、as_of、source；缺值为 NULL，不填零。
- **假设**：未明确的地区、价格、渠道、技术可行性等写成 assumption 条目（statement 内容、basis 依据、validation 待验证方式与回看时机、related_item_ids 关联条目），不写进 section 正文冒充事实；提案候选的 assumptions[] 在 proposal.create 时成为 assumption 条目。品类知识里随研究问题保存的假设（research_question 的 assumption）可作为 basis 引用（对象 ID + 版本）。验证后改写相关条目，假设条目按普通 AI 条目 upsert 或 remove。
- **品类背景**：提案引用品类资料时按"对象 ID + 版本"引用；G0 提交时由系统固定快照，品类后续修改不影响在审提案。
- **私有性**：引用了客户原件的提案按私有读取，不进入品类共享对标与矩阵。

## 使用原则

**适用**：新建提案、按用户指令改写提案、把子技能结果落到提案。

**三个入口**：
- **客户需求（含 OEM/ODM）**：先抽取客户要求（rfq_extraction），再比对现有型号与平台差距，起草立项版定义；不要求先做市场研究，OEM 不重做客户已决定的市场策略。标准品匹配不需要开发时，告诉用户无需立项，报价与沟通在 CRM。
- **自主新品**：同口径竞品、人群与完整使用路径、价格带、评论痛点 → 2–3 个定位方案与取舍 → 起草定义。资料不足先起草带 assumption 条目的版本。
- **派生迭代**：以原型号已发布定义为基线，列规格、BOM、认证、模具差异与复用范围；同一型号在项目内的修改应走变更，不走本技能。

**方法**：
1. 判断入口与范围；同名对象可能写错时，只问最小必要的选择。
2. 按字典骨架生成规格条目框架，再填值；每条写来源，或 availability=unknown。
3. 用户指令直接执行（例如"按 B 方案重写定义"），只改、只删 AI 条目；涉及人工值时改出 T1 候选并列入 `conflicts_with_human`。
4. 每轮最多 3 个 `needs_answers`，只问最影响立项方向的。
5. 重的专业确认（完整规格、协审、冻结）留到项目内，不作为立项前门槛。

**边界与禁止**：不整份替换文档；不把 AI 值标为已确认；不共享提案、不提交、不批准 G0（只能准备材料；提交由负责人本人办理，决定是 T2）；不对外发送任何内容；不读客户原件原文；不把客户资料写到品类知识；不宣称未执行的研究已完成。

**失败时**：补丁被拒就报告具体条目和原因类别；子技能失败时保留已完成部分并在 reply 中说明还缺什么。

**输出要求**：
- reply 第一句说本轮改了什么（≤60 字，例如"已按 B 方案起草 14 条关键规格，其中 4 条未知"）。
- 然后 `completed` 不超过 5 条；`needs_answers` 不超过 3 条，每条带推荐但不预选。
- section 每节 150–300 字；关键规格 10–20 条；方案对比交给 option_comparison 的格式。
- 不在 reply 里复述整份提案。

## 示例（示意）

用户（品类 `auto-tire-inflator` 下的自主新品提案页）："续航改成 8 次补气。"
→ 读条目：续航 spec 条目引用 `endurance_tires@1`（auto-tire-inflator；单位"次"，工况为 205/55 R16 每次 26→36 psi），当前 item_status=ai_draft、无人工值 → `proposal.item.patch` upsert value=8（带 base_version），unit 与工况保持字典定义，reason="用户指令"；电池容量 spec（`battery_capacity_mah@1`）也是 AI 起草 → upsert item_status=expert_pending（值不变）；upsert 一条 assumption 条目：statement="现有电芯方案可支撑 8 次补气"，basis="用户指令，暂无测试或计算依据"，validation="按 `endurance_tires@1` 工况样机实测或由电子工程师估算后回看"，related_item_ids 指向续航与电池容量条目；起草问题"按 8 次补气复核电池容量与目标成本"（`proposal.question.create`，T1，related_item_ids 指向电池容量与 commercial_target）。
→ 不拿 bicycle-pump 的 `endurance_tires@1`（700×25C 每次 0→80 psi）或其竞品值作参照：同名不同参数。
→ reply："续航目标已改为 8 次补气（AI起草）；电池容量改为待专家，已记一条待验证假设，复核问题待你确认。"
