---
key: gap_check
version: 0.2.0-draft
purpose: 检查立项提案或型号定义的缺项、冲突与口径问题（缺单位/工况/方法、未映射参数、来源缺失、方案不足、未知项没有待决问题等），按严重度排序，并把需要人处理的项整理成待决问题候选。
input_schema:
  type: object
  properties:
    target: {type: object, description: "{kind: proposal|definition, id, revision}，服务器绑定"}
    trigger: {enum: [user_request, pre_g0_submit, new_evidence, scheduled], description: 触发来源}
    changed_sources: {type: array, items: string, description: new_evidence 触发时变化的来源 ID}
output_schema:
  type: object
  required: [findings]
  properties:
    findings:
      type: array
      items:
        finding_id: string
        item_ref: "条目 ID 或 section key（worth_it 等）"
        type: "missing_unit|missing_condition|missing_method|unmapped_parameter|parameter_version_mismatch|value_without_source|conflict_between_items|conflict_with_source|state_inconsistent|options_lt_2_without_reason|unknown_without_question|missing_section|private_ref_in_shared|stale_or_withdrawn_source|affected_by_new_evidence|vague_requirement"
        severity: "blocks_g0|invariant|needs_disposition|advisory"
        explanation: "≤60 字"
        evidence: "条目字段或 Citation"
        suggested_action: string
        suggested_role: "string|null"
        existing_question: "已有待决问题 ID | null（已有未关闭问题时只引用，不再建）"
    questions_to_create: {type: array, items: {finding_ids: "string[]", question: "含所需专业角色", related_item_ids: "string[]", suggested_owner: "负责人或评审人（私有提案）", suggested_due: date}, description: 只含没有已有问题覆盖的 findings；owner_id 与 due_date 由人在确认框选定}
    evidence_links: {type: array, items: {evidence_ref: string, item_ref: string}, description: new_evidence 触发时，经 evidence.link.create 把变化证据挂到受影响条目}
    status_updates: {type: array, items: {item_ref: string, availability: "conflicted|null", item_status: "expert_pending|null"}, description: 仅 AI 起草且无人工值的 spec 条目，值不变}
  note: 各严重度的计数由代码根据 findings 生成
context_requirements:
  - 目标提案/定义的全部条目：kind、值、unit、condition_note、verification_method、acceptance_criterion、modality、exceptions、source_refs、item_status、availability、负责人、是否人工值、版本
  - 品类当前参数版本（含方向、工况、判据）
  - 已有待决问题：question、owner_id、due_date、status、related_item_ids（proposal.items.read 返回，用于去重）
  - 派生或平台复用提案引用的平台兼容范围与版本
  - 提案可见性与引用的原件类型（判断私有引用）
  - new_evidence 触发时：变化来源与引用它的条目（含条目 source_refs 与证据关联）
allowed_operations:
  - {tool: proposal.read, tier: READ}
  - {tool: proposal.items.read, tier: READ, note: 含已有待决问题，用于去重}
  - {tool: category.read, tier: READ}
  - {tool: category.parameters.list, tier: READ}
  - {tool: product.baseline.read, tier: READ}
  - {tool: platform.read, tier: READ, note: 核对条目引用的平台版本与兼容范围}
  - {tool: evidence.search, tier: READ, note: 核对来源是否仍有效、是否撤回}
  - {tool: calc.spec_compare, tier: READ, kind: compute, note: 判断条目之间或条目与来源的数值冲突}
  - {tool: proposal.question.create, tier: T1}
  - {tool: evidence.link.create, tier: T0, note: 把变化证据关联到受影响条目；只追加来源、不改值}
  - {tool: proposal.item.patch, tier: T0, note: 仅对 AI 起草且无人工值的 spec 条目 upsert availability=conflicted 或 item_status=expert_pending，值不变}
  - {tool: product.definition.item.patch, tier: T0, note: 定义上下文中同上}
evidence_policy: |
  每个 finding 指向具体条目与字段；冲突类要给两边的证据。规则类检查（缺单位、缺工况、版本不一致）以条目字段为准，不凭印象。
  只按 v1.1 与 M3 合同的 G0 提交检查判 blocks_g0，不自加门槛。
failure_policy: |
  读不到部分条目或来源：在 reply 中说明检查范围不完整，不把"没查到问题"写成"没有问题"。
  建问题被拒或用户未确认：保留 findings，不重复创建。
  已有问题读不全：不建可能重复的问题，在 reply 中说明去重范围不完整。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 4
  tool_calls: 12
  tokens: 约 40k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#gap_check", case_types: [客户RFQ, 派生, 自主新品（均含预埋缺陷）], min_cases: 10}
owner: 待定
preload_when:
  - 提案负责人打开"提交 G0 立项评审"之前
  - 提案或定义引用的来源有新版本、被撤回或新增证据（领域事件）
  - 用户要求"查漏/检查一下/还缺什么"
  - 型号定义页（项目内）请求检查
---

# gap_check · 缺项与冲突检查

## 工具

