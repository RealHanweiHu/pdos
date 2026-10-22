# Wave17 第七段：真实候选只读准备 owner

仅新增 `candidate_prepare.py`、`test_candidate_prepare.py` 和本文；不改既有冻结文件、server/web、公共注册或迁移。没有数据库/HTTP、提交、proof 消费、Receipt、业务 DML 或七门禁授权。测试调用实际原锚/CAPA owner 链，SELECT、原件/专业/政策仍是明确离线替身；不能称为实际原值或资格验证。

## 接口

```python
prepare_candidate(s, ctx, product_id, payload, *, origin_ref) -> PreparedCandidate
require_prepared_candidate(s, ctx, product_id, payload, phase) -> same PreparedCandidate
reviewed_candidate(phase) -> dict
require_prepared_candidate_clock(s, ctx, product_id, payload, phase, at) -> same phase
invalidate_prepared_candidate(phase) -> None
```

`payload` 必须按实际 `candidate_commands.CandidateRecordPayload` 重新严格解析；`origin_ref` 是明确 `anchor.VersionRef`，包含真正原完成版行/版本/完整 Issue snapshot SHA。不是最新失败 Current 或客户端构造 anchor。OPERATION 沿 `quality.capa.verification.candidate.record`（T1），本段未注册。

`PreparedCandidate` 是 frozen、eq=False、slots dataclass，字段如下：

- `payload_semantic`：实际严格 semantic，全字段只移 confirmation_token。
- `anchor`：第一次实际读取的完整 StableCapaAnchor；全文、原失败 full proof/SHA、原观察钟保留。
- `binding`、`inspection`：实际 CandidateBinding/CandidateInspect；inspection.binding 必须精确等 binding。
- `raw_source_basis`：全当前闭包的原始稀疏 list；不会补 optional `original:null`/`registration:null`。
- `required_source_read_set`：完整 typed SourceRead tuple；`sources`：实际 SourceRef tuple。
- `authority_snapshot`、`policy_snapshot`：实际当前具名专业/政策结果，不从字符串、ProductGrant 或 SourceRef 存在猜。
- `owner_id`、`visibility`：实际原系列，不是本次 writer；`current_issue_revision`：独立真正 Current CAS。
- `session`、`uow`、`runtime_binding`：本次实际 Session/完整活动根与 SAVEPOINT 链/bind/宿主配置身份。
- `checked_at`：最后 caller SQL、所有 owner/source IO 后真实时钟；`valid_until`：最早实际 Grant/专业/政策 expiry 或 activation 边界。

模块内部弱身份登记仅标记本模块实际产生的 phase。直接 dataclass 构造、replace/copy、材料/TTL 注入、其它 Session/Context/事务/运行入口不能用于 writer。登记不是 source 或专业肯定结果缓存：每个 require 都独立重跑实际 owner 全链，不跨 inputs/preview/execute 复用证明。`invalidate` 在正式 writer 最后保存钟检查之后、第一次 s.add 前使用，防同一阶段再次使用；不等于持久 proof 消费。

## 真正读取和固定版本

1. 当前真实 Context 必须具名 human、actor=requester、无 run；真实 Product/Principal/Grant scoped SELECT，当前 grant.can_write=True。ProductGrant 只是当前业务读写范围，不能替代专业资格。
2. 调用 B `anchor_owner.read_anchor_from_actual_owner`。缺真实 bridge/refresh 返回503；完整固定原失败/来源/原件和 retained 已由实际 owner 负责。
3. v1 明确要求实际 Current.ref == origin.ref，且两个实际 owner 的 needs_lineage_owner=False。合法后继也先返回 `CANDIDATE_LINEAGE_OWNER_REQUIRED` 503，等待有限谱系 owner 接通；不将后继当固定原失败版。
4. 实际 `load_followup_basis` 按真正 Current CAS 读取，然后调用 `inspect_candidate`。basis 的 scope/逻辑 Issue/CAPA/版行/owner/用途/受众必须逐值等原锚；不能隐藏换入 latest。
5. 请求 visibility 必须精确等实际 origin/basis.visibility，否则 `CANDIDATE_AUDIENCE_MISMATCH`。共享系列允许独立具名 writer，不把 writer 变 owner；private Project/Issue/原失败只真实 owner 可读。

CandidateInspect 保留现有真实 missing；允许 incomplete、indeterminate、applicable/independently_verified/observation_complete 三 NULL、未完成观察范围。两个 effectiveness/close caps 始终False。不从新 Run pass、客户映射或材料 hash 装配完整 VerificationEvidence。

## 专业、政策和完整来源闭包

调用实际 `professional_authority.assess`，operation 必须候选精确操作、purpose/project/subject 精确。当前公共矩阵尚未配置此操作，因此真实默认 `PROFESSIONAL_OPERATION_NOT_CONFIGURED` 503；不借 followup.link 等旧操作资格。authorized/qualified 必须真实 True，完整 fact refs/fingerprint/期限缺失503；合成专业不能授真实事实资格。

