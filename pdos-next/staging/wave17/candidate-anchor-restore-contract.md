# Wave17 候选确认原锚恢复接缝

本段仅新增 `candidate_anchor_restore.py`、本段纯测试和本文。没有公共注册、DB/HTTP、业务写入、flush/commit、proof 消费、Receipt 或专业资格授予。它恢复真正未消费确认中的原材料，不是候选写入口，也不能装配七门禁肯定证明。

## 实际接口与绑定

```python
host = CandidateAnchorRestoreHost(actual_module)  # 可信服务器启动配置
restored = host.restore(s, ctx, command, payload, proof)
host.require_restored(s, ctx, command, payload, proof, restored) -> same restored
```

`actual_module` 必须是实际 ModuleType，操作精确为 `quality.capa.verification.candidate.record`，semantic 必须是实际 `candidate_commands.semantic`，Payload class 必须是实际 `CandidateRecordPayload`。模块、函数和 class 的启动身份固定；替换属性或 generic JSON owner 不被接受。本段不修改或自动注册该模块。

参数必须包含实际 Context、完整 Command、严格重新解析的 Payload，以及实际同 Session 中 persistent、完整已加载、干净且 consumed=False 的 Confirmation。主体必须具名 human、actor=requester、run=None，有当前写 Grant；Product revision 是共同水位，Issue revision 是独立 Current CAS，两者不能混同。

`RestoredCandidateAnchor` 是 frozen/eq=False/slots/weakref dataclass，字段：

- `anchor`：原 Confirmation.snapshot 中完整 StableCapaAnchor，保留全文与原 full_failure_proofs_sha256/anchor_sha256。
- `reviewed_snapshot`：原 13 键确认投影全文。
- `proof_id`、`proof_revision`、`proof_sha256`、`material_sha256`：实际 proof 身份、全部持久列摘要和实际共同 material_digest。
- `command_sha256`、`payload_semantic`、`current_issue_revision`：完整外层命令摘要、实际无 token semantic、当前 CAS。
- `session`、`uow`、`runtime_binding`：实际 Session/活动 root、所有 SAVEPOINT ancestor、bind 与本次运行端口/issuer epoch 绑定。
- `checked_at`、`expires_at`：全部 IO 后真实 UTC 钟，以及 proof/Grant 最早期限。

只有本 host 真正产生且弱身份登记的唯一实例可被 require；构造、copy/replace、其它 host/Session/Context/Command、修改材料或把原 UOW 换入新 SAVEPOINT 均拒绝。登记仅标记出处，不能缓存当前肯定结果。require 会独立重读全部实际 owner/来源/SQL proof，仍要求未消费。

## 原确认的精确材料

snapshot 精确 13 键，不接受多余授权字段或缺项：

`operation, payload_semantic, stable_anchor, binding, inspection, raw_source_basis, required_source_read_set, sources, authority_snapshot, policy_snapshot, owner_id, visibility, current_issue_revision`。

逐值严格解析 StableCapaAnchor/CandidateBinding/CandidateInspect 并保持原 JSON 结构，不能补 optional null 或重封原锚。原 semantic 必须精确等完整 Payload，仅移 confirmation_token；confirmation_token SHA、共同 material_digest、tenant/actor/product/operation/subject=Product、Product revision 全匹配。

inspection 必须保持 candidate_ref=None、indeterminate/三个 NULL 和原缺项；其完整读集、self SHA、raw source_basis SHA 精确核对。binding.basis 的完整 self SHA 与原安全子集 SHA 均重算；最后从实际原 Issue 与实际不可变行通过既有 `basis_from_issue` 纯投影核对 requirement、root cause、失败、措施 completion、用途、owner/visibility 等全部字段，不凭重新密封的 hash 接受改变。该纯投影不授权限。

原来源、basis 来源/读集必须被完整 closure 包含；≤20 且版本不冲突。raw source_basis 保持真正 native/上传分支稀疏键集与排序，不能 typed dump 补 null 后漂白旧摘要。用户 exact refs 经实际 evidence reader 核对；原结构化报告由实际原件/失败 bridge 核值，额外人工来源逐整行核位置/hash。共享候选不能含私人来源。

## 实际原锚刷新与三个准确例外

