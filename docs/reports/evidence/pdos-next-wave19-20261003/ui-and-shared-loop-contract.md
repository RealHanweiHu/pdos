# 第十九波 · 当前复验输出与独立具名复核接线建议

本说明定向审阅当前清单、第十八波结果/`next-live-pair-handoff.md`及实际宿主/界面源码；没有运行数据库、HTTP、浏览器或公共检查，也未修改被审的领域源码。Root 后续授权的独占前端选择/恢复增量及纯检查另列末节。第十八波已保存可信 Rule 和部分 Observation，NamedReview 仍为 0；19份完整来源、未实物复测、观察期/抽样不足、有效性/关闭未知的原结论保留。本说明不是新正例通过或新增批准关卡。

## 最小可用闭环

先在独立新 Product/Project 的真正产品共享**新失败链**建立 Issue/CAPA，完成具名根因、执行者本人措施完成；保留旧私人 Issue/原件/回链。新 Product 不能引用旧 Product 的私有行或把旧对象UUID当新 scope对象；可复用纯算法/表单、真实受控的全局物理资源身份及经合法新登记的公共原始材料，实际 Definition/配置/Build/资格/资源事实仍绑定新范围。采用同项目、同用途、实际有权可读的独立新 logical Formal/Run，沿既有准备→正式草稿→方法/实际方法→交样/接收→Plan→Promise→实际 Start→报告捕获/原值导入→确定性计算→分别 Run Review/Disposition。Plan/Promise 零占用，实际开测仍由 Start 的原子组决定；旧 Run 和原样件使用不能伪装成新开测。

**先完成新 Run 的专业 Review/Disposition，再选择真正 Current 输出保存新 Link 和 Candidate mapping。** NamedReview 的 `_mapping_pairs` 按不可变 Run 行 ID/revision 与 live Current 严格比较；专业办理续版之后，早先 Candidate 不会自动迁到新版本。Projection 仍按真实完整 basis 绑定，不能因一条 pass 或专业文本代替全部原测量。新 Mapping 的 failure/run/sample/item、实际配置、measurement/projection均由服务器真实选项提供，客户端不输入 UUID 或拼新配对。

正例建议明确三位不同具名人：执行/原问题与措施办理人；新 Run 专业 Review/Disposition 办理人；未参与前两组事项的 CAPA 独立 reviewer。专业 Run 审核/处置也是实际新 Run writer 参与者，不能同一人再签 CAPA 独立复核。各自当前资格由服务器核对，不通过前台切换角色授予。

可信 Rule/完整实际 Observation 独立办理，再由未参与原测试、报告、根因、遏制、措施完成、新测试/测量/观察或相关专业办理的另一位具名 quality reviewer 作 NamedReview。读权限、当前职责/资格、实际参与者排除和方法/措施适用分别核对；产品 write 或选择“独立”不能替代任何一项。当前本人属于旧链参与者，不能用旧私人场景作独立正例。

## Current 输出选项：两个不同证明入口

| 输出 | 可复用实际入口 | 第十九波须接的精确分支 |
|---|---|---|
| 当前 Run | `quality_followup_views._option` 已区分 series owner 与本版 writer；`capa_verification._owner(verification_run)` 已读固定 plan/Start、当前来源、retained execution 和精确 Current。共同 subject 为 `test_run`。 | `quality_followup_integration.request_options` 当前仅枚举直接 Formal Receipt，需新增真实同项目 Current Run refs。每个 immutable Run ref用本版实际直接 Receipt/Audit/Outbox/RequestKey及专业依据，不借起点 Draft 或原 series owner的 Context。 |
| 由 Start/结果推进的 Current Formal | Formal 的真实 Current/固定 items、method/window source与专业状态必须保留。其推进对应共同 Receipt常属于 Run，不能假定 Formal也有直接 Receipt。 | 独立 paired dispatch：同Session/current UOW组合精确 Formal+Run+LaunchFact/ResultAction+共同组，必须是真正 LivePairedOwner opaque proof，不是客户端标志。`quality_followup_views._option`当前统一 `_receipt(subject=verification_request, exactFormal)`须显式分支，不能回退旧 Draft Receipt或伪造一份新Formal Receipt。 |
| 历史 Draft/Run/Link | 现有不可变 ref、snapshot和历史阅读保留。 | 不改旧 Link snapshots、owner_basis SHA或原 receipt；旧版 planned/current_evaluation未评估继续只读。新的真实完成输出另存一条 Link，不能把旧 Draft Link meaning自动升为performed。 |

