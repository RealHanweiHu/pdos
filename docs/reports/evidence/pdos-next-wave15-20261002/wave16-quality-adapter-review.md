# Wave16 品质后续适配审查

状态：2026-10-02 实施前只读审查；仅新增本文，未施工、未授专业/AI/生产资格，未运行数据库、HTTP、pytest 或浏览器。Wave15 的在途验证及完成状态由主线管理，本文不宣布该波通过，也不改变其冻结 runtime。

依据：[Wave16 草案](../../../design/2026-10-02-pdos-next-wave16-quality-followup-draft.md)、[Wave15 冻结合同](../../../design/2026-10-02-pdos-next-wave15-quality-loop-implementation-contract.md)、[目标架构](../../../design/2026-10-02-pdos-complete-target-architecture-v1.md)中的根因假设/专业结论分界与“新 Run → 独立验证”序列。建议下一切片交付 **具名根因决定 → 本人实际措施完成 → 所有者创建新复验分支 → 固定输出回链及可重核复验候选**；有效性决定、关闭、正式 ChangeOrder 实施仍不开放。

## 可直接复用与必须新增的接缝

| 资产 | 已有真实规则/DTO | 新宿主必须补齐 |
|---|---|---|
| [quality DTO](../../../../pdos-next/server/pdos_next/schemas/quality_issues/contracts.py:73) | `RootCauseDecide{text,sources}`、`NamedConclusion`；`ActionsComplete{completions}`、`Containment{id,text,executor_id,evidence,at:EventTime}`；CAPA/action/失败身份均已固定 | 根因 wrapper 加 `issue_id/expected_issue_revision/approval_token`；完成 wrapper 加同一领域目标及 `confirmation_token`。actor、决定钟、接收钟、角色、nature 由服务器产生，不接客户端可信字段 |
| [QualityIssueHandler](../../../../pdos-next/server/pdos_next/domain/quality_issues/handlers.py:375) | 根因仅 actioning、已有结论不可覆盖；完成对应原 action、执行者相等且本人、不能重复；部分完成仍 actioning，全部完成进入 awaiting_verification | 直接调用原 handler，不复制状态机。记录真实完成不强加“必须先根因”的新规则；有效性原核另要求根因。根因更正/追加措施没有现成动作，不能通过再次 draft 或 patch JSON 绕过 |
| [独立性/观察期核](../../../../pdos-next/server/pdos_next/domain/quality_issues/handlers.py:127) | 全部措施完成、完整失败覆盖、观察窗、禁止原失败 Run、同 nature、独立参与者排除、effective/ineffective/unknown 分路 | `PolicyPort.verification` 所需新证据尚未接入。先保存候选/缺项，保持有效性及关闭 caps=false；新 Run review/disposition 不等于 CAPA effective |
| [质量端口](../../../../pdos-next/server/pdos_next/domain/quality_issues/ports.py:105) | CommandPort 的 begin/replay/confirm/record，RunPort 原失败 currentness，EvidencePort 来源，`VerificationEvidence` typed DTO | 新 adapter 绑定同 Session、common Command 与固定 Issue，不新建 Receipt、Confirmation、连接或 commit。当前 [TransactionCommands.confirm](../../../../pdos-next/server/pdos_next/domain/quality_execution/adapters.py:48) 只接受 Wave15 三个 T1，不能原样用它假装已支持新 T1/T2 |
| [持久 Issue](../../../../pdos-next/server/pdos_next/domain/quality_execution/models.py:35) | 不可变 `QualityIssueVersion` + 唯一 Current/CAS；CAPA 内嵌于同一 Issue | 不新增 CAPA/IssueCurrent 真值。现 CHECK 仅 open/triaged/actioning、五个 Wave15 operation，主线须显式迁移加入 awaiting_verification 与两个后续 operation；不能只加 payload 即写库 |
| [原失败桥](../../../../pdos-next/server/pdos_next/quality_result_bridge.py:117)、[质量 source](../../../../pdos-next/server/pdos_next/domain/quality_execution/evidence.py:34) | 固定事件/RunVersion/Measurement/Projection/规则、报告 bytes、retained 原执行、native 登记来源与上传原件两类 basis、安全 epoch/ACL | 回链/复验 bridge 对新 Run 聚合真实范围，重新证明测试项/实际方法/判据对 CAPA 要求适用。原失败桥不能直接返回新验证证据，单条 pass 或同 requirement_digest 都不足以证明全覆盖 |
| [Formal owner 保存](../../../../pdos-next/server/pdos_next/domain/verification_front/service.py:743)、[RunIdentity](../../../../pdos-next/server/pdos_next/domain/verification_launch/models.py:43) | 请求由当前合法 owner 创建；每 request 最多一个逻辑 Run；原子开测占用、样件使用和后续原值/复核链 | 新复验必须新请求/新 Run，由该真实 owner 按既有命令创建；质量包只能提出需求与回链。不能代填 owner、伪造其回执、复用原失败 Run 或重复使用破坏性已消费样件 |

