# G3.1 Issue/CAPA 首版接入合同

本包只有独占的 quality_issues 领域、schema、测试、组件和本证据目录。TestRun/Measurement/Sample/ActualConfiguration 的权威仍是品质/共同对象；未注册公共ORM、迁移、命令、API、BFF或父页面，没有第二个确认/回执入口。

## 可调用入口

`QualityIssueHandler(Ports).preview(operation, subject_id, expected_revision, payload)` 做实质规则核对，返回固定失败范围、所有问题版本、服务器政策、差异和读集摘要；不 begin/consume/record。规则拒绝使用标准 DomainError（503 INTEGRATION_REQUIRED、403权限/资格/具名/独立性拒绝、422缺失败事实和封闭载荷、409版本/重核/状态冲突）。

`execute(Invocation,payload)` 验证专用载荷及 semantic_digest → 主线 begin → 当前授权/取消/资格 → 原意图回执重验或重新准备 → 主线共同 confirm(T1/T2) → record。T0也须真实操作资格和当前授权；合成测试资格不是生产资格。Invocation是本地adapter DTO，不是第二套HTTP信封。主线仍检查公共 Product revision，领域wrapper另外携带 Issue expected_revision。建单 subject_id=权威Run ID、expected_revision=0，其最终Issue ID由scope+稳定失败身份确定性生成。

`QualityIssueReader.get(issue_id)` 从服务器认证context读取问题，逐项核验受众、固定失败当前性及精确归档Run。原值只在可访问/当前且归档固定版本完全匹配时从TestRun映射，不持久化第二份测试结果；失效行只有固定引用与原因。读模型还对根因、假设、措施发生时间、当前效力/关闭依据核验当前性，在持久失效标记尚未传播时已返回current=false和recheck_reasons；主线应将其映射为前台待重核。持久来源变化传播应对接受控重核动作，不绕过T1证明。读模型另返回全部 alias 原问题历史和后续工程变更评估/新Run需求；不创建ChangeRequest/Order/Build/Run，不继承或补造批准。

## 操作与注册

| 操作 | 封闭 payload | 等级 / 领域事件 |
|---|---|---|
| quality.issue.create | IssueCreate(run_id,measurement_id,event_id,title) | canonical T0 / issue.created，仅首次实际建单 |
| quality.issue.merge | IssueMerge(sources: Ref[],reason) | canonical T1 / issues.merged |
| quality.capa.draft | CapaDraft(capa_id,hypotheses,actions,requirement) | canonical T0 / capa.drafted |
| quality.capa.effectiveness.decide | EffectivenessDecide(result,text,evidence_ids) | canonical T2 / capa.effectiveness_decided |
| quality.issue.triage | IssueTriage(reason) | **拟注册** T1 / issue.triaged；risk从policy取得 |
| quality.issue.containment.record | ContainmentRecord(action) | **拟注册** T1 / issue.contained；当前执行人本人 |
| quality.issue.root_cause.decide | RootCauseDecide(text,sources) | **拟注册** T2 / issue.root_cause_decided |
| quality.capa.actions.complete | ActionsComplete(completions) | **拟注册** T1 / capa.actions_completed；当前执行人本人 |
| quality.issue.recheck | IssueRecheck(reason) | **拟注册** T1 / issue.recheck_recorded |
| quality.issue.close | IssueClose(text) | **拟注册** T2 / issue.closed；有效性复核人本人 |

除四个canonical动作外，只交付registry候选，须主线明确专用合同/政策注册后才暴露。本包没有变更canonical等级，也不授T0/T2资格。

## 稳定失败、事件与归并

稳定身份绑定 tenant/product/project、Run ID、具体Measurement ID、Sample ID、测试项ID和判据原出处固定版本；event_id、命令ID、标题和Run无关revision不构成新失败身份。样件/实际配置、方法、测量出处版本固定在FailureRef；source revision只作当前性重验，纠正/撤回需原历史与待重核，不能覆盖测量。原测试执行者也在固定引用中，用于独立性判断。

