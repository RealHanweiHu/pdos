# 第十六波：根因、实际完成与独立复验回链施工合同

**2026-10-08：本施工合同已被[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)整体取代，仅作只读历史对照。下方旧“当前/下一步/冻结”不再作为施工指令。** 范围根、一致性、期限与数量限制按 v1.1 和已批准的 [S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md)执行；[旧条款对照与 B0 基线](../reports/evidence/pdos-next-s0-20261008/baseline/baseline.md)保留取代依据。原证据、失败与当时范围不改写。

状态：主线冻结首段范围与并行归属。第十五波仍在公共复验和实际页面收口，本文不登记其通过。独占新增目录可先施工；共享注册、Issue writer、迁移及公开入口在第十五波收口后接入，不修改其冻结候选。

依据：[完整目标架构](2026-10-02-pdos-complete-target-architecture-v1.md)、[执行方案](2026-10-02-pdos-next-execution-plan.md)、[后续盘点草案](2026-10-02-pdos-next-wave16-quality-followup-draft.md)与[实际接缝审阅](../reports/evidence/pdos-next-wave15-20261002/wave16-quality-adapter-review.md)。草案中的完整变更实施、有效性和关闭属于后续缺口，本合同没有开放其执行。

## 业务结果与边界

当前真实 Issue/CAPA 保留原失败、原值、假设、遏制和风险政策。接通具名根因结论、执行者本人记录有原文依据的实际完成、引用既有 owner 保存的真实输出、创建并回链一条新的复验请求分支，以及适用性/独立性/观察期缺项的清晰读取。输出由既有 owner 创建，回链不能创造配置、样件、请求或 Run。

调查类措施可以在真实调查事实完整后记录完成；措辞要求正式改版/量产切换的措施，不能凭草稿或检查报告标记完成。固定八个图 facet 继续 UNKNOWN；正式 ChangeOrder 批准、实施、生效、CAPA effectiveness、Issue close、Change verification/close 仍不注册为可成功办理动作。

演练使用独立合成环境和明确 synthetic 来源。真实资格、专业决定、观察事实、生产政策、真实业务出站和人工出口保留原关口。AI 身份不得执行 T2，源撤回/权限/政策/专业 epoch 与过期守卫仍在每次 validate、preview、apply、replay 和最后 I/O 后核对。

## 公共动作与单一聚合

| 动作 | 分级 | 保存语义 |
|---|---|---|
| `quality.issue.root_cause.decide` | T2 | quality 职责的具名专业结论，引用当前固定 Issue/CAPA 与精确来源；保留原假设，不覆盖已有根因；实际 actor、决定钟、共同已消费具名 proof 由服务器绑定 |
| `quality.capa.actions.complete` | T1 | 本人负责的一个或多个 action 的实际完成事实，一次实质预览；精确 action ID、本人、非未来 EventTime、原 IANA 时区与原文结构化事实；不覆盖既有 completion |
| `quality.capa.followup.link` | T1 | 固定 action 与真实 owner output/创建回执的不可变回链；最窄受众、来源、当前性、适用缺项完整保存；不声称批准、实际实施或独立验证通过 |
| 复验候选读取/核对 | 只读 | 固定新 Run/Projection/原件及 pair/方法/判据/观察事实；缺真实 owner bridge 时明确 `INTEGRATION_REQUIRED`，不返回有效性或关闭资格 |

根因和完成复用原 `quality_issues` kernel。部分完成继续 actioning，全完成按旧规则转 awaiting_verification。旧核只在 actioning 接受根因，因此首条演练先根因、再全部完成；界面说明无根因全部完成后的真实限制，不偷改 kernel 或默许补办。事后根因、根因更正或追加措施需要另冻正式规则。

仍只有既有 `QualityIssueVersion/Current` 一份聚合。主线提供窄 `append_issue` hook：同一 Session，固定 before_row、旧 kernel Mutation、authority/policy_snapshot、完整 readset/source_basis、input_snapshot/intent_digest、expected_issue_revision → 追加既有版本并 CAS Current，返回 `(row, "quality_issue", visibility)`。无独立 commit/第二份 Receipt；共同 RequestKey、proof 消费、Receipt/Audit/Outbox 保持一笔事务和末端回滚。A 的 adapter 不调用被冻结首版 `_load` 偷接新动作。

## 证据与接口

B 在新包先交 `typed-binding-contract.md` 和严格 DTO，A/C 使用其冻结字段，不分别发明相同对象。服务器建立 FollowupBasis，完整绑定 tenant/product/project/purpose/audience/nature、固定 Issue 版本行与 logical/revision、CAPA/action、requirement、全部原失败、根因/完成/输出摘要及来源。客户端不提供政策事实或服务器身份。

`load_followup_basis(s,ctx,pid,issue_id,expected_issue_revision,*,write=False)` 返回固定 basis；`resolve_followup_outputs(s,ctx,pid,basis,action_id,output_refs,*,at=None,write=False)` 返回真实 owner 证明/缺项；`inspect_verification(s,ctx,pid,basis,evidence_ref,*,at,write=False)` 返回固定候选及结构化缺项。OutputRef 使用封闭 kind 与 exact id/revision/key；模型仅声明 append-only RemediationLink/CapaVerificationEvidence，不建第二套 Issue/CAPA/Run。