当前源码未定义名为 `IndependentVerificationRequest` 或 `RemediationLink` 的 DTO/持久服务；这些是下一波待冻结对象，不能把 Wave15 `followup_needs.created_output=None` 当已创建请求。

## 建议最小端口合同

以下是派工建议，尚非可调用 runtime 协议。B 先冻结 typed binding，A/C 按同一版本接线。

1. `FollowupBasis`：完整 scope/purpose/audience/nature；固定 Issue 版本行 + logical ID/聚合 revision；CAPA/action key、requirement 摘要、原失败 identity 集及精确 FailureRef；根因、完成和所引用输出的内容摘要。公开请求只指定固定引用/理由，服务器核 scope、当前性和最窄受众。
2. `IndependentVerificationRequest` 若保留这个名称，只表示受控复验需求：固定上述 basis、期望方法/判据/观察期与明确待办责任人。未取得真实 owner 创建回执前，`created_request`/`created_run` 必须 null。它不能代替既有 FormalVerificationRequest、另持 RequestCurrent、自动 stage Run 或授专业资格。
3. `RemediationLink`：不可变 basis + 固定输出 Ref（kind/id/revision/item key）、该 owner 的实际创建/办理 Receipt、输出实际状态、完整源读集/source_basis/专业及政策引用。输出可以是研究草稿、待开测请求或真实完成事实，必须逐项明示；正式变更实施另核 fixed ChangeOrder/批准/实施输出，不能把配置创建回执说成生效。
4. `resolve_outputs(s,ctx,pid,basis,refs,*,write=False)`：逐 owner 服务只读核范围、可见性、固定版本、真实回执及状态，返回 typed proofs/完整读集/阻断，不代创建对象。`inspect_verification(s,ctx,pid,basis,evidence_ref,*,at,write=False)`：返回原核 `VerificationEvidence` + pair 映射、实际方法/判据适用证明、固定新 Run/Projection/原件位置、全部测试/测量执行者、独立 reviewer、真实观察事实及缺项。缺 bridge 返回明确 INTEGRATION_REQUIRED，不能返回 empty-pass。

候选须保存创建时的固定 Issue 版；后续核查比较当前同 CAPA/action/requirement/失败集合及根因、完成、输出、政策等实质依据，不能只要求历史 Issue revision 永远等于 latest，造成自己的完成/回链推进后失效循环。真实依据改变、归并、撤回或 source/runtime epoch 漂移仍须重核；不得跳过这些依据使历史候选永远 current。历史/merged 原单只读，不能晋升当前办理能力。

## 来源、本人时钟和专业授权的具体缺口

