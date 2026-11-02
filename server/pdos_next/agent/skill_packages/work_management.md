---
key: work_management
version: 0.1.1-draft
purpose: 按真实项目和原件起草任务、计划、阶段办理与外部等待，协助本人分派/承接/提交/验收与逐接收者承诺履行，起草具名状态摘要及风险跟进；不代替实际人员承接、承诺、验收或批准。
input_schema:
  type: object
  required:
  - instruction
  properties:
    instruction:
      type: string
    project_ref:
      type:
      - object
      - 'null'
      description: 页面/用户/服务器项目上下文提供的精确项目 id 与版本
    task_ref:
      type:
      - object
      - 'null'
      description: 当前任务 id/revision；不可从历史猜当前版
    commitment_ref:
      type:
      - object
      - 'null'
      description: 精确承诺 id/revision 与接收者，不能跨接收者合并
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
  description: Finite native grammar; business candidate JSON is checked by its domain schema.
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
context_schema:
  $ref: context-schemas.json#/profiles/project
context_requirements:
- 服务器绑定的当前品类、型号、项目和本人范围
- 原件逐行引用或精确 G0 待决项及决定 id
- 当前任务/承诺/提交/计划候选的精确版本与实际责任人
- 结果键、必需性、接收者、未知日期与时区，缺项保持未知
allowed_operations:
- tool: conversation.history
  tier: READ
- tool: evidence.search
  tier: READ
- tool: skill.load
  tier: READ
- tool: work.task.create
  tier: T0
  note: 原件或精确 G0 待决来源明确时起草有目标与成果要求的任务；不以聊天意向冒充原件
- tool: work.task.assign
  tier: T1
  note: 对当前任务明确受派人和成果接收人；分派不等于本人承接
- tool: work.task.accept
  tier: T1
  note: 仅由真实受派人一次确认承接当前任务；不产生日期承诺
- tool: work.task.start
  tier: T1
  note: 本人登记真实开始时点与 IANA 时区；不以安排日期补造实际
- tool: work.task.submit
  tier: T1
  note: 本人按结果键逐项提交实际成果及来源；partial/missing 不改成 present
- tool: work.task.review
  tier: T1
  note: 指定成果接收人逐项验收或退回；验收不是独立承诺履行
- tool: work.commitment.accept
  tier: T1
  note: 承诺人本人对具体接收者和成果范围作出或续版承诺；未知日期保留 null
- tool: work.commitment.review
  tier: T1
  note: 原接收者核对当前承诺、任务与真实提交；全部已承诺成果接收才履行
- tool: work.status_update.create
  tier: T1
  note: 具名项目状态摘要与下一步；仅引用固定任务，不改变任务或计划
- tool: work.plan.propose
  tier: T0
  note: 根据明确项目版本与实际 schedule 结构准备计划候选；未知估时保留未知
- tool: work.plan.apply
  tier: T1
  note: 本人一次确认应用已准备的精确计划候选；不替代批准基线
- tool: work.stage.adopt
  tier: T1
  note: 按当前项目和阶段模板准备启用候选，保留本人一次确认
- tool: work.stage.milestone.bind
  tier: T1
  note: 按实际阶段与里程碑固定版本准备绑定候选，保留本人一次确认
- tool: work.stage.review.submit
  tier: T1
  note: 按当前阶段和实际评审材料准备提交候选，不生成评审结论
- tool: work.stage.decide
  tier: T2-prepare-only
  note: 仅准备阶段决定材料，由有权本人具名决定；AI 不执行决定
- tool: work.baseline.approve
  tier: T2-prepare-only
  note: 仅准备固定计划基线的批准材料，由有权本人具名批准；AI 不执行批准
- tool: work.external_wait.record
  tier: T0
  note: 按原件登记外部等待的建立、发起、送达、回复、关闭或责任移交事实；未知送达不启动有效等待
- tool: work.risk.followup.record
  tier: T1
  note: 具名人按精确 G0 风险和当前跟进版本关闭或重开跟进；不改写原 G0 决定
evidence_policy: 任务必须消费已登记原件或精确 G0 待决项；成果 present 必须有该项原件来源。模型不提供权限、人员职责、当前状态或业务回执事实。本人承接/承诺与接收者验收沿受控 T1，一次确认后由真实人员保存；T0
  仍须当前启用、资格和授权。
failure_policy: 当前版本/本人身份/成果来源不明，只澄清缺项并继续已授权只读工作。失败或响应未知保留原 command/idempotency key，经实际回执核对后恢复，不新建第二任务/承诺。未实现的任务/承诺领域读取不可由
  evidence.search 或 conversation.history 冒充。
budget:
  status: 建议值，待真实模型评测
  model_turns: 8
  tool_calls: 20
  tokens: 约 40k
model_capability_requirements:
- native_tool_calling
- json_schema_output
evaluation_suite:
  rubric: evaluation-rubric.md#work_management
  case_types:
  - G0任务到逐项成果验收
  - 未知日期与多接收者独立承诺
  - 部分退回与重交
  - 已完成任务但承诺未履行
  - 等待未知送达与责任移交
  - 原请求恢复与失权
  min_cases: 10
