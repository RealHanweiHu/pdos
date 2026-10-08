# Wave17 facts registry／origin／atom 组合只读审阅

本报告仅审阅已冻结的暂存源码及既有合同，没有修改源码、连接数据库、发 HTTP、运行检查或挂载公共服务。这里确认的是 **raw 登记／历史材料基础可继续接线**；不是七门禁、真实资格、生产启用或正式出口通过。下表的 SHA 是本次实际读取字节值，匹配各归属 agent 的最终冻结通知。

## 精确绑定范围

| 文件（均位于 `pdos-next/staging/wave17/`） | SHA256 |
| --- | --- |
| `fact_registry_storage.py` | `18c7d06f06ee67d23ce82ef2ee6141781be4b7528f5d7a3325b6f02587ec46c7` |
| `test_fact_registry_storage.py` | `a83d76496b120493d1aa745ac7a99ad08b0e4c78a2195822f969d88ada62bea9` |
| `fact-registry-storage-contract.md` | `dd719baae48bb7eefa4ef9579f0cc2931a242634768f8217a7cbcbd50b1e9180` |
| `anchor_storage.py` | `b3d71c70e076d1f77ee9a9b95fe0300b54ace14ba48fe0ca59334b832c9b325c` |
| `test_anchor_storage.py` | `63dcb791de8f71f5bfb44b8479f435177d097d7401a49023736b9638e613b5bb` |
| `anchor-storage-contract.md` | `a4dd15cf21eb150601361c3866229c7f9d834e92048ddff89c92e02545bc7cbc` |
| `fact_atom_storage.py`（Root v5） | `b3794750da19f6394dc12cce062489e1aad7022619f4aac7dccb7e7246b9e604` |
| `test_fact_atom_storage.py` | `3161020f64902b0d54f2606a458a079bb0f3381e38ec161af0719c06df8b29d4` |
| `fact-atom-storage-contract.md` | `2c1c2dbffebbe6ace8092642f571ba2e3b3ba01723b4d21db41ce7ac2136f1bb` |
| `fact_storage_codec.py` | `962a7ad94babe6a5a4552d85dffa993cf0d8271e9ae49d4338f6ebf05fa835cf` |
| `fact_storage_models.py` | `c5e19ebd676ebca70421897a2ada1e3214d6fd1d6e7905bdb9a57d7be39f9a56` |
| `facts.py`（v2） | `a9c06b974300729fe8953f1c7b85ec5a5c3ceb57416bc4d81c0c79f708083f50` |

没有重新运行 51／53／20 项离线检查。各原有结果分别由归属 agent 与 Root 留存；这些 SELECT 替身／无连接真实 Session 检查不等于 PG 权限、约束、并发或实际 source owner 验收。

## raw 返回前的范围与末端链

[A registry](../../../../pdos-next/staging/wave17/fact_registry_storage.py) 的 `read_stored_fact` 捕获真实 Session 活动 root／全部 SAVEPOINT 祖先、bind 和 Context，入口核 Product／当前 human／Grant；每个 exact Fact 首先在同 tenant/product 下定位，然后按它的真实 project_id 读取实际 Project。Project 必须 active，visibility 只能 private/product，private 只当前实际 owner 可读。共享 Fact 不能因 Product Grant 绕过私有 Project。

A 的 SQL 均为 exact WHERE-before-LIMIT 2、populate_existing、autoflush=False，整个读取处于 no_autoflush；没有 Current 写入、预留、flush、commit 或替代 Session。最终 `finish` 在全部 immutable／group／父引用／candidate callback IO 后，重读全部遇到的 Current 并比较完整行及 epoch，再重读全部 Project 的 tenant/product/id/owner/visibility/status，最后执行 Root v5 当前 caller ACL、真实 UOW／Context核对并取 post-IO observation clock。项目名称与 current plan revision 不是这个 raw ACL stamp；后续专业适用性不能据此忽略业务范围变化。

[B origin](../../../../pdos-next/staging/wave17/anchor_storage.py) 同样在入口核真实 Product／caller／Grant、精确原版与实际 Project private owner。它显式返回 Project business scope，与 owner/visibility 一起在末端再读比较。原 descriptor 在后续 IO 前被复制成独立 DTO；末端重读 origin／前版／原组／Current，并再次读取 mutable caller、Current 与 Project，用最后 IO 后的真实 clock 拒绝期限经过，再核原活动事务链。

[Root v5 atom](../../../../pdos-next/staging/wave17/fact_atom_storage.py) 本身只提供 Product／caller／Fact owner 范围及实际保存组。它**没有独立 Project 或 source ACL reader**。调用者必须保留 A/B 的 Project 包装，不能把直接 `read_fact_atom` 的返回当作完整对象可读性或专业授权证明。三个模块都不获取跨连接的串行化锁；后续 writer 必须维持真实共同锁序和 post-all-owner-IO 授权／issuer／source epoch／TTL复核。当前 raw 描述不是该线性化授权结果。

## origin、全字段与固定 full refs

