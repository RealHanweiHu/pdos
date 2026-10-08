# Wave18 · 下一段真实 LivePairedOwner 衔接

只读源码衔接，未修改 runtime/core，未读取私有配置、未连接数据库、未调用 HTTP 或运行测试。下列事实来自当前保存合同和现存 owner；这里不登记任何门禁已经通过，也不增加用户批准关卡。Root 正在执行的 Observation 集中验证与本说明的下一缺口分开。

## 已有结构 owner 与真正未接的部分

`capa_effectiveness/paired_storage.py:272–568` 已能从实际 caller Session 读取精确 Formal/Run Current、RunIdentity、固定 Build/双配置、唯一 LaunchFact 或 ResultAction、前后版、Projection 和共同 Receipt/Audit/Outbox。它在当前行身份下选事实，不按 created_at 猜最近事实；Scope/Build/request/run/next_request/next_run 都必须一致。`StoragePairReader:586–597` 只有 read/refresh，明确没有 attest。其末端 Current、fresh caller ACL 和全活动 UOW 链检查仍只是存储结构基础。

`paired.py:1338–1450` 要求真实 reader 的 read→结构核→attest→独立 refresh→结构核→attest。六项基础 stamp 为 acl/sources/professional/original_bytes/semantic/runtime，performed 再需 retained，result 再需 numerical_rules（八种精确 kind，不是一个 positive bool）。每份 HostGateProof 要由实际 reader 签发，绑定 reader/Session/main+nested transaction/caller/scope/完整结构 SHA、实际检查钟和当前最早期限；两轮材料、stamp 指纹、valid_until 必须相同。`named_review_owner.py:191–231` 还要求 performed、真实 HostGate 和非空期限。缺 attest 的 raw reader 或客户端构造的 stamps 不能补这一步。

精确 DTO 缺口也不能由结构 SHA 补齐：`paired_storage._formal/_run/_fact` 将实际行归一成 FormalRow/RunRow/LaunchFact/ResultAction，保留 snapshot/intent/reads 和 Formal 的 authority_actor_id，但没有把完整 saved authority_snapshot、raw source_basis/完整 sources、安全/issuer 当前 epoch、真实原件字节和 retained/数值 gate 变为认证材料。attest 必须按这些真实固定 row/fact/projection IDs 重新读现存 ORM 的完整列和实际 owner，不从 Typed DTO 或 authority_actor_id 猜资格。原 Current 与原 RequestKey 关联已经能恢复；缺的是这些实际证明的末端同-UOW装配，不是缺一张可以自造的 Formal Receipt。

现 `ActualNamedReviewOwner` 的默认启动只接 `candidate_semantic_owner=semantic_owner()`；paired_owner/applicability_owner 均未装。它先读取实际候选、Rule、顺序 Observations、Current 和参与者，再排除当前本人，才进入 live pair。本人可以得到真实 INDEPENDENT_REVIEWER_REQUIRED；读权限或上游依据缺失仍先按实际 owner 拒绝，不承诺每个旧私有输入都到达相同错误码。

## 最小真实接法：组合现有 owner，不增加第二份状态

新增一个宿主 `LivePairedOwner`（建议以后独占 `server/pdos_next/paired_output_bridge.py` 与其新 tests；本轮未创建）实现冻结 PairedOutputReader 三方法。read/refresh 委托当前 StoragePairReader；attest 执行同 caller/same Session 的真实 owner 组合，并在所有原件 IO 后独立重核。Root 将该真实对象传给 `fact_owner.review_owner.paired_owner`。只注入对象不能配置资格、读取私人来源或创建 Run。