必须消费权威TestRun：已有actual_start/execution、Run result fail，按verification.compute_results复算所选pair为fail，且与权威computed_result逐项一致；测量不得早于actual_start或晚于actual_end，最终状态须保留真实结束/返回事实且返回不早于结束。planned、pending、indeterminate/unknown、invalid、空结果、无数值出处或配置不完整均拒绝；一个Run同时含pass/unknown时，仅确定fail的具体测量可建单。

事件投递去重和业务失败去重分开：RunPort.delivery核验真实持久事件确实包含该Run的测量/判据；同一事件允许多个失败，投递映射唯一键为(scope,event_id,failure_identity)，稳定失败唯一键为(scope,failure_identity)。不同event/key/title仍映射原问题。已有失败且无变化只增加必要delivery/回执，不再发issue.created（Mutation.event_name=None）；来源变化时原单增版标重核并发issue.recheck_required，原FailureRef保持。

归并必须一次实质确认、同精确scope、相同受众集合、未进入整改/具名根因/CAPA且未归并的open/triaged问题。禁止自并、版本冲突、重复失败、受众扩大；不使用标题相似度。目标保存失败并集与全部alias、遏制并集，原单不删除且原状态/全部事实/历史保留，只追加merged_into与操作历史；目标标待重核并重新取聚合风险。已有整改/结论冲突显式拒绝，保留独立办理。by_failure必须解析alias链到当前主问题，不覆盖原身份映射历史。

## 状态与专业责任

open→triaged→actioning→awaiting_verification→closed；遏制是执行记录，CAPA是假设和措施候选，根因结论是独立具名T2。全部措施完成只进入待验证。CAPA包含精确失败范围、方法、验收条件和观察截止；根因假设不能填入具名结论，AI不能决定根因/有效性/关闭。

有效性依据由PolicyPort读取具名审核的新Run/观察记录：绑定本次requirement_digest、精确全部失败、固定新配置适用性/来源、服务器nature、实际观察起止。观察开始不得早于全部措施完成；观察结束覆盖要求且不在未来。原失败Run不能自证整改，合成与真实依据不可混用，未知不决定有效/无效。措施执行人、原/新测试执行人、遏制执行人和根因决定者不能担当独立复核/有效性决定。高风险或服务器独立政策要求证据复核人本人决定；关闭须有效性复核人本人再次T2，重验同证据/政策摘要。

每次有效/无效决定完整追加effectiveness_history，latest decision另外指针，不抹除原失败决定。新来源/配置/政策影响判断时阻断新操作，IssueRecheck记录原因；历史关闭不被重写，失效后的当前适用性独立标重核。没有默默自动关闭或重开。无效仍待验证；追加措施/CAPA修订的专用动作尚未实现，后续需主线版本化注册，不能篡改完成记录。

## 主线最小ports和共同事务