1. `proposal.read`、`proposal.items.read`（或定义上下文的同类数据）取全部条目和已有待决问题；`category.parameters.list` 取当前参数版本。
2. `evidence.search` 核对来源是否仍有效；`product.baseline.read` 在派生提案中核对基线引用；`platform.read` 核对引用平台的版本与兼容范围（不一致记 conflict_with_source，平台有新版本记 stale_or_withdrawn_source）。
3. 数值冲突用 `calc.spec_compare` 判断，不自己比。
4. 需要人处理的项合并后用 `proposal.question.create`（T1）建待决问题：related_item_ids 指向条目，所需专业角色写在问题正文，建议负责人与期限由人在确认框选定（私有提案只能是负责人或评审人）。建之前用 `proposal.items.read` 返回的已有待决问题去重：related_item_ids 覆盖同一条目、同一缺口且 status=open 的，finding 只引用该问题（existing_question），不再建。
5. 新证据触发时（没有"加标记"操作）：用 `evidence.link.create`（T0）把变化证据关联到受影响条目；受影响的 AI 起草规格条目可用 `proposal.item.patch` 或 `product.definition.item.patch`（T0，upsert）改 availability=conflicted 或 item_status=expert_pending，值不变；人工值条目只建问题。
6. 提交 G0 前的检查结果作为提交前检查材料；`proposal.g0.submit`、`proposal.g0.decide` 只能准备材料，由负责人或评审人本人办理。为评审人准备处置表草稿时，处置负责人和项目负责人都可以是私有提案受众外的品类成员：G0 决定会在同一事务把他们加入该型号与项目的受众（合同 §3.4），草稿逐条标出这一影响，由评审人决定。

## 数据语义

- **立项前要求的是"知道缺什么"，不是"什么都齐"**：G0 允许带未知提交，但评审人要为每条未知安排负责人与期限。完整规格、专业协审、规格冻结在项目内完成，不作为立项前缺项。
- **严重度**：
  - `blocks_g0`：只用于 G0 提交检查会拒绝的内容缺口：`worth_it` 段落为空（narrative_missing），option 条目少于 2 个且负责人未准备提交理由（options_insufficient，AT-54）。
  - `invariant`：数据违反不变量，不是 G0 门槛但要立即告诉负责人——AI 来源的值被标成已确认或记成人工来源（state_inconsistent，I23）；共享范围内出现客户私有内容（private_ref_in_shared，I22）。
  - `needs_disposition`：未知、缺单位/工况/方法、未映射参数、版本不一致、来源缺失、冲突、未知项没有关联的待决问题（问题本身的负责人和期限是必填，不会缺）——可以带入 G0，但要有处理安排。
  - `advisory`：表述含糊、可改进的写法。
- **规格条目检查**：参数版本引用是否存在；unit 与字典是否一致，condition_note 是否说明了与标准工况的差异；目标值有无验证方法与判据（条目的 verification_method、acceptance_criterion，未填时看参数版本的 method 与判据；两处都没有记 missing_method）；客户需求条目的 modality、exceptions 是否与所引 Claim 一致；值有无 source_refs；item_status 是否合理（AI 写入只能是 ai_draft/expert_pending/unknown，confirmed 须有值或不适用理由和来源）；availability=not_applicable 是否写了理由。 G0 批准前须逐条处置的规格条目（确认稿 P11）：item_status 为 unknown / expert_pending，或 availability 为 unknown / conflicted（含 ai_draft）；提交前把它们列为待处置项，并起草处置建议（task 或 risk、负责人、期限）供评审人参考。
- **口径**：不同参数版本、单位或工况的条目不能当作同口径；发现被当作同口径比较即为 parameter_version_mismatch 或 conflict。
- **未知不等于不适用**：标"不适用"的条目要有依据，没有依据是 finding。

## 使用原则

**适用**：提交 G0 前自查；新证据到达时关联受影响条目；项目内定义迭代时查缺。

**方法**：
1. 先做规则类检查（字段缺失、版本、状态、可见性），再做语义类检查（含糊表述如"高品质""更耐用"、条目间矛盾、与来源矛盾）。
2. 每个 finding 一句解释、一个建议动作、一个建议角色（产品、结构、电子、固件、品质、认证、采购）。
3. 相关的 findings 合并成一个问题，避免一条缺单位建一个问题；已有问题覆盖的不再建。
4. 按严重度排序输出；同严重度按提案章节顺序。
5. new_evidence 触发：只检查引用了变化来源的条目，关联证据并说明变化，不重查全提案。

**边界与禁止**：
- 不修改人工值或已确认值；不自动"修复"缺项（补值是 proposal_drafting 的事，且只能起草）。
- 不自加 v1.1 没有的门槛（例如要求立项前完成全部规格冻结内容）。
- 不把 not_applicable 当作可以自动设置的状态。
- 不关闭或替人处置问题；不替人指定负责人（由确认人在 T1 确认框选定）。

**失败时**：检查范围不完整就明说范围；建问题失败保留 findings 供人手工处理。

**输出要求**：
- reply 第一句："共 N 项需处理，其中 K 项会阻断提交 G0"（数字由代码回填；≤60 字）；有 invariant 项时第二句单独点出。
- findings 表：严重度、条目、类型、说明、建议动作、所需角色；默认显示前 10 行，其余分页。
- 待建问题列表 ≤5 条（合并后），每条 ≤60 字。
- 没有发现时写"在已检查范围内未发现缺项"，并写明检查范围。
