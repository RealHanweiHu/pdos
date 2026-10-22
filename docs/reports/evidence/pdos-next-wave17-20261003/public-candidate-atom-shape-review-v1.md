# 公共候选正向原子组结构审阅 v1

2026-10-03。限定源码只读比对；发现确定的 JSONB 结构阻塞后，Root 明确授权仅两处 public 文件与自有回归测试的窄修。未运行 DB、HTTP、公共测试、迁移；真实保存及回滚仍由 Root 验证。

**结论：初稿有一个会阻断合法预览/保存的序列编码缺陷，已窄修；修后本限定正向结构未见其他确定不互认。** 此结论不是 PostgreSQL 编译、真实提交、七 owner 门禁或生产资格通过。

## 发现与唯一功能修复

`PreparedCandidate.sources` 和 `required_source_read_set` 是 typed DTO tuple；`anchor.json_value` 对整个 tuple 仅 deepcopy。原 `candidate_prepare._material` 和 `candidate_write.apply_prepared_candidate` 用该结果写 review/JSONB，默认 `database.engine_for` 无自定义 JSON serializer，会遇 DTO 非 JSON 可编码，加载后的数组也无法和 DTO tuple 全文相等。`common.digest(default=str)` 不能替代规范 JSON。

四个调用现改为逐元素 `[anchor[s].json_value(v) for v in ...]`；保留原序、UUID/revision/kind/position 全字段。未改变 `anchor.json_value`、域规则、来源检查、所有权、消费或 SQL。Ruff 另只清理 public writer 五个迁入 import 的尾空格。旧 staged 源与原 v1 证据保持。

新 case 真调用 public writer 和实际 ConsumptionHost，在禁止连接的真实 persistent ORM/UOW 中验证：13 键 review、实际模型全部 JSONB 列及扁平回执结果都可 `json.dumps`，无 `default=str`；保留数组顺序/字段，严格 revision 拒绝 `True`。18 项 owned pure 通过（1.87 秒）；Ruff check/format 和三文件内存 AST 通过。两次新增 case 夹具状态失败原日志保留，修正仅在该 case，不作为生产失败或 PG 通过。[v2 检查](candidate-write-prepare-check-result-v2.json)、[v2 源清单](candidate-write-prepare-source-manifest-v2.json)。

## 正向字段互认

| 接缝 | 实际对应与限制 |
|---|---|
| Confirmation 原 13 键 | `candidate_write.reviewed_prepared_candidate` 加 operation，完整 payload_semantic/stable_anchor/binding/inspection/raw_source_basis/required_source_read_set/sources/authority_snapshot/policy_snapshot/owner_id/visibility/current_issue_revision。`candidate_anchor_restore.REVIEW_KEYS` 精确相同；common 存 whole snapshot；write prepare/最终 writer 全文相等核对，不重新 seal 原锚。 |
| 保存 input_snapshot 四键 | `semantic` 为 actual module.semantic 无 token；`shared_proof={id,tier:T1}`、actual first-capture `proof_consumed_at`、原完整 `stable_anchor`。它不是丢失另外九键：完整 binding/inspection/basis/source/专业政策另在不可变 row；mig26 明确要求这个四键 envelope。 |
| common actual intent | common.execute、ConsumptionHost._material、candidate_storage._group 均用 actual domain semantic + operation/product/named_actor/source_revision=None；private_owner 为本次 ctx.requester（真人 actor=requester），不是原 series owner。row.intent_digest 取 live.common_intent_sha256，mig26 与 Receipt.intent_digest 对照。 |
| 原锚、Current、purpose、受众 | row 从 phase.binding.basis 保存 exact issue_version_id/revision/CAPA/purpose/nature；owner 继承 origin series，writer 本次本人；payload.visibility 必须等于实际 origin/Basis。prepare v1 独立 CAS Current=origin，不借 origin 代 Current。mig26 assert_capa_fact_origin 对 exact immutable 完成版、scope/原 purpose/全部 original snapshot 和 private Project/Issue 做对应检查。 |
| 全来源闭包 | review 与 row.required_reads 为同一 canonical 完整数组；candidate_snapshot.required_reads 已扩大为同数组；source_basis.artifact_sources 保留 raw sparse native/uploaded provenance 不添缺省键。mig26 assert_capa_fact_source_closure 要 1..20 唯一 Artifact、逐版/原hash/active/owner/vis对应，所有 Artifact SourceRef 需在读集，private 不能共享。 |
| 候选保持未知 | basis_snapshot 等于 binding.basis；candidate_snapshot.binding 等于 row.binding，inspection_sha/basis_sha 对应；status candidate/result indeterminate/三个 NULL，符合原 ORM CHECK 与 mig26。候选无 Issue Current 写入、无有效性/关闭/再占用。 |
| proof / Receipt / Audit / Outbox | common 在消费 True 前绑定，True 后首行捕获 marker；writer 末端刷新后再 require_live 与真实 save clock。mig26 双向 deferred proof/target 配对支持同 UOW/SAVEPOINT，要求唯一目标、未改 proof、时效/Product 水位/真人。append_receipt 产生基础 id/revision/status + `action_result` 两展平摘要，正好匹配 mig26 不允许额外键的 candidate result。事件 `CapaVerificationCandidateRecorded` 与同 command correlation 一致。原 assert_quality_followup_receipt 还核初始 RequestKey/Audit/Outbox 恰一组。 |

