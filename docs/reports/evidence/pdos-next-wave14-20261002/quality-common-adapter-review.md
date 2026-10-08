# Wave15 共同命令适配审查

状态：实施前只读接线建议。仅写本文；未修改 Wave14、两个纯领域包、公共注册或清单，未连接数据库、运行 pytest 或启动公共验证。本文不宣布 Wave14 通过，不授专业/AI/生产资格。

范围依据：[Wave15 草稿](../../../design/2026-10-02-pdos-next-wave15-quality-loop-draft.md)、[复用审阅](quality-reuse-review.md)。首切片为 **确定 fail → 原 Issue 或新 Issue → 分诊/CAPA 草稿 → ChangeRequest/双线影响 UNKNOWN**；不新增 indeterminate Issue，不办理根因结论、措施完成、有效性、关闭、变更批准/实施/生效。

## 唯一事务路径

共同 [service.execute](../../../../pdos-next/server/pdos_next/service.py:462) 已拥有 Product 锁、当前授权/运行资格、原件来源门禁、RequestKey/语义回执去重、T1/T2 消费、`module.apply`、Receipt/Audit/Outbox 和请求别名。新宿主模块保持现有接口：

```text
semantic(payload) -> 普通 JSON（去除 confirmation_token/approval_token）
validate(s, ctx, command, product, payload) -> None
preview_view(s, ctx, command, product, payload) -> 固定 before/after/read_basis/effect
apply(s, ctx, command, product, payload) -> (实际持久版本 ORM, subject_type, visibility)
replay_subject(...)/replay_subject_type(payload) -> 原实际版本 ORM/类型，或 None
```

`validate` 在两层共同去重之前执行：当前人、职责资格、固定来源/原件及受众必须再核；**只在新写阶段 CAS**，不能先因旧聚合版本落后而拒绝已经成功的原意图。`command.expected_revision` 是 Product 版本，Issue/Change 的期望领域版本另置 wrapper payload，不混用。T0 人工合法职责办理直接 execute，不增加 preview/token；T1 仅共同 preview 返回一次 prepared command。

## 纯端口到共同入口的具体映射

质量包 [ports.py](../../../../pdos-next/server/pdos_next/domain/quality_issues/ports.py:88) 将 Session 存在适配器实例；变更包 [ports.py](../../../../pdos-next/server/pdos_next/domain/change_control/ports.py:88) 显式传 `uow`。二者均绑定 **同一个** `s/ctx/product/command`，不另建连接、事务或 HTTP 信封。

| 纯入口/端口 | 宿主实现与调用位置 |
|---|---|
| `commands.context(...)` | readonly inputs/preview/read 使用当前服务端绑定的 Scope、actor、purpose、目标 audience、角色和资格。读权限不要求写资格；办理的 `qualified` 只映射 `assessment.qualified is True`，null 不转 true。 |
| `commands.begin(invocation)` / `begin(s, invocation)` | 仅核对 Invocation 与已绑定 common Command 的 operation/command_id/逻辑目标/领域前版/领域载荷摘要，锁领域 Current/稳定失败身份并重新取 Authority；不消费证明、不另建 RequestKey、不 begin/commit。Product 已由共同入口先锁。 |
| `commands.replay(...)` | 共同入口已处理 same-key 与相同 semantic intent。新 `apply` 的适配器可返回 None；如另查领域 Action，只认精确历史意图，先重核旧来源/权限并须存在共同 Receipt，不能以“载荷看起来相似”重用。pure Outcome 并非回执，不能直接返回给 HTTP。 |
| `commands.issue/by_failure`；`commands.request` | 读取精确不可变 Issue/Change DTO 与真实 Current；先 scope/audience/ACL，再核固定来源。failure map 唯一键至少包含完整 Scope 和 `FailureRef.identity`，resolve 归并别名；锁排序保持 Product → 稳定身份/Current（归并多个 ID 稳定排序）。 |
| `commands.confirm(...)` | 只断言 **module.apply 内部**构造的 `accepted_confirmation=True`、相同已绑定 operation/actor/payload/readset；T2 还绑定真实已消费 Confirmation 行 ID 为 `decision_id`。不 mint/consume 第二个 token，不从客户端 bool 授权。common [consume_material_confirmation](../../../../pdos-next/server/pdos_next/service.py:442) 已消费且与后续 staging 同事务，失败整体回滚。preview 模式从不构造这一已接受写适配器。 |
| `commands.record(invocation, mutation)` | 校验 Mutation、领域前版、insert-only ID、完整来源/资格；同 Session 插入不可变版本/历史、更新 Current CAS、failure/event 映射。保存本次实际版本行到 `saved_subject`，返回纯 `Outcome(subject_id=逻辑ID, revision, status)` 给 handler；**不写 Receipt/Audit/Outbox、Confirmation 或 commit**。Mutation.event_name 是待与共同注册核对的建议，不私自发布。 |
| `module.apply` 返回 | 调用 `QualityIssueHandler.execute(invocation, domain_payload)` 或 `ChangeControlHandler.execute(s, invocation, domain_payload)` 后取 `saved_subject`；返回其 **版本行 UUID**、确定 subject_type、真实可用 audience 对应 visibility。common [append_receipt](../../../../pdos-next/server/pdos_next/service.py:187) 要求行具有 `id/revision/status`；不要把 Outcome 的逻辑 ID 或 CAPA ID 当版本行 ID。 |