- **根因 T2**：原核只接受 human + quality 角色；AI 假设或采纳假设都不能成为决定。主线须给 exact operation/purpose/project 当前职责资格事实和共同 T2 注册；ProductGrant.can_write、工程资格、Run review 均不替代根因资格。root actor/决定钟来自共同提交，专业 basis/已消费 approval 关联留存。
- **完成 T1**：原核 `_completion` 核本人、非未来发生钟和 SourceRef 当前性，但没有解析证据内容来证明“该 action、该执行人、该完成事实”。新 host 须核精确整行结构化发生事实（Issue/CAPA/action/executor/操作/真实 occurred_at），严格重复 JSON key、完整字段、aware UTC instant + IANA 时区、来源整行 SHA/真实位置；服务器 received_at 不早于发生且不能由客户端填。普通文字 evidence 当前可读并不自动证明措施已发生。
- **指派不是资格**：Wave15 CAPA 草稿只核责任人是当前有效具名成员。完成时还需本动作当前专业职责/资格；原核通常允许 quality/engineering/test，T2 另限定 quality。纯 manufacturing 责任人不能被临时映射成 test 来过关，主线需先明确角色矩阵或保持该责任动作阻断。
- **政策**：[当前 Policy](../../../../pdos-next/server/pdos_next/domain/quality_execution/policy.py:1) 只有带出处/版本/epoch/有效期的 synthetic 风险/独立性发布。生产可信发布仍缺；风险未知不默认 low。复验方法/判据适用、措施输出类型与观察期 owner 尚非现有风险 bool 的含义，不能从该 bool 扩授。
- **自然到期与撤销分开**：新 Run 原实际执行继续由 retained 核原期间资格/消费证明；当前办理人的资格则按现在核。观察窗口 elapsed 不是原 Start 被撤销，也不是 observed_until 的实际证据。原件撤回/不安全、原签发者 epoch/消费证明或用途配置变化仍阻断。
- **全部 I/O 后刷新**：复用 [质量 `_refresh`](../../../../pdos-next/server/pdos_next/domain/quality_execution/service.py:350) 的窄 reader 边界，逐一重核此前已 byte 验证的旧失败和新验证 proof，再核完整 source_basis、当前 policy/authority/runtime registry；避免后一个原件/reader 回调撤销前一个证明。validate、preview、apply、replay 各 phase 独立，不跨 phase 缓存肯定资格。

## 共同事务与可并行归属

主线先冻结一项窄 **existing Issue append hook**（同 Session，接固定 before、旧核 Mutation、完整证据 basis、operation/intent/actor → 新版本 ORM）。新 A adapter 的 begin 仅核绑定/锁 Current；replay 使用共同历史回执且先当前权限/源核；confirm 只断言 apply 已由 [共同一次 T1/T2](../../../../pdos-next/server/pdos_next/service.py:402) 消费，T2 把实际 proof ID 绑定 Invocation.decision_id；record 调该 append hook，return `(new_version,"quality_issue",visibility)`。共同入口统一 RequestKey/Receipt/Audit/Outbox，不发第二份回执或 commit。

新 A 不直接调用被冻结 Wave15 `_load`：它的 PAYLOADS、域转换、额外 source、confirm allowlist、caps 和 preview 均仅首切片。主线在下一候选集中开放窄 writer/注册，不在当前 Wave15 runtime 偷接新动作。根因拟保存的 NamedConclusion.at 与 History.at 使用 server_on_save/null，占用/政策/来源摘要保留完整，避免实时 now 进入确认摘要；完成 EventTime 是实质已发生事实，必须固定。

| 路 | 独占新增目录/文件 | 汇合前必须交的合同 |
|---|---|---|
| A 品质后续办理 | `domain/quality_followup/`、`tests/quality_followup/` | root cause/complete wrapper，旧 handler Ports，同链 append、实质预览/caps/readset。只办理具名事实，不生成 Run |
| B 回链/复验 bridge | `domain/capa_verification/`、`tests/capa_verification/` | 需求/RemediationLink/候选 typed models、owner resolver、pair/观察期/独立性 proof 与刷新入口；A 只调用 B，不争模型 |
| C 前端 | 新 `build-quality-followup.tsx`、helper/test | 逐 Issue/action 本人 capability、固定输出和候选选择、真实/未知时钟、returned prepared command；不据角色自行授 cap |
| 主线 | 下一候选公共注册/API/BFF、窄 Issue writer、真实 head 迁移/生命周期/RLS/原子门禁 | T2 root cause/T1 complete/辅助回链明确分级，当前职责事实、scoped FK/CAS、immutable history、单一共同事务和集中验证 |

独立可施工部分是 typed DTO/model、来源事件核、owner resolver/缺项投影、UI；真实政策/人员资格/观察事实不足只阻断相应正向办理。它们不能通过 mock positive 或 generic 确认解除。

下一候选集中验证重点：AI/非 quality 根因拒绝、既有根因不可覆盖；他人/未知 action/重复完成/未来或错事实原文拒绝；两人并发部分完成 CAS 与全部完成唯一推进；同键/跨键旧意图先重核而不再消费；末端 Outbox 失败全部回滚/原 token 未消费；private/跨 scope/issuer 撤销与 ABA；输出须真实 owner 创建，新 Run 一请求一身份及共享资源/消费守卫；原失败 Run、nature 混用、漏失败/方法映射、不足观察期、参与者兼 verifier 均不能生成可用验证证据。合成正例只证明本地受控链，不证明生产整改有效或人工 Exit。