fresh 原锚不能由调用者传入。入口自己调用 `anchor_owner.read_anchor_from_actual_owner`，以原确认中的明确 origin.ref 读取实际原 Issue、完成共同组、全部固定失败/原件/retained/来源与 Project/Current。

v1 只允许 Current==origin，且真实两个 owner 的 needs_lineage_owner=False；有效后继也保守返回 `CANDIDATE_LINEAGE_OWNER_REQUIRED` 503，等待有限谱系 owner 正式接通。原 origin 全字段、来源、安全闭包和固定失败材料须逐值等 fresh 结果。

稳定失败材料仅沿已冻结 `anchor.stable_failure_material` 排除三条完整路径：

1. `result.retained.checked_at`
2. `result.retained.execution_window_elapsed`
3. `result.source_basis.runtime_stamp`

原完整 proof/SHA、固定 Start/计划/占用/usage、安全 epoch、issuer、配置/方法/原观察钟等全部保留。跨进程重启允许原存档 runtime_stamp 与本次运行不同；本次 restore 开始到末端的实际 callback 身份、issuer epoch/runtime stamp 必须不变。不能借这三个例外省略当前源/权限或授完整观察。

## 原始 SQL、最后时钟与活动事务

入口和全部 owner IO 之后都用 Confirmation **全标量列**、tenant/product/id 精确 WHERE、limit 2、autoflush=False 独立 SELECT。不通过 identity-map 旧对象或 populate 覆盖脏 proof；原始 SQL 图像必须等 loaded ORM 全部列。深层 JSON 未被 ORM dirty 标记的更改也会被实际持久列比较拒绝。

原 Issue/Current/Project 在全部来源 IO 后精确再读；最后 raw Confirmation 再读，随后 Product/Principal/Grant 独立 fresh scoped SELECT。完整 proof 全文前后不变，caller 的 watermarks、active/kind、can_write/access_epoch/expiry 必须相同。最后一次 Grant SQL 后才取真实 UTC 钟，核 created<=checked_at<min(proof expiry, Grant expiry)、不早于 actual owner checked_at，并再次核完整活动 UOW/Context/bind/runtime。查询或来源回调期间 crossing expiry、issuer ABA、权限撤销/停用、SAVEPOINT 切换均拒绝。

该 reader 不证明真实 false→true 消费。历史 consumed=True 明确不能 restore；也不能从原普通 True、输入 bool/hash 或该实例推断本次事务消费。

## 留给未来 prepare_write 的实际接线

未来公共 host 必须在消费前调用本 host，以真正 persistent Confirmation 为唯一旧锚来源，再将该 opaque restored 实例交给专用 prepare_write（目前尚未实现）。prepare_write 应核 host.require_restored，独立重新核当前候选输出、完整来源、新 operation 专业与政策，然后保持 `restored.anchor` 与原 reviewed_snapshot 的完整首锚，不能重新 seal fresh full proof，也不能直接把原 authority_snapshot 当当前资格。

正式消费仍由共同 consumer false→true 后第一行实际 ConsumptionHost 捕获；正式 writer 仍需真实 require_live、全部 owner IO 后 fresh 守卫和保存钟、Current CAS/单次 phase/同 UOW 的原子写入。消费后不能调用本段未消费 restore 来冒充 write 许可。冻结 candidate_prepare/candidate_write 未改，跨 HTTP 保存接缝尚未挂载；缺专用 write owner 仍 INTEGRATION_REQUIRED/503。

## 检查证据与限制

首轮 33pass/1fail 指出启动配置函数身份未捕获；已固定实际 semantic/class 身份。第二轮 37pass/1fail 是新推进钟 hook 误命中 actual anchor 内部 Grant 查询，真实 ACL 已正确拒绝；测试限定至全部 owner IO 后最后 Grant 查询，再次 38 项通过。随后增加重新密封改变真实措施材料反例。所有原日志保留。

测试使用真实无连接 SQLAlchemy Session/活动 SAVEPOINT、实际 persistent ORM 状态及实际 owner 调用链；raw SELECT、source bytes、bridge、专业/政策皆明确替身。连接事件主动拒绝连接，没有 DB、公共 pytest/HTTP 或生产资格结论。最终原始日志、退出码、精确来源 SHA 由本段 manifest/result 记录。
