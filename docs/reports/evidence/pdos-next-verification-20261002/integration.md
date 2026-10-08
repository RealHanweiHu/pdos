# Verification 首版接入合同

本包按完整架构 04.6/04.7、03.3 和 02.7 实现独立领域切片。源码仅在 `domain/verification/`、`schemas/verification/`、`tests/verification/`、`components/verification/`；本目录保存证据。没有注册实体/命令/API/页面，没有连接数据库、调用模型或写实际业务事实。模块当前可被主线调用，实际办理仍须主线适配。没有独立 BOM、Build、SampleUnit 或 ActualConfiguration 所有者。

## 后端入口与事实

- `VerificationHandler(Ports).preview(operation, subject_id, expected_revision, payload)` 返回实质覆盖、缺项、效果和摘要；不调用 `begin/confirm/reserve/record`。
- `execute(Invocation, payload)` 先核对专用载荷和摘要，调用服务器 `begin`，复查范围/角色/资格/来源/版本、消费当前 T1/T2 证明，再交给 `record`。没有 `commit`、SQL、数据库连接或自行授权。
- `semantic_digest(payload)` 规范化精确覆盖集合，用于主线稳定意图绑定。它不代替主线跨命令编号/请求 key 的业务去重。
- `document_gaps` 逐测试项返回资料缺口；`coverage_gaps` 逐项按实际数量/模穴显示未覆盖；`compute_results` 保留原始字符串、Decimal 确定性判据及逐样件/测试项结果。
- `BuildRef` 固定 id/revision/product/project/工程与制造配置 id+revision；`SampleRef` 固定实际单件版本、实际配置版本、Build 与模穴。当前主线 Build 只有 `planned`，不能满足实物操作；缺实际接口须返回 `INTEGRATION_REQUIRED`，不得由 planned_quantity 或计划配置合成 SampleRef。
- 实物动作仅接受主线 Build `executing/evaluating/closed`，并额外复查真实样件。状态本身不是产出或可用性证明。
- Request 与 Run 使用独立执行状态；Run 的 `pass/fail/indeterminate` 是该 Run 固定范围的确定性判定。请求未齐数量/模穴/实际接收覆盖时保持 `executing`，不设整体最终返回。`invalid` 是独立结果维度，首版不自动写无效结论。
- `request_created/sample_ready/documents_complete/offered/accepted/promised_start/actual_start/preliminary_result/final_result/disposed` 各自保留来源。事件含发生时间、UTC 系统接收时间、原 IANA 时区、可选业务生效时间；expected_at 有值时 expected_timezone 必填并保留预期原时区。样件物理就绪与当前可用性分开，消耗不清除历史就绪事实；部分接收另存所选样件就绪与该范围接收时间。
- `Measurement` 的原值不裁剪；单位、工况、设备原标签和固定引用、环境、方法、原文件版本/位置、观测时间及原时区、缺项和补充说明独立保留。缺字段、单位/工况/方法/设备不匹配、非有限读数或只有定性判据均保持不确定，不做隐式单位换算或填值。
- 专业结论与处置为具名 T2，保留 actor/内容/来源/时间；它们不覆盖确定性判定。AI 不能执行。

## 主线需要提供的最小端口

| Port | 必须提供的权威事实和事务条件 |
|---|---|
| `CommandPort.context/begin` | 从当前认证/run 绑定 tenant/product/project、真实 actor kind、当前职责、授权、适用能力/专业资格、取消状态和 aware 系统时间。模型/payload 同名字段不能作为依据。`begin` 进行稳定业务意图锁定；相同持久意图可返回原 Outcome，返回前重验当前受众与授权；同 key 不同载荷冲突。 |
| `CommandPort.request/run/runs` | 按租户/产品/项目读取和锁定领域快照；`runs` 提供该请求全部 Run，聚合仅依据精确实际覆盖，禁止把计划行作为已有测试。多 Run 更新同一请求时先锁父 Request，再以一致顺序锁 Run/样件。 |
| `CommandPort.confirm` | 复用共同 T1 实质预览+一次确认，或独立具名 T2 决定。证明绑定操作、actor/受众/当前范围、目标版本、全部固定来源/样件/配置读集、payload/preview 摘要、有效期和取消标记；执行时重验，原子消费。UI 的 allowed/digest/token 不能自授权限。 |
| `CommandPort.record` | 根据 `Mutation.request_before_revision/run_before_revision` 对双对象作 CAS；0 仅新增，不能 upsert 覆盖现有 ID；未变化快照不能再增版本。所有 next_owner_id 必须解析为当前租户/项目可承接此责任的人员，不能凭提名授予成员关系或权限。同调用者事务写领域/必要 SampleUnit 消耗、ActionReceipt、Audit、Outbox；共同框架负责唯一回执及最终 commit。不得先发业务事件后补事实。 |
| `BuildContextPort.get` | 从共同 Build/configuration 所有者给固定双配置版本与状态，验证 current scope。任何版本漂移要求重新审阅/新请求，不用当前配置填历史。 |
| `EvidencePort.check/verify_measurement` | check 验证精确 source id/revision/kind/position、原件存在、未过期撤回、来源/受众 ACL、租户/项目与操作用途，不依赖客户端的 current/approved 标记。verify_measurement 还须用确定性原件解析或服务器绑定的具名人员/仪器原观察核对原值、单位、工况和观测时间等实际字段；只验证引用存在/哈希不证明数值来自该位置。缺这个接口时不能导入结果；缺项仍原样保留，不能让模型补造。当前命令事件来源由服务器证明；每次提交/审核也重验已存的部分测量原值和来源。 |
| `SampleAvailabilityPort.inspect` | 锁实际 SampleUnit/ActualConfiguration，核对版本、Build、模穴、真实物理 ready_at（可缺）、当前可用/预约/消耗及本次方法适用性。返回不确定则阻断接收/开测；不会创建样件。 |
| `SampleAvailabilityPort.reserve` | 同事务检查真实执行者资格、设备/校准/环境、治具适用/验收、预约冲突；对固定样件做 reservation/破坏性消耗。相同实际单位不得重复破坏；不得在此提交或调用 LLM。异常使全部领域/证明/回执/消耗一起回滚。 |
| `SampleAvailabilityPort.recheck_running` | 结果导入再次核对固定配置、该 Run 的 reservation/consumption、设备约束和范围。已被本 Run 消耗的样件允许返回其已有真实测量，不能给另一个 Run 重用；中途换固件/配置需分段或新请求/新 Run，不覆写旧含义。 |

