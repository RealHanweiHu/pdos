# 第十七波首段施工合同 · 稳定材料与真实配对证明

**2026-10-08：本施工合同已被[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)整体取代，仅作只读历史对照。下方旧“当前/下一步/冻结”不再作为施工指令。** 范围根、一致性、期限与数量限制按 v1.1 和已批准的 [S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md)执行；[旧条款对照与 B0 基线](../reports/evidence/pdos-next-s0-20261008/baseline/baseline.md)保留取代依据。原证据、失败与当时范围不改写。

本合同在既有完整建设授权内冻结首段实现选择。技术依据为 [Wave17 草稿](2026-10-03-pdos-next-wave17-effectiveness-contract-draft.md) §9–12，冻结草稿 SHA256 `05163de7294e0150995f21e75a4cee2dc10032d1ad2cce5330f0c68e6330cdb9`。真实具名 T2、生产、外发及原人工出口保留；本合同不授予真实资格或替代这些批准。

第十六波旧480份v3候选及20项检查已于10:23UTC停止，历史保持；新的484份v4后端候选正在9项替代事务验证。首段仅在 `pdos-next/staging/wave17/` 构建未挂载的新纯逻辑、严格 DTO 和宿主协议；不编辑 `server/`、`web/`、依赖锁或迁移，不导入公开操作。主线核对首段后统一迁入正式目录并完成公共接线。暂存交付不是已可用业务能力。

当前公共接入范围见文末；以下首段到第七段的“未挂载/尚未登记”是各阶段冻结时记录，不能据后续候选接入扩展到其他操作。

## 首段结果与单一事实边界

1. 以真实原完成版建立 StableCapaAnchor：固定完整调查材料、全部原失败证明和原来源安全闭包。初始要求 awaiting_verification、有具名根因、全部本人完成、未归并、无重核标记。版本不硬编码为 v6。
2. 严格核有限后继谱系，最多允许一次有效性决定和其后一次关闭；所有其他调查材料和原源安全保持。当前授权闭包单独核齐原源及合法新增来源。不能删除 history/source 后作宽泛相等，不新增第二份 Current。
3. 真实 paired Formal 证明按实际 LaunchFact / ResultAction 的精确 next_request、Run 和 Receipt 配对。Run.request_version_id 是 immutable origin，不当 Current；domain intent 与 common intent 分别核，不直接判相等。Promise、Plan、Start、Result 实际推进不同，不假设两边都 +1。系列 owner 与当次 writer 分别固定。
4. 首段所有证明是纯验证输入，不能独立授予当前权限、专业资格、原件可读或有效性。真实宿主缺口返回明确 missing；缺 callback 时不能启用决定/关闭。现 Wave16 私有失败链保持原受众，不能通过给独立复核者授权来扩大可见性；后续正例须从合法共享来源的新失败场景初建。

## 并行归属

| 归属 | 独占暂存路径 | 交付 |
|---|---|---|
| A / reuse_foundation | `anchor.py`、`lineage.py`、`test_anchor_lineage.py`、`anchor-contract.md` | 严格锚及有限谱系 DTO、完整材料规范摘要、来源闭包与 append 白名单纯核；不访问 DB/HTTP，不自己产生批准/Receipt |
| B / reuse_engineering | `paired.py`、`test_paired.py`、`paired-contract.md` | 严格实际 pair DTO、最小宿主读取协议及纯配对校验；真实 Current/事实/回执/前版/Scope/Writer 必须闭合；缺失保守拒绝 |
| C / reuse_product_ui | 待 A/B 字段交付后再分配暂存前端路径 | 读取及两次具名预览界面，保持未知、缺项、历史与原请求恢复；首段不预先发明公共 API |
| 主线 | 暂存共用入口、施工合同、后续模型/迁移/共同 T2/宿主/API/BFF及公共验证 | 明确消费 UUID、single Issue append、原子回执/审计/事件、实际 owner/bytes/当前授权与末端重核；统一迁入和验证 |

A/B 可导入现有纯 DTO、canonical digest 和只读类型，但不得改其实现。互不编辑对方路径；必要共用字段先报告主线，不分别定义同一真值。纯检查仅用明确暂存用例、不得加载 repo 数据库 fixtures。原始结果及文件哈希分别放 `docs/reports/evidence/pdos-next-wave17-20261003/`。

后续严格遵循草稿 §9–12 的两个不同 T2、反向同事务证明、晚回链、观察与独立复核和保守降级约束。首段通过后仍需实际新共享失败/新复验、真实规则与观察/复核证据、公共迁移及事务/页面验证，才能分别办理有效性和关闭。G3 整体仍未通过。

