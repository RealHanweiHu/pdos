---
key: experience_distillation
version: 0.1.0-draft
purpose: 业务事件触发后（G0 评审结束、品质问题关闭、项目关闭），只读触发对象及其关联记录，起草范围条目候选、知识候选或复盘清单；起草的一律是候选，由触发对象负责人确认后才生效。
input_schema:
  type: object
  required: [trigger]
  properties:
    trigger: {type: object, description: "服务器绑定的事件：rule、event_id、对象种类、id 与版本；模型不提供"}
output_schema:
  type: object
  required: [drafted, unknowns]
  properties:
    drafted: {type: array, items: {kind: "scope_note|case_record|candidate_method", statement: string, applicability: {model: string, build: string, condition: string}, evidence: "root_source_id[]", counter_examples: "string[]"}, description: "只是候选；服务器按 distillation.admit 收：适用条件锁定、按根来源计数、小Pai 生成的内容不算来源、一次成功只作案例记录"}
    unknowns: {type: array, items: {field: string, reason: string}}
context_schema: {$ref: "context-schemas.json#/profiles/project"}
context_requirements:
  - 触发对象（提案、问题、项目）的 id 与当前版本（服务器绑定）
  - 评审意见、根因、措施的已发布记录与回执
  - 本范围的有效范围条目
allowed_operations:
  - {tool: memory.search, tier: READ}
  - {tool: evidence.search, tier: READ}
  - {tool: scope_note.save, tier: T1, note: "只预填，由负责人确认"}
  - {tool: knowledge.candidate.create, tier: T0, note: "现有档位：须资格与当前授权；没有资格时进入“AI 需要你”例外队列"}
evidence_policy: |
  只用原始记录、条目和业务对象作依据；小Pai 以往的回答、范围简报、派生物都不是来源。
  一次成功不推广：单个案例只生成案例记录，适用条件锁定在那个型号、Build、工况上。
  晋升为候选方法须至少两个相互独立的案例有业务结果回执支撑，并列出已知反例。
  不改可信状态：起草的内容不会是“已核实”。
failure_policy: |
  缺触发对象或其已发布记录：不起草，交回“缺来源”。
  来源不可读：不起草该条，说明哪条来源不可读。
budget:
  status: 草稿（未启用，未实测）
  model_turns: 4
  tool_calls: 8
  tokens: 约 20k
model_capability_requirements: [native_tool_calling, json_schema_output]
evaluation_suite: {rubric: "evaluation-rubric.md#experience_distillation", case_types: [一次失败不推广, 同一来源不重复计数, 小Pai 回答不被再提取], min_cases: 10}
owner: 待定
preload_when: []
---

# experience_distillation · 经验沉淀（草稿，未启用）

本技能包只登记为草稿：放在 `skill_packages/drafts/`，技能目录不加载它，没有租户启用，没有任何 T0 资格。上线前须有 golden-case 与“租户 × 技能包 × 模型版本”资格（v1.1 §06.12、P88 第 1 项），启用走 `ai.skill.enable` 与 `ai.skill.qualify`。

## 做什么

- G0 评审结束：评审意见里反复出现的关注点 → 品类备忘或同客户标签的备忘候选，由提案负责人确认。
- 品质问题关闭：根因和有效措施 → 知识候选（`knowledge.candidate.create` 现有档位）。
- 项目关闭：本项目的备忘逐条建议“升到品类 / 转为知识候选 / 随项目归档”，由项目负责人确认。

## 不做什么

- 不写触发对象以外的对象；不改有效条目；不改可信状态；不写 golden-case。
- 不旁听讨论（P34）；只由业务事件和明确的订阅触发。