建议 receipt family 首先冻结为 `quality_issue` 与 `change_request`，CAPA 随 Issue 聚合版本保存：`quality.capa.draft` 也返回新 Issue 版本，并可在 `subject.action_result` 附 `{issue_id,capa_id}`。这是建议注册名，当前公共代码尚未注册，不当作已上线合同。

完整质量 Mutation 可能含多条 changes/before/insert_ids/deliveries；宿主必须全部 CAS/保存，不能只保存第一条。变更 Mutation 的 change/expected_revision/insert/new_fact_ids 同理。纯语义摘要各自使用 [quality.semantic_digest](../../../../pdos-next/server/pdos_next/domain/quality_issues/rules.py:20) 与 [change.digest](../../../../pdos-next/server/pdos_next/domain/change_control/rules.py:68) 对**剥离宿主字段后的领域 DTO**计算；共同 semantic 仍包含固定领域目标/前版/Run/事件/源版本，避免 token 或 wrapper 字段污染纯摘要。

## 预览、去重和事件的两个接缝

1. 两个公开 `handler.preview` 只返回 Preview；`execute` 才把 Mutation 交给 record。实质 before/after 可以在宿主的小适配函数调用既有 `_prepare`：质量 `_prepare(authority, invocation, parsed_payload)` 返回 `(Preview, Mutation)`；变更 `_prepare(s, authority, operation, subject_id, revision, parsed_payload, decision_id)` 返回 `(Preview, (request, insert, new_ids, event))`。这次只计算 DTO，不 record，不写表。明确把这一私有调用收束为一处、加边界回归即可避免复制状态机/改纯包；若以后需要公共 `prepare` 扩展，另行分配指定纯文件。
2. [quality create](../../../../pdos-next/server/pdos_next/domain/quality_issues/handlers.py:236) 对同失败会保留原标题/配置，仍可能新增 `(event_id,failure_identity)` Delivery；旧依据漂移还会产生 recheck 续版。不能只凭 failure identity 在共同 `replay_subject` 提前返回，漏掉新事件映射。精确相同意图可共同早期重放；不同 title/event 的稳定失败归并应在 record 后返回原 Issue，并按原版本回执别名处理。源事件→失败映射独立唯一，一个事件可以有多个失败；具名手选入口不冒充 Inbox 的自动消费授权。

共同 Outbox 当前由 `EVENTS[operation]` 静态产生，而质量 Mutation.event_name 可为 `None` 或 `issue.recheck_required`。首切片须主线明确语义：无变化重复失败返回原回执，不再发 `issue.created`；对已有失败依据漂移明确 `RECHECK_REQUIRED`，不借 create 隐式续版/假发布创建事件。若以后接纯核自动 recheck 分支，公共事件选择/辅助注册须显式扩展，不能让领域适配器自写第二套 Outbox。CAS、Delivery 和别名失败均同调用者事务回滚。

预览绑定纯 Preview.digest 加宿主完整固定 read_basis（原件/安全 epoch、专业 issuer/fact/current 指针、政策版本、事件/Run/Measurement/Projection、聚合前版/受众）。拟提交 History.at、named conclusion 时间和服务器生成新版本行 UUID 使用明确 `server_on_save`/null；只排这些提交生成字段，不能删政策或事实摘要。actual containment 的 EventTime 是已发生证据，必须完整绑定。不要把 authority.now 或即时 checked_at 放进确认摘要造成每次 execute 漂移。

