# Wave14 结果接线定向审查

范围：只读核对 `verification_results` 原件核值、捕获委托、Run/Request CAS、共同 T1/T2 与重放、确定性判定基底；仅新增本报告。未修改生产代码、测试或迁移，未连接数据库、运行测试或进行外部操作。本文是源码接线审查，不是整轮通过或生产资格结论。

## 发现与修复状态

### 1. 原件 I/O 后缺少运行时权威重核，可能用撤销前的事实完成结果动作

原路径在 `_load` 起点取得当前专业授权及 retained 原开测证明，之后回读旧/新报告原件。Product/Current 锁可保护数据库中的受控写入，不能保护服务器内存中的 issuer 启停、合成 profile 或受控资格 callback。若这些事实在报告读取期间变化，首次导入/专业动作可能继续使用旧肯定值；没有 ActionFact 的确定性计算重放也不能依赖旧动作的专用重核兜底。

F 已在 `verification_results/service.py:647` 的 `_load` 末端加入 `_refresh_phase_proofs`：全部原件 I/O 与来源基底核对之后，重新核 retained 证明，再核当前动作专业授权；完整 authority 字典及 retained 稳定摘要不相等即 `SOURCE_STALE`。每个 validate/preview/apply/replay 入口重新办理，不跨阶段缓存。

已定向确认：authority 返回没有动态评估时钟；retained 仅排除 `checked_at`、`execution_window_elapsed` 两个展示字段，其余固定 Start 身份、来源读集/安全基底、签发 epoch、资源占用及样件使用事实均参与比较。窗口自然结束不会因此撤销已发生的开测，新增占用/消费也不会因迟到导入产生。

已读新增真实 PG 守卫源码 [test_runtime_guards.py](../../../../pdos-next/server/tests/verification_results/test_runtime_guards.py)：真实报告读取后分别停用 professional/resource issuer，以及导入后计算原意图重放时停用 resource issuer；断言拒绝、Current 不推进、结果/回执计数不增、确认不消费。这里没有执行这些测试，其数据库结果待主线统一记录。

### 2. 新捕获未核对 Current，可保存无法提交的历史候选

原 `prepare_capture` 可从历史 running Run 版本生成新私有候选，即使 Current 已进入最终结果或复核版本。正式 apply 的 CAS 已能拒绝错写，因此发现的是新候选可恢复性/错误反馈问题，不是已证实能覆盖正式结果。

F 已加入 `_capture_current`（`service.py:354`）：相同 owner/capture_key 的精确历史重放先返回原候选；仅新 INSERT 前核对当前正式请求和 Run 两个指针均等于选定版本，漂移或缺失返回 `VERSION_CONFLICT`。该位置保持幂等恢复，不回退任何 Current。

已读纯反例覆盖 request/run 单边漂移、指针缺失与精确匹配；真实 API 的“历史版本新 key 拒绝、原 key 同 id 回放”宜并入主线受影响检查。此报告不把纯替身检查当作真实数据库 CAS 联验。

## 已确认的接线边界

