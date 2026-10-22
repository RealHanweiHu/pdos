---
key: category_framing
version: 0.2.2-draft
purpose: 按依赖顺序追问（每次最多三问、推荐答案不预选）确定品类边界，未明确项作为显式假设，起草可一次确认的品类候选。
input_schema:
  type: object
  required: [user_message]
  properties:
    user_message: {type: string}
    answers: {type: array, items: {question_id: string, answer: string}, description: 本会话已回答的问题}
output_schema:
  $defs:
    ClarifyOption:
      additionalProperties: false
      properties:
        value:
          title: Value
          type: string
        label:
          title: Label
          type: string
      required:
      - value
      - label
      title: ClarifyOption
      type: object
    WireQuestion:
      additionalProperties: false
      properties:
        id:
          title: Id
          type: string
        question:
          title: Question
          type: string
        why:
          title: Why
          type: string
        options:
          items:
            $ref: '#/$defs/ClarifyOption'
          title: Options
          type: array
        recommended:
          anyOf:
          - $ref: '#/$defs/WireRecommendation'
          - type: 'null'
        allow_free_text:
          title: Allow Free Text
          type: boolean
        depends_on:
          items:
            type: string
          title: Depends On
          type: array
      required:
      - id
      - question
      - why
      - options
      - recommended
      - allow_free_text
      - depends_on
      title: WireQuestion
      type: object
    WireRecommendation:
      additionalProperties: false
      properties:
        value:
          title: Value
          type: string
        reason:
          title: Reason
          type: string
      required:
      - value
      - reason
      title: WireRecommendation
      type: object
  additionalProperties: false
  description: Finite native grammar; business candidate JSON is checked by its domain
    schema.
  properties:
    status:
      enum:
      - completed
      - partial
      - needs_input
      title: Status
      type: string
    summary:
      title: Summary
      type: string
    result_json:
      title: Result Json
      type: string
    questions:
      items:
        $ref: '#/$defs/WireQuestion'
      maxItems: 3
      title: Questions
      type: array
    unfinished:
      items:
        type: string
      title: Unfinished
      type: array
  required:
  - status
  - summary
  - result_json
  - questions
  - unfinished
  title: WireAgentOutput
  type: object
context_schema: {$ref: "context-schemas.json#/profiles/category"}
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
model_capability_requirements: [native_tool_calling, json_schema_output（maxItems 与封闭字段约束）, interrupt 恢复后续写]
evaluation_suite: {rubric: "evaluation-rubric.md#category_framing", case_types: [含糊品类词, 明确品类, 混入客户信息, 已存在同名品类], min_cases: 10}
owner: 待定
preload_when:
  - 用户点击"新建品类"打开的个人小Pai对话
  - 个人对话中用户表达要建立/研究一个新品类或市场空间
---

# category_framing · 品类界定

## 实际运行输出与授权

原生输出必须遵守 `WireAgentOutput`：`status` 为 completed / partial / needs_input，`summary` 为回复正文，`result_json` 为 JSON 对象序列化后的字符串，`questions` 与 `unfinished` 始终为数组。额外展示信息放在 result_json 内；工具参数按当前 ToolRegistry 下发的 DTO，不能把展示候选当工具参数。工具调用和真实回执决定是否完成，输出文字不能替代执行。

需要澄清时用 status=needs_input，questions 为 1–3 条；不需要时为 []。每题完整提供 `id, question, why, options[{value,label}], recommended{value,reason}, allow_free_text, depends_on`；无推荐时 recommended=null。推荐 value 必须来自选项，只标推荐和理由，不代表用户选择、不预选，不输出 preselected 字段。依赖尚未回答的问题本轮先不问。用户说先不管或拒答时写明假设与回看方式，不循环追问。恢复时沿用原问题和答案，不再生成同一 interrupt。

本版本仅更新技能内容，不授予启用或 T0 资格；资格由服务器按当前租户、技能版本及模型版本核对。真实模型验证仍待授权。工具仅有名称或占位 schema 不表示已有执行能力；缺前置能力时在 unfinished 说明，继续独立且已授权的工作，不编造已执行结果。