## 第二段暂存归属：规则、观察与具名复核材料

主线已核对首段最终七文件：A 的57项纯检查与B修正后的58项分别绑定准确哈希，独立审阅的Plan时钟缺口已修复；旧51/57项记录保留，不累计为更多覆盖。见[主线范围核对](../reports/evidence/pdos-next-wave17-20261003/root-staged-integration-observation-v3.json)及[最终增量复核](../reports/evidence/pdos-next-wave17-20261003/ui-proof-final-delta-review.md)。这些代码仍未挂载。

在Wave16后端候选按代冻结的条件下，A独占新增 `staging/wave17/facts.py`、`test_facts.py`、`facts-contract.md`，按草稿§5/6/12实现Rule、Observation和具名Review的纯DTO、最小宿主协议与保守结构核验。不得修改首段七文件、server、web、依赖锁或迁移；仅检查本段纯用例，不加载数据库fixture或运行HTTP。其他Agent只读审阅该段，公共验证仍由主线执行。

字段必须固定范围、用途、CAPA要求及全部失败/措施完成映射、完整来源与参与者依据、原始时钟、实际观察范围、nature和对应T1/T2出处。客户端结论、名单、hash和结构核对不能授予可信事实；真实同Session source/participant/applicability/observation callback缺失返回明确missing，不装配完整VerificationEvidence，不复制旧有效性规则。三项辅助公共操作尚未注册，当前不产生证明、Receipt或业务事实；后续主线统一接线后才可执行真实持久化验证。

第二段facts v2已修复真实活动Session/主子事务证明缺口，88项纯检查通过；旧77记录及原缺口保留，主线与C只读复核见[范围核对](../reports/evidence/pdos-next-wave17-20261003/root-facts-source-observation-v2.json)。三个暂存文件仍未挂载，也未产生业务事实。公共候选运行期间，A/B/C仅在独占新报告内并行核对真实持久化、paired owner和界面接线，不修改公开候选或自行执行PG/HTTP。

## 第三段冻结：真实存储读取与事实 body

在公共后端484份v4候选保持冻结、9项替代PG运行期间，新增暂存归属如下；均未挂载公开操作，公共迁移、数据库/HTTP/浏览器验证仍由主线统一执行。

| 归属 | 独占新增暂存文件 | 本段交付 |
|---|---|---|
| A | `fact_storage_models.py`、`fact_storage_codec.py`、`test_fact_storage_codec.py`、`fact-storage-contract.md` | 五张事实/Current模型与严格不可变body codec；不导入公共模型注册、不运行DDL |
| B | `paired_storage.py`、`test_paired_storage.py`、`paired-storage-contract.md` | 真正同Session/UOW、实际调用者ACL与SQL读取的六操作配对材料；缺真实出处返回missing，不实现肯定授权attest |
| C | `ui-contract.ts`、`ui-state.ts`、`ui-state.test.ts`、`ui-state-contract.md` | 服务器DTO与scope capability消费、原请求恢复状态转换；不请求HTTP、不修改公共web |
| Root | `fact_atom_storage.py`、`test_fact_atom_storage.py`、`fact-atom-storage-contract.md` | 实际存储body/共同Receipt/原Key/Audit/Outbox/proof组读取；不授当前七owner或false→trueUOW |

持久化选定body＋真实原子组reader方案：body严格保存FactBase材料减`provenance`及自身`ref.sha256`，全部子FactRef完整SHA保持；`payload_sha256`等于冻结`fact_payload_sha256`。真正宿主读取已经保存的事实与准确Receipt/Audit/Outbox/proof，提供实际FactAtom，再计算完整FactRef SHA并通过原typed事实校验。apply内不发明将来回执UUID，不事后UPDATE immutable body，不把payload摘要冒充full fact摘要。

共同消费时钟由主线未来在实际false→true之后、任何下一次SQL/autoflush之前捕获，并与新事实保存；不反推Receipt/旧bool、不改旧Confirmation列或三操作守卫。本段只声明存储字段，不宣称真实宿主hook已接通。transaction proof identity T1/T2绑定实际Confirmation UUID，host-only publication绑定实际共同Receipt UUID，摘要由真正持久原子组reader派生，不用xmin/XID或客户端自填值。

辅助名称、分级和回执族在本段冻结，尚不注册：

| 操作 | 分级 | 回执族 | 事件 |
|---|---|---|---|
| `quality.capa.verification.rule.import` | host-only import | `capa_verification_rule` | `CapaVerificationRulePublished` |
| `quality.capa.verification.candidate.record` | T1 | `capa_verification_candidate` | `CapaVerificationCandidateRecorded` |
| `quality.capa.observation.record` | T1 | `capa_observation` | `CapaObservationRecorded` |
| `quality.capa.verification.review` | T2 | `capa_named_verification_review` | `CapaVerificationReviewed` |