措施完成新增宿主核对：实际登记回执、整行原文 SHA/位置及 ACL，严格 JSON（含重复 key 拒绝），字段精确绑定 Issue/CAPA/action/executor/operation/occurred_at/purpose，保留全部小数秒与原时区。received_at 取服务器；普通文本可读、责任人已指派或有产品写权限不能替代完成事实与本操作专业资格。

原失败 result bridge 不能作为新通过证明。新候选须不同 Run、新逻辑请求，每请求仅一个 Run；实际样件/方法/判据/工况/资源/消费沿原 owner。调查复验可复用仍适用固定配置，但不能复用原失败 Run 或已破坏样件。适用性、全部失败 pair、独立测试/复核者与实际观察证据未接入时明确缺项，不以日期到期或 aggregate=pass 填空。

## 并行文件归属

| 路 | 独占新增路径 | 汇合交付 |
|---|---|---|
| A 根因与完成 | `pdos-next/server/pdos_next/domain/quality_followup/`、`server/tests/quality_followup/` | 严格载荷、旧 kernel adapters、结构化完成事实核对、事务 callback、预览/能力/恢复；仅调用 B，聚合由主线 writer 保存 |
| B 回链与复验 | `pdos-next/server/pdos_next/domain/capa_verification/`、`server/tests/capa_verification/` | DTO/模型声明、来源及真实 owner resolver、需求/候选缺项、I/O 后刷新接口，以及 `followup.link` 同事务 handler；返回真实 link 行，不推进 Issue Current、不创建 Run、不导入公开 models/API、不授真实资格 |
| C 页面 | 新 `build-quality-followup.tsx`、`build-quality-followup-view.ts`及其测试 | 按服务器 caps 办理具名根因、本人完成、真实输出和候选；精确时钟/来源、返回的 prepared command、原请求恢复和未知显示；不改父页面/共享 BFF |
| 主线 | 共享 writer、operation/professional/生命周期注册、API/BFF/挂载、实际 head 单调迁移 | scope FK/不可变/CAS/RLS/Agent零写、共同 proof 和原子事务；公共 PG/HTTP/浏览器/构建与证据收口 |

当前冻结 Wave15 的303后端、138前端路径不得被并行包修改。新增包属于 Wave16，未导入/未挂载/未迁移的实现不计为 Wave15 联验或可用能力。独立包只运行自身无数据库的必要纯检查；公共环境与验证仍由主线负责。

前端读取合同为 `GET v1/products/{pid}/quality-followup?issue_id=<logical>[&revision=<explicit>]`，严格一个固定 Issue。envelope 为 `issue/current/basis/operations/actions/output_options/links/candidates/required_source_read_set/source_options/integration`；current 是精确 `version_id/revision`，逐操作 `allowed/authority/reason_codes` 来自服务器。完成候选尚未填写时，逐 action 的 `can_prepare_completion` 只表示当前本人/专业/状态和 assessment 端口允许开始事实核对，`completion_verified=null/can_complete=false`，不声称发生事实已核。表单与“核对实际完成事实，一次确认”使用准备资格，实际执行只接受完整 inputs.allowed 和共同 T1。历史版全部写 caps false，缺 assessment 或当前专业也无准备资格。output options 只有有实际 label/ref/status 的可读 owner 对象；用户不手造 UUID。

三个操作 `POST v1/products/{pid}/quality-followup/inputs` 收完整共同 Command。预览/写入复用 `v1/commands/preview`、`v1/commands`；根因 T2 返回 `approval_token/named_decision:true/write_tier:T2`，完成/回链 T1 返回 `confirmation_token`。root cause/complete 的 Receipt subject family 是 `quality_issue`；link 是 `capa_remediation_link`，不能以此声称 Issue 版本推进。候选首段只显示既有固定候选/缺项；其创建公开合同另冻结，UI 不猜端口或占位身份。

新增实际完成 assessment 是必要宿主端口：绑定固定 basis、action 内容摘要、完整实际 EventTime/原文、当前专业政策，返回 `allowed/current/classification/reason_codes/owner_proofs/required_source_read_set/proof_sha256`。调查类别也须明确受控当前依据，正式变更须实际批准/实施证明；缺失按 `INTEGRATION_REQUIRED` 失能，不用关键词猜类别。本地合成 assessment 明确限定隔离环境与 exact action，不构成真实生产分类资格。

主线核对真实 head 后分配下一迁移，不能提前复用预留号。业务表与 schema 一致、全部新表强制 RLS/Agent零直接写、引用及时间生命周期分类完整。测试仅复用已核对 marker 的62513/pdos_test，不回退 `.env`。

## 本闭环验证与剩余范围

验证实际本人/角色/来源、T2 proof 与 T1 固定预览、微秒时钟、部分/全部完成状态；已保存事实不能覆盖。核 CAS、相同/跨 key replay、全部 I/O 后撤回与 ABA、Outbox 故障连同 proof/Current/Version/Receipt 回滚。真实 output 只按创建回执及精确版本回链，跨 scope/private 扩大/草稿冒充实施拒绝。独立分支有实际新请求/Run 或具名待办阻断；观察/方法/pair/独立专业缺失明确保留。

亮暗/窄屏和 HTTP/浏览器整链集中到冻结闭环候选。复用原规则和既有实际 owner，不重复整树回归或累加各包检查数冒充联合通过。G3 整体、真实有效性/关闭、八 facet 完整图、正式切换/放行/外发和人工 Exit 仍按原完整验收办理。
