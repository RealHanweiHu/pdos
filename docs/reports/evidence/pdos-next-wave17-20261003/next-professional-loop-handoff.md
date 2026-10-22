# 下一专业闭环交接：真实规则、观察与具名复核

这是实施前只读交接建议，不修改当前候选、施工合同或唯一清单，不分配新的运行授权。依据现 [施工合同](/Users/huhanwei/Documents/ai-native-R&D-platform/docs/design/2026-10-03-pdos-next-wave17-staged-implementation-contract.md)及 [草稿 §9–12](/Users/huhanwei/Documents/ai-native-R&D-platform/docs/design/2026-10-03-pdos-next-wave17-effectiveness-contract-draft.md:134)，本次未执行 DB/HTTP/浏览器/tests，未读取凭据。以下建议文件归属需主线后续明确，任务描述不授真实 T2 资格或人工 Exit。

建议下一可交付闭环是 **可信 host Rule 出版 → 本人 T1 保存实际观察 → 独立本人 T2 保存固定候选的 Review → 七 owner 当前回读及缺项显示**。Rule/Observation/Review 都是 companion，不推进第二份 Issue Current、不改候选的 indeterminate/三个 NULL、不再占用或消费原 Run。有效性与关闭的公共适配可并行建设，但只有上述真实材料完整后才分别办理两个 T2；不把 Review 保存等同有效性或关闭。

## 最短业务顺序

1. **保留原锚与受众。** 主线现原完成 Issue6 的 exact 版行、完整 history、FailureRef、原件证明、措施完成、全源及 full anchor 原样保留，不用原失败 Run 的 Current 替代。复用 [实际 anchor owner](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/anchor_owner.py:127)。该私有系列仍仅 owner 可读；若此 owner 已参与原测试/根因/措施，则不能当独立复核者，给另一人 Product Grant 也不能打开 private 来源。完整独立正例应从合法 product 来源建立**新的共享失败/调查完成系列**，不用改旧 Issue6/Run 或扩围原资料。
2. **先固定规则与办理依据。** host-only 出版 exact scope/purpose/requirement、全部 failure/action completion、实际观察目标/采样/接受规则、方法/判据、独立性政策、issuer/version/epoch/nature、期限和来源。专业 operation 矩阵和当前真实 duty/qualification 必须由 host separately 提供；不能从 Rule 发布或 Grant 推出资格。没有可核规则出版者/原文时，其正式出版 positive 暂停，读取/缺项和 handler 仍可完成。
3. **复用 owner 创建真正新复验。** 需要数值依据时，由有当前资格的 owner 通过已交付 Request→实际方法→交样/接收→Plan/Promise/Start→真报告 capture/import/compute→规则要求的 review/disposition 建立**新 logical Run**；实际开始和原值在措施完成之后。旧失败 Run 后继 pass、旧 Draft Link、模型生成测量不代替它。复用 [测量 verifier](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/measurement_evidence/verifier.py)、[结果宿主](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/verification_results/service.py:526)、[retained](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/test_resources/retained.py)。先由真实 paired owner 证明准确 Formal/Run/LaunchFact/ResultAction/common group，再晚回链并保存完整 mapping 的新候选；旧 planned Link 保持历史。
4. **本人记录已发生观察。** Observation T1 选真实 exact 来源和目标，保留原始记录、实际 executor、EventTime 微秒/IANA、observed_from/until、覆盖与采样出处。`observed_from >= max(全部措施 completion.occurred_at)`；实际终点必须覆盖要求、已发生且不在未来。长观察期尚未结束只暂停完整观察/effective 正向，不能挪钟、以接收时刻或短测试冒充完整观察；仍可保存真实部分/缺项版本。
5. **独立本人 T2 复核。** 固定 candidate **full SHA**、Rule full ref、按原序完整 Observation refs、逐失败新 Run/sample/item/实际配置/方法/判据映射、逐措施履行及全部参与者。资格、本人身份、政策和原文当前核独立于保存时的结论。unknown/not_applicable 可作为真实结论保存并显示缺项，不装配假完整 `VerificationEvidence`。
6. **完整后再分别有效性与关闭。** 复用旧 [QualityHandler._verification](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_issues/handlers.py:127)及 [PolicyPort.verification](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_issues/ports.py:178)，不复制有效性规则。effective 要全部精确原失败覆盖且结果 pass；ineffective 要确定 fail，indeterminate 不能冒充任一结论。关闭由原有效性决定者本人另一次 T2，重核同 evidence read_digest/policy。原锚→effect→close 是仅两次精确后继，两个 command/proof/Receipt 各不同；[有限谱系纯核](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/lineage.py:512)仍需实际 host 读取绑定，不能单凭输入 hash/布尔授权。

## 已有交付与七 owner 的实际接缝

[facts.FactReader](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/facts.py:848)明确七门禁；[load_verification_facts](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/facts.py:964)有两轮读取/门禁及 post-all-owner refresh，但缺实际 callbacks 时返回 missing，**不返回旧核 VerificationEvidence**。

