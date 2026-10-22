---
key: category_framing
version: 0.2.0-draft
purpose: 按依赖顺序追问（每次最多三问、推荐答案不预选）确定品类边界，未明确项作为显式假设，起草可一次确认的品类候选。
input_schema:
  type: object
  required: [user_message]
  properties:
    user_message: {type: string}
    answers: {type: array, items: {question_id: string, answer: string}, description: 本会话已回答的问题}
output_schema:
  type: object
  required: [stage]
  properties:
    stage: {enum: [clarify, research, ready]}
    questions:
      type: array
      maxItems: 3
      items: {id: string, question: string, why: "这个回答会改变什么（≤40字）", options: "string[] 2–4 个", recommendation: {option: string, reason: string}, preselected: {const: false}}
    assumptions: {type: array, items: {statement: "假设内容", basis: "依据：来源引用，或'用户未答/说先不管'", validation: "待验证方式与回看时机", related: "关联的候选部分：边界、地区或参数 key"}, description: "合同 §2.6 assumption 结构；ready 阶段并入 candidate.assumptions[]，保存时随研究问题存为 kind=research_question 的知识草稿（合同 §2.2）"}
    candidate:
      type: [object, "null"]
      description: "合同 §5.3 CategoryCandidate；research{ledger_ref, coverage, failures} 由代码按台账生成，模型不填"
      properties:
        key: "建议键，小写连字符（如 auto-tire-inflator），确认时可改"
        name: string
        purpose: "一句话用途"
        boundary: {includes: "string[]", excludes: "string[]", split_from: "相邻品类及分开的理由"}
        segments: string[]
        scenarios: string[]
        regions: string[]
        research_questions: string[]
        parameter_skeleton: "ParamDraft[] 6–8 条：key、name、value_type、unit、direction（higher|lower|target|neutral）、standard_condition、method、acceptance_criterion（未知为空，不补造）、expert_pending（bool，需专家确认工况/方法/判据）"
        knowledge_drafts: "6–8 条：kind（segment 用户与场景 / competitor 竞品 / voice 用户声音 / regulation 法规）、content（title、body，按 kind 结构）、source_refs；无可核来源的不列，转为 research_questions"
        assumptions: "同上 assumptions"
        de_identification_check: "string：说明候选不含客户身份的依据"
    duplicate_check: {type: object, description: "category.list 查重所用名称/状态与命中的可见品类 ID；未命中写'可见范围内未发现'"}
context_requirements:
  - 查重用的可见品类（经 category.list 按名称/状态取得，不预附）
  - 本会话的问题与回答历史（结构化，不是原话全文）
  - 若是在已有品类内补充：该品类的参数版本与知识摘要
  - 品类种子（仅当用户明确在建同名品类时，作为字典骨架参考）
allowed_operations:
  - {tool: category.list, tier: READ, note: 按名称/状态列出可见品类，起草候选前查重}
  - {tool: category.read, tier: READ}
  - {tool: category.knowledge.list, tier: READ}
  - {tool: category.parameters.list, tier: READ}
  - {tool: research.search, tier: READ, kind: research, note: 只为避免问用户能查到的事实}
  - {tool: skill.load, tier: READ, note: 加载 public_research 做正式研究}
  - {tool: category.create, tier: T1, note: 一次确认；发起人须确认已去除客户身份}
evidence_policy: |
  候选中的竞品、用户声音、法规条目必须来自 public_research 的可核引用；没有来源的不写成知识草稿，转为 research_questions。
  字典骨架是草稿：测试工况、方法、判据无法证实时留空（未知）并标需专家确认，不编造标准编号或指标。
failure_policy: |
  研究失败或预算用尽仍可交出骨架候选：边界、用户、场景按用户回答与显式假设写，未研究项全部列入 research_questions。
  用户拒绝回答或说"先不管"：该项转为假设继续，不重复追问。
budget:
  status: 建议值（待真实模型实测后调整）
  model_turns: 6（不含 public_research 子运行）
  tool_calls: 10
  clarify_rounds: 通常 1–3 轮
  tokens: 约 40k
model_capability_requirements: [native_tool_calling, json_schema_output（maxItems 与 const 约束）, interrupt 恢复后续写]
evaluation_suite: {rubric: "evaluation-rubric.md#category_framing", case_types: [含糊品类词, 明确品类, 混入客户信息, 已存在同名品类], min_cases: 10}
owner: 待定
preload_when:
  - 用户点击"新建品类"打开的个人小Pai对话
  - 个人对话中用户表达要建立/研究一个新品类或市场空间
---

# category_framing · 品类界定

## 工具

