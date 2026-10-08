# Wave17 原完成版 Issue 实际存储读取基础

仅三个新暂存文件，未公开接线。用户已授权连续建设，公共迁入由主线统一办理。本段没有 DB/HTTP、迁移/注册、来源 bytes/专业授权、Run/Receipt/事实写入、消费、flush/commit、StableCapaAnchor 构造或有效性/关闭授权。纯正例为明确 synthetic SQL 返回替身。

## 接口与准确输出

```python
read_origin_descriptor(
    s: sqlalchemy.orm.Session,
    ctx: pdos_next.service.Context,
    product_id: UUID,
    issue_id: UUID,                     # logical Issue identity
    origin_ref: anchor.VersionRef,       # immutable row UUID + revision + full Issue SHA
) -> StoredOriginRead
```

必须显式提供原完成 ref，没有取 Current 作为原锚的默认值。读取本来就是全部措施完成版的真实 QualityIssueVersion，不从任意旧版/待办 DTO 生成完成事实。VersionRef.id 与 logical Issue ID 分开，revision 不硬编码 v6。

输出准确字段：

- `origin: anchor.IssueVersionEvidence`：实际原行、精确前版 ref、scope/logical Issue/purpose、系列 owner/当次 writer、visibility/nature/operation/domain意图/原保存钟；完整 Issue（root/actions/completion/requirement/failures/history）、完整 sources/readset、原保存声明的 typed SourceSafety，以及原 input/authority/policy/persisted_source_basis，原样保留。
- `project: StoredProjectScope`：实际 Project scope、owner/visibility 与 business scope 字符串。入口 exact tenant/product/project 有界读取，Project private 只实际 owner 可读，Product Grant/共享 Issue 不能绕过。
- `current: StoredIssueCurrent`：真实 pointer_id/pointer_created_at/epoch、当前目标版本完整 ref/operation/created_at；目标实际在同 scope 再读、完整 snapshot SHA 与 owner/private 核对。
- `completion_group: StoredCompletionGroup`：原 Receipt/command/writer/Audit/Outbox/Confirmation 身份、原 Product proof 水位、proof 创建/到期与 Receipt 创建钟、各自 domain/common意图、原 request digest、material 与 reviewed snapshot SHA。
- `needs_lineage_owner`：当前 ref 不再等于显式原完成 ref 时 True。完整原描述/历史保留，不删 Current 新 history/sources 与旧版宽比；本段不证明后继合法。
- `missing_owners` 总含 original_failure_bytes_owner/current_source_security_owner/current_professional_policy_owner；后继时另含 limited_issue_lineage_owner。
- `current_evidence_authorized/source_bytes_verified/original_failures_verified` 与 group.same_uow_consumption_attested 均为 Literal False。

没有 assemble_from_actual_owner 默认实现，不调用 build_anchor。未来 Root 必须先提供同 caller/Session/UOW/完整原 ref 的真实原 FailureRef→固定 Run/Projection/Measurement/Original bytes/retained、专业、来源安全 owner，全部 IO 后独立 fresh refresh，再装配原冻结 anchor/lineage 协议。缺接口持续 missing/INTEGRATION_REQUIRED，输入 DTO/Hash/SourceSafety 声明不能自授肯定。

## 真实存储与固定历史 CAS

复用 Root 冻结 fact_atom_storage v5 `_uow/_same_uow/_acl/_one`，源依赖 SHA `b3794750da19f6394dc12cce062489e1aad7022619f4aac7dccb7e7246b9e604`。必须真实 Session 已有活动完整主/嵌套祖先链，首尾 chain identity/bind/Context 一致；无 begin/换连接/Session.info/global cache。SQL bounded limit1/2、tenant 与 exact refs 限定、populate_existing/autoflush=False，不自动保存 pending Row。

入口为当前本人 Context actor=requester/run=None，真实 Product/active human/Grant 与 exact Project scope/private owner 独立读取；私有 origin/前版/Current 只原 owner 可读，不借 owner Context，不把 ProductGrant 作专业资格。原历史 writer 核 human，不凭其现在 active/Grant 否认原保存，也不凭历史身份授当前专业资格。

精确 predecessor 为 origin 保存的 immutable UUID/revision，WHERE 包括 tenant/product/project/logical Issue；revision+1、owner/visibility/purpose 一致且完整 snapshot SHA 核对。只取真实相邻前版，不枚举全系列。