canonical `quality.capa.effectiveness.decide` 与辅助 `quality.issue.close` 仍是两个不同T2及分别真实proof/Receipt，沿既定唯一Issue Current办理。Rule不存在人工UI self-grant。新的事实模型、codec和前端状态不授专业资格或effective/closed；候选仍保持indeterminate及三个NULL。

实际配对读取只用真正ctx与当前ACL，immutable Run origin不当Formal Current；原RequestKey关联要求至少一条实际writer/Receipt id/digest等于原Receipt.request_digest，不要求合法后续aliases摘要都相同。缺原关联、任一准确父版/事实/原子组或实际caller读取权时保守missing。六操作storage reader不默认实现bytes/retained/专业/数值/runtime及末端IO授权attest，须主线接这些可信owner后才可用于公开办理。


第三段固定结果：A四文件38项纯检查及离线DDL编译、B三文件61项纯检查、C四文件26项状态转换及严格TS、Root三文件20项原子组读取纯检查分别通过，各自证据保持分范围。Root实际62513/next_0025只读解析并求值五模型的46条CHECK表达式（typed NULL），仅确认PG JSONB/操作符类型语法，不应用DDL，不冒充FK/唯一/RLS/immutability/消费成功。实际资料/源/专业/观察及同事务false→true依旧须公共接线；两项读取边界（ACL最后IO跨期、JSON true误当v1）已窄修，原18/19记录保持，最后20项及格式AST相容见[Root v5](../reports/evidence/pdos-next-wave17-20261003/root-fact-atom-storage-result-v5.json)。B/C独立审阅未发现第三段新增实质阻塞，但共同Confirmation复合Unique、SQL双向target及当前七owner仍未实施。

第四段已在独占暂存路径继续：A `fact_registry_storage.py/test_fact_registry_storage.py/fact-registry-storage-contract.md` 读实际固定事实/真实系列Current与有界前版；B `anchor_storage.py/test_anchor_storage.py/anchor-storage-contract.md` 读真实显式原完成Issue版/Current与原回执组；C `ui-view.tsx/ui-view-contract.md` 实现数据驱动React视图，不造HTTP或具体payload表单。Root仍独占公开注册、实际源/失败/专业/issuer全IO门禁、共同消费时钟、DDL及集中验证。未读原失败/SourceSafety就不能build可信anchor；历史Current合法后继返回needs_lineage_owner，不删history宽比。前端未有真实表单/完整选择时禁用预览，caps/资格只从宿主模型读取，UNKNOWN全部输入锁定，slots/labels不改变政策。第四段仍施工，不作完成声明。

Root 同段独占新增暂存 `fact_consumption.py/test_fact_consumption.py/fact-consumption-contract.md`：仅冻结两个T1（候选、观察）及三个T2（具名Review、有效性、关闭）的共同消费扩展。实际persistent Confirmation在原共同消费前绑定完整材料，false→true后首行捕获真实UTC钟，必须保持原Session及完整活动事务链；任何SQL/flush后不得补造该首个消费标记。它不改旧三操作、不执行consume/SQL/commit、不注册公共hook，也不把本次内存标记当持久SQL双向目标证明、来源授权或专业资格。实际共同consumer接线及数据库反向原子守卫仍由主线后续统一实施。

第四段最终A51/B53纯检查、C严格React TS、Root29真实ORM状态纯检查分别冻结，actual Project私有访问与末端重核已补齐。Root用实际app身份及READ ONLY事务读取现有v6原完成，完整描述与共同组通过；纯检查、该实际只读观察及独立复核均不授7owner/原失败字节/专业资格或G3出口。

第五段新增归属：A `candidate_storage.py/test_candidate_storage.py/candidate-storage-contract.md`，B `fact_sql_guards.py/fact-sql-guards-contract.md`，C只读candidate独立复核报告。公共注册、Actual Payload/consumer、迁移/DDL与集中验证仍Root独占，不改已冻结源或预留迁移号。candidate full SHA冻结为canonical digest：`{schema_version:'pdos-capa-candidate-full-v1',candidate:全部实际不可变行列,group:实际共同原子组}`；不包含Outbox投递状态/后续key aliases，不以binding/inspection SHA冒充full。新candidate input_snapshot严格为`{semantic,shared_proof:{id,tier:'T1'},proof_consumed_at,stable_anchor}`，实际原消费钟与完整锚来自可信宿主；row.intent_digest为实际common语义，Receipt.result展平真实candidate_binding_sha256/inspection_sha256，不放full SHA。candidate public Payload尚未注册，reader只收实际严格Payload/semantic owner的可信启动注入，缺失默认503，不猜旧Link语义。