| Port | 实际适配要求 |
|---|---|
| CommandPort.context/begin | 认证/run绑定Scope/actor/职责/audience/授权/资格/取消/aware now；不得从payload取这些事实。begin锁稳定意图与业务目标，key载荷冲突先拒绝。 |
| CommandPort.replay | 持久精确意图和原读集，跨请求key只重用同一合法业务意图；重验当前授权/来源ACL/取消/受众，不永远合并相同载荷。handler额外检查当前Issue权限/当前性。原回执重放不再次消费proof或写历史。 |
| CommandPort.issue/by_failure | 租户/产品/项目scoped读取与锁定；by_failure先锁稳定失败身份，解析归并链；Merge按一致ID顺序锁全部原/目标Issue。 |
| CommandPort.confirm | 复用共同一次确认/T2具名证明，绑定操作、actor、scope/audience、专用payload、目标/全读集版本、policy、preview digest、有效期和取消。无token/过期/编辑/来源漂移拒绝；同事务原子消费。 |
| CommandPort.record | 全Issue CAS；insert_ids只新增，不upsert；稳定failure/event-pair唯一约束和alias链/历史完整保存。同Session写领域、Inbox delivery、唯一ActionReceipt、Audit、必要Outbox；所有proof、事件映射、写入一起回滚，不自行commit。无changes且event_name=None不发重复业务事件。resolve所有executor/assignee当前成员/可承接责任，提名不授予权限。 |
| RunPort.fixed/original/delivery/currentness | 品质模块唯一结果所有者。fixed锁当前实际Run并核验原值/资源/来源，planned Build不可冒充真实；original读精确归档revision不替换最新；delivery验证源事件；currentness只对精确测量/判据/方法/样件/配置/出处变化重验，无关Runrevision不失效。权限撤回raise，撤回/修正/配置漂移返回current=False和原因。 |
| EvidencePort.check/currentness | 原件版本、位置、真实内容及用途/受众/ACL/撤回/过期；currentness区分失效原因与撤权异常，不能用no-op。 |
| PolicyPort.assess/verification | 当前风险/独立验证政策来源和版本由服务器决定；verification返回可信具名固定新结果，requirement_digest、全部原/新执行者、实际观察窗口和适用性由专业权威适配取得，不能接受客户端bool作为资格或有效性事实。 |

各port必须共享主线同一事务，不开启跨库事务，不等LLM/网络，不自行commit。record抛错必须使proof消费、所有对象、Inbox、审计、回执、Outbox一起回滚。测试fake展示回滚契约，不能证明真实DB事务已接好。

持久化建议由主线统一决定：Issue聚合+immutable revision/history、stable failure map、event/failure pair map、merge alias/history、Containment、CAPA/action/requirements、具名root/effectiveness/closure决定。保留scoped FK、positive revision、CAS、insert-only ID、每稳定失败一个canonical issue、无alias循环、具名来源和合成/现实性质。TestRun归档revision和原Measurement引用由品质模块保存，本包不创建第二份测试结果表。

## 前端接线

组件消费真实IssueReading、权威Run失败投影和server capability/context；`onPrepare`对接共同预览/实际T0资格流程，`onConfirm/onResolve`消费主线共同ActionReceipt状态，组件不生成proof、不消费token、不储存成功业务实例。权限/来源/配置/政策变化须更新context.key；失权/切换scope时主线还须清空旧读模型和旧预览，不能只更换key而保留先前敏感数据；编辑和范围漂移禁旧预览，unknown只允许核对原回执。缺port/未注册动作禁办理，具名T2入口禁AI。

camelCase→封闭snake_case DTO映射详见ui-integration.md；SourceRef.status只展示，提交时剔除状态；FailureRef中的原值是RunPort只读投影，不上传为新测试事实。Measurement没有独立revision，UI显示的VersionRef revision必须来自所属固定Run版本；CAPA无独立revision，UI revision来自Issue聚合版本，不伪造独立实体版本。context draft IDs只作当前候选身份，服务器仍insert-only并验证意图。后续需求不得编造Change/Build/Run ID。

## 联合验收留给主线

接线后至少覆盖并发同失败跨key只落一单、同event多失败不漏单、两单并发归并/CAS、来源/ACL/config/policy漂移、proof过期/取消、record故障全回滚、真实固定Run原值读取、T2独立复核与闭单、历史决定来源撤回、HTTP与浏览器亮暗/窄宽/键盘/unknown回执恢复、迁移往返/RLS相容。不把本包纯合成检查相加为G/N/P/Q联合验收。

当前实库TestRun、事件、归档原值、资源/资格、政策和共同事务adapter尚未接入；真实办理明确待接。不连接DB、不读.env/.local/凭据、不启停服务、不共享构建，不做外发/模型/云/生产/提交/push。
