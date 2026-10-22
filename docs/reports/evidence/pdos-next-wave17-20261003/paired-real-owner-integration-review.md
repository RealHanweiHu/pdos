# Wave17 paired 实际 owner 接线只读审计

状态：2026-10-03 定向源码审计；只新写本报告，未修改 staging/server/web、未执行 DB、HTTP、pytest 或公共验证。现有存储已有配对真值，不需要第二份 Formal、Run、Current 或消费账。暂存纯结构协议尚无真实 PairedOutputReader，不能据此开放候选或宣称资格通过。

## 结论与当前真实缺口

可直接复用不可变版本、真实 LaunchFact/ResultAction、共同 Receipt/Audit/Outbox、原值报告核验和 retained execution。需要新增的是**同调用者 Session 的只读宿主 bridge**，以及读取后独立 fresh/attest 门禁；另须在公开输出适配中明确选择 direct-owner 或 paired-owner 证明。不能把 `quality_followup_views._receipt` 缺回执改成默认通过，也不能将 Run origin 当作 Formal Current。

当前 `quality_followup_integration.request_options`（17–57行）只枚举具有直接、精确 canonical Formal Receipt 的 Current 行；`configure_integration`（84–93行）明确保留 `PAIRED_FORMAL_OWNER_PROOF_NOT_CONFIGURED`。这符合现有范围。新桥接通前，Advanced Formal 不能借旧 Draft 回执进入选择；既有 Draft Link 保留 planned/history，不能悄悄更换 ref 为新 Current。

## 实际字段与精确选择

所有查询先核 server Context、tenant/product/project、可见性及 Build，再生成 PairBinding；客户端 FormalRef 只选择 immutable 行。现有 `_row` 的 private 检查只允许 series owner，ProductGrant 不扩大私人读取范围。

| 暂存 DTO | 实际持久字段与读取规则 |
|---|---|
| PairBinding | `scope` 从真实 Formal/Build；`build` 用 `_snapshot` 内完整 BuildRef（包含双配置）；`request_id` 是 logical Formal ID，`run_id` 是 logical RunIdentity ID；`caller_id=ctx.requester_id`，purpose 为真实请求原值。 |
| FormalRow | `verification_formal_requests`: id/revision→ref；previous_request_id/previous_revision→previous；request_snapshot/snapshot_sha256、operation、intent_digest、owner_id/visibility、required_source_read_set、created_at。`authority_actor_id` 取实际 authority_snapshot.subject_id，不取系列 owner；没有 writer_id 或 source_basis 列。 |
| RunRow | `verification_run_versions`: id/revision/previous_run_version_id/previous_revision、run_snapshot/snapshot_sha256、execution_plan/plan_sha256、operation/intent_digest、owner_id/writer_id/visibility、required_source_read_set、created_at。origin 是 request_version_id/request_revision，固定保留。 |
| Current | `verification_current_formal_requests` 按 tenant/product/request_id 取 request_version_id/request_revision；`verification_current_runs` 按 tenant/product/request_id/run_id 取 run_version_id/run_revision。两个指针必须各自等于实际选择行，不按 created_at 猜“最新”，不用 origin 替代。 |
| LaunchFact | `verification_launch_facts`: tenant/product/project/build/request/run、id/revision、request_version_id/request_revision、next_request_version_id/next_request_revision、run_version_id/run_revision、operation、owner_id（当次 actor）、visibility、input_snapshot、kernel_event/snapshot_sha256、intent_digest、sources/required_source_read_set/source_basis/authority_snapshot、created_at。 |
| ResultAction | `test_result_actions`: 对应 scope/id/revision；request before/next、run before/next、operation/actor_id、projection_id、capture_id、input_snapshot、event、intent_digest、sources/readset/source_basis/authority_snapshot、created_at。其 owner_id 是 Run 系列 owner，不是 actor_id。 |
| Projection | `test_result_projections`: id/revision、scope/build/request/run、run_version_id/run_revision/run_sha256、basis_sha256、rules_version/rules_sha256、input_snapshot、result/computed_results、sources/readset/source_basis。需读取其真正 projected Run，可能是 Review 的前一 import 版。 |
| Receipt | `action_receipts`: 精确 tenant/product/operation/subject_type/subject_id/subject_revision、command_id、actor_id/requester_id、visibility、run_id、request_digest/intent_digest、result/created_at。result 为实际 `{id,revision,status}`，不是 receipt_id；六步只支持本人 human，run_id 应为空。 |
| 原子伴随 | `audit_entries` 按 tenant/receipt_id 核唯一实际 actor/operation；`outbox_events` 按 tenant/receipt_id 核唯一实际 type、subject_id/revision、actor、correlation_id=Receipt.command_id、schema_version=1。不得因 delivered_at/lease/attempts 变化重新发出事件。 |

