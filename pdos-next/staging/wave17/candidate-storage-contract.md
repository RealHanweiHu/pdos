# Wave17：候选完整登记读取（暂存第五段）

本段只实现不可变候选和实际共同组的读取。没有公开保存操作、迁移、权限注册、七 owner 门禁、真实原件读取或专业资格授予；没有运行数据库、HTTP 或公共检查。模型定义和原子关联可读不等于本次真实 false→true 消费已被证明。

## 接口与依赖

```python
CandidateSemanticOwner(payload_type, module, semantic)
read_candidate(s, ctx, product_id, candidate_id, expected_ref=None,
               *, semantic_owner=None) -> StoredCandidateRead
candidate_owner(semantic_owner) -> Callable[[s, ctx, product_id, FactRef], CandidateRegistryRead]
```

`candidate_owner` 可供已冻结 `fact_registry_storage.read_stored_fact` 的显式 callback 参数使用，不修改该模块。第一次读取可省略 `expected_ref` 得到真正 `FactRef(id, revision=1, sha256)`；后继读取必须逐值匹配完整 ref，不能用 `binding_sha256`、`inspection_sha256` 或 payload 摘要替代。

宿主在服务器启动时配置 **实际**候选 module 和严格 Pydantic Payload class：`extra='forbid'`，`confirmation_token` 缺省为 `None`；`module.OPERATION` 必须精确匹配本段 operation，`module.semantic is semantic`。每次读取和末端均重核对象。保存 `semantic` 经该 Payload 重新 typed parse 后，实际 callback 返回值必须与保存 JSON 逐值一致，并禁止两 token 字段。没有实际 owner、传 dict/字符串或临时通用 identity adapter 时为 `CANDIDATE_SEMANTIC_OWNER_REQUIRED` 503。本段 **没有定义未来公共 Candidate Payload 字段**；测试的 `TestOnlyPayload` 是显式假宿主协议样本，不能生产注入或作为注册合同。

依赖冻结的 Root `fact_atom_storage` v5 `_uow/_same_uow/_acl/_one`、B `anchor_storage.read_origin_descriptor`、A `fact_registry_storage.CandidateRegistryRead`、现有 `CapaVerificationEvidence / FollowupBasis / CandidateBinding / CandidateInspect`。不调用 `read_fact_atom` 来猜候选组，也不调用旧 Link 的 semantic。

## 保存材料与摘要

唯一允许的 `input_snapshot` keyset：

```json
{
  "semantic": "实际 module.semantic(payload) 对象，排除 token",
  "shared_proof": {"id": "实际 UUID", "tier": "T1"},
  "proof_consumed_at": "宿主实际首行捕获的 aware ISO 时钟",
  "stable_anchor": "完整 StableCapaAnchor"
}
```

旧包装缺钟或原锚为 `CANDIDATE_NEW_WRAPPER_REQUIRED` 503，不补时钟、占位 UUID 或新原锚。只接受 v1、`status=candidate`、`result=indeterminate` 和三 NULL；`CandidateInspect.candidate_ref` 可保持保存前的 None，不事后补写。若原保存已有 ref，则须精确等于该行 id/v1。

依现有纯函数严格复算：

- `basis_from_issue` 以 B 实际原 Issue 行身份/完整聚合投影，核 requirement、失败全序、措施/完成/EventTime、根因、scope/owner/purpose/nature 与 basis 全摘要；原版身份必须等于 stable origin，不猜 Current。
- `binding_sha256 = digest(CandidateBinding.model_dump(mode='json'))`。
- `inspection_sha256 = digest(CandidateInspect.model_dump(mode='json', exclude={'inspection_sha256','candidate_ref'}))`，与现服务相同。
- `source_basis['artifact_sources']` 必须为完整原始 `quality_execution.evidence.source_basis` raw list；typed `SourceSafety` 只核结构与完整读集。hash 按原 raw entries 的原有顺序及各 basis/inspection 完整 reads 的精确子集计算。**不得 model_dump 增加另一原件分支的 optional null key 后重算旧 SHA**。其他 `source_basis` 原字段全部保留。
- 行 sources 必须含全部原锚和 basis 来源，完整读集包含原锚和 basis；与 inspection 读集精确一致，总量 1..20，不截断。固定 child refs 的原顺序、版本及其他字段完整保留，不用 latest 替换。现 `CandidateBinding` 的 Link 子引用只有 FixedRef，不能因此宣称已取得相应完整 owner proof。

完整 ref 唯一公式：

```python
digest({
    'schema_version': 'pdos-capa-candidate-full-v1',
    'candidate': canonical_all_actual_candidate_columns,
    'group': complete_actual_common_group,
})
```