SQL 保持 shape/持久原子组职责；全文 canonical SHA、真实原件、当前专业/政策/issuer/runtime 与三允许评估路径以外的不变性仍由 actual host 承担。本次没有用 SQL 文本 hash 冒充 Python digest，也没有授予七门禁。

## 精确审阅文件摘要

| 文件 | SHA256 |
|---|---|
| `pdos-next/server/pdos_next/domain/capa_effectiveness/candidate_prepare.py` | `c27c60bfc02ce565adec098175651f4dc70120f7f38ef09885b5bacc41ea9cf9` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/candidate_write.py` | `db63ba46bdf3e76c9683a89c6685e81ce65749bfae3710894ff7e949da25b696` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/service.py` | `33b7343e50e551d681a289d8d61f073a3b0ef1dce05d5f61aa16997dbca55223` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/candidate_anchor_restore.py` | `8fb00c833ade38f46668a1d7d9d94f94db8d81e7aa0cc48dd097fcb481c4d5a1` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/fact_consumption.py` | `6734844b1e844a4dabe71a261feb9a98a4d491da17268ffd9f2a4bb6284dbea5` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/candidate_storage.py` | `38c9dd40b454d92217040a1816465a7af47f1ff0373cafa5189542b0378e0dcc` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/anchor.py` | `2db9d275a2718fd1d0449e33372c3c2876fb73523c2120968e32f9fef70e7c82` |
| `pdos-next/server/pdos_next/domain/capa_verification/models.py` | `321a721fd5b90d9857f8e29603ef057f6b7cc1cf62e29ba27b036c3296952ef4` |
| `pdos-next/server/pdos_next/domain/quality_execution/evidence.py` | `f9b128b0cff62607415d16824bd6a8c1a7e9b30c397b1252991f1ec76bd98903` |
| `pdos-next/server/pdos_next/service.py` | `d1ba6e06be3a7369c60bbe163560bf59057b82091cee4540817fda8840732ce5` |
| `pdos-next/server/pdos_next/database.py` | `a64c91d9f9a465be48b2585198ca7db802d37de0a38b2fed1064e445535c0858` |
| `pdos-next/server/migrations/versions/0024_quality_followup.py` | `a957c6dbc22647f2f5dbb39fc014bb4b7ef269b014d9497642110cc4664df252` |
| `pdos-next/server/migrations/versions/0026_capa_verification_facts.py` | `2229809083a26528a9122e596c69a31c615218a0c44ced7cfd39fdb64b05c053` |

只读定位使用 `rg` 与限定源码行读取；静态迁移 SQL 未 import/执行。新的 functional 源 delta 仅上述四个序列调用；主线 actual HTTP/PG 正例与 rollback 结果不在此报告中推定。
