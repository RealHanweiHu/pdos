# Wave17 五表生命周期登记合同 v1（静态、未应用）

本材料给 Root 统一迁入模型/字段清单/迁移使用，唯一模型身份为 `a7b5f65137f5456f72aa32e9b50d8749ea7a62003f699dedf596495b0a174162`。全部五表必须 **GUARDED**；两张 Current 持有业务 anchor/来源/事实指针，不能标 **NON_CONSUMING**。本段只读源码，并用既有 server venv 在无连接新进程枚举模型列；没有 DB/HTTP/测试/公共检查/SQL 执行。系统 python3 首次生成尝试在 import 阶段缺 pydantic，未写文件，随后使用既有 venv 成功。

## 完整有序映射

实际 `table.columns` 顺序，共 **5表/195字段，50+23+53+20+49**。它不是已迁入数据库证明；`schema_covered` 比较列名集合而不要求 ALTER 后物理顺序相同。issuer key/version 100 字符、完整 purpose 与来源均保留，不因索引调整删除。

```python
# 静态复制材料；未应用到 public source。
COVERED_COLUMNS.update({
    'capa_verification_rule_facts': (
        'issuer_key',
        'issuer_version',
        'issuer_epoch',
        'external_id',
        'valid_from',
        'valid_until',
        'series_id',
        'previous_fact_id',
        'previous_revision',
        'revision',
        'writer_id',
        'actor_id',
        'requester_id',
        'command_id',
        'operation',
        'tier',
        'fact_kind',
        'status',
        'fact_body',
        'payload_sha256',
        'intent_digest',
        'sources',
        'required_source_read_set',
        'source_basis',
        'read_set_sha256',
        'input_snapshot',
        'authority_snapshot',
        'policy_snapshot',
        'shared_proof_id',
        'shared_proof_revision',
        'proof_expires_at',
        'proof_consumed_at',
        'token_sha256',
        'material_sha256',
        'product_id',
        'project_id',
        'issue_id',
        'capa_id',
        'origin_issue_version_id',
        'origin_issue_revision',
        'owner_id',
        'visibility',
        'nature',
        'purpose',
        'anchor_snapshot',
        'anchor_sha256',
        'requirement_sha256',
        'id',
        'tenant_id',
        'created_at',
    ),
    'capa_current_verification_rules': (
        'issuer_key',
        'issuer_version',
        'external_id',
        'series_id',
        'fact_id',
        'fact_revision',
        'epoch',
        'product_id',
        'project_id',
        'issue_id',
        'capa_id',
        'origin_issue_version_id',
        'origin_issue_revision',
        'owner_id',
        'visibility',
        'nature',
        'purpose',
        'anchor_snapshot',
        'anchor_sha256',
        'requirement_sha256',
        'id',
        'tenant_id',
        'created_at',
    ),
    'capa_observation_facts': (
        'rule_fact_id',
        'rule_revision',
        'rule_sha256',
        'issuer_key',
        'issuer_version',
        'issuer_epoch',
        'executor_id',
        'observed_from',
        'observed_until',
        'series_id',
        'previous_fact_id',
        'previous_revision',
        'revision',
        'writer_id',
        'actor_id',
        'requester_id',
        'command_id',
        'operation',
        'tier',
        'fact_kind',
        'status',
        'fact_body',
        'payload_sha256',
        'intent_digest',
        'sources',
        'required_source_read_set',
        'source_basis',
        'read_set_sha256',
        'input_snapshot',
        'authority_snapshot',
        'policy_snapshot',
        'shared_proof_id',
        'shared_proof_revision',
        'proof_expires_at',
        'proof_consumed_at',
        'token_sha256',
        'material_sha256',
        'product_id',
        'project_id',
        'issue_id',
        'capa_id',
        'origin_issue_version_id',
        'origin_issue_revision',
        'owner_id',
        'visibility',
        'nature',
        'purpose',
        'anchor_snapshot',
        'anchor_sha256',
        'requirement_sha256',
        'id',
        'tenant_id',
        'created_at',
    ),
    'capa_current_observations': (
        'series_id',
        'fact_id',
        'fact_revision',
        'epoch',
        'product_id',
        'project_id',
        'issue_id',
        'capa_id',
        'origin_issue_version_id',
        'origin_issue_revision',
        'owner_id',
        'visibility',
        'nature',
        'purpose',
        'anchor_snapshot',
        'anchor_sha256',
        'requirement_sha256',
        'id',
        'tenant_id',
        'created_at',
    ),
    'capa_named_verification_reviews': (
        'candidate_id',
        'candidate_revision',
        'candidate_sha256',
        'rule_fact_id',
        'rule_revision',
        'rule_sha256',
        'reviewer_id',
        'valid_until',
        'revision',
        'writer_id',
        'actor_id',
        'requester_id',
        'command_id',
        'operation',
        'tier',
        'fact_kind',
        'status',
        'fact_body',
        'payload_sha256',
        'intent_digest',
        'sources',
        'required_source_read_set',
        'source_basis',
        'read_set_sha256',
        'input_snapshot',
        'authority_snapshot',
        'policy_snapshot',
        'shared_proof_id',
        'shared_proof_revision',
        'proof_expires_at',
        'proof_consumed_at',
        'token_sha256',
        'material_sha256',
        'product_id',
        'project_id',
        'issue_id',
        'capa_id',
        'origin_issue_version_id',
        'origin_issue_revision',
        'owner_id',
        'visibility',
        'nature',
        'purpose',
        'anchor_snapshot',
        'anchor_sha256',
        'requirement_sha256',
        'id',
        'tenant_id',
        'created_at',
    ),
})

# 追加到原 GUARDED；原项全部保留。不要加入 NON_CONSUMING。
FACT_LIFECYCLE_GUARDED = (
    'capa_verification_rule_facts',
    'capa_current_verification_rules',
    'capa_observation_facts',
    'capa_current_observations',
    'capa_named_verification_reviews',
)
GUARDED = (*GUARDED, *FACT_LIFECYCLE_GUARDED)
```

