# s0_0722 独立只读审查

本审查覆盖 0722 批量受众函数、随候选进入的领域读取／输入准备优化、对应新增测试与现有实测证据。结论：未发现本次改动移除完整来源、当前受众、写入锁／CAS、最终重核或历史回执读取守卫的具体缺陷。当前证据支持受影响功能与迁移恢复通过；最终性能采样仍由主会话统一完成，本文件不判定 S0／M1 完成。

审查仅读取源码、JSON、XML 与既有日志；未运行 PostgreSQL、pytest、collect、迁移或性能测量。仅写此文件。审查时 `0722-affected.json` 与 `0722-recovery.json` 所记录的当前源码 SHA-256 均无差异；前者覆盖 1008 个源文件。

## 完整来源与受众

`pdos-next/server/migrations/schema_s0_0722.py:58–71` 先检查当前 `category_access`，再检查型号确属租户／品类及型号自身受众。内联谓词与原独立 `source_object_audience` 的纯受众部分相同：品类可见、本人拥有，或精确匹配租户／品类／对象类型／对象 ID／owner／principal 的 `object_audiences`。独立 helper 及其可独立调用的授权检查没有修改。

`:74–112` 完整验证每个依赖的精确三键、JSON 类型、42 类白名单、UUID 与声明型号，再按类型批量 SELECT 精确 ID；动态表名受白名单和 `%I` 保护，值仍绑定参数。每行真实型号必须等于根型号，`:142` 必须命中全部去重后的 ID，因此缺失、跨租户、跨品类、跨型号依赖不会因批量查询而被忽略。重复相同依赖可合并，重复 ID 搭配不同声明型号会在合并之前拒绝。

`:98–105` 对当前 schema 的 37 类 source-bearing 行读取完整 `required_source_read_set`；其余 5 类无该列，保留原先无该读集的行为。`:120–152` 要求每个完整读集为数组、每个来源为合法对象且含非空 UUID `artifact_id`，随后按完整 JSON 值合并去重，最终调用原 `direct_source_set_visible`。没有 `LIMIT`、取前 20 项或剥离来源字段；相同 ID 但不同原始 ref 内容不会被错误压成同一 ref。所有实际依赖的型号已核对为 `p`，故该调用覆盖它们唯一实际型号的完整来源集合。来源版本、安全与状态仍由现有领域来源核对执行；本次没有把这个 SQL 受众谓词改造成完整事实证明。

`:136–139` 保留 `projects → project_definition_visible` 与 `definition_revisions → definition_sources_visible` 的 live 特殊守卫，未以合并读集代替它们。`quality_event_failure_links` 缺少 owner／visibility，`:99–119` 显式投影 NULL 并保留原 `IF NOT` 的三值语义；这是原函数行为，祖先依赖与完整来源仍被核对，不等价于新授予失败链接的独立受众。

实测覆盖：新 `tests/category_root/test_business_audience_batch.py` 两项在 0722 批中通过，含 21 个来源、两个私人 BOM、重复依赖、精确授权与撤回第 21 个来源、直接应用角色 SELECT 隐藏结果、另一当前读者的独立权限，以及缺失／伪造依赖拒绝。现有 `tests/test_business_audience_summary.py::test_summary_cannot_expand_ancestor_audience_and_source_revoke_hides_build` 同批通过，核对定义祖先授权缺失、补齐后可读、来源授权撤回后隐藏。

## RR 请求范围证明与领域读取

`database.py:22–50` 的正式入口为每次请求创建新 Session／事务，在 `read_snapshot=True` 时设置实际 REPEATABLE READ 和 `SET TRANSACTION READ ONLY`，服务器绑定 tenant／actor／requester／category；`:53–66` 防止领域 Context 借用不同身份的事务。

`request_proof.py:97–104` 以真实根事务对象识别证明，事务变更即建立新证明；`:163–215` 的 snapshot 复用只接受实际读快照或已取得的型号 gate，脏读快照拒绝。ORM flush、直接 ORM DML 与 rollback 会清除受影响读值／来源／授权证明；锁标记与锁升级没有被结果缓存代替（`:38–94`、`:182–198`）。`command_inputs_once` 的键含函数、完整 Context 身份与 run、command ID、命令／payload 摘要、型号 revision 和选项，并先执行 `require_context`（`:264–298`）。它只复用本次输入准备，不缓存最终允许写入的结论。

`domain/test_resources/retained.py:53–71` 的新 `_one` 只在真实 Session 的读快照分支复用 exact query（含条件／参数）；非 snapshot 仍真实读取，返回后仍要求恰好一行。`inspect_retained_execution:348–513` 继续核对原 Start v2、固定范围／计划／实际开始、完整源 basis、历史资格、实际资源依赖／issuer epoch、原预约与所有 occupancy／sample usage；所有 IO 后再次核对来源、资格、runtime、caller 和同 UoW，最后检查当前读者实际授权期限。没有重封旧 Start 或创建消费效果。