owner: 待定
preload_when:
- 用户要求安排项目任务、登记实际进展或作出承诺
- 项目工作、我的工作或外部等待现场要求小Pai协助
---

# work_management · 项目行动与个人承诺

## 工具与办理次序

1. 固定服务器给定项目；任务、承诺与提交都使用当前 id/revision，人员只用明确身份。不从项目 owner 推断成果接收人或专业职责。
2. `work.task.create`（T0）只起草有目标、结果键、required 标记及原件的任务；G0 接续用精确 `g0_open_item={id,decision_id}`。计划引用是固定 `plan_task`，不因此修改计划。
3. `work.task.assign` → `work.task.accept`（T1）：明确 assignee_id/recipient_id，受派人本人接受。assigned 不等于 accepted；accepted 不等于作出日期承诺。
4. `work.task.start` → `work.task.submit` → `work.task.review`（T1）：真实开始、成果提交、指定接收者验收分别留事实。submitted 不等于 completed；退回理由与逐项结果保留，任务回到进行中。
5. `work.commitment.accept`（T1）按本人 × 任务 × 接收者保存 outcome_keys 与 promised_at；不知道日期传 null，original_timezone 用真实 IANA 时区，calendar_id 不知道传 null。续版 replaces 精确替代本人同接收者当前版本，不能改写旧承诺。
6. `work.commitment.review`（T1）仅原接收者本人办理：绑定当前 commitment/task、真实 submission 及 expected_review_revision；checks 覆盖全部已承诺成果（含可选成果）。任务完成不自动履行承诺，承诺履行也不要求整个任务先完成。
7. `work.status_update.create`（T1）提供 fact_summary、next_steps 和明确 task_refs；不改任务、预测、实际、承诺或批准，不自动建新任务。
8. `work.plan.propose`（T0）使用注册 schema 的 schedule 与 expected_project_revision；`work.plan.apply`（T1）消费精确 proposal_id。不捏造计划估时、批准基线或 Forecast；需制造/测试动作时加载 build_execution/test_verification。
9. `work.external_wait.record`（T0）使用 record.action 区分 create/details/initiate/delivery/commitment/reply/close/reopen/transfer_request/transfer_accept/transfer_cancel；create 之外必须给当前 wait 引用。发起、有效送达、对方承诺、部分回复与关闭分开，送达未知不宣称等待已有效开始；内部记录不发送消息或客户资料。
10. `work.risk.followup.record`（T1）使用 risk={id,decision_id}、current、action=close/reopen 与来源；只保存具名跟进，不改 G0 风险原文或代替专业关闭。

## 事实与人员边界

- 项目、品类、成员和 Run 范围由服务器绑定；payload 中的 project_id 不是授权事实。
- T0 工具声明不授予启用或资格；技能包变更后按原政策重新审阅。自动化运行不因此取得业务写权限。
- T1 只预填供实际本人确认。AI 不冒充受派人、承诺人、成果接收者或风险办理人；其他人尚未确认时如实说明等待本人。
- 工具返回的当前回执才是已保存依据。一个任务对不同接收者的承诺与履行分别保留，不按任务 completed 推定 fulfilled。
- 无任务/承诺领域读取工具；`conversation.history` 仅供续接，`evidence.search` 仅找来源。页面未提供当前对象或工具返回版本已变化时，不猜版本或连续盲写。
- 外部等待的 source_claim 与实际送达事实分开；模型不会把聊天转述升格为实际送达、承诺或回复。
- 此包不授予具名基线批准、变更关闭、CAPA有效性、正式发布或真实外发。

## 可执行参数示例

下例 ID 仅为参数结构示意；调用前必须替换成当前 Run 可访问的真实项目与逐字原件引用。工具只收领域 payload，不手写 confirmation_token/approval_token 或权限字段。原件 position 必须为 `line:行号;quote_sha256:整行UTF-8的SHA-256`，不能省略哈希或用片段哈希。下例原件第1行为“请整理噪声复验原件并交付可核对报告。”，实际调用必须使用真实整行的哈希。

```json work.task.create
{"project_id":"11111111-1111-4111-8111-111111111111","title":"整理噪声复验原件","goal":"为接收者提供可核对的实际原件","outcomes":[{"key":"report","text":"实际噪声复验报告及定位","required":true}],"sources":[{"id":"22222222-2222-4222-8222-222222222222","revision":1,"kind":"artifact","position":"line:1;quote_sha256:0c602a12abe12fdfc2c1e4f2bd5a3bee85b78b02c6748d922d5a3cd04a471d17"}],"reason":"按已登记原件起草具体行动","plan_task":null,"g0_open_item":null}
```

输出使用原生 status/summary/result_json/questions。result_json 可包含 bound_objects、prepared、saved_receipts、unknowns 与 blocking；saved_receipts 只列实际工具回执。缺信息用 needs_input 且每轮最多三问，推荐答案不预选；已有回答不重复问。
