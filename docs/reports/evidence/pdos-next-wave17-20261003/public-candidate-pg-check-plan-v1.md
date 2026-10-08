# Public candidate — minimal actual PG check plan

仅静态计划，未 DB/HTTP/pytest。Root 在既有已核对独立目标再次核 marker/head `next_0026` 后集中执行；每个 SQL 负例独立 SAVEPOINT，最后回滚，不更改已保存演练行。
绑定：迁移26 `2229809083a26528a9122e596c69a31c615218a0c44ced7cfd39fdb64b05c053`；common `d1ba6e06be3a7369c60bbe163560bf59057b82091cee4540817fda8840732ce5`。
actual prepare JSON修正版 `c27c60bfc02ce565adec098175651f4dc70120f7f38ef09885b5bacc41ea9cf9`；writer `db63ba46bdf3e76c9683a89c6685e81ce65749bfae3710894ff7e949da25b696`。

## One reusable legal group

使用真实 Current=原完成 Issue、CAPA、真实原失败桥/源/专业/政策与完整≤20读集；未接端口按实际503，不能用 DTO/布尔stub制造正例。
入口：candidate `inputs`取得真实选择/读集 → `preview_command`保存13键 Confirmation → 同 actor exact返回命令 `execute`；如需分解 SQL 负例，用同 Session actual `prepare_write_review` → `consume_material_confirmation(prepared_review,write_phase)` → `apply_prepared_write(consumption=actualtuple)`，不自行造消费marker。
合法 outer COMMIT：1 candidate、1实际False→True proof、1匹配 Receipt/Audit/Outbox及原RequestKey；owner/visibility继承origin、writer实际actor、Issue Current与既有占用/样件消费计数不变。
同/跨key replay：先当前来源/资格 gate，再返回旧Receipt；candidate/proof/Audit/Outbox数不增，跨key只可增加RequestKey。保持原token/key有序读集语义，不重建request_digest。
保存必须 `candidate/indeterminate`，三列NULL和snapshot三项JSON null；四键input_snapshot，无token，实际common intent，Receipt仅展平id/revision/status/binding和inspection两hash。
Audit/Outbox负例使用分解入口在actual `append_receipt` 返回后处理pending子行，随后flush；完整execute末尾831行已flush，不能在它返回后expunge旧子行假装未保存。RequestKey/digest取同真实命令和actual common材料，不从任意alias推原请求。

## SQL/permission matrix

| 检查 | 最窄构造（全合法组只改这一处） | 预期阶段 / 真正边界 |
| --- | --- | --- |
| 缺Receipt | actual分解writer已add，flush proof+candidate，暂不调用append_receipt | deferred `capa_publication_required` / `assert_capa_publication_atom`拒绝 |
| 错Audit | common append后、首次flush前，将pending Audit.actor_id改为同tenant另一真实Principal；其余组完整 | deferred `assert_quality_change_receipt`拒绝，不接受FK错当通过 |
| 缺Outbox | append_receipt已flushReceipt后，expunge其尚未flush的唯一pending Outbox；保留Audit/RequestKey | deferred same receipt-group guard拒绝；不要DELETE已保留event |
| 错Receipt两hash | actualwriter后在append_receipt前仅改非mapped action_result其中一hash；完整body保持 | deferred candidate Receipt hash guard拒绝，不靠重复PK |
| 消费钟早于proof | writer add后首次flush前，仅改新row.input_snapshot.proof_consumed_at为proof.created_at−1µs | deferred `Candidate retains actual consumed and saved clocks`拒绝 |
| 消费钟晚于保存 | 同上改为row.created_at+1µs，原proof/row其余不改 | deferred同clock guard拒绝 |
| 保存时已过期 | pending新row.created_at=原proof.expires_at；完整group仍配对且Grant期限覆盖该钟 | deferred `assert_quality_followup_proof`拒绝（expiry end-exclusive）；不改原proof TTL |
| 列三NULL违规 | pending新candidate三个nullable布尔列逐项设True/False，其他不改 | immediate CHECK / SQLSTATE23514；逐项参数化 |
| snapshot伪null | pending snapshot三个字段逐项删除或置false，列仍NULL | immediate snapshot CHECK拒绝，COALESCE不能缺key失开 |
| agent直接INSERT | admin设置实际pdos_agent角色/tenant后用新UUID完整合法candidate列INSERT | immediate privilege SQLSTATE42501；agent无直接写，不用invalid NULL/PK测试 |
| app直接UPDATE/DELETE | 对已保存候选尝试改reason/DELETE，nested rollback | immediate privilege拒绝；不能以app权限代替append-only触发器证据 |
| admin UPDATE/DELETE | 对同已保存候选尝试reason=reason或DELETE，nested rollback | immediate既有24 `retained_record`→protect_next_snapshot拒绝 |
| 无target却consume | fresh真实未消费proof，实际False→True但不保存任何candidate/Receipt | deferred `require_quality_followup_consumption_atom`拒绝，无孤立消费 |
| old消费复用 | 仅在独立nested probe引用已成功proof构造第二target（fresh UUID/intent） | deferred proof uses必须exact1；不得将旧consumed=true当本次证明 |

各 deferred 负例先完成非被测组的合法insert/flush，再 `SET CONSTRAINTS ALL IMMEDIATE` 显式触发；另保留1个真正outer COMMIT正例核 deferred原子组。SAVEPOINT失败后回滚该点，恢复deferred模式；不删除/禁trigger、不改role grant或旧资料。
检查缺Receipt/错Audit/缺Outbox时必须保留实际False→True及完整source/origin，避免先被错误readset、旧proof重用或FK拒绝。每次fresh UUID/key/intent和fresh真实预览，隔离重复PK/唯一性误命中。
权限/时效业务负例另经actual `execute`：private非owner或当前newOP资格不足应403且未消费；当前来源撤回/issuer或专业ABA阻重放；过期proof拒绝新写。只改变真实具名门禁，不能用Owner Context代授权。
采集 actual SQLSTATE、constraint/trigger/function或RAISE原文、before/after candidate/proof/Receipt/Audit/Outbox/Current/holds/usage；任何意外PK/FK/源缺口算构造失败，不算目标guard通过。
本矩阵不检查七owner正向适用性/独立性/观察完成，不开放Review/Effectiveness/Close；所有正常候选继续三NULL/indeterminate。