实库新增 `test_retained_rr_evidence_does_not_survive_source_withdrawal_between_requests` 同批通过：同一 RR 请求两次核对保留完整一致材料，提交来源撤回后，新 RR 请求明确拒绝。它证明复用不跨请求；它不声称已经开始的 RR 快照在事务中途观察到外部提交，这符合既定请求快照口径。

`domain/professional_authority/service.py:1094–1163` 仅在干净 RR 读快照且 `write=False` 时以 RLS 可读 Current 的完整摘要复用 exact immutable fact；旧／缺失 Current 必须按完整 ID 集读真实历史。`:1164–1214` 每次仍检查范围、revision、epoch、fact hash、series、角色／资格、当前 issuer 与实际事实时间边界。非 snapshot／writer 路径继续历史读取与 Current 锁；没有凭 summary 构造缺失旧事实。

`domain/build_start/service.py:1431–1510` 的合并 Current 查询仅由 `execution_projection:1522–1525` 的 RR 分支使用。先由当前 RLS 核对真实 Build，再查询它的完整 Current 集；Start 独立 exact 读取。每次仍调用 `_row` 核对固定双配置、项目和事实完整摘要（`:135–147`），并继续 `_read_evidence`。非 RR 保留原查询。`domain/test_resources/service.py:292–331` 仅 RR 读取复用规范的 Build operational pointer，实际资源 union 仍完整生成，资源获取／锁行为按传入 `lock` 保留。

实测覆盖：`tests/verification_launch/test_read_projection_reuse.py` 14 项实际通过，包括 exact ref/hash、伪造 Current identity／series／revision／epoch、旧／缺失／不可读历史 fallback、issuer／事实时间边界、非 snapshot／writer、Start 与资源 pointer 复用。此文件使用明确替代 IO 的纯测试，单独不宣称实库 RLS 通过；实库祖先受众、跨请求来源撤回及下面的写入负例提供对应实际边界证据。

## write／lock／CAS 与历史回执

`domain/quality_execution/api.py:50–62` 的 inputs 入口使用 RR／READ ONLY；`service.py:251–256` 与 `:809–818` 仍要求当前具名人员写权限，读取准备时不取写锁。实际命令保持写事务：共同 `service.py:827–869` 取得当前范围 gate／授权锁并执行运行资格与来源证明；领域 `_new_write:525–543` 保留型号 revision 和 `FOR UPDATE` 下 issue 前版 CAS，`_record:571–573` 在落领域变更前重新执行 `_refresh`。

`quality_execution/service.py:419–458` 最终重核完整结果、policy、来源 basis、当前专业资格／issuer、当前具名写权限及真实资格／政策期限，包含共同 confirmation 消费之后的重核。输入准备缓存没有消除这一步；outbox／Current／confirmation 与领域写入仍处于同一共同事务。Build 领域实际写入仍检查型号 revision 和 `lock=True` 的 assessment／decision CAS（`build_start/service.py:660–683,892–928`）。

`pdos_next/service.py:775–787,816–825` 的同键／同 intent 成功回执恢复位于领域输入准备之前；RequestKey 与 Receipt 在当前 RLS 范围读取，撤销当前读权限后不会由缓存恢复。新动作仍走写权限、来源、确认、锁／CAS 与最终领域守卫。此行为保留 v1.1 C9：来源／资格在保存后变化不抹掉可读历史，也不授予一次新动作。`domain/test_resources/retained.py` 的证据读取不进入写／reserve/stage；`build_start/service.py:1566–1577` 显式关闭历史核对投影的所有当前动作能力。

实测覆盖：新 `tests/quality_execution_transactions/test_request_prepare.py` 两项实际通过，核对 inputs 真正 READ ONLY、零 FOR UPDATE／FOR SHARE 与零效果，inputs／preview／confirmation 每请求准备一次，并在确认 review 后撤回 issuer 时整笔回滚。`test_original_bytes_read_runtime_revocation_is_atomic[professional/resource]` 两项与 `test_outbox_failure_rolls_back_issue_version_pointer_and_common_confirmation` 同批通过；真实源字节 IO 后撤回 runtime 和末端 outbox 故障没有留下部分效果。两个 sample_handoff 实库负例覆盖新观察来源撤回及资格撤回恢复 epoch；verification inputs 实库负例覆盖缺 sentinel 时仍只读。

0722 备份恢复后，通过原始 Start command 恢复同一回执，完整 before／after 数据指纹无变化；该实际证据覆盖本候选下历史回执恢复零新增效果。未把既有 full-regression 或早期历史分散通过冒充新的全量回归。

## 迁移、owner 与 ACL

`migrations/versions/s0_0722_batch_business_audience.py:7–19` 为真实 `s0_0721` 后新增的单调迁移；upgrade／downgrade 仅同签名 `CREATE OR REPLACE`。没有 DROP／新访问入口／DCL，因而保留函数 OID、普通 owner 与既有 EXECUTE ACL；独立来源 helper 原有 PUBLIC／agent 撤权未变。两向定义均为 STABLE SECURITY DEFINER，固定 `pg_catalog,public,pg_temp`。`schema_s0_0722.py:9–44` 的 PREVIOUS 已与 `quality-history-query-plan.json` 捕获的真实 0721 `pg_get_functiondef` 逐字相等，不依赖旧 schema 快照推测。