固定 owner source closure只包含实际保存父版/子 method/window和它们真实安全、专业/current状态，不能带入当前 caller未来能办理的 command authority；第十七波已针对该漂移做过窄修。新增 reviewer 的资格来源属于本次 NamedReview完整读集，不能改变旧固定输出SHA。真实 negative、撤回、epoch/ABA、期限和private ACL仍必须保留。

公开 option保留真实 label/ref/status/logical_id/source_status/readset；若新增 paired proof类别展示说明，必须由宿主返回，不把 opaque proof或stamps给客户端。proof仅当前调用内使用，不缓存到 Session.info、跨HTTP或持久state作为资格。

## 现有前台需要的确切材料

现 `FactWorkflow` 已具备单次T1/T2确认、精确来源、原微秒时钟、返回命令原封提交、UNKNOWN原key恢复、Receipt先保存后刷新、401/403清私有及最低saved提示。`FactPanel`挂在原整改入口；无需另建导航或第二份事实模型。

NamedReview提交字段沿冻结 `fact_commands.NamedReviewPayload`：

| 字段 | 前台来源与交互 |
|---|---|
| issue_id / expected_issue_revision / capa_id / visibility | 真正当前 Host binding，Current CAS独立于原锚点；必须与原系列固定受众一致。 |
| candidate / rule / observations | 精确已保存 FactRef，候选v1、当前同规则的观察版本；不按时间猜“最新”。 |
| pair_applicability | 按 Candidate mappings原顺序逐项全覆盖；whole mapping、固定方法/判据来源只读，本人明确 applicable/not_applicable/unknown、reason与来源。空或缺方法不能补假适用。 |
| action_fulfillment | 原固定CAPA全部action IDs；本人逐项明确结论、reason与来源。服务器提供真实 action binding/classification/owner_material，不能以回链存在推履行。 |
| conclusion / reason | 本人明确总体专业结论与原因；unknown保持未知，不变ineffective/effective。 |
| at / sources | 带偏移的实际发生时钟与原IANA timezone、真实whole SourceRef，保留完整微秒；received_at仅服务器保存。源行选项含完整原文/版本/定位，非任意JSON或参与者/issuer编辑器。 |
| approval_token | 仅共同T2预览返回；客户端不自造。必须有实际 named_decision=true/write_tier=T2，一次具名确认后原封提交。 |

实际 preview继续13键：payload_semantic/stable_anchor/binding/inspection/raw_source_basis/完整读集/sources/authority_snapshot/policy_snapshot/owner/visibility/Current/operation。必须可读原失败值、工况、原设备与所有完成钟、原根因/规则、当前复验对应、方法/措施专业材料、参与者独立性/专业政策、三项未知及保存后果，不能只显示泛化“已核对”。whole返回命令除既有四声明clockpath同微秒瞬时外不归一化；raw数字字面、来源、quote hash、时区和顺序保持严格相等。

未来真实正向T2还需定向核阅读完整性：当前预览措施段仅显示结论/原因，真实classification在保存历史中才显示；应把服务器真实调查性/正式变更/未知分类及其依赖结论提前放入预览。当前配对段依赖host.detail和精确原文，尚不能凭泛化label表述新Run原值/工况/原设备/判据对照；Host detail或新增只读材料须来自实际配对owner。不能以“complete=true”取代尚未给出的真实业务材料；该增量等待实际Host冻结，不更改专业结论或原值。

施工前盘点曾有三处公开缺口（后续实际修复见末节；此处保留为何不能只注入两个新owner）：

1. `capa_fact_api.py:195–226`把 review固定为allowed=false/independence not_verified，并无条件添加未接通missing。须由真正相同scope的参与者/paired/applicability读取生成评估；已核来源、实际专业资格和独立性均通过才可准备，具体结论仍在inputs/preview/execute当前核对。
2. `fact_context`返回 `pairs:[]`，前台没有可编辑的真实配对；新Host须提供实际 whole映射、真实method/criterion、业务label/detail和全部可读来源。空pairs不能因顶层allowed被开放。
3. `capa_fact_api.py:252–276`按created_at升序取第一个同anchor Candidate后break。旧空mapping候选会遮住新完整候选。须冻结**明确候选选择协议**（宿主真实选项与显式ID，或Root批准的窄query扩展），前台不得按最新时间猜测。选择变化清未提交draft/preview，UNKNOWN仍锁旧命令不能迁Current；同scope历史保留。

盘点时前台仅候选单Ref，尚无Candidate selector。Root 后续已明确冻结 optional candidate_id 与实际候选选项，独占实现见末节；没有另建公共路径或默认肯定资格。

