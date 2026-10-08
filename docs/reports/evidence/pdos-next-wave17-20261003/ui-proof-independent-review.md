# Wave17 暂存证明 · 独立只读审阅

审阅快照：2026-10-03T09:56:55.086079+00:00。依据冻结首段施工合同与 effectiveness 草案 §9–12，定向读取三份暂存源码、两份暂存合同和所属纯用例。仅本报告为写入；未编辑源码，未执行 pytest、数据库、HTTP、浏览器、构建或公共检查。下述结论是代码审阅，合成结构用例不构成实际业务证明。

## 结论与已反馈修复

当前读到的暂存源码已修复本次发现的精确配对问题，没有新增已确认的未修阻塞项。它们仍是未挂载结构逻辑，不能据此启用有效性或关闭。

1. **两次决定不能复用命令。** 初读 `validate_lineage` 只区分批准 UUID 和 Receipt，未区分 effect/close 的 command_id。两个合法单步经完整重密封后可以复用命令。已反馈 Root/A；现 `lineage.py:528` 明确核两个 command_id 不同。新增负例先证明每个完整单步 `_check_step` 成立，再由全链拒绝重复命令，避免偶然被外层摘要或旧历史错配拦住。
2. **分次结果只能准确追加历史。** 初读 `_run_transition` 整体放开 partial_returns/preliminary_result，只按 measurement ID 保留旧值。第二次 partial 可改首条历史、首次 Run 钟或旧数组顺序。已反馈 Root/B；现 `paired.py:789` 起要求旧测量完整有序前缀、partial 完整历史前缀加准确一项、final 原样保留 partial 历史；新增项 returned/pending/reason/next_owner/事件与原载荷一致，已有首次钟不替换，并核 Formal/Run 首次钟和最终钟。
3. **观测必须在真实执行和本次返回内。** 原 `compute_results` 不校验 observed_at 的实际时序，初读 pair 只校 EventClock。已反馈 Root/B；现 `_payload_binding` 核本次新增观测 Start≤observed≤return，`_run_shape` 核全部已知观测处于真实执行边界，final 不晚于实际 End。None 仍为未知，不补时钟。所属用例已增加 Start 前、End 后、本次 partial 返回后的反例。
4. **本 v1 固定全部已接收范围。** 初读 pair 允许 accepted 子集，与真实 `verification_launch.service._full_coverage` 的 oneRun 门禁不同。B 已明确本暂存合同不兼容任意子集，现 `paired.py:914` 前使用完整 accepted 等式，并有缺一 pair 的负例。

以上补丁由 A/B 在各自归属实现，C 仅重新读取。A 已通知其 v2 所属纯检查结果另存；B 最后所属检查/冻结由 B 提供。C 未重跑或把这些结果归为自身运行证据。

## 已核对的边界

- **固定锚与准确变化：** origin 来自完整完成版，不能硬编码 Issue v6；保留原根因、措施/本人完成、失败、要求和完整 history。有限谱系仅 origin→effect→close，精确 immutable predecessor、连续 +1、同 scope/owner/audience/purpose/nature；按完整预期 Issue 构造后逐值比较，不删除 history 比较。effect/close 是两次独立命令、两实际 T2 UUID、两 Receipt。
- **资料闭包：** Artifact read-set 按真实版本去重，冲突、缺来源安全项或总数>20明确拒绝，不能截断。原安全 basis 和合法新增 basis 均保留，private Issue 当前调用者必须是实际 owner，private 来源不能借 ProductGrant 或历史作者扩受众。paired 汇总前后 Formal、origin、Run、Fact、Projection 的读集，并检查嵌套 Artifact/精确引用也被覆盖。
- **仅三个准确排除路径：** stable failure material 只排除 `result.retained.checked_at`、`result.retained.execution_window_elapsed`、`result.source_basis.runtime_stamp`；完整失败证明仍保存，嵌套同名字段不排除。当前 closure 的前后比较仅排除自身 checked_at 和 typed authority.now，实际期限、安全/issuer epoch、ACL、政策与 runtime 仍绑定。
- **IO 后新时钟：** `lineage.py:608` 末端 closure 与 Current 都完成读取，随后 `clock()` 再核到期；最后 Current IO 跨期限也会失败。paired 每轮 read/refresh 后取得实际 attest，再取新钟校 gate，比较两轮完整 material、门禁摘要和有效边界；不是跨 inputs/preview/execute 缓存。
- **Caller/UOW 与 writer：** paired opaque HostGate 绑定可信 reader、同一 Session、实际主事务/嵌套事务 identity、server caller/scope/material；reader 不可 commit、换事务或跨 SAVEPOINT。系列 owner、历史 writer、当前 caller 分开。Current Formal 和 Current Run 分别核，Run 起始 request_ref 只作为 origin。Plan 不推进 Formal，Promise 不推进 Run，review/disposition 按真实矩阵核；common/domain intent 分别核，不强求两 hash 相等。Receipt/Audit/Outbox 的 actor、目标 immutable 行、事件与 correlation 精确配对。

