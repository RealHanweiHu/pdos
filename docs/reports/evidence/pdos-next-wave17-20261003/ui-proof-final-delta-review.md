# Wave17 paired 最终增量 · 追加只读审阅

记录时间：2026-10-03T10:04:13.477165+00:00。保留[原51项版审阅](ui-proof-independent-review.md)（SHA256 `1764a2d0f4e20f083944b72281ecc80d99aa8ec931139c60f8652944b19b6db3`）不修改。这里只读 Plan `_command_fact` 增量、六个新增拒绝用例及工具 planned/draft 断言；未编辑源码、执行测试、连接数据库/HTTP或运行公共验证。

## 57项版准确快照与增量

| 文件 | B 冻结57项版 SHA256 |
|---|---|
| `pdos-next/staging/wave17/paired.py` | `da00ee74196eb5a5165cec97c2ec3d16c57b93b6f23913b619fd796103354141` |
| `pdos-next/staging/wave17/test_paired.py` | `3358e8b1405738c4b4e12f5e65a065b9122f11a0864f78ab275325a2615b72a9` |
| `pdos-next/staging/wave17/paired-contract.md` | `3a597197ae30ebdfc94515c25d5c12f201770a0b2073e086e0e3b5265f5900f1` |

`paired-final-delta.json` 记录 B 所属57项纯用例通过；C未执行它们，也不把51+57累计成108。读取57版 `paired.py` 后在内存中仅删除新增 Plan 检查块，SHA256 精确还原原已审 `73bff65b00b45e2678a18ad9ff8ea8def12d01aff3c4fb85d60d5d5386c420e3`，确认逻辑变更仅该块；没有改动文件或导入模块。

新增 `paired.py:1094` 检查 Plan.kernel_event.at 的 SourceRef 必须为真实 Receipt.command_id、revision=1、kind=command、position=receipt，original_timezone=UTC，actor与Fact/Receipt一致，occurred_at=received_at；既有完整Fact hash、Event逻辑subject/coverage、保存钟与Receipt顺序、Scope/Current、opaque same-UOW gate均继续核对。对应四个SourceRef字段及两个钟字段的六个负例，都重算kernel event SHA后要求拒绝，避免仅被旧摘要拒绝。

## 尚待修复的准确缺口（57项版）

**Plan的 effective_at 未被限定为None。** 实际 `VerificationHandler._command_fact`（`server/pdos_next/domain/verification/handlers.py:117`）构造 TimeFact 时未指定该字段，沿 `EventTime.effective_at=None` 默认保存。57版新增检查却未核它。可保持command来源、UTC、actor、occurred/received以及全部其他材料不变，仅把 Plan.kernel_event.at.effective_at 改为任意aware时间并重新密封event摘要；EventTime允许该值，Plan原载荷不含事件，其他Plan路径也未拒绝，无法证明是实际 `_command_fact` 完整时钟。

最小修复：Plan检查增加 `clock.effective_at is None`；补一个重密封负例验证非空effective_at拒绝，合法Plan继续保留None。该发现已发送Root/B，Root已授权B仅在所属staged两Python文件修复；C不改文件、不运行用例。57版不能宣称没有剩余问题。实际宿主尚未挂载，这不是已启用业务写入漏洞。

## closeout planned/draft 对照

当前 `tools/wave16_closeout.py:833` 同时核 output.status='draft' 与 output.meaning='planned'，与实际 `domain/capa_verification/service._reading` 的 verification_request 分支一致。新Draft的 Current v1、真实direct canonical Receipt、精确prep/Build/来源、无Run/实物样件/交接/执行钟仍由 new_draft 独立核。planned只表示计划输出，不把Draft当performed，也不放宽任何proof gate。

工具SHA256：`72a1aac6f01c7244c9ed5a262af98f0fd5be460297e79788131867249fcb806d`；实际owner service SHA256：`91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af`。本轮仅确认该准确断言，不重跑工具或扩大工具审阅。

## 后续修复复核

待B最终源码哈希交付后追加本节。原57项快照、发现与旧51项证据保留；真实host/bytes/专业资格/同事务消费与公共集成边界不变。

### v3 最终58项版复核追加

追加时间：2026-10-03T10:05:02.664831+00:00。上文57项版准确快照、发现和暂存待修状态保留；本追加为最新结论。追加前本报告SHA256为 `990f54ca1d224e642a0cc1503de8f116e5daee03a7c4b6578996815247d6b6ee`，原51项审阅文件未修改。

| 最终文件 | B v3冻结 SHA256 |
|---|---|
| `pdos-next/staging/wave17/paired.py` | `3cff4b1534533b2797f201faceede7e2a9514d84240ca06c6953b1de20dce750` |
| `pdos-next/staging/wave17/test_paired.py` | `8da00ea85c90fb6694a911351623821ab69c6289f4e5868b71bc3486e8a60987` |
| `pdos-next/staging/wave17/paired-contract.md` | `3a597197ae30ebdfc94515c25d5c12f201770a0b2073e086e0e3b5265f5900f1` |

已只读确认 `paired.py:1100` 增加 `clock.effective_at is None`；`test_paired.py` 的实际server command clock参数增加 aware非空effective_at，仍重新密封kernel event SHA后要求PAIR_EVENT_MISMATCH。合法Plan初始TimeFact保持None，真实 `_command_fact` 默认含义不改变。

只在内存中撤去这一行，源码SHA精确还原57项版 `da00ee74196eb5a5165cec97c2ec3d16c57b93b6f23913b619fd796103354141`；只撤去新增负例参数及其格式展开，用例SHA精确还原 `3358e8b1405738c4b4e12f5e65a065b9122f11a0864f78ab275325a2615b72a9`。合同SHA不变，证实最终增量未扩DTO、宿主或六操作规则。上述是文本/哈希只读核对，无文件修改或测试执行。

B 的[所属v3检查记录](paired-v3-checks.json)（SHA256 `ec5675b2666998b48799338769494056fa205961316664dbd6edd3d4fc102843`）记录58纯用例、0失败、0.99秒及所属静态通过。C只读该记录，未运行它们；58是当前覆盖数，不与57/51相加。

**最新结论：本次准确Plan时钟遗漏已修复，定向最终增量未发现新的明确结构错配。** 同一command来源、UTC、actor、occurred=received、effective_at=None与真实kernel `_command_fact`一致；计划仍planned且无实际执行/结果事实。opaque host gate、真实 bytes/专业/Current/同事务证明与公共集成仍未接通，不能据结构通过宣称当前业务资格或生产启用。closeout的status=draft/meaning=planned断言结论不变。
