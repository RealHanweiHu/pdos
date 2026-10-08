# G1.2 三方派生纯核 · 主线接入说明

日期：2026-10-02。DTO 版本：`derivation.v1`。本包只生成差异与采用候选，当前产品包的 `difference(previous, current)` 两方历史比较保持原样。

## 接口

模块：`pdos_next.engines.derivation`，Python namespace 父目录无需新增公共 `__init__.py`。

| 入口 | 输入 | 输出 |
|---|---|---|
| `snapshot_from_definition(view, variant_id=None)` | **主线已授权读取**的当前 Definition view | `DefinitionSnapshot`，将十进制字符串精确转为 Decimal |
| `merge_paths(snapshot)` | 固定 Definition 快照 | `field/<section>` 与 `specs/<key>` 的 `PathValue` 映射 |
| `three_way(request)` | `DerivationRequest` | `DerivationResult`：五类差异、前后/子版值、冲突、重新确认原因、缺项、请求摘要 |
| `accept_changes(request, selection, validation_port=None)` | 同一固定请求与绑定摘要的选择 | `AdoptionCandidate`：可继承内容、保留/新增覆盖、来源轨迹与待校验条件 |

输出 `kind` 固定为 `calculation_candidate`，没有发布状态、批准、发布身份、定义负责人或命令回执。`missing` 中的诊断带路径；`DerivationError` 是 `ValueError` 子类，具有稳定的 `code`，区分版本、路径、范围、摘要和未解决冲突等拒绝原因。DTO 结构校验失败仍为 Pydantic `ValidationError`。

## 固定输入与状态语义

`SnapshotRef` 包含 `definition_id / revision / product_id / variant_id`。`pinned_parent` 必须精确等于 `old_parent.ref`；新父必须同产品/变体范围、版本递增且具有独立定义 ID；子定义 ID 独立。主线还须从权威记录确认来源系列、实际版本/内容、父子关系与访问范围，纯核不能证明这些输入真实。

`DefinitionContent.specs` 是完整集合，按稳定 `key` 匹配。旧父已有规格在新父或子版完整集合中缺席，表示 `deleted`；旧父从未存在的 key 表示 `missing`。不得把稀疏覆盖列表直接作为完整 `specs` 快照传入。条目重新排序不改变含义。

七个可继承 section 为 `purpose / use_cases / requirements / constraints / unknowns / exclusions / sources`。未传 section 是 `missing`，显式 `None` 是 `null`；删除 section 须放入 `deleted_fields`，不得同时传该字段。`availability=unknown` 是仍存在的规格，保留完整条目和空目标，不补零。`conflicted / not_applicable` 按独立 availability 保留；不混成不存在或删除。

规格比较忽略本地 `owner_id / state`，保留数值、上下限、允差、值型、单位、工况、方法、判据、事实性质、原因和精确引用。Decimal 不经浮点，也不受当前 Decimal 运算精度影响。规格、来源和测试条件顺序不制造假规格变更；其他文字 section 的条目顺序仍按输入保留。

五类为 `unchanged / parent_only / child_only / same_change / conflict`。双方删除属于 `same_change`，父删除而子编辑属于 `conflict`。有显式覆盖且父更新与子值不同时也为 `conflict`，即使子覆盖目前与旧父同值。子差异缺少覆盖元数据时返回 `missing_override`，不伪造原因。

## 显式覆盖与采用

`Override` 记录合法路径、`set/delete`、原因、来源与 `ApplicabilityScope`。scope 描述请求中的子产品/变体及适用文字，**不代表权限或有效适用性**。非法路径、重复覆盖、覆盖动作与当前子值不一致、范围不匹配被拒绝。

`AdoptionSelection` 包含上次计算的 `request_digest`、选中路径、`resolve_conflicts`、原因、来源和子 scope。仅能选择真实父变化；冲突必须另外明确选择采用父值。缺失输入不得当删除采用。重复选择、无效路径、跨范围选择及摘要不一致均拒绝。