## 公共接线归属与最小验证

Root统一 `api.py` startup注入新LivePairedOwner/applicability owner、`quality_followup_integration.request_options` Current refs和`quality_followup_views._option` direct/paired dispatch、`capa_fact_api.fact_context`真实host选择/能力/来源，以及共同Commands/Receipt事件。现 canonical review T2/family `capa_named_verification_review`已登记，不能把 Run专业Review的 `test_run` Receipt当CAPA Review。

BFF现已有 `quality-followup`/`capa-facts`及inputs、两fact操作allowlist和600秒窄传输。若Host只是增加真实fields不需拓新route；若Root冻结candidate query，才同步精确UUID/允许列表及其纯检查。不拓通配路径/身份切换/自动重试。薄UI改动归现 `capa-effectiveness/fact-panel.tsx`及必要本包contract/workflow；Root持父整改页面，原导航保留。

最小正例只证明新共享合成场景完整办理：真正Current新Run及advanced Formal都能用各自正确保存组展示；新Link/Candidate固定完整配对；独立reviewer实际13键预览→具名T2→唯一Receipt/Audit/Outbox/真实false→true确认消费→原请求恢复→固定Review历史。Issue仍未effect/close，不授生产或真实专业资格。原private场景仍403或独立性拒绝，旧历史摘要保持。

受影响反例至少覆盖：Current推进使旧mapping不匹配；旧Draft Receipt冒充advancedFormal；source撤回/原件安全epoch改变；原 writer与当前caller互换/private peergrant；原参与者办理Review；缺方法/措施owner；opaqueproof跨reader/Session/main或nested UOW/结构SHA；末端IO跨expiry/issuer ABA；完整sources>20；T2已保存后重放唯一、不清UNKNOWN造新key。实际数据库/HTTP/浏览器与新旧源码冻结检查由Root集中，不把各包纯替身positive当实际职业或同事务通过。

来源按完整Artifact id/revision闭包计算，同版合法去重但全部SourceRef行定位保留。新场景可真实登记兼容专业事实在同一共享Artifact不同精确行以控制完整并集，不能截断到20、改旧private或删negative依据。独立reviewer必须从新场景创建起具备真实共享读取和当前该操作资格，并未参与执行；不提供前台自授切换。

## 并行归属与后续独立业务线

- A的新 `paired_output_bridge.py` / 自有tests：真实read/refresh/attest及固定owner组合；不要同时改公共dispatch或客户端caps。
- B的新typed applicability owner / 自有tests：实际配对方法/判据及措施履行/当前专业依据；缺callback明确503，不把客户端conclusion当owner事实。
- C：Root后续明确归属的候选选择/恢复UI、contract/test及原BFF route/test已交；其余父页和集中实际验证由Root统一。
- G1研究/OEM可独立复用已交 `domain/discovery` / `schemas/discovery` / `components/discovery`，新增真实scope/来源端口及薄API/命令宿主，Definition唯一写入仍留products；不依赖本波独立Review结果。
- 工程/制造正式变更实施与观察/制造良率可独立做真实输出/8facet缺图端口的缺项阅读，沿既有 `change_control` / `manufacturing_trials`纯包；没有效力/基线/真实分母不强算。公共迁移和正式批准按实际闭环汇合，不与本波争公共文件。

## 新 typed 端口与公共接线定向复核

A 的冻结 LivePairedOwner 实际 `read/refresh` 返回真正 ServerPairRead，read identity 注册只用于防克隆/篡改，不缓存正向资格；完整 binding 与 material 都进注册摘要。`attest`重新核纯结构后读取真实父 Formal/Run/fact/projection保存行与整组、原签发人的 retained 专业快照和当前 Principal/Grant、当前 caller/Project，实际原件字节/完整 source closure、自然窗口结束后的 retained 执行以及全部测量和固定 Projection规则。字节之后再独立重核同一批 Current/rows/来源/专业/retained/numerical；最后 caller/signer SQL完成后采 fresh clock并核最早期限/UOW/runtime。opaque gate 的 issuer、Session、主/嵌套事务、caller、scope、结构全文 SHA均被上层 paired核验。没有以纯结构、产品Grant、旧Draft Receipt或read registry代替真实 gate，也不生成占用/消费。

原专业签发人的历史时点核对通过 `front._recheck`内部构造该真实 signer Context，和当前消费者 Context独立；不把当前 reviewer 当原 Run writer。planned路径单独读取当前完整资源事实及未来生效/期限边界；performed路径保存原 Start/已提交占用与使用，不能以窗口已结束删历史。该 gate仍不是独立 reviewer、适用性、Observation完整或本次 T2消费证明。