所有端口绑定同一个主线已开启的命令事务。跨数据库端口、no-op 安全检查和端口自行 commit 均不满足此合同。`Ports()` 默认缺接口会拒绝依赖动作；测试 fake 只用于合成检查。

## 命令适配与注册

本地 `Invocation` 是领域调用 DTO，不是新的 HTTP 信封。主线保持共同 `Command.expected_revision` 对 product 的检查，再从主线专用 wrapper payload 抽取 Request/Run subject 与领域 expected_revision，构造本地 Invocation；客户端不能传 Authority/Scope。创建 Request 使用自身 id、expected_revision=0；创建 Run 的 subject 为父 Request，Run 的 `before=0` 单独传入 Mutation。输入 schema 均 `extra=forbid`。

| 本地操作 | Payload | 权限性质 / 事件 |
|---|---|---|
| `verification.request.create` | RequestCreate | T0；当前工程/品质职责与资格；verification.requested |
| `verification.method.prepare` | MethodPrepare | T1 品质本人；verification.method_prepared |
| `verification.schedule.propose` | ScheduleProposal | T0 当前品质资格；verification.schedule_proposed；只暂定 |
| `verification.handoff.offer` | HandoffOffer | T1 工程/生产；handoff.offered |
| `verification.handoff.accept` | HandoffAccept | T1 品质本人；handoff.accepted |
| `verification.handoff.return` | HandoffReturn | T1 品质本人；handoff.returned |
| `verification.schedule.promise` | SchedulePromise | T1 品质本人；verification.start_promised |
| `test.run.plan` | RunPlan | T1 品质本人；test.run_planned |
| `test.run.start` | RunStart | T1 品质/测试本人；test.run_started |
| `test.results.import` | ResultsSubmit | T1 当前品质/测试职责与资格；test.results_imported |
| `test.run.review` | RunReview | T2 品质具名；test.run_reviewed |
| `test.disposition.decide` | RunDisposition | T2 品质具名；test.disposition_decided |

原操作目录以外的 method.prepare/return/promise/run.plan/start/review 为包内拟接入动作，必须由主线登记明确的专用合同和政策后才暴露。`test.result.compute` 首版通过提交命令内的确定性函数完成，没有另开可调用的公共写工具。

先建请求、准备方法/暂定时间，无实际样件也可继续。资料缺失只阻断适用项。Offer 保存具体真实样件与精确 sample/item pairs；Accept 可只接收独立齐备范围，必须为部分范围填写原因及下一责任人。退回范围与已接收范围不得重叠。交接后 `MethodPrepare` 只能补未接收项；已接收方法和适用资料不能重写，测试项身份集合不变。承诺时间不自动改暂定时间或实际开始。

RunPlan 仅消费实际接收 pairs；start 按该 Run 各 Coverage 的接收时间校验，不能用另一个范围的更早接收时间代替。结果可分批返回；已记录 pair 原值不被覆盖。每次部分返回保存 returned_coverage、服务器计算的 pending_coverage、来源时间及可选成对的 incomplete_reason/next_owner_id；这是未完责任记录，不凭输入创建Task或分派权限。若全部测量已作为部分结果返回，最终提交允许空 measurements，仅确认真实 actual_end 与最终返回时间/来源，不能暗中新增未完责任。最终未知仍是 `indeterminate`。主线会通过固定原件导入器提供源测量，首版未接原 xlsx/OCR 导入。

