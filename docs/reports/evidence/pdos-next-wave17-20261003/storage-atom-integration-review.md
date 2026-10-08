# Wave17 事实存储与实际原子组读取衔接审查

本次只读审查 A 的暂存模型/codec 与 Root 的暂存 atom reader，并核对最终源 SHA 和既有检查记录。未运行 DB、HTTP、pytest、迁移或公共验证，未修改任何源码/测试。三者字段与摘要合同相容；未发现当前最终版本新增的实质误拒或授权放行。以下已关闭问题与未实施前置必须分别保留。

## 已关闭问题

1. 初读 Root reader 时，`_acl` 使用三次 SQL 前传入的 `at` 核 Grant expiry；末次查询期间到期可能仍返回。最终 [`fact_atom_storage.py:133`](../../../../pdos-next/staging/wave17/fact_atom_storage.py#L133) 已在 Product/Principal/Grant 查询完成后采真实 UTC 时钟，入口与所有存储读取后的末端均调用该核对；旧 v3 记录保留，不能改称其已覆盖此边界。
2. C 发现 Receipt JSON `True == 1` 的 Python 比较问题。最终 reader 第 276 行先要求 `type(result.revision) is int`，再核精确版本；布尔值不能充当 rev1。此项为 C 的独立发现，本审查核对最终实现。

Root [v5 结果](root-fact-atom-storage-result-v5.json) 和 [v5 原日志](fact-atom-pure-v5.log) 对应 20 个 owned pure 检查通过；A [最终结果](fact-storage-final-check-result.json) 对应 38 个 owned pure 检查通过与离线 DDL 编译。这是读取既有证据，不是本审查追加验证；替身 SQL 返回及纯结构通过不等于实际 PostgreSQL 原子性/资格通过。

## 精确衔接核对

| 边界 | 当前实现与结论 |
|---|---|
| scope/前版/NULL | `SCOPE` 含 tenant/product/project/logical Issue/CAPA；`BINDING` 再含 origin IssueVersion/revision、owner/visibility/nature/purpose、anchor/requirement SHA。事实前版和 Current FK 带完整绑定；首版/连续前版显式处理 NULL，body 镜像检查使用 `COALESCE(...,false)`。Observation 额外固定同规则完整引用与 executor。见模型第 106、152、223、282 行。 |
| Rule 系列 | RuleCurrent 唯一系列含 scope/purpose/anchor/issuer key/external id，故 issuer version 更新不会另开指针；Current→Fact 另有包含 issuer version 的精确 FK。FK 声明不是首版、连续 epoch/CAS trigger 的替代品。 |
| body 与 full SHA | codec 的 v1 envelope 只删顶层 provenance 与自身 ref.sha256；子引用的完整 SHA、嵌套同名字段、原观察钟/时区仍保留。`body_payload_sha256` 对应材料摘要；`assemble_fact` 加入实际 atom 后才产生 full FactRef SHA，避免把 full SHA 写回 Receipt 形成循环。见 codec 第 144、170、205 行。 |
| Receipt result | 模型 `action_result` 返回 `{fact_kind,payload_sha256}`；共同 Receipt 展开真实 row id/revision/status。reader 第 259–282 行核 exact scope/operation/family/row version/实际 command/actor/visibility 与该扁平 result，不要求不存在的嵌套字段。 |
| 独立意图 | 存储 `intent_digest` 合同明确是实际 common semantic intent，reader 只与真实 Receipt 的同名摘要比较。领域意图格式不被冒充为 common intent；也不从失去原 token 的材料重造 request digest。可信 writer 以后仍须以实际 handler 语义产生该值，单纯存储相等不自证语义来源。 |
| 原始 RequestKey | reader 第 289–302 行要求至少一条真实 tenant/actual writer/Receipt id/原 Receipt.request_digest 对应关联；不要求后来跨 key aliases 的摘要全相等，也不以任意 alias 代替原关联。 |
| proof 与时钟/水位 | T1/T2 六列完整，核实际 Confirmation id、scope、actor、operation、subject Product、当时保存的 Product 水位、token/material、固定 expiry 与 `proof.created_at <= consumed_at <= fact.created_at < expiry`。历史读取不拿当前 Product revision 或当前时钟否认当时合法消费；host_import 六列全 NULL。见 reader 第 152–196 行。 |
| 调用者/UOW/identity map | 真实 caller 为当前 Context 本人 human、run=None；私有事实仅原 owner 可读，不用 owner Context 代读。全链 Session/SessionTransaction 活动性、祖先归属/循环上限、根/嵌套 identity 与 bind 首尾核对；ORM exact 查询 `populate_existing=True,autoflush=False`，事实 body 使用 scoped Core row，避免 identity map 的旧 body 冒充本次读值。见 reader 第 80–149、199–253、380–382 行。 |

## 迁入前置与明确失能

模型 proof FK 为 `(tenant_id,shared_proof_id) → confirmations(tenant_id,id)`，而现公共 [`Confirmation` 的 table_args](../../../../pdos-next/server/pdos_next/models.py#L344) 尚无 `UNIQUE(tenant_id,id)`。这是 A [冻结合同](../../../../pdos-next/staging/wave17/fact-storage-contract.md) 已明确的真实迁入依赖：Root 迁入时须同时补父 metadata 与实际唯一约束；离线 DDL 编译不能证明 PostgreSQL 接受该复合 FK。本次不分配 head，不建议改历史迁移。

五个新表仍只是暂存声明。Current 首版/连续前版/epoch、不可变/RLS/Agent 零写、源生命周期闭包、跨 target 全局一次消费与双向 deferred Receipt/Audit/Outbox/RequestKey pairing 均需 Root 正式接线及实际验证。本 reader 通过现存行派生固定 transaction-group 摘要，不是新增数据库事实，更不是已安装这些守卫的证据。

`StoredAtomRead.current_evidence_authorized` 与 `same_uow_consumption_attested` 明确为 False。历史 `Confirmation.consumed=True` 加保存的 consumed_at 不能证明真实 False→True、同调用栈 marker 或当时 kernel Invocation；这些仍由未来真实 writer/consume host 提供。新增 consumed_at 是本新事实合同，不能反向要求旧 native Artifact 登记回执拥有该新字段。

七类 owner 的当前源 bytes/安全 epoch、规则与观察 Current、原失败与措施、候选实际适用性、独立专业/政策/issuer、retained effects 与末端 runtime/clock 门禁尚未由该读取层签发。codec 的完整 DTO 与存储组摘要都不能替代上述权限/资格。缺真实 gates 继续 missing/INTEGRATION_REQUIRED，不构造 positive、不创建资格、有效性或关闭。

## 最终源绑定

以下 SHA256 由本审查重新读取计算，与 A/Root 最终记录一致：

| 文件（均在 `pdos-next/staging/wave17/`） | SHA256 |
|---|---|
| `fact_storage_models.py` | `c5e19ebd676ebca70421897a2ada1e3214d6fd1d6e7905bdb9a57d7be39f9a56` |
| `fact_storage_codec.py` | `962a7ad94babe6a5a4552d85dffa993cf0d8271e9ae49d4338f6ebf05fa835cf` |
| `fact-storage-contract.md` | `eb020013ea6f10c7ca8ee6959bc361ef878679317fe1ea485d9a5a6c6e9f9f85` |
| `fact_atom_storage.py` | `b3794750da19f6394dc12cce062489e1aad7022619f4aac7dccb7e7246b9e604` |
| `test_fact_atom_storage.py` | `3161020f64902b0d54f2606a458a079bb0f3381e38ec161af0719c06df8b29d4` |
| `fact-atom-storage-contract.md` | `2c1c2dbffebbe6ace8092642f571ba2e3b3ba01723b4d21db41ce7ac2136f1bb` |

Root v5 记录中的公共 484 候选未变是其指定 manifest 的观察范围；本审查未另外复算公共全树，不将暂存检查算入公共 PG 或业务闭环验收。