B 的实际 `ActualApplicabilityOwner` 已读取：真正 Current ActualMethod、对应不可变 Batch及共同保存组/固定父 Formal、真实 sample/actual configuration、原固定item与 Rule的 typed Method/Criterion；caller的文本不是方法适用 owner。动作链重新读取原完成 Issue组、严格9键实际完成事件、原来源全文及 saved classification、当前受控 classification profile；缺正式 implementation owner时非unknown action明确拒绝，默认unknown不冒充履行。最末两次完整来源闭包、late pair/action/current Rule/Issue/政策/专业/Project/Grant/UOW/runtime均保留。B最后补入结果纯构造后再核真实期限/UOW；最终代码/测试/合同已收到冻结SHA并与实际读取字节相符。未发现这次定向范围内新的明确放行缺陷，仍不把纯替身positive称实际资格通过。

Root新增公共 `capa_review_context`先核 selected Candidate原固定anchor与当前Issue CAS、完整failure coverage且至少有mapping、同Rule的真实registered Observation、参与者独立性、实际performed pair与mapping，再给whole options/readset；这些是准备材料，不生成用户结论。`fact_context`只在这组实际检查成立时开放该行 review准备，0mapping选项仍只能读历史/缺项，不能通过选项存在授予能力。末端重复完整review读后精确比较 basis/sources/reads/deadline，Current/caller/Project/runtime保持实际核。

本次发现并已通知Root、在最新读取源码确认窄修两处：

1. 初版 pair choices仅取 `item.criterion_source`，遗漏定量 `item.criterion.source`，使前端whole引用提交后无法满足B精确核。现 `capa_review_context.py`对定量/定性分别取原真实引用，没有重造定位。
2. 初版 GET末端未把第二次 `fresh_review.valid_until`纳入最终期限，可能在末次Scope/Grant IO越过参与者或paired证明期限后仍显示可准备。现 `capa_fact_api.py`在末次 `require_access`之后采最终时钟并核该deadline、rule/authority/policy；写入inputs/preview/execute守卫未放宽。

API startup注入同一个实际 paired owner给 NamedReview与applicability；缺action履行宿主保持拒绝/未知。Current Run和advanced Formal option独立dispatch仍须Root/A按最小正例统一联验；此报告没有读取真实HTTP或声明该场景已经办理。

## 已交前端选择与原请求恢复增量

Root冻结公开 GET只允许必填唯一Issue UUID及可选唯一candidate UUID。实际 Host必须含 candidate_options，每项完整 MaterialRef/真实label/mapping_count/受众；无选择返回candidate=null，前台不按时间、行序或mapping_count猜候选。显示Host的product/caller/issue必须与组件scope对应，selected完整ID/revision/SHA必须等于返回candidate及实际选项。只同scope版本/SHA不一致是读取冲突而不是权限撤回，保留原pending；真正401/403或scope错才清私有材料。

选择框在任何 read/inputs/preview/execute/成功后刷新busy以及pending（包括UNKNOWN）期间锁定。用户明确切换才读新的candidate，未发送form/preview作废；完整原Command/key/token/readset没有改变。重载后先核真实无选择Host，再从已验证 `restoreFactLocal` 的原pending NamedReview恢复其**原明确完整候选**，第二次GET成功前不暴露无candidate中间Host；这不是普通draft或最新候选自动选择。普通网络失败保留原请求和只读重试，savedReceipt仍优先于后续刷新失败，不重发已保存业务。

read callback不依赖selected状态或产品revision，每次用户选择和原pending恢复明确发读取，避免 `setSelected`触发额外冷读循环。原内存UNKNOWN和本机原请求恢复语义不变。BFF仅扩大该GET的candidate_id唯一UUID查询，没有扩大路径/操作/权限、自动重试或改写请求体；原600秒总期限/undici headers/body、单fetch、no-store、redirect:error及业务POST一次读取保持。

C检查范围：v2实际29 helper通过、3受影响文件局部lint零错误/警告、5 owned路径定向类型检查通过；BFF两源码v1之后未变，原30个实际handler VM纯检查日志保留，不累计成新的浏览器或公共联合数。源码/命令/历史见 `ui-selection-source-manifest-v1.json`与`ui-selection-source-manifest-v2.json`。未运行公共build、实际HTTP、浏览器、PG或A/B用例，不把纯替身positive当实际职业资格/同事务通过。

## 实际读取身份与剩余核验边界