- **原值与固定范围**：`_read_report` 从注入的受控 OriginalStore 读取登记原件 bytes，核对实际 hash/size/media、安全 epoch 与 Artifact/Original 当前 ACL；不使用派生 `Artifact.content` 替代报告原件。固定 ReportBinding 含历史 Run 基底、原件身份和完整 sample/item/实际配置/模穴范围，Measurement UUID 由服务器分配。旧 Measurement 的 DTO、保存摘要及逐行原件核验仍相互比较；可空/缺失元数据由纯 verifier 保留未知，不从计划回填实测值。
- **私有捕获委托**：提交候选使用 `_row`，限当前 owner。`_measurement_capture` 只为当前可读的正式 Measurement 委托读取其固定证明，精确限定 tenant/product/project/build/request/run；原件 ACL 仍独立核验。该委托不使他人获得草稿列表或提交权限，也不扩大私人原件受众。
- **CAS 与回执**：共同 execute 在幂等/semantic 回放之前调用模块当前 validate；新写 `_new_write` 核 Product revision、FormalCurrent、RunCurrent 及状态。旧合法意图返回原 Receipt，不更新 Current。共同服务拥有唯一确认/具名批准消费、Receipt/Audit/Outbox 与事务；领域包没有独立 commit 或第二份确认。最后一步失败应由共同事务回滚，待 PG 证据确认。
- **分级与资格**：`test.results.import` 为 T1，`test.result.compute` 为确定性 T0，`test.run.review` 和 `test.disposition.decide` 为具名 T2。T2 使用 `approval_token`，与 T1 `confirmation_token` 分开；当前人类身份及精确用途专业资格重新核对，ProductGrant 不作为专业资格。当前结果服务不授 AI 写入资格。
- **部分/最终结果**：部分结果保留未覆盖范围，要求缺项原因与下一责任人；最终结果检查固定覆盖和实际结束时钟。专业复核/处置追加不可变 Run/Request 版本，不覆盖原读数、原报告或原实际配置。
- **稳定判定基底**：`_projection_basis` 绑定 `fixed_run_sha256`、按 UUID 排序的完整 Measurement、实际结束/最终返回事件、规则版本及规则文件 hash，仅排事件 `received_at`。Preview 与 apply 的服务器接收时刻变化不会制造不同判定意图；复核/处置时钟不进入原值判定基底。结果适配器 `RetainedSamples` 明确拒绝 reserve/inspect 新资格，回读原消费证明，不重新预约或消费。

## 证据与尚待出口

[results-initial-get.json](results-initial-get.json) 的当前 running Run `import=true/compute=true` 与已过窗口并不冲突：这些动作核对保留的原开测事实，仍要求今天的结果办理资格，不能据此宣称新开测许可、资格续期或库存释放。

[priority-pg-initial-result.json](priority-pg-initial-result.json) 记录两项初跑 `exit_code=1`；[retained-priority-initial-result.json](retained-priority-initial-result.json) 也保留原失败。主线已说明初跑受已应用 next_0019 JSON 操作数优先级 guard 错误影响，准备以单调 next_0021 修复并复验。本审查未运行迁移或复验，不替这些记录宣称通过。最终出口仍须主线记录修正后结果链、回滚、TOCTOU 三项 PG、候选联合选择及真实窗口后的 HTTP 导入；模拟迟到读取时点测试与真实自然经过窗口证据须分别表述。

未发现上述两项修复在本次定向源码范围内仍存在具体未解问题；此结论不扩展为全仓库安全审计、所有并发路径证明或生产资质验收。

## 本次读取摘要

| 文件 | SHA-256 |
|---|---|
| `pdos-next/server/pdos_next/domain/verification_results/service.py` | `c0f4e4dc465868264167c77362ed831224856b923d073e06aae7c3979b27b8d0` |
| `pdos-next/server/pdos_next/domain/verification_results/adapters.py` | `856b4b3c828f0b8de4124191aa09d2144a821f9aff7de67f3c77a16bab0caee5` |
| `pdos-next/server/pdos_next/domain/test_resources/retained.py` | `abf1c6d4599b3a5c13f113666b1971e85bfb173b5c27e1b34e1e17197517e0de` |
| `pdos-next/server/pdos_next/domain/measurement_evidence/verifier.py` | `0f833b0dfcfa151442580ef1aa92dd0c55b57a79c9d0afb56eda995741ff162f` |
| `pdos-next/server/tests/verification_results/test_pure.py` | `52da69b7d399720de607884b3727054d78d124cbf22623ee31e9bdc90a662816` |
| `pdos-next/server/tests/verification_results/test_runtime_guards.py` | `3047f29de5aefda1087a869885efc41db6fde6d15520a7cc9a359ca4254b55b7` |

这些摘要描述审查读取时的有限集合，后续候选以主线冻结记录为准；不覆盖整个旧轨、工作区或联合候选。