原完成条件：operation=quality.capa.actions.complete、awaiting_verification、未归并/无待重核、有具名 root、全部原措施 completion、无 effectiveness/history/closure、requirement 精确覆盖全部 Failure identities。原 typed ActionsCompletePayload 精确等于真实 handler semantic，expected_issue_revision 等真实前版。

从完整前版只按原 payload 更新本人对应未完成措施，发生钟不晚于原保存钟；History 保留完整前缀+本次单项，writer/command/operation/真实 kernel fallback note/保存钟匹配。重建的完整 Issue 逐值等于保存完成版，根因/措施/要求/失败/aliases/risk/旧历史不能暗改。root/actions/completion/containment/Failure refs 均在原 sources 声明闭包，Artifact refs 与 1..20 readset/原声明 basis 精确对应；没有读取其 bytes 或当前安全状态。

## 共同组与旧证明边界

Receipt 唯一 exact tenant/product/op/quality_issue/**不可变 version row id/revision**；actor=requester=原 writer、command=新增历史 command、run=None、原 visibility，扁平 result.id/revision/status 精确，revision 须真实 int。domain intent 按实际 followup `_intent` 格式独立重算；common intent 按真实 common semantic/op/Product/named_actor/source_revision=None/private_owner=原 writer 格式独立重算，二者不互判相等。

丢失 token 后不能恢复原完整 request digest。仅要求至少一个 tenant/原 writer/Receipt id/digest==Receipt.request_digest 的真实原 RequestKey 关联并保留原摘要；其他 aliases 不必全等，不从异值 alias 猜原请求。Audit/Outbox 各唯一，实际 actor/op/event/subject/command correlation/schema 配对。

source_basis.shared_proof 的实际 UUID/tier=T1 指向原同产品 Confirmation；核历史 consumed bool/actor/Product subject/op/正整数原 Product 水位及 proof.created_at<=origin.created_at<expiry。当前 Product revision 或 proof 现在自然到期不替原历史时钟/水位。原 reviewed before/after（真实 `_preview_issue` 的 server_on_save 视图）、authority/policy/source_basis/readset 与原保存材料一致，material_digest 用 proof 当时水位与原完整 readset 核对。

旧 completion 来源没有新增 consumed_at。本段不由 Receipt/Row 创建钟或 consumed=True 反推消费钟，不要求旧 native Artifact proof 拥有新字段，不宣称该历史 bool 自证同 UOW False→True/marker/deferred 原子守卫。

## 末端复核与剩余限制

原 descriptor 在后续 IO 前 deepcopy 成独立 DTO。末端独立重读原行/前版/原组/Current，比对全部保存材料与 pointer identity/epoch/ref；不能以同一活 ORM 对象与自身比较充当刷新。再次读当前 ACL 与 Current，末端另外再读 Project scope/owner/visibility 并比较原完整描述；最终 clock 在最后 Current/Project IO 后采样，拒绝 IO 期间到期；完整 UOW/Context 末端核对后返回。

本段不保证跨连接串行化，也不获取 writer Product 锁。数据库 snapshot/可见性由真实 caller UOW 决定；未来授权 writer 仍须共同真实锁顺序、fresh owner gates/原子 guard/CAS。所有失败真实 bytes、source/issuer/专业/政策、后继 T2 companion/有限谱系、actual effects/Current 完整授权仍缺，输出仅为存储描述，不可公开 allowed/current/qualified/effective/close。

## owned 检查与证据

只运行此新增 `--noconftest` pure。真实 ORM/Session/Transaction/SQL 编译配显式 SELECT 返回，无真实 DB 连接；覆盖 exact ref/CAS、完整完成/history/source 声明、私有 caller、原组/material/原 RequestKey/独立意图、后继保留、Current epoch/pointer 漂移、Project private/owner/scope漂移、末次 IO Grant expiry、活动/嵌套/UOW替换、无 autoflush、WHERE-before-LIMIT，不调用 build_anchor/actual failure owner。

```sh
PYTHONPATH=pdos-next/staging/wave17:pdos-next/server:pdos-next/server/tests \
  pdos-next/server/.venv/bin/python -m pytest --noconftest \
  pdos-next/staging/wave17/test_anchor_storage.py -q
```

首轮 v1 fixture 将纯 Containment 直接喂给 wrapper Completion 并误添不支持的 text，46 setup errors；随后改用真实 closed Payload 字典、实际 kernel operation fallback note，并修此新 reader 同一 note 约束。初失败日志保留，不隐藏成全通过、不算业务数据失败。最终结果/hash 见新 `anchor-storage-check-result.json`，不并入公共 484/142 候选验收。