Root 可沿原 catalog 风格直接追加五个 tuple 和 GUARDED 项；独立常量只是复制材料，不要求新增公共常量。原 `capa_remediation_links` / `capa_verification_evidence` 与其余旧登记全部保留。

## 完整公共接线点

1. `server/pdos_next/models.py` 从实际迁入 namespace 注册 `RuleFact`、`RuleCurrent`、`ObservationFact`、`ObservationCurrent`、`NamedReviewRecord` 到唯一 `Base.metadata`。不要同时导入 staged 与迁入声明导致同表双定义。
2. `server/pdos_next/lifecycle_catalog.py` 的 `COVERED_COLUMNS` 与 `GUARDED` 按上述完整映射追加。`lifecycle_access.NON_CONSUMING` 不加五表。
3. Root 实际单调迁移与公共 schema ledger 安装五表 enabled `lifecycle_reference`：`BEFORE INSERT OR UPDATE OR DELETE` 调用原 `lifecycle_reference_gate`。同时保留真实 RLS/权限、事实不可变、Current 窄更新、child/原子 proof/Receipt/Audit/Outbox 守卫，不能用登记替代这些约束。旧 gate 与 `next_0012` Inbox 投递非业务引用例外必须保留。
4. **实际 metadata/catalog/DB 必须同批一致**：`schema_covered()` 只比 DB 与 catalog；随后 `References.read_current` 遍历 Base.metadata。只加 DB/catalog 而未加载真实模型，会漏扫五表但仍可能 known。Root 必须同批 runtime 导入并做实际结构核验。本材料不改该公共函数。
5. 新写保留 Product 栅栏、Current CAS、真实 source/owner/proof 门禁。`source_for -> require_original -> require_safe` 的当前权限/安全检查仍在；完整 source/child 并集 ≤20。登记或 pure body/anchor 不能授 bytes/专业/current/同 UOW 消费事实，不能删 source_for 的锁。

## 递归保护的真实范围

`References.read_current` 在同 Product 栅栏下扫描 tenant/product 中受查 Current 与历史业务行，私人记录参与保留保护但不向用户返回正文。`_uuids` 递归字典/列表/UUID标量，从原件 ID 开始，命中引用行后加入该行 ID 形成固定点闭包。真实 `Artifact.original_id` 连接原件→Artifact；五表 `required_source_read_set[].artifact_id` 再连接 Artifact→事实。五表均不在 formal 排除集，命中其任意行即 formal history。

