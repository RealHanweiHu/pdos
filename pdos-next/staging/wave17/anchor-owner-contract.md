# Wave17 实际原完成锚组合入口 · 第六段暂存合同

本段仅 `anchor_owner.py`、`test_anchor_owner.py` 与本文三个新增暂存文件。用户已授权连续建设，主线负责公共迁入及实际联验；本段未挂载、不修改已冻结 SQL/模型/旧 owner，不运行 DB/HTTP/公共测试或构建。

## 接口和结果

```python
read_anchor_from_actual_owner(
    s: sqlalchemy.orm.Session,
    ctx: pdos_next.service.Context,
    product_id: UUID,
    issue_id: UUID,               # logical Issue
    origin_ref: anchor.VersionRef # explicit immutable completed row/rev/full SHA
) -> ActualAnchorRead
```

依赖真实活动 Session、完整主/嵌套 UOW、本人 server Context，和同 engine 实际配置的 `_pdos_quality_result_bridge`、`_pdos_quality_result_refresh`。回调不能由 payload 提供。缺任意回调返回 `INTEGRATION_REQUIRED`/503，无肯定 fallback、无新 assembly/gate 的布尔准入。配置仍由 Root 真实宿主负责，本段不配置合成 issuer。

返回：完整 `anchor.StableCapaAnchor`、`origin_descriptor: anchor_storage.StoredOriginRead`、末端实际 `checked_at`、`needs_lineage_owner`、`missing_owners`。实际运行已配置端口后，可以准确标记 `original_failure_bytes_verified=True`、`current_source_security_checked=True`；这两项描述本次调用了真实端口，不签发 HostGate。始终 `current_evidence_authorized=False`、`same_uow_consumption_attested=False`；原 raw descriptor 的三个核验标记与 completion_group.same_uow_consumption_attested 仍保持 False，避免改写原基础读取器的保证。

始终缺 `current_professional_policy_owner`。Current 与原完成 ref 不同，另缺 `limited_issue_lineage_owner`，保留全部原历史和当前实际描述；不因 Current 后继存在就授有限谱系，不删除历史比相等。此入口不提供 effectiveness/close、新专业审批、共同 False→True 消费、receipt、占用或批准能力。

## 实际 owner 调用与固定原失败

首先调用原冻结 `anchor_storage.read_origin_descriptor`：显式原完成 ref，不借 Current 任意旧版，不借 Owner Context。沿用其真实 Product/Principal/Grant、Project scope/private owner、原 Issue/前版/Current、完整 completion 和历史共同 Receipt/Audit/Outbox/原 RequestKey 证明。

每条原 `origin.issue.failures` 按原业务顺序调用实际配置 bridge：

```python
bridge(s, ctx, product_id,
       run_id=failure.run.id,
       run_revision=failure.run.revision,
       measurement_id=failure.measurement_id,
       event_id=None, write=False)
```

始终重新解析完整 `FixedQualityResult` 和 `OriginalFailureProof`，不相信 model_construct/model_copy 绕过验证。核 exact scope、logical Run、原 Run revision、measurement、purpose、nature、无未经选择的 event、实际 runtime stamp；原完整 FailureRef 的 Build/样件/实际配置/覆盖/判据/方法/测量源由原 `failure_ref` 精确相等闭合。`current`、完整 retained Start/实际时钟/计划/占用/消费/固定事实、确定 fail 与来源专业证明均由真实 bridge 实现，不从客户 UUID 或当前 Run 推导。

真实 bridge 的 private result 只当前实际 owner 可读；共享原调查不能把 private result 提升受众。共享结果的历史 owner 和原 Issue writer 可以不同，不凭其当前身份代替当前 caller，也不因为历史作者不再 active 就伪造撤销其原保存事实。

所有原件 IO 完成后，每条调用实际配置 refresh，`write=False`，入参是独立深复制的完整原 proof。仅 frozen `stable_failure_material` 中以下三条确切观察路径允许变化：

- `result.retained.checked_at`
- `result.retained.execution_window_elapsed`
- `result.source_basis.runtime_stamp` 的 stable 摘要例外；本入口另外要求其仍等于真实同 phase 配置 stamp，不能借此绕过签发变化。

其他 raw value、配置、source/安全/issuer/专业、Start、effects、plan 内同名字段全部保留比较。锚保存第一次实际 byte-read 的完整 proof，不用后来的观察钟或窗口已过字段重封原 proof；full proof SHA 和 stable material SHA 分开。旧窗口自然结束或旧资格按 Start 时钟自然到期不被此入口新增拒绝，是否仍为合法历史执行由原 retained owner 核定；这不产生当前执行资格。