模型位置：Formal `verification_front/models.py:40,184`；Run/Current/Launch `verification_launch/models.py:62,121,136`；Projection/Action `verification_results/models.py:120,143`；共同模型 `models.py:252,280,296,309`。

最小 pair 选择顺序：选定可读 Formal Current → 同 logical request 的 exact Run Current → 取 `next_request==Formal Current` 且 `next_run==Run Current` 的 ResultAction，或 `next_request==Formal Current` 且 `run==Run Current` 的 LaunchFact → 按 fact 的 before refs 读取前版、按 Run origin refs 读取原已接收版 → 按该动作真正 subject 取共同 Receipt 和唯一 Audit/Outbox。若无唯一事实或指针不一致，明确 missing/冲突，不用时间排序挑一条替代。

## 不同动作的真实推进与 intent

真实写入见 `verification_launch.service._record:774–925` 与 `verification_results.service._record:962–1112`：

| operation | Formal | Run | 共同 Receipt subject |
|---|---|---|---|
| test.run.plan | 不变 | 新 planned v1 | 新 Run |
| verification.schedule.promise | +1 scheduled | planned 不变 | 新 Formal |
| test.run.start | +1 executing | +1 running | 新 Run |
| test.results.import | 每次 +1；partial 仍 executing | 每次 +1 | 新 Run |
| test.run.review | 不变 | +1 reviewed | 新 Run |
| test.disposition.decide | 仅实际完整条件成立才 +1 disposed | +1 disposed | 新 Run |

`test.result.compute` 的 subject 是 Projection，不是六步 paired transition，不能借它补造 next_request/next_run。Plan 的 command SourceRef 是真实 `_command_fact`：id=Receipt.command_id、revision=1、kind=command、position=receipt、UTC、actor=当次人、occurred_at==received_at、effective_at=None（旧核 `verification/handlers.py:117`）。Promise 的未来承诺不成为 Actual。

Domain intent 使用 owner `_intent` 的 `{operation,actor,payload}`，真实 input_snapshot 已保存 semantic。Common intent 来自 `service.execute:579–595` 的 `{operation,product,payload,named_actor,source_revision,private_owner}`；两者各核各的，不能判定彼此相等。`verification_launch.semantic:75`、`verification_results.semantic:84` 可直接复用，原 exact typed payload 由 fact.input_snapshot 验证重建，不从 snapshot 补缺字段。

这六个 payload 都不是 Claim/Work，source_revision 按原共同分支为 None；当前 schemas 没有 visibility 字段，private_owner 按原 payload 默认 private 分支取**原 requester**，不能按输出 visibility 或当前 reader 猜。named_actor 取原真实本人 writer。C 同时只读复核了此六步 family 与 common intent 规则，未运行验证。

Receipt.request_digest 是完整原请求（含产品水位、原 readset 顺序和 token）的摘要；fact.semantic 已删除 token，不能重建原 request_digest。可读取真实 RequestKey.digest/receipt_id/actor 与 Receipt 保存摘要核关系；若宿主需要重算完整原请求却没有原材料，明确 missing。也不能把 alias key 的新请求摘要冒充最初 Receipt.request_digest：跨 key 成功重放可以新增指向旧 Receipt 的合法 RequestKey。建议公共只读 semantic hook 明确返回“实际原 handler、闭合原 semantic、实际共同分支材料与保存 provenance”；不新增一张原命令真值表。

## 可复用门禁与不可直接当 reader 的入口