实际风险政策 `quality_execution.policy.assess` 必须有当前 scope/purpose、完整 issuer/epoch/出处/期限，缺端口503，不猜低风险或 independent=False。共享候选拒任何私人政策/完整来源。

读集是原锚、固定 basis、inspection 输出/Link、实际用户 exact sources、专业和政策的完整并集，≤20；冲突 Artifact 版本拒绝，不截断。用户 quote/位置由实际 `refs_from_exact` 核，原件/原值由既有实际 owner 核，不能用 Artifact.content 替仪器原件。

初始 inspection 的 self SHA 与原完整 source_basis SHA 必须先核，不能重封坏摘要。扩大只作用于 inspection.required_source_read_set/source_basis_sha256/inspection_sha256：排除 self inspection_sha256 与现 candidate_ref 后，沿现实际算法重算；binding.basis 原安全摘要不改。全 closure raw list 同时供新 row 保存，sources/完整 authority refs 均保留；source metadata 核对不冒充缺失的七门禁。

## 最终刷新、时效和 UOW

实际原锚、inspection、新操作专业与政策、完整来源 raw basis 都在全部 initial owner/source IO 后独立重核。原锚全文仍用第一次结果，刷新仅比较 frozen `stable_failure_material` 的三个准确路径例外：

- `result.retained.checked_at`
- `result.retained.execution_window_elapsed`
- `result.source_basis.runtime_stamp`

全文 full proof 摘要不重封。runtime_stamp 虽不进稳定失败材料，本入口实际当前运行 stamp 仍必须精确相同。所有其它原值/时钟/Start/计划/占用/使用/安全/issuer/方法/配置字段保留；不递归按键名删除。随后最后 scoped 原 Issue、Current、Project、caller 再读；真实钟在最后 Grant SQL 后，全部活动 UOW/Context/bind/issuer callback identity/epoch须一致。

`professional.assess.valid_until` 现只包含 Grant/当时有效匹配事实 expiry，未完整纳 future valid_from。本段因此按实际 assessment.fact_refs 逐条真正 scoped tenant/product/project/subject/id/revision 读取 ProfessionalFact（每SQL≤2，上限现100），取所有 active 事实的未来 valid_from/valid_until 和原期限最小；不另判专业资格。所有查询后时钟若跨该边界立即 SOURCE_STALE。policy.assess 已提供全部 active scope 的下个 activation/expiry。writer 不应自行猜剩余 TTL。

`require_prepared_candidate_clock` 只做无IO最终绑定/runtime/UOW/真实 aware 非未来保存钟守卫，不替代 `require_prepared_candidate` 独立 owner 刷新，也不证明 T1 消费。正式 writer 应：实际 require_live → require_prepared 全刷新 → actual require_live → fresh 保存钟/clock guard → invalidate phase → s.add。proof 消费、SQL 原子组、回执仍由 B/Root。

## 共同预览到保存的明确缺接缝

`reviewed_candidate` 精确 top keys：

`payload_semantic, stable_anchor, binding, inspection, raw_source_basis, required_source_read_set, sources, authority_snapshot, policy_snapshot, owner_id, visibility, current_issue_revision`。

其中 `stable_anchor` **就是第一次完整真实 anchor**（不是稳定材料摘要的替代物），保留其 full_failure_proofs_sha256/anchor_sha256 和原全文。只不把本 phase checked_at、对象/事务地址放进 review。原 proof 的真实观察钟不是后来动态刷新钟，不能删后声称全文相等。

跨公共 preview→apply，重新读取的新 anchor 全文 SHA 会因真实 bridge checked_at 改变。后续 Root 必须从真正 persistent Confirmation.snapshot 的该 path 恢复原完整首锚，严格 token/material/actor/scope/proof/UOW 绑定并只比较三准确稳定路径。该 trusted restore seam 本段**尚未实现或注册**；不能从 Payload/任意 DTO/Live 返回锚替代，不把重造新 full SHA 与旧确认硬比或伪称接通。当前接口仅本次 phase 内刷新保留首锚。

## 离线证据与限制

首轮22fail/3pass：新测试桥未为实际 load_followup_basis 无 write/event kwargs 设置自身替身默认；Current 反例直接破坏真实指针与版行，先触完整性守卫。第二轮21fail/4pass：旧模块 import 的 source_basis alias 未接本次明确替身。均修测试接口，不修改既有 owner 或生产守卫。25项先过，扩展38，再补初始 inspection self/source SHA 保留到40；原日志全部保留。

全部只运行本文件 owned `--noconftest`、Ruff/format/内存AST；实际 Session/SAVEPOINT/ORM，explicit SELECT memory 和禁止连接事件。无实际DB/原件/生产资格/公共闭环结论。最终来源哈希、准确退出码及原始日志单独写 candidate-prepare manifest/result。