| stamp | 可直接复用的实际入口 | 仍须组合的精确边界 |
|---|---|---|
| acl | paired_storage `_acl/_uow/_guard_uow`；front/launch `_row`；anchor_storage `_project` | 当前真实 ProductGrant/Principal/Project 和每个原/新行 private ACL；末端 fresh Grant SQL 后采真实钟，不借历史作者 Context 授 caller 阅读。 |
| sources / original_bytes | quality_execution.evidence `check_source/source_basis`；fact_sources_owner `read_source_closure`；results `_measurement_capture/_report_for_capture`；measurement_evidence `verify_measurement` | 原报告必须实际 OriginalStore 安全字节/hash/epoch/固定 JSONL 定位；原生文本按真实 registration Receipt 分开。完整原、新、当前专业/政策读集与 sparse 安全 basis 无截断，末端再读；domain/command 引用由其真实事实/回执证明，不直接当人工 line 引用。 |
| professional | front `_recheck` / professional_authority `recheck_snapshot`；retained `inspect_retained_execution` | 每个有关历史具名操作按实际保存钟/原 fact_refs 再核当前撤回和 epoch，保留 negative 事实；原 Start 自然窗口/资格到期不重做执行。当前 CAPA reviewer 的新操作资格仍另由 NamedReview `_authority` 核，不能从旧 writer 或 paired positive 推出。历史身份只用于专业读取，来源仍用真正 caller。 |
| retained | test_resources.retained `inspect_retained_execution:21–140` | 保存的 Start v2、固定 plan/binding/actual_start、当时合法时钟、当前 physical/current/issuer/source/专业 ABA、自己的 occupancy/sample_usage/reservation 都需一致。无 reserve/stage/消费；past window 是历史观察，不是当前开测许可。 |
| numerical_rules | results `RULES_VERSION/RULES_SHA256/_projection_basis/_basis_sha` + verification.rules `compute_results`；quality_result_bridge `fixed_failure_result/refresh_fixed_failure` | 全固定测量、原值与判据、Projection/basis/规则、Current paired Run/ResultAction 都要闭合。fixed_failure_result 本身不判 fail，并核该精确结果 Run 的全部测量；若复用，应明确取真实新 Run/版本/测量并比完整 verified.run，不能套原 FailureRef、只选一条 PASS 当全部新复验、或构造 OriginalFailureProof。缺测量/原报告/数值依据仍 missing。 |
| semantic / runtime | paired_storage `_common:235–261`，actual launch/results `semantic`；Root 当前 source/issuer/professional/resource port registry | 使用实际 fact.input_snapshot 的原 typed payload，不从 Receipt.result 或当前 actor 反推；原 domain intent 和 common intent 各自核。捕获 actual callbacks/issuer epochs/原事实 fingerprint，全 IO 后再核。不能用 DTO hash 自行生成已认证 stamp。 |

其中存储/来源/retained/数值入口已存在；尚缺的是把这些实际读结果绑定为此 reader 的同一次 opaque HostGate、完整最终 refresh 和最早 expiry/未来 activation 窗口的窄宿主代码。七-owner facts attestation、真实方法适用和 CAPA 条件仍不因为该桥接通自动变 true。NamedReview 的非 unknown pair/action/conclusion 另需 actual applicability_owner；默认 classification/fulfillment 仍未知。

业务只读允许原件/当前来源门禁保留 SELECT FOR UPDATE 等真实读锁，所以不能把该组装器误运行成禁止锁的 PG READ ONLY transaction。它不 begin/flush/commit、不连接新数据库、不生成 Receipt/proof、不改 Current。全活动 UOW/identity map/实际 caller 验证应沿现 guard，不能跨 inputs/preview/execute 缓存肯定结果或使用 Session.info 授权。

## Current 与共同回执的真实推进

存储关系见 `verification_launch/service.py:774–925`、`verification_results/service.py:962–1112`，业务时钟/原值规则见 `verification/handlers.py:555–735`。不要统一假设两条聚合都 +1。

| canonical 动作 | 实际 Formal/Run 变化 | 精确共同 Receipt subject |
|---|---|---|
| test.run.plan | Formal 保持；新 Run v1 planned，固定全部 accepted coverage（公开 v1 比纯核 subset 更严格） | test_run，新不可变 Run 行 |
| verification.schedule.promise | Formal 续版为 scheduled；Run 保持原版 | verification_request，新 Formal 行 |
| test.run.start | Formal 续版 executing；Run v2 running；原子新增真实资源/样件使用 | test_run，新 Run 行 |
| test.results.import | Run 每次续版；Formal 每次按核的 request mutation 续版；partial 保持旧 measurements/partial_returns 前缀和首次钟，final 给真实结束/返回并明确全部范围 | test_run，新 Run 行 |
| test.run.review | Run 续版 reviewed；当前核不改变 Formal | test_run，新 Run 行 |
| test.disposition.decide | Run 续版 disposed；满足整个请求真实完成条件时 Formal 才续版 disposed | test_run，新 Run 行 |