| 门禁 | 可直接复用 | 必须保留的边界 |
|---|---|---|
| 当前 caller/ACL | `service.require_access:135`；`supply_execution._human:73`；front `_row/_version/_current:144–184`；launch `_row/_version/_current:103–149` | 当前本人 active、Grant 未过期、tenant/product；private 必须真实 owner。读权限与原历史 writer 专业证明分别核，不能 owner Context 授 caller 读取。 |
| 固定快照 | front `_snapshot:186`；launch `_snapshot:151` | 验真 hash/scope/status/固定双配置/items/sample-item 全 coverage；partial 原值与旧历史顺序保留。snapshot positive 不是当前可用资格。 |
| 当前原文/安全 | `source_for:159`；`verification_handoff._basis:106`；`quality_execution.evidence.source_basis:34`、`check_source:108` | 原文 fixed revision、hash、精确 locator、ACL/status、OriginalSecurity epoch/withdrawal；native text 用真正 Artifact.register Receipt provenance，不能冒充测量报告。读集完整并集≤20，冲突/超限拒绝，不截断。 |
| 原实际执行/消费 | `test_resources.retained.inspect_retained_execution:21`；`launch._saved_effects:996` | 核真实 Start v2、fixed_run hash、保存时钟、原 authority fact refs/epoch、资源事实/自有 occupancy/sample usage；不调用 reserve/stage/init sentinel。窗口自然结束不抹去已发生事实，也不授当前再执行许可。 |
| 历史具名专业 | front `_recheck:103` → professional `recheck_snapshot:739`，retained 精确原 fact_refs | caller 当前读 ACL 独立；历史 writer 只作只读资格再核，原 refs 撤回/epoch ABA 阻断。有关新增事实不能忽略，无关 result-only 事实按既有 retained 合同处理。新 CAPA 复核操作资格另由其 owner 判定，不从 paired positive 获得。 |
| 真报告逐值 | results `_measurement_records:480`、`_measurement_capture:503`、`_report_for_capture:458`、`_read_report:153`；`verify_measurement:435` | capture 的 private ownership 不能扩大；仅从当前可读 formal measurement 委托原固定报告 proof。真 OriginalStore 门禁、safe epoch、bytes hash/size、ReportBinding、每字段原值/定位都核，不用 Artifact.content 替代 bytes。 |
| 确定性结果 | results `_projection_basis/_basis_sha:403,420`；旧 `verification.rules.compute_results` | 核 projected Run/原值/规则版/hash/basis/input snapshot/computed results；Review/Disposition text 不替换测量基底。 |
| post-I/O fresh | `quality_result_bridge.recheck_fixed_failure_result:262` 的模式；results `_refresh_phase_proofs:662`、`_retained_stamp:649`；真实 `_runtime_stamp:31` | 全部 owner/bytes I/O 后重新核源、当前 pointers、历史专业、retained、issuer/runtime 与 caller。只排既有观测钟 checked_at/execution_window_elapsed，保留所有事实/安全 epoch。 |

`quality_result_bridge.fixed_failure_result:117` 只读且已有真报告/投影/retained 深核，可以直接复用其具体步骤；它以一条精确 measurement 为输入，**不是通用 paired-request loader**，无测量的 Plan/Start、全部 pair 结果、LaunchFact/Audit 选择和 Current 配对需要新的窄组合。不能选一条 fail 就视为全部新复验完成。

现 `get_request:1098` 会额外构建当前多操作能力和方法/窗口 UI；其 `current=true`/source_status 是展示信息，不是完整 paired HostGate。`results._load`/`launch._load` 以 writer/当前操作权限、命令读集与 effect 语义设计，且会取相应写门栓；不适合作为普通只读 owner reader。应组合已有行/快照/来源/retained/report 门禁，复用实际规则，不伪造 Command 后调用写入口。

## 最小新增 hook 与并行归属建议