第五段已冻结：A候选完整保存读取53项纯检查；B仅Python静态/import及实际六函数绑定生成，4替换函数/6新函数/15触发器/41权限语句，未执行SQL；C只读复核未发现新增明确阻塞。Root组合五表与进程内待加Confirmation复合Unique，离线解析38条外键的完整目标唯一约束/列类型并编译PG DDL，通过；未写公共模型、注册生命周期或应用迁移。证据见[第五段结果](../reports/evidence/pdos-next-wave17-20261003/result.md)。

第六段独占新增：A `candidate_commands.py/test_candidate_commands.py/candidate-command-contract.md`，只定义真实严格candidate请求、canonical无token语义及对照实际Binding/Current的结构核验；B `anchor_owner.py/test_anchor_owner.py/anchor-owner-contract.md`，组合实际原完成descriptor、已配置固定失败桥/末端refresh及完整源闭包来构建锚；C `candidate-form-contract.ts/candidate-form.tsx/candidate-form-contract.md`，只从实际宿主固定选项填候选表单，不请求API或自启资格。Root独占实际读取观察、公共接线及集中验证。全部旧暂存及484份v5公共候选保持。

candidate请求字段固定issue_id/expected_issue_revision/capa_id/remediation_link_refs/mappings/sources/reason/visibility/confirmation_token；Current CAS与原锚版不同，来源受众、原件和实际owner由宿主核，不接受客户端anchor/binding/inspection/proof/资格结论。UI默认disabled/private、真实完整映射固定选择，scope/Current/choices改变不能沿用旧填写，UNKNOWN依原共同请求恢复锁；无token表单回调不等于确认/保存。

真实anchor owner使用原桥逐项读取确切原FailureRef，不用Run Current代替、不把报告字段位置套作人工原文行格式。全部原件IO后逐failure refresh，再刷新完整源安全、原descriptor/Current/Project/实际caller及runtime/issuer epochs/UOW，最后取新时钟。旧owner会取实际行锁，所以此段是业务只读；PG READ ONLY事务只适用于此前raw descriptor观察，不能取消原锁来使新桥假通过。Root实际读取拟以driver禁止DML、禁止flush并最终rollback核验；本地合成读取不授当前专业政策/有限后继谱系、七owner/消费或G3资格。

## 第六段收口与第七段并行

第六段A63/B54纯检查、C表单v3严格TS/实际lint、Root真实TS→Python契约核对分别通过。实际旧原失败读取v2在62513/app通过，1失败/16来源、保留行锁且零业务DML/flush并rollback；当前专业授权与消费仍未授。Wave16仅断言修正v5单节点通过，所需九项替代影响范围已补齐，原代分别绑定，不据此称整树联合通过。

候选v1受众冻结：继承原basis.owner_id/visibility，writer是当次真实actor；payload.visibility必须精确等于origin.visibility，差异报CANDIDATE_AUDIENCE_MISMATCH，不能默默用private默认转换共享源或扩大旧私有范围。候选可保存真实partial/indeterminate与三NULL，缺专业/观察/配对等资格仍不能有效性/关闭。

第七段A独占candidate_prepare.py/test_candidate_prepare.py/candidate-prepare-contract.md；B独占candidate_write.py/test_candidate_write.py/candidate-write-contract.md；C负责fact_storage_models.py的purpose宽索引/可信issuer长度窄修及独立边界用例与合同。原模型c5e19、原SQL2a10/旧plan私有备份或证据保持。完整purpose事实与anchor/源不截断，可信issuer key/version明确100字符（与既有服务器issuer配置边界一致），purpose不作为冗余宽B-tree FK列；Current、原版及child的实际purpose关联须SQL与host继续核定。Root补5模型索引生成与候选受众/实际purpose SQL核，实际数据库DDL/回滚观察、公共接线与共同consumer仍统一执行。

首次预览full anchor包含实际bridge检查钟与完整proof；后续仅3确切观察路径可用于稳定重核，不能重封full anchor。跨HTTP写阶段必须从实际persistent Confirmation.snapshot恢复原完整锚并重新读取真实owner/源/范围；客户端DTO或后来新phase不能替代原保存材料。当前公共专业矩阵尚缺新operation，prepare明确503，政策批准不是资格。


## 当前公共接入范围：仅候选T1