ResultAction 的 `request_before/next_request` 允许相等，必须读真实字段；Run.request_version_id/request_revision 永远是起点，不能替代当前 Formal。Plan 的事件来自实际 command fact：command_id/rev1/kind=command/position=receipt，occurred=received、UTC、effective_at=None。Promise 是承诺钟，不成为 Actual；Start、测量、partial/final、专业结论和处置保留各自真实发生/收到时钟。

`paired_storage.py:419–518` 精确核每次共同 Receipt 与原 writer、至少一条 actual RequestKey digest==该 Receipt.request_digest 的关联，以及 Audit/Outbox。跨 key alias 可能有另一 request digest，不能要求全部 aliases 相同；不能从丢 token 的输入重造原 request_digest。原 common intent 使用真实原 handler.semantic + operation/Product/named_actor/source_revision/private_owner；domain intent 的 actor/payload 合同独立，不判两者相等。

## 已存在业务入口的最短合法正例顺序

从一条新、真正 product 可见原始失败场景起建共享 Issue/CAPA，不复制旧 Failure，不修改旧 private visibility。可以复用实际可读的已保存 Definition/BOM/工序/基线和物理资源身份；新作用域/计划/资格/原件/窗口仍由各 owner 绑定。

先办理真实具名 Build 准备评估→工程/制造 T2→Build Start→实际配置/Lot/Sample/ready；或者仅在既存当前合法、同 scope/purpose、未停工/未偏离的 Build 上复用实际样件。然后既有 verification.preparation.record→verification.request.create 保存真正新 logical 请求草稿→verification.method.prepare / verification.actual_method.prepare 明确固定方法与实际配置→verification.handoff.offer→verification.handoff.accept 固定完整样件/item 覆盖。

通过真实 trusted TestResourceFact/当前物理资产/人员校准与资格后，办理 test.run.plan→verification.schedule.promise→在真实窗口与实际事件出处下 test.run.start。Plan/Promise 零占用；Start 才原子 stage。导入真实安全 JSONL 报告（capture 固定原件/行、test.results.import partial/final），用 test.result.compute 确定性投影，再分别办理 test.run.review(T2) 和 test.disposition.decide(T2)。后两项不是 CAPA 独立复核，也不授有效性/关闭。

新复验必须是不同的 logical request/Run；v1 oneRun/request，不能再开原失败 Run。非破坏样件仅在当前 ready、exact purpose/configuration/method 和 usage/resource owner 全部允许时才能复用；destructive consumed 样件永久不可再分配，未知/hold/配置偏离不能推为 ready。新数据必须如实注明 synthetic，不能因本地正例推生产资格。

先完成新复验轮次所需的专业审核/处置，再将真正当前的输出回链、保存精确 candidate mappings，最后由另一位可读全范围且不参与上述实际事项的具名 quality reviewer 办 NamedReview。原因是现 `_mapping_pairs` 比较 mapping.run 不可变行/revision 与 live paired Current：先封 v3 mapping、再推进到 v4/v5 不会自动被改为最新，原候选与旧 Draft Link 应保留为历史，需要按真实当前输出重新办理。候选自身仍 indeterminate，不能为了接通 Review 清掉未知。

公开枚举仍有独立接缝：`quality_followup_integration.request_options:16–74` 只选具有直接 canonical Formal Receipt 的 Current；`quality_followup_views._option:161–213` 核该精确直接 Receipt。advanced Formal 的 common subject 常是 Run，故不能借旧 Draft Receipt，也不能伪造一个 Current Formal Receipt。Root 可提供真实 Current Run 的直接输出候选并让既有 Run owner 核其 direct Receipt；若要选 advanced Formal，须另做明确 paired-owner option dispatch，消费上述真实 paired group/HostGate。这个 dispatch 目前未配置，现 missing 文案应保留；只注入 NamedReview paired_owner 不会自动改变旧 Link/选项协议。

## 旧 private 本人为什么不能成为正例

