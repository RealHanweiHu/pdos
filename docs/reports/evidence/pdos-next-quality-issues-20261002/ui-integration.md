# 品质问题 / CAPA 前端独立交付

本包只写 `pdos-next/web/src/components/quality_issues/` 和本目录 `ui-*` 证据。`QualityIssueWorkbench` 提供问题阅读、精确失败建单、归并、遏制、根因、CAPA 和有效性办理；`QualityIssueReading`、`FailureReading`、`QualityActionReview` 可分别复用。无页面、BFF、注册、共享 CSS、依赖或数据库修改，不调用网络、不保存 Measurement 第二份业务事实。

25 项显式合成纯契约/静态渲染检查与局部非 incremental/noEmit TypeScript、ESLint 通过，见 `ui-validation.json` 与原始日志；固定候选见 `ui-candidate.json`。这不证明 DB/HTTP/真实浏览器、联合 G/N/P/Q 或真实资格通过。类型检查首次发现夹具联合类型收窄问题，已在本包修复，首次原始输出保留为 `ui-typecheck-attempt1.log`。

## 主线接入方式

组件挂在主线已有客户端 workspace 内。受控 `Context` 必须来自服务器当前读模型：actor 是只读具名身份；capabilities 为逐操作、已注册且已核验权限/资格的能力投影；key 在目标版本、当前来源/配置、权限、风险/独立政策或读集变化时必须变化。组件不能从这个投影授予权限。没有端口、actor、明确注册或回调时显示未接入且禁止办理。

`onPrepare(intent, contextKey)` 接至已有主线预览/准备入口，绑定封闭载荷、固定读集与实际目标；组件没有独立确认、回执消费或持久命令引擎。T0 的创建/CAPA草稿仍由主线按当前真实资格与授权执行，主线可在 `onPrepare` 内直接完成并提供回执，不应为了复用组件另增一次 T0 人工确认。T1/T2 主线传入 `ControlledAction.preview` 后由 `onConfirm(preview)` 接既有一次确认/具名决定入口。

主线共享 handler 拥有 pending/unknown/错误/预览生命周期、单次消费锁和 `onCommitted` 刷新；必须在同步异常或网络失败时吸收异常并发布受控 error/unknown，不让回调 rejection 丢失。组件不重复调用 `onCommitted`，避免两次回执消费/刷新。确认期间及 outcome_unknown/缺失已提交回执时锁定新准备；`onResolve(preview)` 只能核对原动作，不能重发。未知状态缺原预览时组件禁止继续，主线须恢复原预览/token 与原回执查询。成功也只展示主线返回的实际回执。

修改输入会改变完整意图，确认前比较 canonical 意图与 contextKey，并检查到期、tier、具名身份、能力及阻塞缺项；不允许旧预览确认。服务器仍须重新核对并原子消费；UI 守卫不能替代安全或事务检查。

## 读模型映射

后端 `Issue`、`Capa`、`FailureRef` 映射包内 camelCase props。`FailureRef.failureKey` 必须是后端稳定 failure.identity；投递 eventId 独立来自权威结果事件；event ID 或无关 Run revision 不生成新的业务失败身份。`run`、`sample`、工程/制造/实际配置均解析真实固定引用。方法与判据映射 SourceRef 全部 id/revision/kind/position，并提供服务器当前性 status 和 criterionText 原判据。不能由标题推测来源。

`measurement.id` 是固定 Run 内的不可变测量 ID，没有独立 revision；rawValue/unit/conditions/result/runStatus 只通过权威 RunPort/TestItem 解析为阅读投影，保留原始精度，不写进 Issue 存储。Reader 在原来源失效/撤权时 measurement=None，UI rawValue/unit/conditions 映射 null，显示未读取/原值待核验，不读旧原值补齐；组件也主动隐藏来源非 current 或未经核验的旧原值。历史事实仍在权威存储保留，不因撤回抹除；独立许可的历史原件阅读需主线另行实现，本包不提供旁路。`serverVerified` 必须表示精确原值/来源已由服务端核验，synthetic 从 FailureRef.nature 明确映射，不得把合成资料混入真实业务页。计划 Run、不确定/未知/无效/通过、无测量或来源未核验都禁止从失败入口建单。

IssueReader 的 `current`/`recheck_reasons` 与持久 needs_recheck 合并到 requiresRecheck/recheckReasons，即使来源失效传播尚未落库也呈现待重核。撤回/过期的固定失败引用、原问题和具名历史保持；原始测量保留在权威存储，当前界面只显示已允许读取的值。retainedOriginals/aliases/history 需通过具备原受众权限的读取端口补齐，不能因为归并只保留目标卡片；本版归并表单仅接受相同受众的可见来源候选，服务端还须拒绝跨租户/范围以及任一原记录受众扩大。

