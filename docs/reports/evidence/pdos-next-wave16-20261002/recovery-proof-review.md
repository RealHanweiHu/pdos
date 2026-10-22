# Wave16 · 未知提交、到期 T2 与重预览的只读恢复审阅

本记录只审阅当前源码。没有读取私有种子/凭据，没有连接 DB/HTTP，没有运行测试或修改 Server/UI。Root 提供的事实是：原 T2 在延期 SQL guard 抛 `22P02` 后回滚；UI 保留 `stage=execute` 的原 prepared command；原 T2 已到期，按原请求恢复得到 `409 CONFIRMATION_REQUIRED`。本记录不替代 Root 对实际回滚与回执的核查。

**结论：普通 HTTP 409 或这个错误码不足以让未知提交界面解锁、删除原请求或换键。** 已核实原 SQL 请求回滚能证明该次 UOW 未保存；它不自动证明其他可能的恢复请求未保存。当前代码的确定失败分支具有更强的内部含义，但错误响应没有把完整原请求、失败阶段、proof 的具体状态及“未查到保存”绑定成客户端可验证的合同。最小恢复应先取得服务器明确的原请求结果；仅在原证明确实未消费且已不可执行、三层保存查找均为空、当前固定前版仍可新办时，允许去掉旧 token 并重新预览同 command/key/业务语义。

## 共同执行的实际次序