B 只接受显式原完成 `VersionRef`，不把 Current 当原完成版。它重建真实连续前版→最终完成版：本人对应尚未完成 action、真实发生钟、完整 history 前缀及新增 command、原 failures／requirement／root／actions 全字段都必须匹配。原 source／readset／保存 basis 不变，并核当次 completion Receipt／原 RequestKey／Audit／Outbox／Confirmation、各自 domain/common 意图及真实 reviewed before/after/material。旧 proof 没有 consumed_at；B 没有反推该时钟或声称 `consumed=True` 证明同 UOW false→true。

A `_origin` 检查完整 StableCapaAnchor 声明与真实固定 IssueVersion 的 snapshot、scope、owner、原来源和保存 metadata。它**尚未调用 B 的原完成重建与共同组 reader**：A 的 raw anchor 声明比较不是 B 原组验证的替代，也不能只比两者 UUID/revision 就视为衔接完成。未来真实 registry/origin owner 要在同 phase 调 B，完整比对 `StoredOriginRead.origin` 与 anchor.origin，包括 domain intent、真实前版 full ref 和保存 metadata，再独立获取全部原失败 bytes／retained 当前证明。

这是一项明确待接的 owner 接缝，不是当前代码的肯定授权：A 始终返回七 gate＋issuer＋lineage missing，B 始终返回 source/failure/professional missing 与 Literal False。不能把它们串起来后自行把这些 False 改 True。

A Rule／Observation Current 是精确 series／scope／owner／purpose／anchor／requirement 绑定，完整实际 target FactRef SHA 由 immutable body＋真实保存 atom 计算。每个前版保持 full SHA，连续走到 v1，不按 MAX(created_at) 或 latest猜旧父。Rule issuer key/external series 不能重绑；Observation固定 Rule full ref／executor 不可重绑。正整数实际 epoch 与末端一致性已检查，**历史每次 epoch 单调递增仍需真实 Current writer/门栓 attestation**，单个 Current 行不能证明它。

Observation依旧返回其 saved Rule full ref；Review返回固定 Rule 后的完整有序 Observation refs，历史父不会偷偷换成 Current。body payload SHA 不能代替 full FactRef SHA；Root atom保存组摘要与独立 full body 共同参与后者。Root Group reader保留实际 Receipt／Audit／Outbox／RequestKey关联，并排除 delivery 状态变动与后来的 alias key，使 full SHA 不因投递或别名回执漂移。

## candidate、有限谱系与时间边界

Review 的 `candidate_owner` 默认 None → `FACT_CANDIDATE_OWNER_REQUIRED` 503，Rule／Observation可独立读取。现有 Candidate 的 inspection/binding SHA不是完整 Candidate FactRef SHA，因此当前缺口不能通过选任一旧 SHA、构造假 atom 或“以后 UPDATE”补齐。未来 typed candidate owner必须在实际同 Session／Context读取精确候选和真实共同组，核 full ref/scope/owner/purpose/anchor/requirement；它仍不授七 gate。当前候选 raw 状态保持 indeterminate／三个 unknown，不能向 FactReader补完整 evidence。

B 在 Current不同于 origin时返回 needs_lineage_owner，不把合法后续 effectiveness/close一概判成原材料失效。Current相同只能说明不需要解释**这个差异**；不代表 source、原失败或当前专业 owner已经核完。A一直显式 needs_lineage_owner=True。未来 owner须调用冻结的精确 effect→close有限谱系协议，保留原 history prefix／原失败／原 source，并核真正 companion／T2批准／Receipt绑定，不使用“剥 history 后相等”的宽放行。

保存 proof现在自然到期不否定原期间的真实完成；B 与 Root atom用原 created/consumed/expiry关系核历史材料。另一方面当前 caller Grant在最终 IO后到期会被拒绝。A 的 registry_observed_at不是 valid_until；current_registered不是 Rule有效、观察完整或当前专业适用。真实 source、issuer撤销、参与者、专业与 applicability期间／当前 closure必须由七 gate实际 owner在自己的 phase末端再核；不允许跨 inputs／preview／apply／replay复用 raw 正登记作为资格。

## 最小下一接缝

1. Root统一迁入路径与安装 append-only/RLS/lifecycle/Current CAS及 reciprocal 原子门栓，实际 PG验证；暂存声明不等于已经安装。
2. 实际 registry/origin owner在同 Session组装 A固定事实＋B实际原完成组，完整 origin相等后读取固定原失败／来源安全，并保留完整 ordered refs；不要新建第二份 Current。
3. 冻结 Candidate full-body＋actual common group codec与只读 owner，再给 Review提供该端口；此前继续503。
4. 真正 FactReader补齐七 gate及有限谱系 owner，全部 owner IO后独立 fresh refresh／真实 clock／UOW校验；新消费 helper的实际消费 marker与历史保存 group分别办理，不能把旧 consumed bool提升为 marker。

在明确的 staged raw 范围内，本次没有发现额外错误肯定资格或跨 Project复用的放行；上述未接 owner／实际DB守卫仍是公开有效性与关闭办理的阻断，不能把模块或API定义视为业务闭环完成。