## 工具

1. 先用 `category.list` 按名称（含同义词与中英文，例如"充气泵/inflator"）和状态查重；可能重名或相近时，先按列表返回的可见名称与用途问最小必要的选择。个人 Run 没有品类，不能按命中 ID 调用 `category.read` 或其他品类读取；已有品类 Run 才能用 `category.read` 读取其服务器绑定的当前品类。列表只含你可见的品类：没有命中只说"可见范围内未发现"，不说"不存在"；不可见品类占用的键由 `category.create` 返回冲突。
2. 能查到的事实（例如某类产品通常有哪些供电方式）用 `research.search` 粗查一下，不拿去问用户；搜索结果只是线索。
3. 用途明确后 `skill.load("public_research")`，按其原则做正式研究，再回到本技能整理候选。
4. 在已有品类上补充时，用 `category.knowledge.list`、`category.parameters.list` 读现状，只补缺口。
5. 个人新品类候选就绪后调用 `category.create`（T1）；已有品类的补充不调用该工具，须加载对应维护技能并使用当前已实现操作。这会触发一次确认；回执到达前不得说"品类已建好"。

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
3. **每次最多三问**；每问给 2–4 个选项和一条推荐及理由，**推荐不预选**（recommended 只表达建议，不填用户答案）。
4. 用户没回答或说"先不管"的，转为显式假设，继续研究，不强迫先填表。
5. 已回答的不再问；对话恢复时不重开历史问题。
6. 方向够明确就开始研究，不等所有问题都有答案。

**边界与禁止**：
- 不把两个使用场景不同的产品混成一个品类；拿不准就问。
- 用户提到具体客户或 RFQ：告诉用户客户需求应建私有立项提案（客户需求入口），品类候选只保留去掉身份的通用内容；在展示候选的 `de_identification_check` 写明依据；实际确认勾选由人完成。
- 不编造测试标准编号、认证要求或指标数值；法规只列来源可核的条目，其余作为研究问题。
- 不宣称品类已创建、已共享。

**失败时**：研究不到也可交骨架候选，未研究项写 unknown 并列为研究问题；说明覆盖限制由代码附加，不自己解释失败原因。

## 展示候选与 category.create 参数

合同 CategoryCandidate 的信息仍须完整：key、name、purpose、boundary{includes,excludes,split_from}、segments、scenarios、regions、research_questions、parameter_skeleton、knowledge_drafts、assumptions。用 result_json 的 candidate 展示这些内容；research{ledger_ref,coverage,failures} 由服务器据真实研究台账附加，模型不生成覆盖或失败事实。不把 snapshot_digests 等服务器证明字段当作模型政策事实。

实际 `category.create` 参数只有 `key,name,purpose,groups`，其中 groups 只有 `knowledge,parameters,snapshot_refs` 三组。不存在自动把展示候选转换为保存参数的隐式步骤，调用时须显式按以下 DTO 映射，并保证展示与保存同义：

| 展示内容 | 实际保存映射 |
|---|---|
| 边界、含/不含、分开的依据 | knowledge 的 kind=boundary，content 必填 definition，可填 includes/excludes；split_from 的对象与理由保留在 edge_cases 或 classification_rule，不传未知字段 |
| 用户群、场景、地区 | kind=segment，content 必填 segment，场景/使用路径写 jtbd，地区写 regions；外层 regions 保留适用地区 |
| 竞品 | kind=competitor，content 必填 brand/model，metrics/features/prices 按当前 DTO；不得用通用 title/body 替代 |
| 用户声音 | kind=voice，content 为 label/source_platform/representative_refs；样本量由服务器从引用回填 |
| 法规 | kind=regulation，content 必填 instrument/region/source_state/applicability_state/compliance_state/requirement_kind，保持来源、适用和合规状态分开；无可核来源转研究问题 |
| 研究问题与显式假设 | kind=research_question，content 为 question/assumption。assumption 保留 statement/basis/validation/related（边界、地区或参数 key），不得只放展示层而丢失保存信息 |
| 字典骨架 | parameters 每项 key/name/value_type/direction/change_note 必填；enum_values/unit/standard_condition/method/acceptance_criterion 按 DTO。未知工况、方法、判据用 null；需专家核对的事项另存 research_question，不传 expert_pending |

