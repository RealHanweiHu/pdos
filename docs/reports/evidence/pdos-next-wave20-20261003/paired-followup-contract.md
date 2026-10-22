# Wave20 PairedFollowupRead：真实业务 owner 接口

本交付为配对正式输出的只读适配器。没有新增表、第二 Current、预约/样件消费、Confirmation、Receipt 或 commit；没有授予专业资格、独立性、措施满足、正式有效性或关闭许可。Root 统一进行公共配置及实际 HTTP/PG/UI 验证。

源码：[paired_followup_adapter.py](../../../../pdos-next/server/pdos_next/paired_followup_adapter.py)。B 独占 `capa_verification.service` 的业务分派和原签发人重核，Root 独占 startup/views 接线。原 Wave19 LivePairedOwner 及其证据保持。

## 真实接口

```python
configure(engine, paired_owner: LivePairedOwner) -> PairedFollowupOwner
configured(s) -> PairedFollowupOwner | None
owner.read(s, ctx, product_id, basis, selected, *, write=False) -> PairedFollowupRead
owner.refresh(s, ctx, product_id, basis, selected, previous, *, write=False) -> PairedFollowupRead
```

`engine._pdos_paired_followup_owner` 只保存可信启动配置，不保存 phase 证明。Root 共用传入 `ActualNamedReviewOwner` 的同一 LivePairedOwner 对象；只有真实 LivePairedOwner 可以配置，StoragePairReader 不能替代 live 门禁。

`owner.runtime` 是新的只读字典：`schema_version/configuration_id/epoch/paired_owner_identity/owners_runtime_sha256`。重配置推进 epoch；最后一字段复用现 `quality_result_bridge._runtime_stamp` 对真实 engine 的专业/资源/供应 issuer、store/security/bridge/refresh 注册表摘要。计算该纯注册表摘要的 engine facade 不是 Session/UOW 或授权证明。所有真正读取另要求实际 SQLAlchemy Session 的完整活动事务链。

返回 opaque frozen identity handle 包含：

| 属性 | 来源/用途 |
|---|---|
| `output: OutputReading` | 唯一可进入既有 ResolvedOutputs/Link 的稳定领域输出 |
| `receipt_id: UUID` | actual `pair_read.material.receipt.id`，同时精确等于结构核 Receipt ID |
| `pair_read: ServerPairRead` | 第二轮 actual LivePairedOwner refresh 后并实际 attest 的原材料 |
| `structure: StructuralPairProof` | 既有规则核验结果；structural-only 不变 |
| `host_gate: HostGateProof` | 同一 actual owner/Session/UOW/caller 签发的当次 live gate |

后四项不进入保存输出 snapshot/hash，尤其不将当前消费者、Grant 剩余期限、当前 checked_at/runtime 或 Gate 作为不可变输出身份。Root/B 可以在本 phase 局部栈保留 handle；不得写 Session.info、跨 inputs/preview/apply 缓存肯定证明。所有 handle 仅 weak 登记实际 Session 与对象 identity，克隆或修改正文不能 refresh。

## 分派与固定身份

只处理 `OutputRef(kind='verification_request', key=None)` 的五项实际 Formal.operation：

* `verification.schedule.promise`
* `test.run.start`
* `test.results.import`
* `test.run.review`
* `test.disposition.decide`

`test.run.plan` 不追加 Formal，实际 Formal 模型不允许该 operation。draft/offered/accepted 的旧 direct owner 路径和直接 Run owner 路径均由 B 保持；adapter 对不属于此集合的 Formal 明确 `PAIR_NOT_REQUIRED`，不借旧 Draft Receipt 放行 advanced 输出。

输入 basis 的 Scope/purpose 与 actual Formal/Build/Run 精确核对。当前 Issue/CAPA/有限谱系重核仍由调用的真实 CAPA owner 负责；传入 DTO 本身不证明当前 Issue。实际 Formal 版行 id/revision、logical request、Build/project/双配置、RunIdentity、唯一真实 Run Current 与版行、actual paired Fact/Receipt/Audit/Outbox/RequestKey 均沿原 storage/live owner 核验。

