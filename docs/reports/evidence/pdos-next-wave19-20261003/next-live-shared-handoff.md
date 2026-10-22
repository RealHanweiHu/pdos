# Wave19 下一段：统一配对输出与共享 Link 原签发人重核

实施前接线合同，只读核对；本文件不修改运行源码、不接数据库/HTTP、不授真实资格或独立性。当前 `LivePairedOwner` 已有 24 项禁连接纯检查，实际公共读写验证由 Root 统一完成。advanced Formal 业务 dispatch 和合法共享 Link 的原签发人重核仍是明确缺口，不能以 option 显示或单个 DTO 哈希宣布接通。

## 1. advanced Formal 必须统一进入业务 owner

实际调用链是 [`views._option`](../../../../pdos-next/server/pdos_next/quality_followup_views.py:161) → [`owners._reading`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py:321) → `_owner`。`_option` 之后还要求直接保存该版本的 Receipt；但 actual Start/结果动作的 Receipt 主体是 Run，Formal 会同步追加，或者 Review 不追加 Formal。不能借旧 Draft Receipt 为当前 advanced Formal 作出处。

不仅 GET：[`resolve_followup_outputs`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py:433) 两次读取每个输出；保存后的 [`_link`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py:620) 再次 resolve，并逐值比较保存的 outputs、source basis 与受众。只在 views 中绕过直接 Receipt 筛选，会形成“列表可选、inputs/preview/execute/回读不等价”的入口。

最小实施位置：新增启动配置的 `paired_followup_adapter`，由 **`capa_verification._reading` 的 verification_request 分支**统一调用；views 的 option 也取同一读结果的实际配对 Receipt，而非另一套许可计算。仅处理无精确直接 Current Receipt 的 advanced Formal，旧直接保存路径不改。

建议冻结内部协议（不是公共 RPC、客户端不能传 owner）：

```python
@dataclass(frozen=True)
class PairedFollowupRead:
    output: OutputReading
    receipt_id: UUID
    pair_read: paired.ServerPairRead
    structure: paired.StructuralPairProof
    host_gate: paired.HostGateProof

class PairedFollowupOwner(Protocol):
    def read(self, s, ctx, product_id, basis: FollowupBasis,
             ref: OutputRef, *, write=False) -> PairedFollowupRead: ...
    def refresh(self, s, ctx, product_id, basis: FollowupBasis,
                previous: PairedFollowupRead, *, write=False) -> PairedFollowupRead: ...
```

`read_option(s,ctx,pid,basis,ref,owner) -> (dict, OutputReading)` 可作 views 的薄包装，但它不能是唯一业务接线。缺 startup owner 返回明确 `INTEGRATION_REQUIRED`，不回退旧 Draft 或借普通 SourceRef 存在授能力。

- `ref.kind` 必须是 `verification_request`、`ref.key is None`，ID/revision 是实际 Formal Current 版行，不是 logical Request。
- 有界读取同 tenant/product/project/build/request 的 Current Run；最多 20，超限拒绝，多个匹配必须报歧义或要求明确实际候选，不能按最早/最新选择。当前 oneRun identity 的唯一约束不能替代完整读取绑定。
- 复用真实 [`StoragePairReader`](../../../../pdos-next/server/pdos_next/domain/capa_effectiveness/paired_storage.py) 与 [`LivePairedOwner`](../../../../pdos-next/server/pdos_next/paired_output_bridge.py:404)，再调用 `paired.read_paired_formal_output` 的两轮独立 owner 核验；basis scope/project/purpose/build 与 actual PairBinding 必须逐值一致。
- Receipt 正确字段是 `pair_read.material.receipt.id`；当前 typed 材料没有 `writer_group.receipt.ref`。必须是当前真实配对 LaunchFact/ResultAction 的原 Receipt/Audit/Outbox/RequestKey/typed semantic，不能以 family 为 Formal 就猜 Receipt 主体。
- meaning 取实际结构 proof 的 `planned/performed`。现 `_reading` 把所有 Formal 默认为 planned，不能沿用此分类来宣称 advanced Formal 实际未执行或已执行。

## 2. 固定输出材料与当次许可分离

新 OutputReading 仍沿现 DTO；fixed snapshot 保留实际 Formal/Run/plan/原子组身份与完整固定业务材料、原保存 authority、来源读集/安全依据，以及 retained 中原 Start/occupancy/sample usage 的固定证明。数值读取必须绑定此新 Run 的全部实际 Measurement/Projection/rules，不能用原 Issue FailureRef。

当次 `HostGateProof`、当前 caller/Grant、checked_at/剩余期限，以及 live 专业/来源许可留在内部 `PairedFollowupRead`，**不保存为 immutable output 的业务真实性替身**。只排除已明确的 retained 展示钟 `checked_at`/`execution_window_elapsed`，不能泛化删 source、method、window、issuer 或 epoch。

