# 下一 retained compatibility 方案（实施前，未接入）

本段只读方案，不改实际 591 源、原 Start/事实/Source/registry，不运行数据库、HTTP、测试或构建。主线统一决定下一候选与实际验证。

## 当前证据

[配置完整 Engine 的 v3](../../../docs/reports/evidence/pdos-next-wave25-20261003/actual-retained-diagnostic-v3.json) 返回 `RETAINED_EXECUTION_CHANGED`，原预约存在、bundle READY、固定 issuer key/scope/version/nature/epoch 匹配，但 saved resource fp `002beeace7977d96e2092a3ee3add0bf03860ac7585ffde36825b6b3b1a463ab` 与 current fp `d792f6252d823f2bb7efe42be0d53368b14442601a5e0c444b9f9053ffd61434` 不同；当前 registry/epochs 各两项。**尚未证明无关新 key 是唯一原因。** v2 的 Session 绑 Connection、未继承 Engine 配置，SOURCE_STALE 不作实际子原因；封存的新 SOURCE_STALE helper 本轮不适用、未执行，见[纠正说明](source-stage-applicability-v2.md)。

[`test_resources._load`](../../server/pdos_next/domain/test_resources/service.py:991) 的指纹包含整个 `_pdos_test_resource_issuer_epochs`，所以新增无关 scope 能影响旧摘要。但其余 material 也是真实依赖：binding/fact/Current、固定 issuer、asset/occupancy、sample/use epoch、样件资格及执行/source 摘要、executor authority、原件安全 basis、全部 named DecisionProof/checks，不能删减或以 READY 替代。

## 旧材料的可恢复边界

[`launch._record`](../../server/pdos_next/domain/verification_launch/service.py:832) 只保存 `plan_binding/resource_facts_revision/reservation`；Run `source_basis` 是来源安全闭包，**不是资源完整 preimage**。Reservation/Usage 也保存 fingerprint hash；完整 reservation report/snapshot 与共同 Confirmation 预览未保存 `_load` 的全部 fingerprint preimage 或旧 global map。只有 hash 无法普遍恢复旧 map，多 key 无可信原材料不可反解、枚举或放宽。不得 UPDATE 原记录、从当前 map 倒填、凭历史配置文件可能只有一 key授准。

## 最窄协议：诊断先于实际放行

下一候选先由真实 `_load` 抽取已完整核对的同阶段 preimage。保留所有字段和所有现有 owner/source/Current/ACL/原专业负事实/issuer ABA/完整 own occupancy 与 usage 守卫。**仅局部候选 dict 的顶层 `issuer_epochs`** 换成 `{actual_fact.issuer_key: actual_fact.issuer_epoch}`，不改 Engine、不移除 registry、不切副 Engine、不缓存、不跳 owner。

用实际 [`build_operational_facts.digest`](../../server/pdos_next/domain/build_operational_facts/service.py:74) 重算完整候选，必须：

1. 原 rev2 Start 的 tenant/product/project/run/request/plan/actual start、来源、安全和真实保存组均有效；Start saved fp 与实际 Reservation.facts_revision 精确一致，原占用/usage/intent逐值完整核对。
2. 固定 fact/Current 与 live issuer object/token/key/scope/version/nature/epoch 当前精确合法；当前消费者 ACL 与原签发人历史资格各自核对，不能借 owner Context授消费者权限。
3. **完整候选 SHA 精确等于原 saved fp。** 只有这个命中才认证“当前全部其他 preimage＋该确切单 key map”能重现原保存承诺；固定 issuer 匹配本身不够。
4. 全部 IO/回调后重核实际依赖、registry/runtime、caller 与完整 UOW，最后真实钟核当前门禁/期限。历史执行仍用原 Start.created_at；自然窗口结束不授新开测许可。

首轮只能输出 saved/current/candidate fp 与相等性、外层 rollback，不改变 `current`。命中后才由主线另行实现这一明确的旧单依赖兼容分支；retained身份仍返回原 saved fp，不重封原 failure anchor。未命中、旧多 key/算法不支持、任何实际材料漂移时保持 `RETAINED_EXECUTION_CHANGED`；不尝试 subsets、epoch±1、删除动态字段或挪 clock。此协议依赖完整当前 preimage，不能从摘要报告虚构。

## 新保存与最小施工范围

新 Start 可采用明确 `test-resource-dependency-v2`：保存完整 canonical preimage＋digest，以实际消费的 issuer key/scope/version/nature/epoch代替无关全 registry业务依赖；其余全部原字段保留。全 runtime registry仍用于本次 IO前后撤回/ABA守卫。材料只由可信 host在真实同 UOW保存，不收客户端版本/材料；Reservation/Start fp必须一致，不新增第二Receipt/消费。Root核新 JSON/原子 SQL约束与现场head后再分配迁移，不回填旧行、不预留编号。

建议下一段归属：`test_resources/service.py` 提取完整preimage/版本；`retained.py` 窄选择并保留旧fp；`verification_launch/service.py` 仅新保存材料。Root独占共享SQL/实际验证。新开测和正常replay不得全局沿用retained fallback。

最小受影响验证：旧单scope新增无关scope可完整命中；固定issuer撤回/恢复ABA或map损坏、fact/Current/source安全、原负专业事实、method/window/实际配置、asset/sample/use epoch、namedDecision任一变化均拒绝；旧多key/无法完整命中拒绝；末端IO撤回/到期拒绝；自然过窗保留历史而新Start仍禁；表全行不变、原Receipt唯一、源/hash/clock原文保持。原SOURCE_STALE探针和旧0probe证据保留，不计为本协议实际验证。

本方案不授真实专业资格、七owner、有效性或关闭；当前首因与实际兼容放行仍待下一轮主线精确诊断/验证。