adapter 的 RunIdentity/Current/版行 SQL 每次上限 2：仅按精确 tenant/product/request/version 查找，发现第二行拒绝，不排序挑最新/最早。原 StoragePairReader 核真实 Current 和唯一配对事实。private Formal、Run 与 Project 都由 actual consumer 的真实权限核，消费者不能借原 owner/signer Context 读取资料。

## 稳定材料与 refresh

读取复用 actual owner `read → attest → refresh → attest` 两轮、`verify_paired_material` 和 `_validate_gate`；序列与 frozen live wrapper 等价，额外保留第二轮 ServerPairRead。没有复制业务状态机或签发匿名 Gate。

每轮还调用真实 `front.get_request(..., assess_capabilities=False)`，保留父 Preparation/请求/Current、Method/Window/current/reasons、documents/freshness 与完整来源检查；仅跳过当前调用者未来三个命令 UI 能力。完整 parent/固定 Method/Window/Run/Fact/Projection 来源读集与真实 source_basis 纳入固定输出，超过 20 或同一 source 两 revision 明确失败。

snapshot 保留上述真实固定显示材料及完整 canonical `PairedMaterial`。只排除 top-level UI authority/capabilities/checked_at/created_at、旧未接通 blocker 和可变计数，不递归剥离历史参与者、原签核时钟、计划、测量、原始来源、安全/issuer epoch 或固定业务正文。完整 PairedMaterial 本身不含当前调用者的 PairBinding/HostGate。

两轮必须相同：配对材料 SHA、全部 actual GateStamp、有效期、固定 child snapshot、实际 source_basis。refresh 独立重新执行整个 owner 门禁，并对照上次稳定 OutputReading/Receipt/结构/门禁材料；原 handle 已过期不能通过新 phase 刷新为肯定。

最后 SQL current consumer ACL 后再核配置/runtime、完整 UOW，取真正 post-IO UTC clock 检查 Gate 的独占终点期限。Root 若在 adapter 返回后还有 owner/Current/consumer IO，仍必须在公共 phase 末端核其收集的 Gate 期限及 owner runtime；本 adapter 不替代 Root 的 post-all-owner closure。

## 检查范围与证据

[paired-checks-v1.json](paired-checks-v1.json) 记录最终两份源码、命令、日志 SHA 和前后 source_stable。

* [最终纯检查](paired-pure-05.log)：28 passed / 2.28 秒。
* [Ruff](paired-ruff-02.log)、[format](paired-format-02.log)、[AST/cold import](paired-import-02.log)：退出 0。

测试使用 actual ORM/结构核/LivePairedOwner/UOW；SQL SELECT、原件、专业、计划资源与 front child reader 明确替身，不加载 DB fixtures、没有连接 DB/HTTP。包括五种操作真实共同组形状、不同合法 consumer 的固定输出一致/实时 Gate 不同、多 Run 与无 Receipt 拒绝、private/scope、完整来源上限、配置/Current/child 漂移、伪造/修改 handle、嵌套 UOW、末端过期、bool revision 严格重验。原 Model 的 JSON serializer 会把通过 model_copy 注入的 bool 转成整数，本段输入改用 python material 先 strict reparse，再规范 JSON 输出。

历史失败不删除：`paired-pure-00-captured.log` 是首轮 25 fixture DTO 失败的工具截断输出，明确不是完整原始日志；`paired-pure-01.log` 保留 4 fixture 边界失败/21 pass；`paired-pure-03.log` 保留 bool-copy reparse 的 1 failure/27 pass。`02/04` 为中间通过候选，不叠加最终覆盖。先前静态检查的未使用 import 已纠正，最终记录仅绑定当前两文件。

实际 PG/HTTP、跨具名共享 Link 的 inputs/preview/execute、旧 Link/Receipt 字节保持和性能测量由 Root 后续统一完成；本交付不宣称这些实际验收或 G3 已通过。