## 来源和末端复核

完整来源 union 是原完成 row 与每条失败桥 readset，冲突版本拒绝、上限 20，不能截断。每条 named root/containment/hypothesis/completion 及真实发生源始终经 `quality_execution.evidence.check_source` 核 full-line position，即使它也出现在 bridge.sources。其他原 row refs 未被 bridge 实际核验时也走这一门禁。原报告 structured field/line/column 位置由真实 report bridge 核验，不当成人工 full-line 格式，也不因此省略根因和完成出处。

原 frozen `EffectivenessRequirement` 没有独立 SourceRef 字段，只有 method/acceptance/observation_until/required_failure_ids。本段完整保留要求及其原保存来源声明，不凭空创造要求出处、方法适用性或独立验证事实；后续实际 rule/专业 owner 仍须补齐。

第一次完整 `source_basis` 读取真实 `source_for`/原件安全或 native registration Receipt，typed SourceSafety 与原声明逐值对应；真实 sparse raw JSON 单独 deepcopy 保留，不补 null 键重算旧来源摘要。所有失败刷新后第二次读取完整 raw basis，全部值必须相同。

最重纯 `build_anchor` 在最后 caller IO **之前**完成。之后独立再调用真实原完成 descriptor（含 Current、Project、原保存组、caller）；再第三次完整来源 basis，防同 Session 的配置 reader 在其后改变来源。末端重新读取 exact 原行、Current、Project owner/visibility/scope，实际 Principal 与 Grant；采真实时钟在最后 Grant SQL 后，直接核 `Grant.expires_at > checked_at`、active human 和原保存钟，最后完整 UOW/Context/config stamp 核对。没有把较早 descriptor 的时钟当 wrapper 最终 TTL。

复用真实 `quality_result_bridge._runtime_stamp`，包括 security/results store/两回调对象身份、professional synthetic profile，以及 professional/test_resource/operational issuer 对象和 monotonic epochs。每个 bridge/refresh、最终 source/descriptor/控件 IO 后核该 stamp 和全活动 UOW/bind/Context；不能用最终 enabled/current 布尔掩盖 revoke→restore ABA。源 DB 安全闭包独立比较，runtime stamp 不替代 DB source basis。

## 业务只读与锁边界

本层不 begin/flush/commit/add、无 INSERT/UPDATE/DELETE、无新 connection、不消费 proof、不创建 Receipt/Run/资格、不保存全局或 Session.info 缓存，整个入口 no_autoflush。读仍沿用真实 bridge/`source_for`/`require_safe` 所需 SELECT FOR UPDATE，相关门栓保留在调用者同 UOW 至其 rollback/commit；不能称为 PostgreSQL READ ONLY transaction，后者会拒合法读锁。

Root 的实际观察工具应维持既定无业务 DML 边界与最终 rollback，不为此绕过源或桥门禁。Root 先前 PG READ ONLY raw descriptor 观察与本组合入口是不同范围。本入口不保证独立连接无门栓串行化，也不以当前 ProductGrant 代替专业 qualification。

## 本段检查与证据

仅新增 owned `--noconftest` pure：使用真实存储读取器、ORM/Session/Transaction 与明确 no-DB SELECT 返回，配置的失败/来源回调是显式 synthetic 替身。正例不等于实际原件授权、真实数据库约束、专业 qualification 或公开接通。

54 项覆盖实际 fixed binding/完整 raw origin/source、所有失败 IO 后逐条 refresh、多失败后序签发撤销、callback/runtime/issuer ABA、Current/Project/private漂移、来源安全/登记/稀疏 JSON 改变、完整读集上限、仅三观察路径例外、纯构造及末次 Grant SQL 期间到期、Session/UOW/ctx 换置、缺端口503、无 writer/连接和合法后继仅 missing。

首轮 49 passed/2 failed 均为新纯替身问题：来源 fixture 已带 `original:null`，测试所谓新增该键没有实际差异；Context 是 frozen dataclass，普通赋值先抛 FrozenInstanceError，未到 UOW guard。随后 source callback 显式按实际 sparse JSON 返回，Context 反例使用显式底层侵入模拟真实 binding 漂移，新增三末端时钟/源反例。首轮原日志保留，不冒充业务失败或全通过。

最终 54 passed in 2.41s，Ruff/format/AST/import 的准确 hash/命令与原始日志见 `anchor-owner-check-result-v1.json` 与 `anchor-owner-source-manifest-v1.json`。没有重跑原 53/61/87 包，没有 DB/HTTP/公共 build 或迁移检查。未来真实 runtime 观察、来源 bytes/professional组合及公开授权继续由 Root 办理。