[`service.execute`](../../../../pdos-next/server/pdos_next/service.py#L481) 在同一 tenant Session 内先锁 Product，并按下列顺序执行：

| 阶段 | 当前代码 | 对“没有保存”的意义 |
| --- | --- | --- |
| 1 | DTO、当前 Product/Grant、Run/AI 资格、每个 `source_read_set` 的当前来源、`module.validate` | 均发生在查 RequestKey 之前。来源撤回、ACL/专业/原执行依据变化可以挡住一个已经保存的请求回执；任何这些错误都不能推断原请求不存在。Wave16 validate 调 `_load`，确切历史版仍重核原失败 bytes、retained、政策和当前办理资格。 |
| 2 | 查当前 tenant/actor 的原 `idempotency_key`，比较完整 `request_digest` | 同键同体直接返回原 Receipt，不要求旧确认仍有效。同键异体抛 `DUPLICATE_INTENT_CONFLICT`，不再进入 semantic replay。 |
| 3 | 服务器派生 semantic intent，查 product/intent 的 Receipt | 同意图别键可登记原 Receipt 的键别名并返回，不再消费证明。不是第二次领域写入或复制 Receipt。 |
| 4 | `module.replay_subject` → 查 exact operation/subject family/subject row 的原 Receipt | Wave16 根因/完成返回精确旧 QualityIssueVersion；Link 返回固定 Link。只有查到原 Receipt 才成功返回，不把“有 row”当成功回执。 |
| 5 | `consume_material_confirmation`：查 proof、校验 material/read snapshot、置 consumed、记录 same-UOW marker | 在三层回执查找之后。原键/意图没有成功返回时，才需要实际有效确认。 |
| 6 | `module.apply`、领域核确认、Issue/Link、Receipt/Audit/Outbox/RequestKey，Session 出口 commit | 延期约束可在出口失败；此前内存里生成结果也不是已提交结果。API 在 Session 出口之后才返回回执。 |

因此，**若** Root 通过实际调用链确证这次响应来自第 5 阶段、输入就是原 prepared command、当前源码与预期一致，那么它说明此事务在 Product gate 内没有通过前三层找到匹配原回执，并且这次失败请求没有新增提交。它不是“所有同码错误在所有操作下都具有 no-saved 含义”的公共合同，也不是对后来并发请求的永久断言。

[`tenant_session`](../../../../pdos-next/server/pdos_next/database.py#L20) 使用 `session.begin()`；异常退出回滚本次事务。原 `22P02` 即使发生在 commit 的 deferred guard，也必须回滚该次新 Issue/Current/Confirmation/Receipt/Audit/Outbox/RequestKey。`quality_followup_host` 内存 marker 只属于实际 Session/transaction，不是持久成功凭据。回滚不抹去较早成功请求的历史。

## token 与两类摘要不能混用

- [`request_digest`](../../../../pdos-next/server/pdos_next/service.py#L506) 使用完整 typed payload，**包含 `approval_token`/`confirmation_token`**；同时包含 product/expected revision 和原顺序的 source read set。更换 token 后仍用原 key，若原请求实际成功会首先变成同键异体冲突，不会顺利返回其 semantic Receipt。不能先替 token，再拿冲突解释为未保存。
- [`material_digest`](../../../../pdos-next/server/pdos_next/service.py#L386) 固定 tenant/actor/requester/operation/product/expected revision、排序读集和 `module.semantic(payload)`。后者在 [`quality_followup.semantic`](../../../../pdos-next/server/pdos_next/domain/quality_followup/service.py#L131) 明确排除两个 proof token，其他 Issue 前版、结论/完成原事实/来源保持。
- generic semantic Receipt intent 与模块持久 row intent 采用不同服务器结构；恢复必须复用现有两层构造及 `replay_subject`，不能只按客户端 text、command_id 或一个猜测摘要查找。
- `request_digest` 不含 command_id；RequestKey 以 tenant/actor/key 唯一，Receipt 以 product/semantic intent 唯一。保留 command_id 是实际 same-UOW marker/历史审计恢复要求，但单查这个 UUID 不是完整幂等证明。

## `CONFIRMATION_REQUIRED` 的可达来源

[`confirmation_for`](../../../../pdos-next/server/pdos_next/service.py#L308) 将以下三种情况合并为同一个 409：找不到精确 actor/product/op/subject/token hash 的 Confirmation、已经 consumed、已经到期。错误返回没有区分三者。

[`consume_material_confirmation`](../../../../pdos-next/server/pdos_next/service.py#L453) 对 T1 token 缺失也抛该码；T2 token 缺失则是 `NAMED_APPROVAL_REQUIRED`。T2 有 token 但无有效行仍走上面的通用 `CONFIRMATION_REQUIRED`，所以码名不能代表分级或提交结果。

[`quality_followup.TransactionCommands.confirm`](../../../../pdos-next/server/pdos_next/domain/quality_followup/adapters.py#L43) 在 apply 中没有 actual UUID 时也能抛 `CONFIRMATION_REQUIRED`。正确 host 的缺少/失效/错误绑定 marker 通常抛 `NAMED_APPROVAL_REQUIRED`；两者都只说明这次证明不能继续，不应被 UI 泛化为成功与否的判据。当前 preview 用 `_prepare`，不调用实际 `confirm`/消费 marker。

仓库其他领域也复用该错误码（旧品质、验证/交接/开测/结果等 adapter、variant 的冲突选择），且 `confirmation_for` 还用于撤回/取消。因此不能在全局 error handler 或所有 UI 的 409 分支增加通用“未保存”承诺。

[`api.domain_error`](../../../../pdos-next/server/pdos_next/api.py#L154) 当前只返回 `{code,message}`，没有 failure stage、已核查请求摘要或 save-state。当前 UI 的未知恢复分支保留原 prepared command、禁改输入、仍按原请求恢复，是必要的保守行为。现 workspace Receipt 列表限 60 且按当前受众过滤，列表中没有原回执不能代替精确无保存查询。

## 最小受控恢复合同（建议，尚未实现）

可以由 Root 新增窄服务器解析器/endpoint，或只在 `execute` 的**特定已完成去重而尚未消费**分支返回明确标记；不能给普通 `CONFIRMATION_REQUIRED` 整体换一个可解锁文案。解析输入必须是原完整 `Command`，包括旧 token。一个建议名称为 `resolve_command_recovery(s,ctx,original_command)`，不执行 apply、不消费 proof、不创建键别名/Receipt、不调用预览。

它应在当前 tenant/具名 actor 与 Product gate 下：

1. 保留当前权限、来源、专业/政策/retained 的独立核查；有权限/来源/资格缺口就返回 `blocked/unknown`，不得把“不可查询”变成“查无记录”。既有 Receipt 的公开投影仍遵守当前私有范围。
2. 用原 request digest 查原键；存在同体则返回原 Receipt，存在异体返回明确 conflict。再查现有 generic semantic Receipt 与模块 exact subject replay 的原 Receipt；发现保存则返回同一原回执，不续期、不再次办理。
3. 精确核查旧 token 对应的原 Confirmation：必须绑定原 actor/product/op/revision/material 与原固定 review；允许重预览的本次范围应要求 **`consumed=False` 且服务器时钟已过 `expires_at`**，或未来另建设的明确撤销事实。`consumed=True` 但没有原目标/Receipt 是需调查的原子完整性缺口；缺失/错 token 也不自动视为已过期原请求。不得置 consumed 来“废弃”旧 proof，这会破坏双向目标配对。
4. 核对 QualityIssueCurrent 仍精确等于原 payload 的固定前版，当前完整 read set/用途/本人及所有实际来源仍能办理。若当前版/依据已变化，返回清晰阻断；不自动改 expected revision、完成发生时点、executor、引用、结论或读集，不自动另造新键。
5. 只有三层保存均不存在、原 proof 已不能未来执行、当前新办理守卫通过，才返回 `no_saved_expired_proof + repreview_allowed=True`。该结果应绑定 tenant/actor/product/op、原 command_id、原 key 的 hash、完整原 request digest、token-free material/semantic digest、fixed subject/version、原 proof identity/hash/expiry、服务器 checked_at。不可输出原 token、私人来源全文或 SQL。

同门锁意味着较早已在执行的同 Product 请求必须先 commit/rollback，再判断无保存；已自然到期的旧 proof 又阻止后面排队的原 prepared command 再新写。这是本次到期场景能够安全恢复的重要条件。若旧 proof 仍有效，不宜返回可重预览状态，因为原在途命令可能在无保存查询以后提交；不能只凭查询瞬间为空保证未来不保存。

建议返回状态为 `saved`（原 Receipt）、`no_saved_expired_proof`（仅允许同语义重预览）、`blocked/conflict/unknown`（继续保留原请求）。不需要为了 this read-only resolution 创造第二套 Receipt/Confirmation；也不能在异常失败事务内发送一个未来无法保证的 no-saved 标记。它必须是同一受控产品水位/原请求的明确结果，HTTP 状态码不是证明。

## 本次同 cmd/key 的恢复步骤

先让 Root 对实际原 SQL UOW 的回滚和原键/意图/subject Receipt、旧 proof 未消费到期、Current 前版做精确核查并形成上述明确结果。若已有保存，只回读原 Receipt；当前 gate 拦住回读就显示阻断并保留原请求，不能重办。

取得绑定的 `no_saved_expired_proof` 后，UI 可将同一 pending 从 execute 转到 preview，**仅移除旧 `approval_token`**；原 command_id、idempotency_key、operation、product/expected revision、payload 业务字段、完整读集及实际时点逐项保留。重新请求共同 preview，显示服务器最新实质 before/after；本人再次 T2 批准其 returned prepared command。旧证明仍留作到期未消费历史，不人工续期，不把新 token 拼入旧 execute 而跳过预览。

如果重预览因真实 scope/source/CAS 改变而失败，继续显示该实际缺口，不换 key 绕过。不把本人再次 T2 当“重试自动批准”；这个恢复只更新已经确认未保存且不能再执行的 proof，原业务意图保持。

## 只读底稿

| 文件 | SHA256 |
| --- | --- |
| `pdos-next/server/pdos_next/service.py` | `8df806e61ad64cc6f87aa2cfea92114c9877e2ba3af7cfba347d729ccf663d84` |
| `api.py` | `837761134b1561526deddbe7170f258de8459f684453cfdba4f4ca67631db056` |
| `database.py` | `a64c91d9f9a465be48b2585198ca7db802d37de0a38b2fed1064e445535c0858` |
| `errors.py` | `156ed50d73580761af3203a586bcc31aa5e251c9109d2a8d0d9b978a92c5a7fd` |
| `contracts.py` | `0e94b31d5323ff40ab789cc6cc2f9468e710fafbe44b1cd3fd307d12adb38bc7` |
| `quality_followup_host.py` | `6b67f2d9d20bfbd48d869aa2028ba92d84e85660e7a27d3e4fc8c049035470de` |
| `domain/quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| `domain/quality_followup/adapters.py` | `7964e501de893cb137b269e54065d3ab1842b860cf35eb85adc8d8eaae9f768e` |
| `domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| `pdos-next/web/src/components/builds/build-quality-followup.tsx` | `b00f6c5be2302a58882a2540a86cdc1a14cbe0a6c6bda54b0f4e76454ae1f4d6` |
| `pdos-next/web/src/lib/build-quality-followup-view.ts` | `c44ea7a6957570350d7af248095a2e6091787dc56906ba165ddabc9108c9f4e3` |

本报告只声明源码次序和建议恢复合同，未实施 recovery endpoint/标记、未清理浏览器 pending、未取得任何实际无保存证明，未授生产资格或人工 Exit。

## Root 实施后的定向复读

上述是实施前读稿；随后 Root 在共享代码实现了窄标记，本审阅者只读核对，没有改这些代码。当前 `consume_material_confirmation` 仅在三操作的 `confirmation_for` 抛 `CONFIRMATION_REQUIRED` 后调用 `quality_followup_host.expired_confirmation_recovery`，并且调用位置仍在 RequestKey、semantic Receipt 和 module subject Receipt 三层查找之后。

host 仅接受本次具名 ctx、当前 Product/expected revision、exact tenant/actor/product/op/subject/token hash 的实际 Confirmation、`consumed=False`、确已过期、相同 material digest，以及 IssueCurrent exact expected revision。返回原 `Command.model_dump(mode="json")`，仅删除 payload 两个 token；不标准化/删除其他字段，不写域对象、Confirmation 或 Receipt。API 只将明确的 `FOLLOWUP_CONFIRMATION_EXPIRED` 所带 recovery 透传；普通缺失/已消费/语义不匹配 proof 的错误仍无标记。

这个实施合同支持上述“到期、没有保存且原 proof 已不能再执行”的最小场景，没有一般性解锁普通 409。fresh preview/execute 仍重新执行全部当前来源、专业、政策、retained、Current 及 actual same-UOW proof 守卫。静态未发现本次新增分支削弱这些守卫。

特别保留两种重放区别：恢复后**新保存的完整 prepared command** 即使 proof 随后 consumed/expired，查原键应返回同一 Receipt；旧失败 command 仍含旧 token，和新保存 key 的 request digest 不同，应精确 `DUPLICATE_INTENT_CONFLICT`。不能把旧请求在换 proof 后也描述为同键同体。

复读源码 SHA256：`service.py=d4afc3197e77899c6211eba339fefe6ca9e317ee6b6d9ddec622128db4b7838a`；`quality_followup_host.py=9400df47e01a8c7b4e9dc7f65bd56279da167e4de1f772509c864d0d079a7cb2`；`api.py=86820c67069235716e687359d775dc03d742ba704d565ec758f5660b9a94eb51`；`errors.py=b1fc79f99e469a9fb8a59c03f602b64e9ade50dfbf35ae23468a97905bf20d5f`。这些与上表实施前底稿不同，旧 SHA 留存，不互相冒充。

另按 Root 归属新增一个实际 PG/API **待运行**候选 `tests/quality_followup_root/test_expired_recovery.py::test_expired_followup_proof_has_bound_no_saved_repreview_and_saved_replay`，SHA256 `62a32281febdc1a8ada168fc5c8f9bd09aec450ea216edf0bea4b0e404f6ea9e`。Ruff、format check、AST 静态通过，没有执行 DB/HTTP/pytest。该候选只在到期拒绝/保存回执重放阶段对两个 expiry reader 使用受控截止时钟；实际保存、SQL、事件/专业时钟保持真实，不声称墙钟经过了十分钟。其余实际 expiry/回滚/浏览器恢复证据由 Root 验证。