## 必须由 Root 实接的范围

`StructuralPairProof.structural_only` 和 `IssueLineageProof.structural_validation_only` 永远为 True。缺 lineage callback 返回 INTEGRATION_REQUIRED；缺 paired reader/完整 live gate 返回 missing。公共 adapter 不得把 missing 中附带的结构 proof 输出为已授权结果。

LineageHost 目前是 trusted-host 的结构协议，没有实现实际数据库读取或独立 Session/UOW identity 门闩；其同 caller UOW 约束要由 Root 的配置绑定宿主落实，不能由客户端构造一个 host 或 closure。`ConsumedApproval.consumed`、事务组摘要、material_sha256/Product 水位等是实际宿主读取后装配的结构字段，单凭输入 bool/UUID/hash 不证明同事务消费。真实 confirmation marker、Invocation.decision_id、reciprocal deferred 原子组、SAVEPOINT/回滚、共同 replay/CAS 和两个新 T2 的公共注册仍待主线实现与数据库验证。

实际 bytes/hash/定位、安全 gate、当前 reader ACL、历史专业 signer 撤回、issuer/runtime ABA、政策/专业期限、retained 资源/样件证据都必须由真实 owner 门禁取得并在全部 IO 后重核。纯 SourceRef/非空 dict/gate 摘要不能自授这些资格。当前暂存没有 CAPA observation/review/candidate 业务持久化、有效性/关闭办理或 UI/public DTO；旧私有调查不扩受众，G3、真实资格、生产、外发及人工 Exit 均未因此完成。

## Root 追加的 Wave16 closeout 工具对照

只读对照 `tools/wave16_closeout.py` 的 new_draft/link_check 与实际 `domain/capa_verification/service.py`、commands.py。确认 Root 已定位的预期误差：工具要求 output.meaning='draft'，实际 `_reading` 对 verification_request 为 meaning='planned'；status='draft'、v1、无样件/实物时钟仍应准确核，不改业务门禁。除此之外，没有找到另一项必然阻断本次显式新 Draft+单 Link 收口的字段错配。

basis/action/completion 摘要、完整安全 basis、owner_basis/resolution 摘要、真实新 Formal immutable ref/direct Receipt、Link 不推进 Issue6及 Candidate 物理缺席均与当前代码对应。工具有意只支持本次 seed 的具名人工原生资料回执和已选上传原件；新增其他原件、AI native 来源会明确 failclosed，不能作为通用 owner 读取能力宣称。

## 审阅文件 SHA256

本表为本报告写入时的只读快照，不替代 A/B 最终冻结清单。若后续源码变化须按新 SHA 定向核增量。

| 路径 | SHA256 |
|---|---|
| `pdos-next/staging/wave17/anchor.py` | `55a8446b68e9bbd466b9bf80ba7de44680ad587da353a4b56b3ed0b93156073e` |
| `pdos-next/staging/wave17/lineage.py` | `252a11c5a48f9d6db8a270e07f979ae1437de4156bd1b16d6fe4bd7dcea6dcce` |
| `pdos-next/staging/wave17/paired.py` | `73bff65b00b45e2678a18ad9ff8ea8def12d01aff3c4fb85d60d5d5386c420e3` |
| `pdos-next/staging/wave17/anchor-contract.md` | `97072e8fa394a290587b3c41ba928c6038aa69788cddb0220b73ee062decf54a` |
| `pdos-next/staging/wave17/paired-contract.md` | `3a597197ae30ebdfc94515c25d5c12f201770a0b2073e086e0e3b5265f5900f1` |
| `pdos-next/staging/wave17/test_anchor_lineage.py` | `c8150cbcf326dc9b441d21bec56c5cca095d8ff889210499c17498ef8d6a8e68` |
| `pdos-next/staging/wave17/test_paired.py` | `ace61c271112f997f1a93770aee27e1e2346bdd5eeab2231a370fd8ee039020e` |
| `docs/design/2026-10-03-pdos-next-wave17-staged-implementation-contract.md` | `918144f56d47344d3066f2419bef04dfd2750884ec7ec69e912df92b3c25b64d` |
| `docs/design/2026-10-03-pdos-next-wave17-effectiveness-contract-draft.md` | `05163de7294e0150995f21e75a4cee2dc10032d1ad2cce5330f0c68e6330cdb9` |