| owner | 可直接复用 | 仍必须实现的真实依据 |
|---|---|---|
| registry | [read_stored_fact](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/fact_registry_storage.py:456)、candidate_storage、atom reader、body codec；精确行/full SHA/有序 children/Rule、Observation Current | host 组合完整 fact material、Current/有限谱系；raw reader 的 `current_evidence_authorized=False` 不能改成资格 |
| sources | [evidence.source_basis/check_source](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/evidence.py:34)、OriginalSecurity/read gate、真实原失败桥 | 原+新增 Rule/Obs/Review/输出的完整来源闭包、原件 bytes/位置/epoch/current ACL/private，≤20 不截断；原报告真实性不能以 native 文本存在替代 |
| participants | 原 Failure/根因/遏制/action completion；实际 Launch/结果原值/Observation actor provenance | 完整实际原测试、整改、根因、新测试/测量/观察参与人集合及出处；名单非客户端声明，不用 owner Context 给复核人借权限 |
| applicability | typed PairApplicability/ActionFulfillment、固定方法/实际配置、actual results/projection | Rule 对实际 pair 的适用核对与每个 action 履行 owner；现 [resolve_followup_outputs](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_verification/service.py:433)仍明确 `ACTION_FULFILLMENT_PORT_MISSING`，不得删除缺项。formal_change 没有真实批准/实施 owner 时继续 unknown |
| observation | [RuleVersion/ObservationVersion](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/facts.py:233)的范围/原钟/记录 DTO 和结构核验 | 实际记录来源、完整目标/采样和观察区间 owner；时间到了、records 数量够或源 UUID 存在都不构成完整观察证明 |
| provenance | read_fact_atom、[ConsumptionHost](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/fact_consumption.py:152)、实际共同 Receipt/Audit/Outbox/RequestKey | Observation T1/Review T2 的真实 same-UOW false→true首行捕获、UUID与Invocation绑定、双向延期目标组。历史 consumed=True 不自证本次消费；Rule是 host import，不造人工批准 |
| authority | [professional.assess/recheck_snapshot](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/professional_authority/service.py:522)、[policy.assess](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/policy.py:270) | 新 exact op/purpose/role 的受控当前专业事实、Rule issuer 和独立性政策；原签发者/负事实/撤回 ABA/current epoch/未来 activation/期限重核。当前矩阵未含 Observation/Review/effectiveness/close，不能借 followup.link 资格办理新动作 |

[StoragePairReader](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/paired_storage.py:586)故意只有 read/refresh，没有 live attest；[PairedOutputReader](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/paired.py:1255)要求真实 ACL/source/professional/bytes/semantic/runtime，performed 还须 retained，result 还须 numerical rules。这是新实际复验→晚回链的先决接缝，不能将已有 SQL 配对结构当完成证明。

已有五表是 RuleFact/Current、ObservationFact/Current、immutable NamedReview（[models](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/fact_storage_models.py:252)）；candidate 另复用旧不可变表。迁移26已有这些表，不新增 Results/CAPA Current。codec 保存 body 材料摘要、保留 child full refs，原子组 reader 后算 full SHA；新 writer 不填未来 Receipt UUID、不 UPDATE body，也不拿 payload/binding/inspection SHA替代 full SHA。**表/reader/纯协议已有，Rule importer、Observation/Review public handler、七 owner、evidence adapter和两个后继公共办理尚未登记。**

## 建议下一轮独占分工与主线临界路径

| 建议归属 | 新文件边界（后续明确分配，不在本次施工） | 可并行交付 |
|---|---|---|
| A | `domain/capa_effectiveness/fact_commands.py`、`fact_write.py`、`fact_sources_owner.py`及对应 tests | strict Observation/Review payload、canonical semantic/preview、Rule host-import writer、复用现五表与codec；只 delegated common append，无第二 Receipt/commit/proof |
| B | 同 namespace 新 `evidence_owner.py`、`participants_owner.py`、`paired_owner.py`、`lineage_owner.py`、`effectiveness_commands.py`及对应 tests | 真七 owner 组合、旧核 evidence adapter、actual paired/有限谱系和有效性/关闭适配；先缺项路径，真实 owner 不足不 positive |
| C | 新 `components/capa-effectiveness/fact-workflow.tsx`、`fact-workflow-contract.ts`及 helper tests | 从服务器 exact options 选 Rule/Obs/Review，实际发生钟、当前/历史和缺项、T1/T2不同确认、UNKNOWN原请求锁；不输入资格/pass/完整参与者名单 |
| Root | 新启动 host/issuer/public integration 文件；公共 registry/roles/common consumer/API/BFF/metadata/SQL/lifecycle 的窄变更 | 冻结 DTO/callback和责任，统一注册/迁移及 actual PG/HTTP/浏览器；必要旧接口修改单独指定所有权，不由 A/B 隐改 |

