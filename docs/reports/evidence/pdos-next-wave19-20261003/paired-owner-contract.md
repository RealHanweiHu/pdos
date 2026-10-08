# Wave19 实际配对 owner 接口

仅本次新 `paired_output_bridge.py` 及其禁连接纯测试；公共接线、HTTP/数据库验收由 Root 执行。本段不产生表、状态、占用、Confirmation、Receipt 或提交，不授当下 NamedReview 人员专业资格、独立性或七 owner 全部能力。

## 启动接线

```python
from pdos_next.paired_output_bridge import LivePairedOwner
owner = LivePairedOwner()
# Root 的启动接线显式将 owner 传入 ActualNamedReviewOwner(paired_owner=owner)。
```

实际协议沿 [`paired.PairedOutputReader`](../../../../pdos-next/server/pdos_next/domain/capa_effectiveness/paired.py)：

- `read(s, ctx, product_id, output_ref, *, at, write=False) -> ServerPairRead | None`
- `refresh(s, ctx, product_id, previous, *, at, write=False) -> ServerPairRead | None`
- `attest(s, ctx, product_id, read, structure, *, at, write=False) -> HostGateProof`

`output_ref` 是真正 Formal 当前版本行 ID/revision，而非 logical Request 或任意旧 Draft。`at` 只用于精确结构核验；所有 owner I/O 之后取实际 UTC 钟。调用方应使用原 `paired.read_paired_formal_output(..., reader=owner)` 的两轮独立 read/attest/refresh，不将 DTO stamp 或客户端布尔作为 gate。真实 `StoragePairReader` 提供 exact Current 配对及原 Receipt/RequestKey/Audit/Outbox/typed semantic；advanced Run option 与业务 `_reading` 的统一 dispatch 由 Root 接线，单显示 option 不足以证明回链预览/执行可用。

## 实际核验

1. 真实 Session、完整活动主/子事务链和 caller/engine 绑定；原始 read 实例登记仅防克隆/篡改，不缓存正向 owner 结果。
2. exact tenant/product/project/build/request/run 行及真实 Project 私有受众；固定行全部列保留哈希，不丢 authority/source_basis/input_snapshot。固定 Source JSON 转实际 strict DefinitionReference，再由既有 `evidence.refs_from_exact` 得到全文行 SHA；完整 union 1..20，超限/版本冲突拒绝。
3. `fact_sources_owner.read_source_closure` 对真实 caller 逐 source 核当前 ACL、native 登记 Receipt 或 uploaded Original、安全 epoch、真实 store bytes/hash/size；不存在已接 domain owner 时明确缺失。仪器测量原行由真实 report verifier 读取，不能用派生 Artifact 行替代。
4. 每个 saved authority 用真实原签发人、原保存时刻和 `retained=True` 路线独立重核原全部 facts/negative/issuer/current source epoch。当前消费者和原签发人分别守 ACL。末端重新取原签发人 Principal/Grant 标量，防全局停用/epoch/expiry 漂移未反映到 Product。
5. planned 使用真实 test resource owner，不授执行；最早界限包含当前 executor 完整 scope Current facts 的未来激活/失效边界。performed 使用 `inspect_retained_execution`，保留原 Start、实际发生钟、占用/样件消费完整证明；自然窗口结束不撤销真实历史执行。
6. result 以此新 Run 的 exact 版本及真正属于它的 Measurement 调用 `fixed_failure_result` 支持的固定查询；该函数核全 Run 的全部原件测量与数值规则/Projection，而不是采用旧 Issue FailureRef 或 OriginalFailureProof。返回 Run/Projection/basis/rules 必须和配对材料逐值相同；没有 Measurement 则明确缺数值 owner。
7. 所有字节之后再核 numerical narrow refresh、retained、原专业、完整 source_basis、原 raw 行、真实 Current group、Project、所有签发人和 caller/runtime；最后钟严格早于 source/caller/signer/plan 最早截止、保持完整 UOW。只排除 retained 的 `checked_at`/`execution_window_elapsed` 两个展示字段，固定 Start/资源/usage/source/issuer/epoch 不删除。

实际 `HostGateProof` 由上述入口签发，issuer 是本 owner 实例，绑定 Session/UOW/caller/scope/structure SHA。stamps 包含 acl/sources/professional/original_bytes/semantic/runtime；performed 加 retained，result 加 numerical_rules。它不证明当下 reviewer 独立性、不替代 Rule/Observation/applicability owner，也不证明本次 false→true 消费。

## 本段检查边界

禁连接测试使用真实公共 ORM、结构 verifier、存储 SELECT 形状以及冻结 Wave17 结构夹具；专业/bytes/retained owner 是显式替身。测试检验接口、完整绑定与失效守卫，不宣称实际 DB/生产资格或完整采样通过。原 fixture 失败及修复过程日志保留；最终退出码/源 SHA 以同目录 `paired-owner-result.json` 为准。没有运行 HTTP/PG、公共 pytest、浏览器或构建。