根因假设投影到 hypotheses，具名 RootCause 独立映射 rootCause。Containment 是实际已记录动作，映射 state=completed，不能用草稿当执行记录。CapaAction.completed 从 completion 是否真实存在映射。CAPA 在 Issue 聚合中无独立 revision，UI `capa.revision` 使用聚合 Issue revision 作为显示水位，不创建第二个 CAPA 版本所有者。

verificationRequirement 的高风险、independentRequired 和 policy 均来自服务端政策；方法/接受判据/观察期来自固定 CAPA requirement，并映射为 description。effectiveness 及 effectivenessHistory 均映射具名决定，旧无效结论保留。actorLabel 必须解析具名 Principal，不能合成人名。independent、verificationRuns 与 evidenceIds 通过服务端验证依据端口解析；AI 或执行人自证不能产生独立=true。当前有效性与历史判断必须区分；最新来源/配置失效会阻断当前关闭。

Context.verificationEvidence 只列服务器当前可用的实际独立复验记录 id 和对应固定 Run；支持多证据选择，服务器核验完整失败覆盖、方法、判据、观察期与独立政策。draftIds 由主线预分配真实 UUID，用于草稿/新遏制身份，不取测试夹具或客户端 fixture。accountablePeople 由主线提供当前允许的具名执行人。

## 命令载荷映射

主线先依据 operation 选择封闭 DTO，IssueTarget 进入既有外层 subject_id/expected_revision，不作为 DTO 额外字段。SourceRef 仅序列化 `{id,revision,kind,position}`；UI status 不传入领域 DTO。

| UI intent | 领域 DTO 载荷 |
|---|---|
| quality.issue.create | `{run_id:runId,measurement_id:measurementId,event_id:eventId,title}`；UI failureKey 仅预览/核对，服务器从固定事实重算稳定身份。新 Issue subject_id 由主线分配与去重。 |
| quality.issue.merge | `{sources:sourceIssues,reason}`，固定所有来源 revision；预览 differences/preservedFailureKeys 来自服务端实质差异，不从标题推断。 |
| quality.issue.triage | `{reason}`；风险取服务端政策。 |
| quality.issue.containment.record | `{action:{id,text,executor_id:executorId,evidence,at:{occurred_at:occurredAt,original_timezone:originalTimezone,source}}}`；真实发生时间独立于系统接收时间。 |
| quality.issue.root_cause.decide | `{text,sources}`；具名人来自主线服务器上下文，不从 text/executorId 得授权。 |
| quality.issue.recheck | `{reason}`。 |
| quality.issue.close | `{text}`；只在 awaiting_verification、所有措施完成、当前独立有效性决定有效时可准备，服务端再次重核。 |
| quality.capa.draft | `{capa_id:capaId,hypotheses:[{text,sources}],actions:[{id,kind,text,executor_id:executorId}],requirement:{method,acceptance,observation_until:observationUntil,required_failure_ids:requiredFailureIds}}`。表单首版一次提供一个假设和一个措施，包含全问题固定失败范围，不声明完成。 |
| quality.capa.actions.complete | `{completions:[Containment]}`，一次记录一项真实完成，id 取已有 CAPA action；说明/执行人/发生时间/证据显式填写。 |
| quality.capa.effectiveness.decide | `{result,text,evidence_ids:evidenceIds}`，可选多条独立验证依据，主线具名 T2 处理。 |

只有 create/merge/capa.draft/effectiveness.decide 在 canonical 附录中；triage/containment.record/root_cause.decide/recheck/close/actions.complete 是明确拟注册需求，默认没有 registered 能力，不绕共同 registry。merge 固定 T1；root_cause.decide/effectiveness.decide/close 固定具名 T2，组件拒绝降低分级和 AI 办理。

## 必要集中验证与限制

主线须集成真实对象持久化、来源/受众/RLS/权限、固定结果投递、共同确认和具名决定、Outbox/Audit/Receipt 同事务。源撤回/配置变化必须更新 contextKey；effectiveness_history/aliases/history 读取需保留全部原记录和权限。联合检查覆盖并发重复投递/跨 key 同意图、精确失败身份、部分独立失败归并保留、来源撤权/配置漂移、独立性不满足、T2 具名/AI拒绝、存储端口失败导致全事务回滚、未知结果原回执查询。组件纯检查不证明这些已接通。

没有创建 ChangeRequest/ChangeOrder、新 Build/Run 或批准入口；只显示后续稳定引用或待对应领域办理。无真实模型/凭据/材料读取、业务资料外发、DB/云/生产/原件操作、服务启停、共享构建或 git 提交/push。已只读复核消费文件，摘要与漂移记录见 `ui-consumption-initial.json` / `ui-consumption-final.json`；后端新 schema 和 globals 是交付前首次记录摘要，未冒充此前冻结过的版本。