主线关键顺序：①先冻结 Rule可信出版/Observation/Review strict载荷和真实参与者/采样/适用 owner callback，逐 exact op 配置当前专业矩阵；②复用 `fact_storage_codec.OPERATIONS` 冻结的三名/三族/三事件，注册仅 Observation T1、Review T2，Rule保持 host-only；复核现SQL guard与实际common意图/返回体/消费原子组互认；③A/B/C并行实现同 DTO，不先制造 positive；④统一候选做最小真实 PG（partial/full、ABA/私有、真实独立人、微秒/未来时钟、错 fullSHA/children、SAVEPOINT、末端 Outbox rollback、same/cross-key单回执）与实际受控材料整链；⑤若要有效性/关闭，单调迁移扩原 Issue CHECK/准确两次延期 proof-target/Current atom，两个 T2分别验证，不覆盖已应用26。

每 phase 的全部 owner/原件 IO后必须再次刷新完整来源/issuer/政策/专业/Current/Project/实际调用者、实际活动 UOW和最终Clock/TTL；后一个 owner撤前一个必须阻断。不跨 inputs/preview/execute 缓存正结果，不把新专属来源混入旧锚重封；旧 full proof保持，当前授权闭包仍包含原+合法新增源。独立人、真实 Rule来源、真实测量或完整观察期缺失只暂停相应正式成功路径；可以继续 reader、unknown保存、缺项 UI与负向原子验证。explicit synthetic 实测保持 synthetic，不声称生产有效性、关闭、G3或人工 Exit。

## 补充：读集 20 条与固定来源预盘点

本补充修订前文档 SHA256 为 `583009bd37e58a0e3daeee0b570cfc149afc86f4038204121e721898eacf6052`，只作施工预审。[v7 公开报告](candidate-actual-http-v7.json)记录实际候选完整读集 **17**（报告 SHA `2f1d2db96202aeb9e6c56f92c6b213728a76a42a52d0c1d37f0be206b6644de7`）。[Command](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/contracts.py:16)限20条；[merge_reads](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/evidence.py:19)按 Artifact UUID 去重，同 UUID 不同 revision 即 SOURCE_STALE，超过20拒绝且不截断；[canonical_reads](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_effectiveness/anchor.py:52)也要求完整1..20。若下一闭包必须保留这17项，再加入第四个新的互异 Artifact UUID 就超限；但17不是下一操作预留预算，换 actor、新 Rule/Observation/Review、实际配对及全部相关专业/政策/issuer出处可能引入更多固定来源。相同 Artifact 的不同原文行可只占一个 SourceRead，行/位置级 SourceRef及载荷自身数量上限仍分别核验。

实际 [source_for](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:160)以指定 Artifact id+product 读取，检查 private owner、当前 active status、指定 revision，并对有 original 的来源调用当前原件ACL/安全门禁；**没有“必须使用最新 Artifact”查询或 ArtifactCurrent 比较**。新建另一 Artifact 或推进别的事实 Current，单从此函数不会把旧 id 替换成最新源；旧源实际 revision/status/内容摘要、原件安全epoch/来源受众变化仍会阻断或改变 [source_basis](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/evidence.py:34)。这不代表可忽略专业/Rule/Observation/Issue Current：它们由各 owner 独立核，Issue后继仍须有限谱系；不能借它们的新来源替换原锚读集。

下一实现前由主线作**只读 inventory**：逐 exact origin/candidate/Rule/Observation/Review/paired ref，列出 saved 与本phase fresh 的 `{artifact_id,revision,来源角色,原文位置,scope,owner/visibility,hash,登记或original安全依据}`，分列全部专业事实（含相关负事实/前版/Current epoch）、政策/issuer、参与者与观察出处；对准备、保存、回放和末端刷新分别计算完整 union、同ID版本冲突、来源位置数及每个实际actor可读性。事实fullSHA、领域Current或inspection hash不能替代这些来源条目。超过20就保守 missing/拒绝；拆成几个请求不能解除最终 Review/evidence 的完整 union，不删除旧refs/历史来源、不更新旧immutable Source、不按最后20截断。

合法的新**独立 synthetic共享case**可在来源登记时，把当时真实已有的完整规则/政策/资格材料按多个准确行放入同一新不可变 Source；native必须有真实登记Receipt，上传原件仍走真实bytes/security。宿主须逐行核绑定和出处，source共用不授资格；不同actor的 duty/qualification/issuer仍各自精确scope/purpose/有效期，并让实际办理者和独立复核者合法可读。尚未发生的完成、测量或观察事件不能预填到旧源，发生后另登记真记录/原件；原private不外扩。若完整新场景仍超限，只能按真实业务上独立的项目/用途/调查范围从初建时分开，各自保持完整failure/措施/观察要求；不能为了腾槽拆掉既有CAPA必须全部覆盖的失败，或跨Scope借来源。该建议不授权放宽20、签发资格或制造真实材料。