以下SHA是本报告最终追加时实际读取字节；Root公共源码仍可能正在冻结收尾，表中身份只覆盖这些字节。领域部分为只读静态复核，前端独占部分的实际pure/type/lint见上文独立日志。

| 实际路径 | SHA256 |
|---|---|
| `pdos-next/server/pdos_next/paired_output_bridge.py` | `b482e06700c602c96fe422448a80a200121119dcd6b188be82b15ea4c219468d` |
| `pdos-next/server/tests/capa_effectiveness/test_live_paired_owner.py` | `f09fa9d8f8288df6ac2a3999f04f169aba577c0ebb8fa99817921be703bb46c5` |
| `docs/reports/evidence/pdos-next-wave19-20261003/paired-owner-contract.md` | `3166931a8b18f9cb0b81e5ea43f7071b2cd72a9c1b58b92b0dc9a918c367500f` |
| `pdos-next/server/pdos_next/capa_applicability_owner.py` | `a493490f3f860ef18bced0d82218884f3d20e57246897ccce906e81623afc208` |
| `pdos-next/server/tests/capa_effectiveness/test_actual_applicability_owner.py` | `bfc88ad06e6d7ec8378192fc59a911c2cccaea0169d66ba9972406f5cf7f8ee8` |
| `docs/reports/evidence/pdos-next-wave19-20261003/applicability-owner-contract.md` | `b40bcb676c2066c455be0f952b8dfea81aa5ada23c6fd11c00918e116021fca7` |
| `pdos-next/server/pdos_next/capa_review_context.py` | `e8358ae188c7b3a6d021f26bcc794626f3220b4d2f3254db356702d603348563` |
| `pdos-next/server/pdos_next/capa_fact_api.py` | `a153c10ec463c737bec7bac1c270582ce86bbb94de4c3e5040553adc29d279ec` |
| `pdos-next/server/pdos_next/capa_fact_owner.py` | `d9e750e17a1441e2b7552d6f3f35b417fe8db9d0716bd6b471f0353758996551` |
| `pdos-next/server/pdos_next/api.py` | `dcadfe73d38349a26748ada81fd688ec532b3871abdc08e28d01a1cd1137f46f` |
| `pdos-next/server/pdos_next/quality_followup_integration.py` | `f992619f1e9c9fab369794f3acb0b8182395ce64557985711e2c6aec0e7fabd6` |
| `pdos-next/server/pdos_next/quality_followup_views.py` | `2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3` |
| `pdos-next/server/pdos_next/domain/capa_verification/service.py` | `77bef966e6d3623ab6199400c612f08b3ab0b36da214483b68ef61889c3cd152` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/named_review_owner.py` | `ca6c235254dbc25e140bdaa4876063a2e00a7fabad59809b1c27a3dd20c7ce6a` |
| `pdos-next/web/src/components/capa-effectiveness/fact-panel.tsx` | `f8e2a86ae785334d887ebc3057d06aee92c9f2e8571f80130503dbe77c257e69` |
| `pdos-next/web/src/components/capa-effectiveness/fact-workflow-contract.ts` | `5de761366993a1f7ae381ad85dee1033a0e8462e0d316f6cc444b0c3230bdb3a` |
| `pdos-next/web/src/components/capa-effectiveness/fact-workflow-state.test.ts` | `34ed47bb516fadf6c9b99e217d351be034d53b334ab49711adcadce6b34bc7bc` |
| `pdos-next/web/src/components/capa-effectiveness/fact-workflow-state.ts` | `748754be30a1fc7047877f1441ac7b60b6ed4849940e1bd0b8c81f25d75c9959` |
| `pdos-next/web/src/components/capa-effectiveness/fact-workflow.tsx` | `320fc294b79fd6043100945ecef256054df2d4b3f140af595edf25264c2825e1` |
| `pdos-next/web/src/app/api/[...path]/route.ts` | `ea9eae767bc2c1a1a488574441db9b3918dd3b1ee4b3e2d2b952dbc4f52b6fb5` |
| `pdos-next/web/src/app/api/[...path]/route.test.ts` | `a935da7f1c5498c513c6033a7406b59f7b9ee93ad64856d9454a70dd8044898d` |

A公布的24项、B公布的43项是各自无连接替身 pure 范围，本报告未运行或累计。C实际29项helper与原BFF30项日志各自绑定候选，不代表共享场景T2/同事务/浏览器通过。下一步由Root完成actual Current Run/advanced Formal dispatch、新合法共享场景、完整业务预览与实际NamedReview保存/重放；专业措施履行真实端口仍缺，effective/close保持未知/禁办。