实际 `0722-checkpoint/upgrades.json` 记录主库（53502）与 B8 库（62303）由 0721 到 0722，独立 pdos_test marker 均存在、私有备份哈希保留且迁移源未变。两份 ordinary owner audit 与恢复后 audit 均为 0722：141 张审计表／43 个函数由普通 `pdos_next_owner` 持有，目标函数固定 search_path，非 superuser／非 BYPASSRLS，runtime 无 owner membership，agent 无业务直接 DML。audit 的函数字段不包含逐角色 proacl 位图；ACL 等价结论来自同签名替换及未改原授／撤权 DDL，未将其表述为独立的前后 ACL 位图实测。

`0722-emptychain/result.json` 已记录新独立空库的 `upgrade head → downgrade base → upgrade head` 实际完成、源码未变及 ordinary owner audit 通过。它覆盖 0722 downgrade 的实际执行；旧函数定义精确性另外由上述捕获文本比对支撑。

`0722-recovery.json/.xml` 精确 1 节点 setup／call／teardown 全 passed，test_exit=0、source_unchanged=true。`0722-checkpoint/backup-restore.json` 恢复 142 张表指纹（含 Alembic 版本）；`configuration-handoff-recovery.json` 记录非空 configuration → Build → Handoff → Run／reservation 链、恢复后的公开 running 读取与原 Start 回执、读取与重放零新增效果。合成字节保留并重读；此为 DB 恢复，不宣称对象存储或真实生产恢复。本次 metadata-only 事件实际 delivered=2、unknown=0，没有工作流／外发效果；不混用上一 0721 批的 5 个事件。

## 证据索引与剩余验收

`0722-affected.json/.xml` 为实际 165 节点，165 项的 setup／call／teardown 均 passed，退出码 0、collect_only=false、source_unchanged=true；当前源码与记录的 1008 项哈希相符。精确范围：verification_read_projection 14、quality pure 33、professional assessment 27、professional batch 35、professional evidence 7、resources rules 37；batch audience 2、ancestor audience 1、quality request_prepare 2、quality transactions 3、retained 跨请求撤回 1、verification readonly 1、handoff 2。后半实库节点共 12 项，未把全部 165 项称为实库测试。

`quality-history-query-plan-batch.json` 在相同 13 版本诊断查询下记录执行 961.053 ms → 214.228 ms；它标明 diagnostic_only=true。这支持所选优化针对真实瓶颈，但单次查询计划不是交互路径 30 个完整成功样本的 p95。客户端 SQL count 仅统计发往 PostgreSQL 的外层语句，不展开该函数内部批量 SELECT／helper，不能用客户端计数未变或下降代替内部工作量／实际延迟结论。

主会话确认 performance-attempt-2 因新测试的 collect 导入顺序问题，在短路径阶段主动中断；保留该次诊断，不能登记为性能通过。这是待修测试导入／collector 的问题，现有审查未要求为此修改业务守卫。collector 修正及两项复验后再冻结最终性能候选。

尚待主会话统一登记：0722 同候选的全部明示短路径与 B4／B5／B6 路径的完整成功样本数、分组 p95／SQL 对比、pytest 退出码与最终 source_unchanged，并将最终性能报告／源码清单一致性核对完成。上面的受影响与恢复 source_unchanged 仅证明各自实际批次，不替代尚未形成的最终性能冻结。本审查没有追加逐 API、全量或并行实库验证要求，也没有更新唯一清单／acceptance map。

核心证据 SHA-256（本次读取）：

- `0722-affected.json`：`71884358bda5a720e7558028c033a5159bcacdf06bd791223f1531122fe53ca9`
- `0722-affected.xml`：`eeaa37451b1d531650d0f2fe55bed3e8cbc4ca3be97d799ac82a194027f9428b`
- `0722-recovery.json`：`a05584e4369228b04d17b65a92b6a94c106ab50cbf601d3994dd8f4c964ce1d4`
- `0722-emptychain/result.json`：`bd3eb8d06a2dc1221bc56c9f95834501635adf691114972337d1898ab39ed160`
- `0722-checkpoint/upgrades.json`：`24caf9c519a248ec7113ffb580031a45539ca98f9e863df13ac20f788fdbb8de`
- `schema_s0_0722.py`：`173872a91effa33b42c06b65ce9cc01a36250fb4513674717e4bbfe97ba3477d`
- `s0_0722_batch_business_audience.py`：`a880868fd7b2f6bd0acec42d94caa79807b15695968fa4960a2f4a07f6e0f95f`
- `test_business_audience_batch.py`：`f0b3aa16e6e8dab6b0737c21977d29da1500f680b74c402c818acada4716a412`
