# Candidate public adapter checkpoint

本记录绑定公共 namespace 的新增薄适配层，不将暂存检查、纯替身或未接 owner 门禁视为真实业务资格。数据库、公共消费、路由、迁移和页面验证仍由主线办理。

## Actual identity and startup

`pdos_next.domain.capa_effectiveness.service` exports canonical `OPERATION=quality.capa.verification.candidate.record`, `TIER=T1`, subject `capa_verification_candidate`, event `CapaVerificationCandidateRecorded`。

`semantic` 与 `CandidateRecordPayload` 直接 alias `candidate_commands` 原函数和原类；`schemas.py` 保持同一 Payload 对象。公共 registry 应直接登记这一真实类，不能生成镜像 DTO 或 semantic wrapper。

可信 startup 调用 `service.configure(engine)`，建立实际 `CandidateAnchorRestoreHost(sys.modules[service.__name__])` 与 `ConsumptionHost({OPERATION: actual_module})`，保存于 `engine._pdos_capa_candidate_runtime`。未配置、替换宿主对象或 module identity 改变明确拒绝。此配置不导入资格、原件、政策、七 gate 或消费事实。

## Common call-stack contract

- `prepare_preview(s,ctx,command,product,payload) -> PreviewPhase` 完成一次实际 `prepare_candidate`，其内部已有全部 owner IO 和末端独立 fresh 检查。`preview_prepared(...,phase) -> dict` 在精确 Session/完整 UOW 链、ctx、command key/token/有序读集、typed payload、persistent Product 和完整阶段材料/运行端口身份核验之后取真实钟，再销毁该单次阶段。只渲染该准备结果；没有跨 HTTP 或事务缓存。
- `preview_view(...)` 使用上述两个函数；`review(s,ctx,product_id,payload)` 返回真实 13 键材料；`validate(...,replay=None)` 在共同去重前执行实际当前准备与完整读集检查，将 Product CAS 留给预览/新写。旧成功回执重放仍经过当前 owner/专业/来源门禁。
- `prepare_write_review(s,ctx,command,product,payload,proof=None) -> (WritePhase, original_snapshot)`。缺 `proof` 时调用实际 `confirmation_for`；传入实际 A `prepare_candidate_write(...,proof,runtime.restore_host)` 恢复持久 Confirmation 的首预览完整锚，独立重新核对当前 owner。`WritePhase.proof` 是共同消费者必须复用的同一 persistent ORM 对象。缺专用恢复/准备接缝明确 503。
- 共同服务在实际 `confirmation.consumed=True` **之前**调用 `bind_consumption(...,write_phase,confirmation) -> binding`。
- 赋值之后紧接 `record_consumption(...,write_phase,confirmation,binding) -> marker`；本适配不先执行 SQL/owner IO，实际 `ConsumptionHost.capture_after_transition` 捕获第一次真实消费钟、ORM False→True 历史。该适配不写 consumed、不生成证明。
- 共同服务局部传 `(binding,marker)` 给 `apply_prepared_write(...,write_phase,consumption=(binding,marker))`。它委托原 `candidate_write.apply_prepared_candidate`，仍执行 actual `require_live`、完整 owner 独立刷新、当前 TTL/钟和来源安全门禁；随后只 `s.add` 不可变候选。追加后纯绑定复核防止 owner IO 中宿主/UOW/完整命令发生替换；异常由共同事务回滚。
- `apply(...)` 没有无证明 fallback，明确 `INTEGRATION_REQUIRED`。本适配不使用 Session.info 储存阶段、Bound 或 DTO 授权；原 actual ConsumptionHost 自身的同 UOW 消费登记保持其真实宿主契约。

`inputs(s,ctx,product_id,command)` 返回 `{operation,allowed,required_source_read_set,authority,review}`。它可供客户端取得完整读集，实际保存/预览必须提交精确并集，不能自动代填确认命令。来源 union ≤20；有序完整 command 绑定仍保留，不能重排后冒充相同 phase。

## Review and saved subject

review 精确 13 键：`operation,payload_semantic,stable_anchor,binding,inspection,raw_source_basis,required_source_read_set,sources,authority_snapshot,policy_snapshot,owner_id,visibility,current_issue_revision`。`stable_anchor` 保留真实首预览完整全文和 full SHA，后续重核不重封原锚。原 raw SourceSafety 稀疏 JSON 字段不补 typed null。

原 writer 继续使用 `CapaVerificationEvidence`，继承原完成 Issue owner/visibility，并单列实际 writer；`status=candidate/result=indeterminate/applicable=None/independently_verified=None/observation_complete=None`。只四键 `input_snapshot`：semantic、shared_proof（实际 UUID/T1）、proof_consumed_at（actual marker first clock）、完整 stable_anchor。intent_digest 是 actual common intent。共同 Receipt 展平实际 subject.action_result 的 `candidate_binding_sha256/inspection_sha256`，不把 full candidate SHA 放入 Receipt，不发明未来 Receipt UUID。

Current=origin 的 v1 限制、有限后继 owner 缺项、专业矩阵/资格/政策/来源/原件缺项仍由实际 prepare 拒绝；七 gate、有效性和关闭都未因此开放。

## Checks and limits

最终仅新增 adapter/schema/test 范围：26 项 `--noconftest` pure，通过；Ruff/format/三文件 AST/compile 与公共 namespace 导入、精确 alias 检查通过。日志与哈希见 `candidate-service-check-result-v1.json` 和 `candidate-service-source-manifest-v1.json`。

纯测试使用真实 SQLAlchemy Session/UOW、persistent detached-attached Product/Confirmation 和 ConsumptionHost 的 ORM False→True 历史；重 owner 准备/序列化与写入委托明确使用无数据库替身，不声称真实字节、专业事实、原子 SQL 或页面通过。首轮空读集错误分类先从 canonical 返回 RECHECK_REQUIRED，后在薄适配加明确空集检查为 MISSING_REQUIRED_EVIDENCE；最终 26 项按本版本绑定，不与初轮重复累计。

未执行 DB/HTTP/公共测试/构建，不修改共享服务、registry、models、SQL、迁移或冻结 staging。公共执行时 proof 时效按实际保存钟/现有 SQL 语义核验，不宣称另有 COMMIT clock 保证。