## 实际来源与专业刷新位置

| 所需端口 | 首切片真实绑定 |
|---|---|
| `RunPort.fixed/original/currentness/delivery` | 沿精确 Outbox → Receipt → RunVersion（compute 事件再沿 Projection.run_version_id）确定原 Run/Measurement；scope/op/事件归属服务器核实。重验保存 Start/使用证明、原 JSONL bytes/位置、Measurement 与 Projection basis/规则，调用 [failure_ref](../../../../pdos-next/server/pdos_next/domain/quality_issues/rules.py:28) 得到确定 fail。`fixed(run_id)` 无 revision 参数，故适配器 closure 必须绑定 wrapper 指定并经事件验证的版本，不能临时取 latest；`original(Ref)` 严格按归档领域 revision 回读。 |
| `EvidencePort.check/currentness` 与变更 `FactPort.source/ref/audience` | 复用 current source_for/OriginalSecurity/精确 hash/来源位置和完整读集；object history 可读不等于当前可用于新写。private 来源不扩大 product 受众，tenant/product/project/config/item 均绑定原对象；新 graph/root/需求不得由客户端给 complete/nature。 |
| `PolicyPort.assess` | 当前可信风险/独立政策版本及出处，不能默认 low。CAPA 草稿前要求已 triaged；可不作 root-cause T2。未提供政策就明确 INTEGRATION_REQUIRED，不写出假风险。 |
| `FactPort.graph` | 服务端保存固定 GraphSnapshot，合法少量真实节点/出处边与逐 facet incomplete/unknown 已可复用 [compute_impact](../../../../pdos-next/server/pdos_next/domain/change_control/rules.py:108)。缺正式治具/试产、库存/WIP/培训路径保持 UNKNOWN；完整遍历已读取子图不等于完整业务范围。CAPA 是 Issue 内嵌事实，变更引用绑定 Issue 版本与真实 CAPA key，不造独立版本。 |

每个 validate/preview/apply/replay phase 在**全部原件 bytes I/O 和图/政策读取之后**重新核当前办理 authority（roles/qualified/facts_revision/issuer/runtime epoch）及 retained 原执行/source_basis/事实摘要，再 staging；Product 锁不会阻止内存 issuer/profile 撤销。沿用 Wave14 [_refresh_phase_proofs](../../../../pdos-next/server/pdos_next/domain/verification_results/service.py:658) 的边界：自然执行窗口结束与动态 checked_at 分开，撤回/ACL/安全/消费 epoch 仍严格比较。不跨 phase/global 缓存肯定资格，不 reserve/release/再次消费原样件。

## 是否需要修改纯包

首切片 **可以不改纯包**：质量包隐式 Session 与变更包显式 uow 是适配器签名差异；两包严格要求完整方法集合，暂未开放的 `verification/selection/implementation/effectivity` 可提供抛 `INTEGRATION_REQUIRED` 的拒绝方法，不能返回合成成功。Change request.create/impact.compute 不调用实施或专业批准政策，因此可保存真实 UNKNOWN；质量分诊/CAPA 会调用真实风险 PolicyPort，不可 stub positive。

两包 replay 宽松程度不同：变更纯 handler 重放仅检查请求访问，ports 注释允许来源漂移后回历史；主线 execute 要求当前源先行。首版采用更严格宿主 validate/replay guard，不需要削弱共同门栓或修改纯包。若将来要在失效来源上“成功办理重放”，那是公共语义变更，不能用纯包注释自行授权。

必须另派主线的内容是窄 `fixed_failure_result` 读取端口、可信风险政策/职责映射、公共 payload/tier/event/subject 注册、不可变版本/指针/唯一映射与来源生命周期门栓；没有现成可直接用的持久 Quality/Change CommandPort。IssueReader 的 followup_need 只表示需求，不自动创建 Change/新 Run。首版 ChangeRequest 明确由人工选择固定 Issue/CAPA 和配置根提出，`UNKNOWN` 不被 generic 确认解除，更不生成 ChangeOrder。

建议集中验收节点：同失败换 key/title/event 与同事件多失败；老意图先当前权限/源核对再去重，末端 Outbox 失败整组回滚及 token 未消费；CAPA scope 精确全失败且 completion 为空；private 受众不扩大；原件读取回调撤销 issuer 后零新增；双线影响保留 UNKNOWN、批准/实施能力未注册。本文仅提出节点，未运行这些检查。