## 前端映射与接线

`components/verification/` 提供独立 typed props/callback 组件；仅消费主线真实读模型。上下文 version 要在 ACL/来源/范围/样件变化时改变，`portReady=false` 禁止接收/开测。`onPreview` 调主线受控预览，返回真实 token/digest/expiry/完整 scope；`onConfirm` 只消费该 preview，成功以共同事务提交后的实际 receipt 为准；结果未知要读原意图回执，不重发写操作。编辑或 props/上下文漂移使旧 preview 失效。

UI `Coverage.pairs` 必须映射为后端 `(sample_id,item_id)`，不能用 sampleIds×testItemIds 补成全覆盖。VersionRef 映射固定 id/revision。SourcePosition 的 `originalId/revision/kind/locator` 映射 SourceRef 的 id/revision/kind/position；kind 不在 artifact/domain/command 时拒绝。展示标题、样件标签、设备名称不是授权或来源证明。

Measurement 的 method 需由主线解析到固定 TestMethod.source，不能编造 locator。设备原文字保存在 `equipment_label`，服务器无法解析真实设备来源时置 `equipment=None` 并保留缺项。observedAt/originalTimezone 映射 observed_at/observed_timezone，空项用 None；note 保留原补充说明。ResultsIntent.incompleteReason/nextOwnerId 在部分结果中映射 incomplete_reason/next_owner_id，未填写用 None，final 两者均 None；未完成范围由服务器按精确pairs计算，不信任UI提交的 incompleteTestItemIds。actualEnd/returnedAt/handoff time 需真实 EventTime；不得用收到请求的系统时间补造先前真实事件。

回调需从本地 action 映射上述完整操作名，补充主线受控 Request/Run ID 和版本。当前退项表单将本次范围共用的原因/下一责任人明确展示，可无损映射一个 HandoffReturn/HandoffAccept；不同原因/责任须分范围办理，不能压成一个未审阅批次。原请求数量/模穴仍缺但无已有实物可退时，仅记录原因/责任和缺量，不创建假的退样件 pair。T2 专业结论/处置由主线具名办理入口提供，组件不代签。

## 主线持久化需求及集中病例

主线负责模型注册/单调迁移：VerificationRequest（scope/固定Build/方法及资料版本/预期和返回形式）、精确交接 Coverage、Acceptance/ReturnedScope（具名身份/原因/下一责任人/各来源时间）、TestRun（固定方法/实际样件配置/执行状态与结果）、Measurement（原值与元数据/来源/缺项）、具名专业结论/处置。建立 scoped FK、唯一身份、合法状态/版本约束、Measurement(run,sample,item) 与 stable intent 唯一约束；纠正原始读数应保留原版/新的纠正事件，不能覆盖。SampleUnit/ActualConfiguration 和 reservation/消耗继续由主线事实所有者维护。

联合检查至少包括：

1. 同意图不同命令编号/重试只落一套事实和回执；不同载荷相同key冲突；已有 Request/Run ID 的 insert-only 拒绝。
2. 两个 Run 同时更新父 Request 的开始/部分/最终时间；CAS/父锁不丢更新。全请求结果聚合必须同事务读完整 sibling Run。
3. 两个破坏性 Run 同时抢同一实际样件；撤销/资源冲突/record失败使样件消耗、确认凭据、事实、审计、Outbox全回滚。
4. Preview 后撤权、取消、来源撤回、Build/实际配置漂移、过期 token 或 T2内容改变；零越权业务写。
5. Request 全数量/模穴范围不齐时，局部 Run final pass 仍只显示局部通过；晚到报告发生/接收/生效时间独立；部分来源被撤回后禁止新有效判定。
6. 合法主线HTTP与实际浏览器办理、亮暗/窄宽/键盘、未知回执恢复、迁移往返及 schema 相容。纯 fake 不证明这些通过。

## 明确保留范围

尚未提供真实持久模型、共同命令/API/路由/BFF、ActualConfiguration/SampleUnit/资源 adapter、正式角色/设备资格和真实材料。未运行数据库、迁移、HTTP/浏览器、共享构建或实际业务整链，不勾 G/N/P/Q，不宣称真实资格或人工 Exit。

首版 Offer 为一次固定样件范围；后续新增实物、扩展交接覆盖、改已接收方法/配置要新请求/新 Run，或由主线增加明确的版本化补交动作。独立 TestPlan 实体、分段测试、新读数纠正/多次测量、自动失败 Issue/CAPA、批量原报告解析/附件上传、资源求解和部分请求整体具名关闭留给后续主线。已有历史测量与决定不被这些缺口抹除。

没有抽取旧工程算法或导入旧 app；复用的是新工程 Button/语义主题，以及独立包的状态/端口方式。消费文件版本见 consumption-initial.json 与候选消费复核；本地DTO没有依赖正在施工的 Build 实现冻结。
