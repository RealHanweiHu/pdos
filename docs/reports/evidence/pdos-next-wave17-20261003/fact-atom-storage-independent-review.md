# Wave17 stored FactAtom reader · 独立只读复核

本次定向读取 Root 的 `fact_atom_storage.py/test_fact_atom_storage.py/fact-atom-storage-contract.md`，以及对齐所需的 A-owned `fact_storage_models.py/fact_storage_codec.py` 和已冻结 `facts.FactAtom`。C 未编辑这些文件，未运行 pytest、collection、数据库、HTTP 或公共检查。此前 C-owned UI 状态纯检查不属于本文的存储证据。

## 两项实际缺口与窄修

1. **末次 ACL 查询跨期限。** 原 v3 `_acl:133–147` 使用调用前传入的 at，再读取 Product/Principal/Grant；`read_fact_atom` 末端也是在这三次 IO 前取 clock。最后 Grant SELECT 若跨 expires_at，会在返回时已过期却仍通过旧时钟比较。B 与 C 各自只读反馈，Root v4 删除内部 at 参数，最终 `_acl:147–148` 在全部三次 SQL 后取真实 fresh clock 再比较 Grant；末端调用和 UOW identity 核对保留。新增 `test_grant_expiring_during_final_acl_sql_is_rechecked_after_that_io` 末次 IO 跨时界反例由 Root 办理。此修复是当前 caller 的读取 ACL，不把历史保存 proof 到期改成当前授权判断。
2. **JSON 布尔误等于首版整数。** 原 Receipt `result.revision == revision` 在 revision=1 时接受 JSON true（Python True==1）；真实 JSONB 也能保存该异常值。C 反馈后 Root v5 在最终 `fact_atom_storage.py:276` 先要求 `type(...) is int` 再等值，新增 `boolean_result_revision` 拒绝 case。没有用 int(...) 宽转换，也没有改变合法数字版本/Receipt 主体。

两项最终源码修复已按实际行读取确认，旧 v3 哈希/18项记录保留。Root v4 19项仅对应 ACL 修复；[最终 v5 记录](root-fact-atom-storage-result-v5.json)记录20项纯检查（Root 通知1.72s）与 Ruff 通过，不加总18/19/20。最后仅 formatter 调整 ACL if 行，[格式绑定](fact-atom-format-only-binding-v5.json)记录测试前后 AST 相同；C 已读取最终3份SHA确认绑定，没有自行重跑或声称PG成功。限定最终源码、模型与 codec 对齐范围，未找到第三项新增明确缺陷。

## 已核对的真实保证

- exact fact 查询限定 tenant/product/id/revision；仅一个精确结果，private 仍原 owner-only。实际 Context 必须 actor=requester、无 AI run，当前 Product、本人 Principal 和 Grant 用 populate_existing 重新读取，不借旧 writer 或系列 owner 代当前 caller。
- 真实 Session/is_active、所有真实 SessionTransaction 祖先/归属、nested/root 与 bind identity 受核；先遍历有界祖先且拒循环，再调用 SQLAlchemy 公共 root getter。全部 SELECT bounded，并禁 autoflush；不把 caller 尚未保存的新 writer 事实偷偷 flush 为已存在。末端再比较 caller/UOW。
- 不可变 body 使用严格 `pdos-capa-fact-body-v1` codec，payload/read-set 摘要与真实 row 对齐；真实 writer、共同 Receipt 的 operation/family/目标 immutable ref/result/status/command、原始 RequestKey writer+digest、准确 Audit/Outbox/correlation 对齐。合法跨 key aliases 不替换原 request_digest 出处；没有 domain intent==common intent 的错误假设。
- 保存的 T1/T2 Confirmation 读的是实际 UUID、原 actor/Product subject、原 Product 水位、token/material/expiry、consumed=true 与保存的消费钟；历史核对按保存钟，不能用当前 Product revision/当前 now 强制重新消费旧 proof。T2 Invocation.decision_id 精确等于该保存 proof UUID；host_import 必须没有公共 T1/T2 proof。
- Rule/Observation/Review 的表、操作/tier/family/event/status 与 A 的 `OPERATIONS`、models 和 codec 对齐。`_Fact.action_result` 是 flattened fact_kind/payload_sha256；Receipt 的 id/revision/status 来自共同追加。FactAtom.received_at 是 fact 实际 created_at，Receipt 可在其后微秒接收，两实际时钟独立且均参与 group material。
- full FactRef.sha256 需要保存 group 后组装，Receipt 中不包含循环依赖的 full SHA。`assemble_fact` 重新验证 typed FactAtom、严格操作映射和 frozen FactBase/Rule/Observation/Review 跨字段约束；不得用 model_construct 跳过重核。source/read-set 闭包与完整原时间仍在事实模型中，codec只排除 provenance 与自身 ref.sha256，不抹 child refs 或原事件。

## 不能扩大成的授权保证

`StoredAtomRead.current_evidence_authorized` 与 `same_uow_consumption_attested` 明确恒 False。group_sha256 和历史 consumed=true 证明的是已保存组的结构绑定，不能证明本事务真实 false→true、当前事实/规则 Current、原件字节、issuer/专业资格、参与者独立性、实际适用或采样覆盖。把 shared_proof_id 填成 Invocation.decision_id 也不自行实施消费。

这个 reader 没有 reads/refresh/attest 的七类 live FactReader owner，没有 Rule/Observation/Review Current 或现场真值资格判断。后续所有 owner/bytes IO 后仍要 fresh refresh 和同 Caller/UOW 校验，不能把此处最后一次 ACL 核对当成全部下游 IO 后核验。真正规则出版、专业 T1/T2 host callback、Current CAS、forced RLS/immutable/lifecycle、跨表 proof 唯一与 reciprocal deferred 组仍需 Root 从实施时真实 head 接线/验证。模型声明或可编译 SELECT 不是数据库已安装约束。

原纯用例用真实 ORM 表达式/Session 结构，但 SELECT 数据、Grant/Clock/保存 proof/资格明确是 substitute；它们可验证拒绝逻辑，不能宣称真实 PG 数据/字节/UOW消费、生产资格、有效性/关闭或 G3 已通过。没有公开 mount、没有命令/Receipt/当前业务状态写入，也没有用 staged atom 升级现有候选。

## 只读 SHA 绑定

| 文件 | v3（问题原快照） | v5（已读窄修快照） |
|---|---|---|
| `staging/wave17/fact_atom_storage.py` | `2923a52fcd7492cd52c308724951baacd558ebdb6f827e3fc7d79bfb876ff34c` | `b3794750da19f6394dc12cce062489e1aad7022619f4aac7dccb7e7246b9e604` |
| `staging/wave17/test_fact_atom_storage.py` | `2a3ff787dd9de132e4ed11c058ef438f0418fd2e173e5554258c13e5a6bb2515` | `3161020f64902b0d54f2606a458a079bb0f3381e38ec161af0719c06df8b29d4` |
| `staging/wave17/fact-atom-storage-contract.md` | `2c1c2dbffebbe6ace8092642f571ba2e3b3ba01723b4d21db41ce7ac2136f1bb` | 相同 |

路径相对 `pdos-next/`。依赖只读快照：models `c5e19ebd676ebca70421897a2ada1e3214d6fd1d6e7905bdb9a57d7be39f9a56`；codec `962a7ad94babe6a5a4552d85dffa993cf0d8271e9ae49d4338f6ebf05fa835cf`；facts v2 `a9c06b974300729fe8953f1c7b85ec5a5c3ceb57416bc4d81c0c79f708083f50`。本文不重新冻结 Root 的公共候选或声称实际业务已完成。
