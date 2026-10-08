# 公共候选专用保存准备接口

本段只修改 `server/pdos_next/domain/capa_effectiveness/candidate_prepare.py`，新增本段 `server/tests/capa_effectiveness/test_candidate_write_prepare.py` 及本证据。全部 staging 冻结文件保持不变；不修改 common、其他实际 owner/writer、注册、API、迁移、角色矩阵。没有 DB/HTTP/shared pytest。

## 标准调用

```python
phase = prepare_candidate_write(s, ctx, command, payload, proof, restore_host)
# 返回相同 PreparedCandidate；不是 Receipt、消费许可或新 Current。
# 共同真实消费前绑定；consumed False→True 后第一行捕获真实 marker。
# B writer 仍 require_live -> require_prepared_candidate -> require_live。
```

参数是完整实际 Command、严格 CandidateRecordPayload、真正 loaded/persistent/unconsumed Confirmation，以及真实 startup CandidateAnchorRestoreHost。先恢复原完整 13-key snapshot 的首次 anchor，并由真实 host 身份登记/require 独立核对；然后 `_read` 完全重新读取 current 原锚、当前固定 CAPA basis/binding/inspection、完整 raw source closure、当前新 operation 专业与政策。恢复前后本次 UOW/Context/runtime 必须相同。

fresh review 中只将 `stable_anchor` 替为实际原 proof 恢复的完整首锚，其他全部字段必须逐值等原 13 键 review，包括当前 authority_snapshot、policy_snapshot、basis/inspection SHA、原稀疏 raw source_basis/顺序、完整读集、source refs、owner/visibility、Current CAS 和 actual semantic。当前专业/政策变化直接重审，绝不复用旧许可。

fresh original 与原首锚只使用既已冻结的 3 条完整路径作稳定材料比较：`result.retained.checked_at`、`result.retained.execution_window_elapsed`、`result.source_basis.runtime_stamp`。原 full_failure_proofs_sha256/anchor_sha256、所有原证明全文、固定 Start/计划/占用/usage、安全/issuer/config/method/实际时钟不重封。其他 review 字段不作通用删键或时间规范化。

## 返回 phase 与后续消费

返回实际登记的原 PreparedCandidate field shape；`reviewed_candidate` 仍 12 keys，由实际 writer 添加 operation 形成原 13 keys。模块内部独立私有登记真实 command/proof、restore 实例与原 review、proof 不可变全列摘要、caller watermarks、Project 全结构及 Current 全结构。客户端不能构造该登记，也不能跨 Session、SAVEPOINT、actor 或调用实例沿用。

`valid_until` 上限包含 fresh Grant/专业/政策及全部未来 activation 边界、原 proof expiry；最后 proof/Current/Project/caller SQL 之后才取 UTC 保存准备钟。真正具名消费 remains actual ConsumptionHost，未注册历史 consumed bool 不授写资格。

共同 consumer 已真实置 consumed=True 后，后续 `require_prepared_candidate` 不再调用要求未消费的 restore。它重新执行完整 `_read`，与原 review 精确比较并保留同一个首锚；还从真实同 Session Confirmation 全标量 SQL 读取不可变字段，核 loaded ORM 与持久图像/初次摘要一致。仅 consumed 字段留给真实消费 host：消费后、首次 flush 前 ORM=True/SQL=False 可以合法出现；两者任一布尔值都不构成本模块消费证明。

原 proof 其他任何列/深 JSON、Current 指针 epoch、Project 全字段、Product revision、Principal/Grant access epoch 或期限变化均拒绝。after-consume writer 必须仍先后 require_live；本模块不能代替实际 false→true 与完整 marker/UOW/command/material/readset 证明。

所有 owner IO 后独立 raw proof SELECT，再 Current/Project/caller，最后 actual runtime/UOW 与真实时效核对。`invalidate_prepared_candidate` 同时丢弃普通和专用 write 身份登记；保留原单次 s.add 接缝，不消费、不 flush、不 commit、不 Receipt、不 reserve。

## 检查边界

17 本段纯检查通过；Ruff/format/in-memory AST 另存结果。第一轮12pass/1fail是测试 Clock 类型替身使 `isinstance(proof.created_at, patched datetime)` 不匹配，已将 fixture proof 时间构造为该实际替身 class；生产无 Clock 修改。原日志保留。

测试只导入 namespaced public production modules；复制两个冻结纯 anchor 工厂作为字面测试样本，不导入 staging 模块/模型，避免新5表重复 metadata。使用实际无连接 SQLAlchemy Session、persistent ORM、SAVEPOINT 与真实 ConsumptionHost 的 false→true history/marker；raw SQL、原锚 owner、current `_read` 来源/专业/政策/inspection 是明确受控替身。不是实际原件、真实资格或 PG 原子组通过；专业 future activation 的实际 `_authority` 算法沿先前真实当前端口实现，测试仅核其最早期限被最后 IO/clock尊重。

本段只交实际服务接口和窄 guard 证据。公共业务链与实际 DB/HTTP 由 Root 统一验证，不把函数/API/模型定义称为闭环完成。读取链可能重复进行完整 owner IO；本段不增加跨 phase/请求 cache，不从此纯测试时间推断实际服务性能。
