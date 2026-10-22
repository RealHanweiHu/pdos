# Wave16 暂存回链预览 phase 合同

状态：仅暂存 Python 协议与纯检查；没有迁入 server、挂载 API、修改共同 handler 或接通公开业务。用户的完整建设授权持续有效；当前保持现有480候选不变是主线冻结纪律，不是新增用户许可关卡。

## 公开签名与宿主接缝

```python
prepare_preview(s, ctx, command, product, payload) -> PreviewPhase
preview_prepared(s, ctx, command, product, payload, phase: PreviewPhase) -> dict
```

参数是实际 SQLAlchemy Session、`Context`、`Command`、本 Session 已持久保存的 `Product`、完整已验证 `FollowupLinkPayload`，只接受 `quality.capa.followup.link`。返回 Phase 是不可构造、复制或 pickle 的进程内单消费对象；不可作为 HTTP 输入/输出，不是权限、ProofID或Receipt。

主线以后可在 `preview_command` 的正常 Product FOR UPDATE、require_access、本人human与完整SourceRead检查之后，为该明确 opt-in 操作调用 prepare，再调用 preview_prepared；其他 handler 维持原 validate/reviewed_view。prepare只调用一次 **实际 `capa_verification.commands._load`**，不另造完整owner结论。第二函数继续调用 **实际 `_new_write`**，因此产品/Issue Current CAS及该函数的独立末端 `_refresh`均保留，再调用原 `_review`。

仅这一个公共预览调用内共享该 Bound；inputs 与 execute 必须从头走各自原入口。主线尚需增加显式公共 opt-in dispatch，不能把所有模块存在 preview_view 当作已覆盖validate。此次不改共同 service/registry，也不改 execute、consume、key/semantic replay、证明记录或任何 writer。

## 精确绑定与 I/O 末端边界

- 保存实际 Session、主 transaction、nested transaction、get_bind()以及Product的对象身份；必须仍是同一活动UOW。进入消费先核事务身份，回滚/关闭/切换事务不能为旧phase触发ORM过期对象回读。
- 保存Context全5字段，限定本人、无Run；Command全字段含 command_id/key、完整payload/defaults/token/readset/产品水位，另保存完整已验证payload及所有实际Product映射字段。客户端摘要、参数相似或新key都不授予复用。
- Bound完整材料含resolution/basis/实际output、authority、policy、所有sources/reads/source_basis、visibility、真实旧Link全部映射字段及Proofcallback identity；nested dict变化也拒绝。允许新增私有来源收窄public resolution的Link受众，不允许反向扩大。
- stamp覆盖既有真实result runtime（安全/存储/专业、测试资源、制造issuer对象及完整epoch）、quality policy issuer/epoch、Link共同Proofcallback及所用真实loader/new_write/refresh/review/deadline/owner/professional/policy函数身份。无实际配置继续由真loader failclosed，不靠stamp缺字段判断可用。
- `_load`及`_new_write`全部owner/bytes I/O后，独立复核同UOW/完整binding/runtime/Bound，并用实际宿主now重新调用原专业/政策TTL守卫。clock倒退、到期、源或issuer ABA均不能复用成功准备；原owner freshness失败原样传播。
- 任何 preview_prepared尝试都消费phase，即使随后CAS/freshness失败，也不得重试旧phase。只能在当前或新调用中再次真实prepare。零global/cache/Session.info写入；既有Session.info共同已消费证明不被读取、复制或删除。
- 不调用consumed-proof callback、不生成Confirmation/Proof/Receipt，不commit/rollback/占用/消费。common仍拥有创建最终review对应Confirmation及后续一次实际消费、Receipt/Audit/Outbox原子组。

## 与原控制流的关系

现有common preview是 validate丢弃Bound，再preview_view完整重建一次。本协议仅合并这次重复：按原当前Issue版控制流可由2次_load/5次resolver变为1次_load/3次resolver。真实速度必须后续主线按新候选单独量取；纯调用计数不是性能验收。

Root另报告冻结候选的PG Link第一次写入在COMMIT被 `assert_quality_followup_proof` 拒绝，运行约2636.78秒。具体过期/水位原因仍待主线核定。**本协议不改变execute或deferred证明guard，不保证消除该实际失败**；不能用preview纯检查解释为该PG已修复，也不增大TTL或放宽真实Proof。

## 检查与限制

本包纯检查只用真实SQLAlchemy Session/transaction/ORM状态的无连接结构和明确fake loader/new_write；检查call sequencing、binding、nested rollback、材料/issuer ABA、源错误传播与时钟到期，不证明实际DB授权、原件字节、专业资格或事务commit。实际_common Product门栓、正常source gate、真实postIO refresh及deferred atom仍须主线公共接入后验证。

运行仅本文件，不加载repo conftest：

```text
cd pdos-next/server
.venv/bin/python -m pytest --noconftest ../staging/wave16/test_link_preview_phase.py -q
```

Ruff/format/AST只针对这两个新增Python文件。第一次纯回滚反例曾暴露过期ORM属性在先核事务前访问；已经移至任何材料访问之前核UOW，再由末端独立核一次。历史工具结果保留于本会话，新冻结检查另列，不与第一次结果相加。