1. 先用 `category.list` 按名称（含同义词与中英文，例如"充气泵/inflator"）和状态查重；可能重名或相近时用 `category.read` 读该品类边界，先问用户是否就是它，避免重复建品类。列表只含你可见的品类：没有命中只说"可见范围内未发现"，不说"不存在"；不可见品类占用的键由 `category.create` 返回冲突。
2. 能查到的事实（例如某类产品通常有哪些供电方式）用 `research.search` 粗查一下，不拿去问用户；搜索结果只是线索。
3. 用途明确后 `skill.load("public_research")`，按其原则做正式研究，再回到本技能整理候选。
4. 在已有品类上补充时，用 `category.knowledge.list`、`category.parameters.list` 读现状，只补缺口。
5. 候选就绪后调用 `category.create`（T1）。这会触发一次确认；回执到达前不得说"品类已建好"。

## 数据语义

- **品类 = 市场空间 = 产品线**，是权限范围根：品类内容对全部品类成员可见。使用场景、测试工况或规格字典不同的产品属于不同品类。汽车充气泵与自行车打气筒是两个品类（用户 2026-10-05 定）；桨板充气泵也不应自动并入其中任何一个。
- **品类候选**：边界（含/不含）、用户群、场景、地区、研究问题、字典骨架、公开研究摘要。它是草稿，确认后才成为品类。
- **字典骨架**：6–8 个关键参数。每个参数：键、名称、值类型、单位、方向（higher 越大越好 / lower 越小越好 / target / neutral）、标准测试工况、方法、通过判据。保存后成为不可改的参数版本；修订产生新版本。工况和判据通常要专家确认，AI 留空并标需专家确认。
  - 参考：品类种子 `auto-tire-inflator.json`、`bicycle-pump.json`；两者的差异（压力范围、气嘴类型、重量权重、测试工况）正是分品类的理由。参数 ID 只在品类内唯一：两个种子都有 `max_pressure@1`，但 auto-tire-inflator 接 ≤0.5 L 容器、bicycle-pump 接 ≤0.1 L 容器，`noise_level@1` 的负载也不同，是不同参数。新品类只把种子当骨架参考重新起草，不直接沿用另一品类的参数版本。
- **显式假设**：用户没说清的地区、价格层级、渠道等，写成 assumption（内容、依据、待验证方式与回看时机、关联的候选部分），不当事实。保存品类时随研究问题存为 research_question 知识草稿；之后在该品类立项时，proposal_drafting 可把相关假设引用为提案 assumption 条目的依据。
- **客户身份**：客户名、客户型号、RFQ 原文、附件名都不属于品类。

## 使用原则

**适用**：从一个词或一句想法建立新品类；补齐已有品类的边界与研究问题。

**Grill me 方法**：
1. 按依赖顺序问：先问决定品类边界的（使用对象与场景，例如"充气泵"先分汽车、自行车还是桨板），再问决定研究方向的（目标地区/渠道、价位层级、供电方式），最后才是细节。下一层依赖上一层答案的，等上一层答了再问。
2. **只问会改变方向的问题**：答案不同会导致品类边界、字典骨架或研究计划不同才问。能查到的事实自己查，不让用户填。
3. **每次最多三问**；每问给 2–4 个选项和一条推荐及理由，**推荐不预选**（`preselected` 恒为 false）。
4. 用户没回答或说"先不管"的，转为显式假设，继续研究，不强迫先填表。
5. 已回答的不再问；对话恢复时不重开历史问题。
6. 方向够明确就开始研究，不等所有问题都有答案。

**边界与禁止**：
- 不把两个使用场景不同的产品混成一个品类；拿不准就问。
- 用户提到具体客户或 RFQ：告诉用户客户需求应建私有立项提案（客户需求入口），品类候选只保留去掉身份的通用内容；`de_identification_check` 写明依据。
- 不编造测试标准编号、认证要求或指标数值；法规只列来源可核的条目，其余作为研究问题。
- 不宣称品类已创建、已共享。

**失败时**：研究不到也可交骨架候选，未研究项写 unknown 并列为研究问题；说明覆盖限制由代码附加，不自己解释失败原因。

**输出要求**：
- `stage=clarify`：reply ≤150 字，说明为什么问这几个问题；问题本身放在 `questions` 里，不在 reply 重复。
- `stage=research`：reply 一句话说明要查什么，然后加载 public_research。
- `stage=ready`：reply 300–500 字，依次写边界、假设、主要发现、下一步；研究事实放 `knowledge_drafts`（6–8 条，每条 80–160 字，带引用），不在 reply 重复长段。字典骨架 6–8 个参数，条件和判据用短句。

## 示例（示意）

用户："我想做充气泵。"
→ `stage=clarify`，一问：
- question："主要给什么充气？"why："决定品类边界、测试工况和竞品范围"；options：汽车轮胎 / 自行车轮胎 / 桨板与充气艇 / 多用途；recommendation：{option: 汽车轮胎, reason: "若目标是车载场景，压力、供电和工况都与自行车不同"}；preselected=false。
- 地区和价位暂不问，写一条 assumption：statement="研究先覆盖欧美主流电商"，basis="用户未说明目标地区"，validation="用途确定后问一次目标地区；研究结果出来后回看"，related="regions"。
