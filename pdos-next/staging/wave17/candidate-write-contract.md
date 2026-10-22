# Wave17 第七段：同次真实候选写入暂存合同

状态：暂存实现，未挂载共同 writer、未执行数据库/HTTP 验证。不新增用户批准关卡；当前仅依主线划定范围建设。候选不授有效性、关闭、专业职责或实际运行许可。

## 公开接口

```python
reviewed_prepared_candidate(phase) -> dict

apply_prepared_candidate(
    s, ctx, command, product, payload, phase, *,
    consumption_host, module, proof,
    consumption_binding, consumption_marker,
) -> (CapaVerificationEvidence, "capa_verification_candidate", visibility)
```

`phase` 必须是 A `candidate_prepare.prepare_candidate` 在同一真实 SQLAlchemy `Session`、主事务及完整活动 SAVEPOINT 祖先链产生并登记的原对象。客户端/复制/自行构造 DTO、不同当前调用者或事务不得替代它。A 的 `reviewed_candidate` 保留首次完整 `StableCapaAnchor`；本模块仅添加准确的 `operation=quality.capa.verification.candidate.record`，其完整来源读集、业务选择和当前资格/政策材料不删减。不得把此摘要作为读取授权。

`consumption_host` 必须为 Root `fact_consumption.ConsumptionHost` 的实际实例，注册的 `module` 必须是共同执行所用的真实语义 owner。本模块不能配置公开 operation、消费 Confirmation 或构造可信标记。`proof` 是同一 Session 真实、完整加载的持久 `Confirmation`；binding/marker 必须是该宿主在共同消费的实际 False→True 赋值前后签发的原 identity。已消费历史行、bool、复制的 `LiveConsumption` 不满足条件。

## 实际执行顺序

1. 核完整活动 UOW、真实准备登记、当前具名 human、完整 Command（含原 key、token、读集顺序）、payload 与真实 semantic、Product 的持久身份/范围/当前修订。比较精确来源集合、origin 与 Current CAS；二者不混用。`Product` 行锁仍由共同调用者保持，本段不新建事务或查询权限。
2. 调用真实 `ConsumptionHost.require_live`，核原持久 proof 的字段及真实 common intent、material/readset/token 摘要。common intent 使用真实 operation/product/domain-semantic/named-actor/private-owner 公式，不能用 domain digest 替换，更不重造已丢失 token 的历史 request_digest。
3. 真实 proof.snapshot 必须等本次完整 material，尤其 `stable_anchor` 必须等原准备阶段首次完整锚。本段对新的 full-anchor SHA 不作假匹配。
4. 调用 A `require_prepared_candidate` 独立重读全部实际 owner、旧失败原件/出处、来源安全、政策及专业事实。只允许冻结的三条观察路径参与 stable 比较排除；保留首次 full proof/anchor。再核 Command/Product/Bound 的完整材料与原 proof.snapshot，不能在 owner IO 中换 nested dict 或 Current。
5. 复制保存的原始稀疏来源安全闭包、完整 basis/binding/inspection、专业/政策快照。在所有 owner IO 完成后再次真实 `require_live`，捕获当前 UTC 保存时钟；调用 A `require_prepared_candidate_clock` 核专业/政策/Grant 期限和未来激活边界、真实 UOW/runtime 及材料身份，另核 first-consumed-at ≤ saved-at < proof.expiry。
6. 失效单次 prepare 登记，再且仅再 `s.add` 一个候选。任何认可该原登记后的失败均不允许复用本 phase；外层共同事务拥有消费回滚、Receipt/Audit/Outbox 与整体 rollback。不得在同一个 failed phase 重试；重新经过共同当前 gate 和准备协议。

全部最终检查后的 flush/COMMIT 延迟不声明另有 COMMIT 时钟 TTL 守卫；此段保证所有实际 IO 后的当前有效性与准确 `created_at` 保存钟绑定。SQL 约束须按真实安装版本另行验证。

## 保存事实与回执交付

仅复用现 `domain.capa_verification.models.CapaVerificationEvidence`，不新增实体或第二真值。继承 origin 的 tenant/product/project/logical Issue/固定完成版本/CAPA/purpose/nature/owner/visibility，writer 为本次实际 actor。所有原根因、措施、完成、失败、来源及历史均完整保留在 anchor/basis；不推进 Issue Current。

固定 `revision=1/status=candidate/result=indeterminate`，`applicable/independently_verified/observation_complete=None`。映射/独立复核/观察依据缺失保留 inspection 缺项，可保存待核候选，不授 pass/effective/close。完整 source union 上限 20 由 A 真实准备核定，不截断。

`input_snapshot` 精确四键：

```text
semantic        # 实际 typed domain semantic，去 token
shared_proof    # {id: 本次实际 proof UUID, tier: "T1"}
proof_consumed_at  # Root capture_after_transition 首次真实 aware ISO 时钟
stable_anchor   # A 首次完整 anchor，不是仅稳定摘要
```

`row.intent_digest` 使用实际 marker 的 **common intent**。不得写 token、未来 Receipt UUID 或完整候选 SHA。`row.action_result` 为非 mapped 的交付属性，仅含 `candidate_binding_sha256` 和 `inspection_sha256`；现共同 `append_receipt` 会把它们展平入实际 Receipt.result 的 id/revision/status 后。model 没有此列，本段不修改 model，也不生成 Receipt。Root 未来需把此行为纳入共同 subject family/事件及准确原子 SQL 配对。

## 尚缺的公共宿主接缝

跨 preview→apply 的原锚恢复尚未接通：桥的 full proof 含首次真实检查时钟/runtime 全文，重新实际读取会产生新 full SHA。Root 必须从真正持久 `Confirmation.snapshot` 读取原完整锚，通过真实 owner 检查与恢复本次 prepare；不能由 payload/任意 DTO 提供旧锚，不能把新的 SHA 替代旧 snapshot。缺此宿主接口或旧锚不等时，本段明确 `INTEGRATION_REQUIRED/503`。

共同 execute 的去重、旧回执重放、当前权限/来源门禁、专业 operation 矩阵、真实 source bytes/issuer 签发、Confirmation False→True/消费 hook、Receipt/Audit/Outbox 和已安装 reciprocal SQL 全由 Root 实际接线。旧 key/跨 key replay 必须走原 current-first 门禁且返回旧 Receipt，不进入本新写阶段。当前暂存成功纯例不证明这些公共能力已运行。

## 验证界限

owned tests 使用真实 SQLAlchemy Session/活动事务、持久 identity map、真实 Confirmation ORM history 与真实 prepare/consumption 模块函数；所有数据库 SELECT、原件 bytes、专业与政策返回是上游明确测试替身，数据库连接在 `do_connect` 处直接失败。fixture 的 False→True 赋值是纯检查模拟，不是 SQL/共同公开消费者的实测。

反例覆盖原 key/token/读集顺序、context/Session/UOW、持久原件 proof/marker/模块、Current 续版、来源/专业/政策/runtime 漂移、owner IO 后过期、nested material 变化、原完整锚恢复缺口与失败单次失效。无 repo conftest、PG/HTTP/迁移/公共构建。原始失败与最终检查日志各自保留；最终 source manifest 绑定冻结 A prepare 和 Root consumption 依赖。