1. **B：新只读宿主模块**（建议 `server/pdos_next/paired_output_bridge.py` + `tests/paired_output_bridge/`，需主线另行分配）。实现 PairedOutputReader.read/refresh/attest，实际映射上述 ORM，不创建任何业务事实；复用 frozen paired.py DTO。read 与 fresh 分别重新读取精确 Current/事实闭包；attest 返回真实同 Session/main+nested UOW 的 opaque HostGateProof，不接受客户端 stamps/booleans。
2. **Root：窄 semantic/provenance 及公开 dispatch**。统一迁入纯协议；若希望共享 intent 构造，增加真正 server-owned 六步 semantic material helper。request_options 增 paired 候选时仍在 limit 前 exact scope/current join，views._option 根据明确 reader-family 选择直接回执或真实 paired proof；旧 direct 规则、missing 标志和历史行保留。该只读桥本身不要求新表/Current/迁移号，未来 Candidate/T2 的持久原子组另按真实 head 处理。
3. **A：CAPA anchor/current closure/Candidate owner** 与 B 共享已冻结结构协议，可并行实现稳定 CAPA 锚、原 Failure 全闭包、独立性/适用性/观察事实规则。只有 B 真 host_gate 和全部 owner facts 俱全才装配候选；不能把 paired performed 当 effectiveness=True。原 private Issue 与 private 原源仍独立 blocked，不借 peer Grant 修通。
4. **C：界面读模型** 可先实现 planned/history/performed/missing、精确不可变 Current ref、old Draft Link 与 late-link 的区分。真实候选只选 server options，不能用 logical UUID 拼 ref、把 origin 展示成 Current、自动升级旧 Link 或从 Run.result 推出 CAPA 有效/关闭。公开 route/mount/专业 registry 仍主线统一。

HostGate 所需实际 hook：`read/refresh` 返回 ServerPairRead；`attest` 核 `acl/sources/professional/original_bytes/semantic/runtime`，performed 增 retained，result 增 numerical_rules。stamps 来自实际核对，不是 DTO hash 的自授。每轮最终刷新应覆盖前一个 owner 在后一个 bytes/runtime callback 中失效的情况；所有 actor/source/security/issuer negative epoch 与 pointer 都参与。valid_until 应含当前 Grant 与相关已知下一有效性边界，读取中到期拒绝；保存时签发资格与当前读者期限不能混为同一个事实摘要。

缺真实 store/security、可信 issuer/professional callback、exact Fact/Receipt/原 semantic、retained/Current/projection/bytes 或独立 fresh 任一项，都返回明确 missing/INTEGRATION_REQUIRED；不默认 positive。当前未做任何实际接线和验证。后续最小主线验收应覆盖六步 exact Current、跨人 owner/writer、多个 partial/原值与时钟、旧 Draft 不升级、scope/private、source/issuer ABA、report读取中撤回、真实 late retained、零新增占用/消费和无 host 的失能。

## 观察范围与哈希

只核以下具体文件，不代表整树冻结或当前公共候选完整一致：

| 文件（相对 pdos-next） | 本次读取 SHA256 |
|---|---|
| staging/wave17/paired.py | 3cff4b1534533b2797f201faceede7e2a9514d84240ca06c6953b1de20dce750 |
| staging/wave17/paired-contract.md | 3a597197ae30ebdfc94515c25d5c12f201770a0b2073e086e0e3b5265f5900f1 |
| server/pdos_next/domain/verification_front/models.py | 954809891be1c66fec8e60351054fdba88bd3744cd906ee7564d706d16a625c5 |
| server/pdos_next/domain/verification_launch/models.py | d5c57c98a2bae45063ce935406474425f60b9bb13d93366e1959e7eb0d62e79c |
| server/pdos_next/domain/verification_results/models.py | 9ae98e9a2a69b7a02a987d38e03940b4983f69f62b030f96464650824efc5403 |
| server/pdos_next/domain/verification_front/service.py | ad7390463fc84cff5b767f3046044a2817edf12e2e4601dfda9eb59c7f6b8996 |
| server/pdos_next/domain/verification_launch/service.py | f2c4484ee8f55a1a64e73bf9a5ab1ae1f57655a67f54c685f9b59a1bbbde64bd |
| server/pdos_next/domain/verification_results/service.py | c0f4e4dc465868264167c77362ed831224856b923d073e06aae7c3979b27b8d0 |
| server/pdos_next/domain/test_resources/retained.py | abf1c6d4599b3a5c13f113666b1971e85bfb173b5c27e1b34e1e17197517e0de |
| server/pdos_next/quality_result_bridge.py | 28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077 |
| server/pdos_next/quality_followup_integration.py | 2c722d0fa94e02fd5d0e1d7ebeec1e52a782015457cb58e4ed5efbf3fce32e5f |
| server/pdos_next/quality_followup_views.py | 2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3 |
| server/pdos_next/service.py | a710834b172d33de60f713333fd63a5d2d6bab3c39d5a7002b03c7d3d2982686 |

本报告是接线设计审计，不是上述文件不可变的永久断言；实际候选、迁入与数据库/页面证据仍由主线分别冻结。