| 材料 | 可识别路径 | 不能冒充的覆盖 |
|---|---|---|
| fact_body / input_snapshot | 明确 UUID 字段及完整 artifact_id 读集可递归。 | 任意深度 `id` 被忽略，不能声称全部 typed Ref/kind 自动被识别。 |
| sources | 精确行/哈希保留，完整 Artifact readset 提供显式边。 | kernel SourceRef.id 被跳过；position/quote SHA 不反查原件。 |
| raw source_basis | host 保留并核完整来源原始材料。 | SourceSafety.id 与 OriginalSafety.id 也被跳过；必须完整读集+真实 Artifact.original_id。原生文本没有上传字节，不能制造 Original。 |
| anchor_snapshot | mapped origin_issue_version_id、明确失败引用、来源并集与保留历史可传递。 | anchor SHA 或纯 ref.id 不够；完整 anchor/原材料不被摘要代替。 |
| fixed child / Current / previous | fact_id/rule_fact_id/candidate_id/previous_fact_id/origin_issue_version_id 等非通用 id 的真实列可连到旧事实。 | Review observations 的 FactRef.id 本身不形成边；其全 child 来源并集仍须保存。只有 child SHA/未知 kind/字符串化 JSON 不反查。 |
| proof / receipt | mapped shared_proof_id 会扫描；Receipt.subject_id 等真实业务引用可传递。 | confirmations 为 NON_CONSUMING，单凭 proof/material hash 不恢复来源、更不授专业或安全事实。 |

**实际 SQL gate 是另一层**：源 `next_0011` 中 `lifecycle_reference_gate` 先锁真实 Product，再做 `position(original.id::text in payload::text)>0`，阻止直接含原件 UUID 的 pending/quarantined/unknown/purged 新引用，并推进 Product lifecycle epoch。它不递归查 Artifact/Fact，也不重建 Python digest；正文出现 UUID 可保守命中。只持 Artifact UUID 的写入仍要由真实 host `source_for/require_safe` 拒绝已失效/隔离来源。不能称 SQL 子串 gate 已覆盖全部 Python 递归来源。

## 必须明示的未知与限制

- `_uuids` 任意深度跳过 id、tenant/product/owner/actor/requester/writer 等身份键；字典键不扫描。hash/digest/kind-only/position/URL/字符串化 JSON 不会解码反查。
- full child/readset/Artifact.original_id 缺失时，字段齐全不代表引用完备。不得只凭五表登记 self-seal complete；Root 必须核真实来源闭包与全部 child。
- 未知表/列、禁用 gate、Journal 不完整、单表>2000或总行>12000、库存>100页，都应 reference_count/formal_history=None，不补零。已登记不意味着 complete=true。
- 注册原件即使 parse_failed 仍 REGISTERED_ORIGINAL 受保护；引用及 formal_history 独立阻止回收。恢复不解除扫描/撤回/ACL；purge 纯资格判断不是物理删除授权。
- `schema_covered` 只查 enabled 触发器名称及函数名，未验证函数内容。本段未读取实际已安装 SQL；Root 实际迁入后另核原 gate 实现及同批守卫。

## 受影响的真实 selected tests（本段未运行）

下表为当前源码存在的选择点。描述需“扩展”者是五表的新验证缺口，旧 Artifact 或生命周期用例不能算本批五表已通过。

| 文件 | 选择点 | 影响 |
|---|---|---|
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_reviewed_business_write_advances_reference_epoch_and_invalidates_preview` | 当前使用 Artifact；须扩展五表合法写入/Current CAS 的 epoch 变化。 |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_unreviewed_schema_is_unknown_and_transactional_ddl_is_always_rolled_back` | 当前 unknown_table/unknown_column/disabled_trigger；须增加新表缺列/禁用 gate 与 runtime metadata 缺登记。 |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_product_fence_is_held_through_real_storage_effect` | 当前 Artifact 并发；须扩展新事实及 Current 写入不穿过 Product 栅栏。 |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_missing_journal_unbound_original_and_partial_inventory_cannot_prove_orphan` | 缺日志/部分库存仍未知，不补零。 |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_registered_original_is_never_orphan_even_when_parsing_failed` | 保留 parse_failed 参数，注册仍受保护。 |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_rls_agent_zero_direct_access_and_immutable_candidates_and_object_identity` | 当前旧生命周期实体；须另核五表 RLS、app/agent 权限、事实不可变和 Current 窄更新。 |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `test_lifecycle_event_claim_and_ack_preserve_reference_epoch_before_real_effect` | 保持 next_0012 Inbox 投递例外。 |
| `pdos-next/server/tests/original_lifecycle/test_rules.py` | `test_unknown_protected_live_or_derived_facts_never_become_orphans` | 未知保护事实不能判孤儿。 |
| `pdos-next/server/tests/original_lifecycle/test_rules.py` | `test_authoritative_refs_and_formal_history_protect_even_expired_failed_uploads` | 引用/正式历史独立保护。 |
| `pdos-next/server/tests/original_lifecycle/test_rules.py` | `test_recovery_preserves_referenced_held_history_but_unknown_or_purged_bytes_block` | 恢复保留历史，未知或失效字节继续阻塞。 |
| `pdos-next/server/tests/original_lifecycle/test_service.py` | `test_new_authoritative_reference_invalidates_preview_and_is_never_recycled` | 新真实引用使旧候选失效。 |
| `pdos-next/server/tests/original_lifecycle/test_service.py` | `test_reference_writer_cannot_enter_between_final_validation_and_physical_marker` | 保持末端读取到实际效果的栅栏。 |