每条 knowledge 外层为 `{kind,content,regions,source_refs}`。来源按实际 Reference 的 type/id/version/line/quote；公开快照的 quote 必须来自实际读过的页和定位，无法证实的竞品、声音、法规转为 research_question，不造知识来源。建议 6–8 条骨架参数与有来源知识，来源不足时少于目标并说明缺口，不凑数。

snapshot_refs 每项只有 `{call_id,content_hash}`：call_id 必须是服务器回传的本 Run 实际 research 子任务 `research.read` 调用 UUID；不是 snapshot_id、fanout 的 execution_ref.call_id、模型调用 ID 或 job_id。使用服务器已核对的 read refs；回传未提供合法子读引用时，该快照组及依赖它的知识尚不可保存，转为研究问题并记录未完成，不能猜 ID。主循环始终不调用 research.read、不读取网页正文。覆盖、读取、失败来自真实 fanout 台账，不能因尚无可保存引用就宣称没有做过研究。

T1 调用只生成候选并等待人工采用。preview 每个可选组只能保留原组全部内容或置空；key/name/purpose 及所选组不就地改写，修改须重新生成候选。去除快照组后，依赖该组的知识不能继续选取。服务器生成 run/event/digest/确认凭据，模型不得填写。确认框由人勾选共享内容已去除客户身份，回执到达前只说候选待确认。

### 无来源骨架调用示例（纯示意）

```json category.create
{"key":"bicycle-pump","name":"自行车打气筒","purpose":"为自行车轮胎补气","groups":{"knowledge":[{"kind":"boundary","content":{"definition":"自行车轮胎补气工具","includes":["自行车"],"excludes":["汽车轮胎"],"edge_cases":["与汽车充气泵分开：气嘴和工况不同"]},"regions":[],"source_refs":[]},{"kind":"segment","content":{"segment":"骑行者","jtbd":["出行前补气"],"regions":[]},"source_refs":[]},{"kind":"research_question","content":{"question":"目标市场和测试工况待核对","assumption":{"statement":"先研究日常骑行场景","basis":"用户未说明使用频率","validation":"研究后回看使用频率与工况","related":"boundary"}},"source_refs":[]}],"parameters":[{"key":"max-pressure","name":"最大压力","value_type":"number","unit":"bar","direction":"higher","standard_condition":null,"method":null,"acceptance_criterion":null,"change_note":"新建骨架，待核对工况和判据"}],"snapshot_refs":[]}}
```

**回复要求**：澄清时 summary 简述为什么问，问题只放 questions；研究时通过 skill.load 加载 public_research 并执行实际工具，不用 stage=research 冒充动作；候选就绪时 summary 依次概括边界、假设、主要发现与下一步，长条目放 candidate 展示信息，保存调用使用上述 groups。

**澄清示例**：用户说“我想做充气泵”，先只问用途；地区暂列显式假设，等用途明确后研究。

```json wire
{"status":"needs_input","summary":"用途会改变品类边界和测试工况。","result_json":"{\"assumptions\":[{\"statement\":\"目标地区尚未明确\",\"basis\":\"用户未说明\",\"validation\":\"用途明确后回看\",\"related\":\"regions\"}]}","questions":[{"id":"use","question":"主要给什么充气？","why":"决定品类边界与测试工况","options":[{"value":"car","label":"汽车轮胎"},{"value":"bike","label":"自行车轮胎"}],"recommended":{"value":"car","reason":"若目的是车载补气，可先研究这个场景"},"allow_free_text":true,"depends_on":[]}],"unfinished":[]}
```