首七段冻结模块已由主线迁入 `pdos-next/server/pdos_next/domain/capa_effectiveness/`。公共只登记辅助 `quality.capa.verification.candidate.record`（T1），回执族 `capa_verification_candidate`、事件 `CapaVerificationCandidateRecorded`；Rule仍host-only设计，Observation/具名Review及effectiveness/close均未开放，专业角色映射或synthetic profile不等真实资格授予。

主线已完成 `next_0026` 的25→26→25→26及schema检查；[postcheck v3](../reports/evidence/pdos-next-wave17-20261003/public-migration-closeout-v3.json)绑定原四步日志，确认111表生命周期目录、新五表强制RLS/启用引用门栓、Agent直接权限0，原106表迁移checkpoint摘要保持。迁移[v1步骤前错误](../reports/evidence/pdos-next-wave17-20261003/public-migration-result-v1.json)与[v2旧表物理序postcheck错误](../reports/evidence/pdos-next-wave17-20261003/public-migration-result-v2.json)原样保留；v3未重跑迁移，不声称旧checkpoint之后仍零业务写入。

公共prepare必须恢复actual persistent Confirmation原13键snapshot中的首个完整StableCapaAnchor，独立重新读Current/basis/binding/inspection/source/专业/政策；只3确切评估路径可用于稳定重核，原full proof/fullSHA不重封。consume在True之前绑定实际same Session/UOW，True后首行捕获消费钟，保存前再次独立刷新及最后Clock/TTL核验。Current v1仍等origin，后继有限谱系owner未接前拒绝；owner/visibility继承origin，writer是本次本人，payload.visibility必须相同；public只新增不可变候选，不推进Issue Current，不再reserve。

[prepare/write v2](../reports/evidence/pdos-next-wave17-20261003/candidate-write-prepare-check-result-v2.json)18项只证明禁连接ORM/UOW、替身owner和实际writer的规范JSON序列/边界；[薄服务26项](../reports/evidence/pdos-next-wave17-20261003/candidate-service-check-result-v1.json)是其独立局部范围，旧依赖hash及新v2修复分别保留，不合计联合覆盖。JSON修复仅四个sources/readset序列逐元素完整dump，原序/字段保持，staged不改；原tuple错误/夹具失败与新源清单见[v2 manifest](../reports/evidence/pdos-next-wave17-20261003/candidate-write-prepare-source-manifest-v2.json)和[atom结构审阅](../reports/evidence/pdos-next-wave17-20261003/public-candidate-atom-shape-review-v1.md)。

候选T1已在明确隔离目标实际保存两份本地合成候选。CLI原完整请求的[v7恢复](../reports/evidence/pdos-next-wave17-20261003/candidate-actual-http-v7.json)返回原Receipt及相同响应SHA；浏览器单次保存先进入UNKNOWN，随后按原command/key取得回执并读到两份历史，未另造确认或候选。[实际存储核对](../reports/evidence/pdos-next-wave17-20261003/closeout-v1.json)确认两组唯一Receipt/Audit/Outbox、17条完整源、原13键预览锚及消费/保存/到期钟，三个列与JSON键均为NULL、Issue仍v6，所列24张旧业务表全行摘要保持。[SQL守卫19项](../reports/evidence/pdos-next-wave17-20261003/candidate-actual-sql-checks-v2.json)包含一项合法组与18项拒绝，3项复用v1、16项实际续跑，各自回滚后111表摘要保持；不以此授专业资格或宣称整树联合通过。

候选新写仅延后一次立即丢弃的早期validate；原key/语义Receipt命中仍先完整当前校验，新写仍由prepare_write在消费前重核、writer在消费后独立刷新及最后Clock/TTL检查，无跨phase正向缓存。BFF仅候选采用专用600秒header/body dispatcher并保留600秒总体Abort、同源/会话/原正文单fetch；[最终web v6](../reports/evidence/pdos-next-wave17-20261003/web-build-result-v6.json)类型/lint/构建与154份源码稳定。短合成计时与实际业务保存/恢复范围分别登记；未把未捕获cause的旧UNKNOWN唯一归因，也未声明真实600秒请求已实测。

七owner、真实规则发布/观察/具名复核、分别有效性/关闭和生产资格未接通，候选保持indeterminate/三NULL，原G3/人工出口边界保持。下一步按[专业闭环交接](../reports/evidence/pdos-next-wave17-20261003/next-professional-loop-handoff.md)先核完整20条来源闭包、真实参与者及Rule/Observation/Review的独立资格，复用现五表和原子组，不扩大旧private受众。当前验证覆盖与最终页面证据见[结果](../reports/evidence/pdos-next-wave17-20261003/result.md)。