Root 集中新增/扩展最小覆盖：actual metadata/catalog/DB列及5个enabled gate；Original→Artifact→新事实/Current历史闭包（含私人来源）；Review child 全来源union；禁用新表gate/漏列/超限返回unknown；direct 原件UUID与Artifact-only隔离引用分别由SQL/host拒绝；合法新事实/Current写推进epoch、不可变和窄更新不退化；五表forced RLS/agent无DML；registered parse_failed 与 Inbox 例外保留。仅在Root已核对的独立环境按影响执行；本材料不提供测试结果。

## 读取源 SHA

以下是本次静态身份；Root公开迁入后会成为新候选，必须生成新的真实覆盖证据，不能借此宣称 SQL 已跑。

| 文件 | SHA-256 |
|---|---|
| `pdos-next/staging/wave17/fact_storage_models.py` | `a7b5f65137f5456f72aa32e9b50d8749ea7a62003f699dedf596495b0a174162` |
| `pdos-next/staging/wave17/anchor.py` | `55a8446b68e9bbd466b9bf80ba7de44680ad587da353a4b56b3ed0b93156073e` |
| `pdos-next/staging/wave17/fact_registry_storage.py` | `18c7d06f06ee67d23ce82ef2ee6141781be4b7528f5d7a3325b6f02587ec46c7` |
| `pdos-next/server/pdos_next/lifecycle_catalog.py` | `8b2031769c02bc57e94b61cbf1199da917178ffd2fec6f05d029851daf660f3e` |
| `pdos-next/server/pdos_next/lifecycle_access.py` | `0137cecae4a937264b6a2607ca4f0f2a2e518192ca0329e2c89106cec2ee84a9` |
| `pdos-next/server/pdos_next/models.py` | `6397c986d170c5ea7d3b31ad3030990c18d4b31811393334dea209e0d6c570d3` |
| `pdos-next/server/pdos_next/original_lifecycle/rules.py` | `263f0783169fe6d74ebe008eee500ab3e276888a79261313fe63f7bb98e7653a` |
| `pdos-next/server/migrations/versions/0011_original_lifecycle.py` | `1812c85b8c1f09aaed5283f53bc3f0d7fa1c7cb457591fdaaaf2d9ec17cd2dd4` |
| `pdos-next/server/migrations/versions/0012_lifecycle_delivery_independence.py` | `2d399d7a63d6bce42a9a467fbdd8cca5bf19203111f1ec414d6bdbc6e5f38255` |
| `pdos-next/server/pdos_next/service.py` | `a710834b172d33de60f713333fd63a5d2d6bab3c39d5a7002b03c7d3d2982686` |
| `pdos-next/server/pdos_next/original_security.py` | `e4cf1636c8f07f06dec043273688ce6099c6a0b0189ff4a53d0bdcba93b90952` |
| `pdos-next/server/tests/test_original_lifecycle_integration.py` | `6f06d603cb15f63986b689949892aa439b8da80b447518857ef6f5a4203789ee` |
| `pdos-next/server/tests/original_lifecycle/test_rules.py` | `3fb7a5ab02235ca6b711c27139ee5d5b0ee4b07141c486335b5ce21e81f4c579` |
| `pdos-next/server/tests/original_lifecycle/test_service.py` | `5988657875012c8c3e6837e2bbcaf58aa557d7014834b84b63df6bd5f3efde93` |

同伴 `docs/reports/evidence/pdos-next-wave17-20261003/fact-lifecycle-registration-v1.json` 记录 `coverage_complete=null`、`status=static_proposal_not_applied`。唯一新增这两文件，没有修改模型/SQL/public/测试源码。