```python
from pdos_next.engines.derivation import (
    AdoptionSelection, DerivationRequest, accept_changes,
    snapshot_from_definition, three_way,
)

# 三份 view、pinned_parent、overrides、scope 和 selection_sources
# 均由主线从固定版本、访问范围和本次选择构造。
request = DerivationRequest(
    old_parent=snapshot_from_definition(old_parent_view),
    new_parent=snapshot_from_definition(new_parent_view),
    child=snapshot_from_definition(child_view, variant_id=child_variant_id),
    pinned_parent=pinned_parent,
    overrides=overrides,
)
comparison = three_way(request)
selection = AdoptionSelection(
    request_digest=comparison.request_digest,
    paths=("specs/power",),
    reason="采用已核对的新父版功率要求",
    sources=selection_sources,
    scope=scope,
)
candidate = accept_changes(request, selection, authoritative_reuse_port)
```

采用后的规格一律 `needs_confirmation`；原子版同 key 的负责人保留供主线复核，新条目负责人为 `None`。父版负责人、确认状态、批准、标题、发布状态及发布身份不复制。父 `nature=decided` 在候选降为 `extracted`，原性质与固定来源父版在 trace 保留，避免冒充子版已有人的决定。

未选覆盖保留，选中路径生成带本次原因/来源/scope 的新覆盖。`pinned_parent` 保持旧父，`offered_parent` 单独记录新父；选择性采用不宣称整个子版已经切换至新父。是否更新父引用、如何保留未选内容，须由主线独立决定并重新计算覆盖。

采用规格时，定义级来源并入所需精确引用，以免遗失保留规格的来源。显式选择 `field/sources` 时尊重其原值、空值或删除，不自动填回；缺少规格来源或定义来源会返回 `missing_definition_source`。超出当前草稿 20 来源上限返回 `definition_source_limit`，主线不能直接将候选写入。

## 主线权威 port 与写入边界

`ReuseValidationPort.assess(ReuseCheck) -> ReuseAssessment` 由主线实现。每个选中路径携带固定三版引用、所需来源与请求 scope；port 返回 `audience / cross_customer / applicability` 及依据。

无 port 可得到纯预览，每条采用 trace 带 `authority_pending`。任一权限或适用性为拒绝/未知，该路径不采用，返回 `reuse_not_permitted`；其他合法路径仍可返回候选。port 通过仍只有计算候选，不能作为服务器已授权事实，更不能作为 T1 确认或 T2 决定。

主线接入顺序：

1. 在服务器绑定身份/产品/变体范围，先授权读取三份固定快照及全部来源；不能先计算私有内容再靠采用 port 补做显示权限。
2. 从新的派生关系加载旧父引用和覆盖记录。当前 `DefinitionRevision.parent_definition_id` 是**同产品草稿续版历史**，不能拿它冒充 Platform/Variant 派生父关系。
3. 计算并展示差异、冲突、来源与未解决缺项；用户/受控工作请求提供选择和原因，明确冲突处置。
4. 通过权威 port 复核来源受众、跨客户权限及适用性；写入前再查固定版本、来源撤回、当前责任/成员资格与目标版本。
5. 用候选内容构造现行草稿 payload，保留**子版** title/visibility，使用本次 change_reason。现有同产品续版的 parent_definition_id/expected_parent_revision 应指向当前子草稿；派生固定父引用和覆盖另由主线管理。
6. 重新运行现行 `DefinitionDraftPayload` 及领域规则：纯核允许呈现缺失、None、删除的候选，不代替草稿/正式发布的有效性校验。只在共同命令入口中办理匹配操作级别的确认、事务、回执、审计与 Outbox。

Spec 字段直接对应现行 `DefinitionSpec`；`DefinitionReference` 对应 `artifact_id / expected_revision / line / quote`。adapter 去除 view 来源的 `title / status / spec_keys` 展示附加信息，不读取 `differences / source_status / created_at / visibility` 为政策事实。纯核仅导入当前公共 DTO/StrictModel，不导入旧 app、领域 handler、数据库、运行配置或服务。公共类型的具体哈希已记录，后续公共 DTO 变更需定向复核。

本包未创建 Platform/Variant 权威对象、未注册新操作、未改 handler/API/迁移/页面、未写平台或子版、未发布。无新依赖需求。G1.2/AT-04/05/10 业务整链与正式资格仍由主线接线并验证。