源码精确说明：`paired.verify_paired_material` 的 `material_sha256=digest(_json(m))`，`m` 是完整 PairedMaterial，因此这个 SHA 本身不含当前 caller；`StructuralPairProof.binding` 才含 caller。此前消息将二者混同，在此纠正。结构材料 SHA 可随对应完整实际材料保存，仍不能单独充当 live gate；完整 proof 对象与 HostGate 均有当次 Session/UOW/caller 绑定，不直接进入固定 snapshot。

如果新增 snapshot schema 会改变旧 Link 的逐值回读，不能重写原不可变记录或静默清除 needs_recheck。旧直接路径保持原形状；新 advanced 输出采用明确版本化配对描述，需新 Link 引用新 exact 输出。方法/window、当前指针、源安全或实际专业相关 epoch 真变化仍须拒绝/重核。

## 3. 共享 Link 专业重核必须使用真实原签发人

[`professional.recheck_snapshot`](../../../../pdos-next/server/pdos_next/domain/professional_authority/service.py:743) 明确要求 `snapshot.subject_id == ctx.requester_id`。现 `_link` 用当前消费者 ctx 调用，即使 `retained=True`，Maker 签发的合法共享 Link 由独立 Reviewer 消费时，也会得到 `AUTHORITY_SCOPE_MISMATCH`/`RECHECK_REQUIRED`。这不是专业角色缺失的证明。

最小修复是在 `_link` 已完成 **真实消费者** fixed row、Issue/CAPA/Project、输出、全来源/原件受众核对后：

1. 从实际 immutable `RemediationLinkRecord.writer_id` 取原 signer；要求 `authority_snapshot.subject_id` 精确等于此 writer、operation 为实际 Link 操作、scope/purpose 与保存 basis 一致，不能从客户端传 signer。
2. 仅构造 `Context(ctx.tenant_id, signer, signer)` 交 `recheck_snapshot(..., at=真实当前UTC, write=False, retained=True)`，保留现 Link 当前专业时效规则；不改成旧 created_at 来放行已失效资格。原 fact refs/负事实/relevant 新事实/issuer/source/Current/Grant epochs 继续守卫。
3. 此 Context **仅用于原专业签发证明读取**。所有 Link/Issue/Project/输出/原件字节和源闭包读取仍用真实消费者 ctx；新 candidate/Observation/NamedReview 操作资格也分别用当前具名 actor assess。不得借历史 owner Context 读消费者不可读的 private 材料。
4. 将原专业证明完整 reads 纳入当前消费者的真实源闭包，原 signer 原文可能仍为 private，Product Grant 不扩大其受众；有任何不可读材料就保守拒绝，不能仅隐藏 title 后继续授资格。全闭包不得超过 20。
5. 全部 owner/原件 I/O 后独立重核原 signer 当前 Principal/Grant/issuer/source 与消费者 ACL、Current/runtime，最后真实钟核期限/UOW；不能跨 inputs/preview/apply/replay 缓存正向证明。

可用窄 helper `recheck_link_signer(s,ctx,pid,actual_row,*,at) -> dict`，但 actual_row 必须已由当前消费者的真实 fixed owner 取得，不接受任意 JSON authority。它不授权当前消费者写入，也不能证明 Reviewer 的独立性；独立性仍由 actual participants owner 排除完整参与者。

## 4. 最小验证与归属

纯检查应击中：实际 advanced Start/Import/Review 的 paired Receipt（包括 Formal 不追加的 Review）；GET/inputs/preview/apply/保存后 `_link` 调同一 owner；wrong Current/scope/purpose/ref.key、多 Current 歧义、私有 Project/原件、晚 I/O issuer 或 TTL 漂移均拒绝；输出稳定材料不混 caller/Grant/实时钟。共享 Maker→Reviewer 的 saved signer 检查要验证真实 ctx 分离及 relevant/negative/ABA/expiry 仍拒绝，不能只测新 Context 字符串。

Root actual 验证应新建合法产品共享来源的失败/Issue/CAPA/Link 与复验链，具名独立 Reviewer 自己有当前真实职责资格。原私有 Issue/Run 不扩围，也不用 peer Grant 或 owner Context借读。实际读取 before/after 来源、Current、原件与数值、全 participants；保存 T2 后核唯一 Receipt/Audit/Outbox、原 proof/记录不重消费，以及末端异常零新增。现 Root 当前 HTTP 检查点可保留 advanced 缺口，不把 direct CurrentRun 枚举等同以上业务路径通过。

实施分工最小化：独立新 adapter+owned pure test；主线统一 startup callback、`capa_verification._reading/_link` 与 views 的薄接线、实际 HTTP/事务验证。`paired_output_bridge.py` 及其现 24 pure 冻结不改；不新增表/第二 Current/占用或提交，不在本合同扩大有效性/关闭能力。
