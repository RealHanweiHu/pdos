# Wave16 单 Issue 公开读取适配冻结

仅新增 `pdos_next/quality_followup_views.py` 与所属纯测试目录。Wave15 v4 原 303 路径当前摘要全部保持；这不是全旧工作区不变声明。未运行 DB、PG、HTTP、浏览器、公开测试或迁移。

公开入口为 `list_quality_followup(s,ctx,pid,*,issue_id:UUID,revision:int|None=None)`。无 ambient 产品索引，必须明确一个 logical Issue。默认读取实际 Current 指向版本；显式历史读取其固定版，同时从真实 Current 表与对应可读 Version 核对 `current:{version_id,revision}`，不得把旧版伪填为当前。调用 A `list_quality_followup` 一次且指定固定版。历史 `basis:null`，三个 operation 全部 disabled。

冻结顶层为 `issue/current/basis/operations/actions/output_options/links/candidates/required_source_read_set/source_options/integration`，与 C `FollowupData` 一致。`operations` 三键为 `quality.issue.root_cause.decide`、`quality.capa.actions.complete`、`quality.capa.followup.link`，每项有 allowed/authority/reason_codes；只使用所选行能力，拒绝产品 summary 的 anytrue。`actions.text` 映射 label，保留真实 completion/event clocks、结构化 blockers 与 reason_codes；`can_prepare_completion` 只表示可开始核对候选，`can_complete:false`、`completion_verified:null` 恒保留。STRUCTURED_COMPLETION_REQUIRED 不会自行禁止准备。

宿主可调用 `configure_output_options(engine,callback)`；callback 为只读受控接口 `(s,ctx,pid,FollowupBasis)->iterable[OutputRef]`，最多20个，不接受客户端数据或输出声明事实。adapter 通过真实 owner 再核 scope/current ACL/固定 ref/来源，并核精确共同 Receipt subject/result/visibility 与 actor/run provenance；标签/status 从实际 owner 取得。Formal/Run 的 series.owner 不等同于该版本保存人；这两类再读取不可变 row 的 authority_snapshot.subject_id，Run 同时核 writer_id。Sample 的真实证明来自其 allocation Receipt，并须包含该 sample_id，不把单件冒充 Receipt subject。Root `quality_followup_integration.request_options` 与本签名兼容，Root新增API与单Issue/history信封兼容；这些公共文件只读，未由本任务挂载。

`output_options` 单项为 `{label,ref,status,logical_id?,source_status,required_source_read_set,receipt_id}`。没有 callback 时返回空数组和 OUTPUT_OPTIONS_NOT_CONFIGURED；有20个以上或重复候选拒绝，读集并集超过20明确失败而不截断。候选存在不表示措施满足或独立复验通过。

`links` 由真实 `RemediationLinkRecord`、精确回执和保存摘要投影 `RemediationLink`：真实 id/revision/basis/action_id/output_refs/resolution_sha256/owner/visibility/received_at/sources/reads/reason，再附 source_status/reason_codes/receipt_id。`received_at` 为原 row.created_at，不回填当前时钟；_link 返回的 ResolvedOutputs 仅是当前 proof，不能当作 LinkDTO。私人不可见的回链内容隐藏，只给 bounded unavailable_count；可读保存事实当前核对失败显式 needs_recheck，不替换其历史 basis。

`candidates:[]` 以及 integration.missing 中 CANDIDATE_PERSISTENCE_NOT_ENABLED 明确保留；本波没有受控候选保存与其真实原子组，不能把已有声明表或临时 inspection 变成实际候选。`integration.effectiveness:false/close:false` 恒为 false；新增只读 metadata 为 missing 与 links.has_more/unavailable_count。

所有实际输出/回链 IO 后，重新读取 owner/link 固定 proof，必要时重新 A 固定失败/政策/来源/专业视图（内部调用，非新增 RPC），并比较安全事实。返回前来源、专业epoch/政策、宿主identity、当前Grant与期限、Current均重核；没有全局或跨phase缓存。公开能力仍是 advisory read；实际 commands/inputs 各自严格重新核对与同事务消费证明。

26个所属 pure 检查、Ruff/format/AST通过。它们使用明确 synthetic 读取端口替身，只证明适配逻辑与错误边界，不证明真实资格、数据库事务或读取延迟。原局部失败日志保留：首次缺夹具观察期；第二次直读 helper 被测试 stub 遮盖；修正均只涉及新纯夹具。Hash与完整范围见 [public-views-freeze.json](public-views-freeze.json)。主线仍负责实际迁移/注册/角色/路由与集中联验。
