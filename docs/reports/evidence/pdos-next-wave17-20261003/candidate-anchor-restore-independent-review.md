# Candidate 原锚恢复独立定向审阅

结论：在本段 **未消费确认恢复** 的窄边界内，未发现需修改冻结源码的实质阻塞。它不授当前专业资格、不产生本次 False→True、不连接公开 candidate writer；专用 `prepare_write` 和共同消费仍是明确缺口。此结论不是真实数据库/原件/专业/公共业务验证。

## 冻结范围与证据

只读核对三份源，与 A 最终通知完整 SHA 相等：

- `pdos-next/staging/wave17/candidate_anchor_restore.py`：`5dd333f70e45a1345da71d63b9b3d4c5da0dc427107c5ebffb50bbda624c1985`。
- `test_candidate_anchor_restore.py`：`6dc6a06511fdbdc3baacb0db0e694fba84208584a67b783ee171d630bd33c5c4`。
- `candidate-anchor-restore-contract.md`：`1218d3dbf6199ba957f8870b4caa5bead6f5a2ad7648a143dacda03501452d8c`。

A 已保存的 [检查结果](candidate-anchor-restore-check-result-v1.json) 为 39 owned pure/4.79s、Ruff/format/AST 0；其中 SQL/bytes/专业返回均为明确替身，本审阅没有重跑。原 33+1、37+1、38、最终39日志各自保留，重复节点不合计。B 只读取源码/证据并写本文，无源码修改、DB、HTTP、pytest 或公共检查。

## 已闭合的恢复边界

1. **真实持久确认与语义**：源码95–130、323–377使用真实同 Session persistent、完整已加载且干净的 `Confirmation`，明确 `consumed=False`；`_db_proof` 按 tenant/product/id 的完整 scalar columns、limit2、无 autoflush 读实际 SQL 图像，前后与 ORM 全字段相等。token SHA、实际 module `material_digest`、actor=requester/run=None、Product subject、operation、Product 水位都准确绑定。不会用历史 consumed=True 或复制 DTO/普通 bool 代替本次材料。
2. **原完整锚保留**：源码187–294严格13键 snapshot、typed全文/自摘要/完整稀疏 source closure；`anchor.StableCapaAnchor` 的原 validator 还重核完整失败与所有 full SHA。源码383–395由配置的真实 owner 自己读取 fresh anchor，保存返回值仍是原 snapshot 的 `saved`，没有重新 seal 它。stable 比对仅原 `stable_failure_material` 的三条冻结路径：`result.retained.checked_at`、`result.retained.execution_window_elapsed`、`result.source_basis.runtime_stamp`；原 Issue/历史、观察钟、来源安全、配置/方法、占用/usage/专业原事实都保留。
3. **原完成版与当前范围**：源码387–393 v1 要求 Current 精确等 origin 且两层 needs_lineage_owner=False，合法后继也明确503。源码411–443重新读实际原版本、通过现 `basis_from_issue` 核 root/actions/completions/requirement 等材料，再核 Current/Project；实际 Project 私有 owner ACL 由冻结 `anchor_storage._project` 处理，不能借 ProductGrant/Owner Context 扩权。basis.owner/visibility/purpose/nature 与原锚相等，payload 不可改受众。
4. **全部源安全与末端读取**：源码396–409核 payload 精确原文引用与全部新增人工出处；原结构化报告沿实际原失败 bridge 核值，完整 raw basis 与存档逐值相等，不 typed dump 补 null。共享候选不能夹私人来源。源码447–462再次 scalar-read proof、再 fresh Product/Principal/Grant；所有 caller watermark 完整对等，最后一次 Grant SQL 后取当前钟，检查 proof/Grant earliest expiry 及 fresh owner 钟，再核 runtime/完整实际 UOW。现 source_for 的同 UOW 来源/产品锁必须一直保留；本 reader 不能被当成不持锁的跨事务缓存。
5. **真实启动与 opaque identity**：源码306–321固定 ModuleType/实际 semantic/Payload class 身份，绑定实际 callback、security/store、issuer registry epoch 与 policy epoch。源码480–521为本 host 的 weak identity 登记；copy/construct/换 host/Session/Context/Command/main+nested UOW 或 nested材料变化都拒绝，`require_restored` 不是只看 seal，而是独立重跑 `_read`。完整 Command 摘要保留 key/token/readset 顺序，不重造已丢失的历史 request_digest。

## 公共接线必须仍保留的缺口

- 恢复器只是旧完整锚的真实存档 owner，不重新核当前 candidate 专业/政策或输出适用性，保存的 `authority_snapshot/policy_snapshot` 不能当当前正向许可。未来专用 `prepare_write` 须先 `host.require_restored`，再真实 current owner/outputs/源/专业/政策重核，沿用原全文 anchor；不能拿新独立 phase 的 full SHA 与旧 snapshot 假匹配。
- `require_restored` 只接受未消费阶段。共同 consumer 的实际 False→True 与首捕获钟、Root `ConsumptionHost` 原 marker、消费后独立刷新/末端时效/Current CAS 和 writer 单次失效必须另接；现 B writer43、恢复39分别是暂存纯范围，不构成完整公开链。
- 最终恢复返回后 pure DTO/hash 构造或未来调用延迟不能视为持续许可；真正消费/保存时还必须取真实当前钟核 expiry。没有 COMMIT-clock TTL 保证，原保存钟/SQL范围按实际迁移合同办理。
- 未调用 DB/原件或安装 next26 的本次审阅，不证明 Reciprocal SQL、RLS、实际证明消费、真资格或效果/关闭通过。有限后继 owner 也尚缺，不能把 Current 不同的问题通过删历史或替换旧锚绕过。

本段没有建议扩大 frozen DTO、恢复器用途或现有 public 写合同；上述缺口均可通过主线已经规划的专用 prepare_write/消费/实际迁入验证继续接通。