候选材料迭代实际 ORM table **全部列**，含完整 body/原锚、原失败 proof、来源安全、所有 hash、reason、受众和时钟；无按键名递归删除。规范列值：UUID→标准字符串，真实 datetime→UTC aware `isoformat()` 保留微秒；JSON 字符串/原 keyset/数组顺序/NULL/有限数值保持原值，不把保存 JSON 内 ISO/TZ 字符串重写。拒非有限数值、naive 时钟、必需列 NULL。完整摘要不包含当前调用者/Grant 或剩余时效。

## 精确共同组

固定 operation `quality.capa.verification.candidate.record`、tier `T1`、subject `capa_verification_candidate`、event `CapaVerificationCandidateRecorded`；本段不注册这些名称。

读取同 tenant/product/id/v1 的唯一 Receipt；actor=requester=实际 writer，writer 是具名 human，run=NULL。行 `intent_digest` 必须是 **实际 common semantic intent**，按当前共同公式从实际 Payload 的 visibility、原 writer、operation、product、semantic 重算；不是 domain `_intent`。

Receipt.result **精确展平**为 id/revision/status + `candidate_binding_sha256` + `inspection_sha256`，不出现 fullCandidateSHA，避免循环。读取唯一 Audit、Outbox、原 Confirmation，核 receipt_id、actor、operation/effect、subject/id/revision、schema、command/correlation。原 RequestKey 必须存在与同 actor/Receipt/原 request_digest 精确关联。

原 Confirmation 核 actual consumed=True、原 scope/actor/op/subject、token hash 格式、非空实际 review snapshot；以 **原 proof.revision**、完整保存 reads 和实际 module.semantic 按 `service.material_digest` 公式重算 material。当前 Product revision 不代替原 proof revision；历史 expiry 不按 now 重新拒绝：

`proof.created_at <= actual saved consumed_at <= row.created_at < proof.expires_at`。

组保存 Receipt、Audit、Confirmation **全部实际列**及 Outbox 全部非投递列，另保存实际 consumed_at、原 request_digest。只排除 Outbox 的 `delivered_at/lease_id/lease_until/attempts/last_error`；所有 RequestKey 行仅作原关联存在性核对，不纳入 key/id/alias 时间，否则后来合法 alias 会改变旧完整 ref。原 request_digest 留在 Receipt/组内；其实际原请求全文/秘密 token 不从 digest 反推。

## 原锚、读取范围与末端

完整 `StableCapaAnchor` 自摘要核验后，必须与 B `read_origin_descriptor` 返回的实际 origin **整个 DTO 逐值相同**，包括完整历史、原 input/authority/policy/persisted source_basis，而非仅 stripped CAPA 相等。B 独立核原完成共同组。原 Issue Current 可已推进；输出明确 needs_lineage_owner，不把 Current 当原失败版，也不批准任何有限谱系。

实际 Session、活动 root 和完整 nested/SAVEPOINT 祖先、同 bind、真实 Context/actor=requester/run=NULL 强绑定。所有 SQL 是 exact SELECT，最多两行，`populate_existing=True/autoflush=False`；原 RequestKey 存在性 SELECT 最多一行；全段 `no_autoflush`，无 lock/insert/update/flush/commit。

除 Product/真实 caller/当前 Grant 外，必须核实际 Project tenant/product/id、active、原 owner/visibility/business scope；private 仅真实 owner。候选、原 Issue 和 Current 可读受众分别检查。末端独立重读完整候选、共同组、原 origin/Current/完成组以及 Project，逐值一致；最后再核 Project、真实 caller/Grant、实际 UOW，**post-all-IO clock** 检查所有保存钟非未来。不存在跨 phase/请求/Session 正结果缓存。

`StoredCandidateRead` 返回完整候选/body/group、真实 B origin、完整 ref 和可接现 registry callback 的字段，所有以下声明恒为 False：current evidence authorized / source bytes verified / original failures verified / same-UOW consumption attested。`CandidateInspect.current` 只保留原保存材料，不升级为 live current。missing 列出来源原件安全、原失败 owner、有限谱系、候选适用、参与者独立性、当前专业/政策/issuer、真实消费原子证明和七 gate。实际 source/issuer/participant/qualification/coverage 的未来 host 必须独立接入。

## 本段离线验收边界

自身测试使用实际无连接 SQLAlchemy Session/活动事务、真实 ORM 类和 B 实际 owner 函数，SELECT 为显式替身；任何数据库 connect 都会失败。反例包含错 fullSHA、原组缺项/actor/op/material、旧 proof 当前产品版不同、源 raw optional key 省略、原锚重密封篡改、完整 child refs、微秒/TZ、私有受众、末端 Project/权限/时钟/UOW/原组变化。测试通过只证明结构读取合同，没有证明 PG/RLS/trigger/真实原件或生产资格。