`quality_execution.service`/quality_followup `_row`、front/launch `_row` 和 anchor_storage `_project/_version` 均按实际 series/project owner 检查 private。给 peer ProductGrant 只授产品范围，不授私有 Issue/原报告/根因/完成/新输出的读取权；不能装 Owner Context 代读。旧本人又是原测试/原报告登记、根因、遏制或措施完成参与者，NamedReview `_independent` 排除其实际 UUID。`participants_owner._Read.run:248–312` 还把固定新 Run 各版真实 writer、actual executor 纳入，专业审核/处置办理人也不能兼任这条 CAPA 的独立 reviewer。

因此旧案例保持其真实拒绝/缺项；合法共享正例从 product 可见且真正已保存来源的新失败初建。项目也须真实 product 可读，原报告/专业出版/规则/观察/完成出处及所有新输出均在适当受众内，不能把私人行标签改 product。独立 reviewer 应从最初具备合法读取与本操作职责/资格，且不进入实际参与者集合；这里没有授权扩大旧 private ACL。

## 来源上限是完整闭包，不是挑二十份

以实际 Artifact id/revision 聚合原 StableCapaAnchor（原 Issue/CAPA/Failure）、新 Formal/Run/LaunchFact/ResultAction/Projection/每个 Measurement/capture/report、retained 资源/样件和原签发专业、Rule/Observations/participant、当前 reviewer 专业/政策与新选择来源。相同精确 Artifact 版本可以合法去重，多条 line/field SourceRef 定位仍完整保留；同 Artifact 不同 revision 冲突，完整 Artifact read set 超过20直接拒绝。`anchor.canonical_reads:44–58`、quality evidence.merge_reads 与 results._union 已执行这条规则。

Root 本轮观察保存反馈为完整19份来源的部分 native 系统观察，非实物观察；本审阅未连接目标库重复核数。该记录不授 sampling complete 或 live pair。后续应对全新的 reviewer/方法/规则/观察/报告并集重新计数，不能因为已有19份只挑剩下一份而漏闭包；新增兼容资料可合法复用其真实同版本出处，超过20则仍明确拒绝。

合成场景可让真实受控出版原文把兼容的职责/多操作资格等内容放在同一 actual registered Artifact 的不同精确行，或复用既有同版本公共基线；每条业务事实仍保存自己精确引用、真实登记与 issuer proof。不能合并/改写已经保存的旧报告与回执、复制假摘要、删除 negative facts 或安全 epoch来省读集。先算全并集再办理；超限时缩小真实业务批次/另建有完整来源的新场景，不能截断或让 bridge 仅返回 positive 用到的来源。

本段最小依赖归属：新的 LivePairedOwner 负责真实 read/refresh/attest 组合；Root 负责 startup 注入与明确 direct/paired 输出 dispatch；现 NamedReview/participant/source/retained/原值/事实模型可直接复用；actual applicability/观察/政策 owner 各自保持 typed 边界。无新表/新 Current/第二真值要求，也不开放有效性/关闭。这是下一缺口的接线事实，不是已通过的运行状态。

## 本次源码绑定

| 实际文件 | 审阅时 SHA256 |
|---|---|
| `pdos-next/server/pdos_next/domain/capa_effectiveness/paired.py` | `4df6e7a2c734d5bc8dcf3f586fb7cec1d2fc637f6e77dd83bd1ce0bba3fd1be1` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/paired_storage.py` | `148480bbb5dd0aa97a3e3482ec4b7674ddd1815c2b53a7b6aa49eaca078e6056` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/named_review_owner.py` | `ca6c235254dbc25e140bdaa4876063a2e00a7fabad59809b1c27a3dd20c7ce6a` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/participants_owner.py` | `a0bb90e954c68c87184cbf5b0526ea023242928f2ae8c6dddd6ea7bc7ee5c282` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/fact_sources_owner.py` | `b431151e49b72e8cce36f36486a670ecce6a2e9fc333e1bd52ba3ddc75db8126` |
| `pdos-next/server/pdos_next/quality_result_bridge.py` | `28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077` |
| `pdos-next/server/pdos_next/domain/test_resources/retained.py` | `abf1c6d4599b3a5c13f113666b1971e85bfb173b5c27e1b34e1e17197517e0de` |
| `pdos-next/server/pdos_next/quality_followup_integration.py` | `2c722d0fa94e02fd5d0e1d7ebeec1e52a782015457cb58e4ed5efbf3fce32e5f` |
| `pdos-next/server/pdos_next/quality_followup_views.py` | `2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3` |
