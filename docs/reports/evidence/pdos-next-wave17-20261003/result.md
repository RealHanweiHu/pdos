# 第十七波 · 独立有效性事实与候选公共接线

本轮已完成候选T1的限定本地合成闭环：实际保存、UNKNOWN保留原请求、按原command/key恢复回执、固定历史回读及最终页面刷新。公共仅登记辅助 `quality.capa.verification.candidate.record`（T1）。CLI候选在v7用原完整请求取得同一回执；浏览器单次确认保存第二份候选，随后恢复原回执，最终web v6刷新后仍展示两份候选。[最终检查点](candidate-final-checkpoint-v1.json)绑定341份运行源码、154份web源码及[实际浏览器记录](candidate-browser-v1.json)，数据库仍只有原两份候选，没有第三份。

[存储核对](closeout-v1.json)确认两份候选各自唯一Receipt/Audit/Outbox及原key、完整17条读集、13键预览证明、真实消费/保存/到期钟顺序、indeterminate与三个显式NULL，Issue仍为v6。最终页面逐一展开对账，候选/回执ID与该核对一致，UNKNOWN恢复按钮和确认弹窗均消失；保存状态在最终版本reload后保留，显式GET刷新成功后新表单解除读取锁。[最终页面](candidate-saved-final-v6-overview.jpg)可供审阅。

`next_0026` 的25→26→25→26及schema检查已完成；[迁移最终核对v3](public-migration-closeout-v3.json)确认111表生命周期目录覆盖、新五表强制RLS/启用引用门栓、Agent直接权限0，原106表在迁移checkpoint的全行摘要保持。业务保存后的[存储核对](closeout-v1.json)另确认所列24张旧业务表全行摘要保持，并核111表Agent直接表/列写权限0；这是两个不同checkpoint与范围，不是保存后全库111表不变或整树联合通过。

候选只保存原完整锚、真实不完整材料及indeterminate/三个NULL；七owner、Rule发布/Observation/具名Review、有效性和关闭尚未接通，不授真实资格或G3出口。唯一活动状态见[清单](../../../../tasks/ai-native-integrated-todo.md#pdos-next-queue)，当前公共范围见[施工合同](../../../design/2026-10-03-pdos-next-wave17-staged-implementation-contract.md#当前公共接入范围仅候选t1)。第十六波实际回链及九项分代替代影响检查保持其原范围，见[上一波结果](../pdos-next-wave16-20261002/result.md)，不冒充本波整树联合通过。

| 可复用交付 | 已有证据与准确范围 | 当前缺口 |
|---|---|---|
| 稳定原材料/有限两次后继与真实Formal/Run配对 | [首段源核对](root-staged-integration-observation-v3.json)、[配对读取61项](root-paired-storage-source-check-v1.json)；原history、失败、源及固定execution保留 | 七owner、有限Current后继实际授权与两个分别T2尚未接通 |
| Rule/Observation/具名Review与body/真实存储读取 | [facts v2 88项](root-facts-source-observation-v2.json)、[body 38项](fact-storage-final-check-result.json)、[原子组20项](root-fact-atom-storage-result-v5.json)、[Current 51项](fact-registry-final-check-result-v2.json)、[原完成53项](anchor-storage-check-result.json)分别冻结；[组合复核](facts-registry-integration-review.md) | reader仍不授当前来源/参与者/专业/适用/观察七门禁；这些事实尚无公共办理 |
| 五表/原子SQL与生命周期 | [迁移closeout v3](public-migration-closeout-v3.json)绑定实际upgrade/down/up/schema日志、111表目录和原106表checkpoint；[SQL病例v2](candidate-actual-sql-checks-v2.json)19项为v1的3项复用加v2的16项实跑，全部回滚后111表摘要保持；[回滚DDL v2](root-actual-ddl-rollback-v2.json)保持此前独立范围 | SQL复制材料/守卫病例不是真实专业资格或完整公共业务测试；迁移完成不等业务发布 |
| 候选固定请求/完整保存组 | [严格语义63项](candidate-command-final-check-result-v1.json)、[存储53项](candidate-final-check-result-v1.json)、[独立读取复核](candidate-storage-independent-review.md)；[真实存储核对](closeout-v1.json)与[最终浏览器](candidate-browser-v1.json)确认两份候选及回执匹配、恢复后没有新候选 | full SHA不由binding/inspection替代；固定存储回读不授七owner当前资格 |
| 实际原失败/source owner | [业务只读v2](anchor-actual-business-readonly-v2.json)：62513/app，origin/current6、1原失败、16源、5561 SELECT/14.08秒；保留原锁、零业务DML/flush并rollback | 该读取不授本次专业/观察/独立验证/消费；后继仍需真实有限谱系owner |
| 公共prepare/首锚恢复/同事务writer | [public prepare/write v2](candidate-write-prepare-check-result-v2.json)18项、[v2源清单](candidate-write-prepare-source-manifest-v2.json)、[正向atom结构审阅](public-candidate-atom-shape-review-v1.md)；13键持久预览恢复原full锚，全部IO后独立当前源/专业/政策重核；真实保存组另由[closeout](closeout-v1.json)核对 | 18项本身使用禁连接ORM/UOW及显式source/owner替身，不与真实存储检查相加或授资格 |
| 公共薄服务与消费接缝 | [薄服务26项](candidate-service-check-result-v1.json)、[接线合同](candidate-service-integration-contract-v1.md)及[common v2 29项](candidate-common-validation-check-result-v2.json)；actual module/strict Payload，False→True后首行捕获真实消费钟，最后writer独立刷新 | 各代源码与检查分别绑定，29项为无DB的实际common/ConsumptionHost与显式owner/SQL替身，不是整树联合或性能证明 |
| 固定输出与当前办理权限分离 | [fixed-output 85项](link-fixed-output-no-ui-authority-delta-v1.json)与[front 14项](front-fixed-output-check-result-v1.json)分别核窄接口：固定parent/真实Method/Window来源闭包保留，仅省未来命令UI能力计算 | 不把当前子事实/来源/专业重核删去，不相加为99项全树验证或真实资格 |
| 公共候选界面与BFF | [原helper/TS/lint范围](public-candidate-ui-check-result-v1.json)、[界面v2局部检查](public-candidate-ui-check-result-v2.json)、[最终web v6](web-build-result-v6.json)类型/lint/build exit0且[154份源码](web-candidate-source-v6.json)稳定；[候选传输59项](candidate-transport-check-result-v1.json)含55项真实route VM/4项短合成socket，实际页面见[浏览器](candidate-browser-v1.json) | 短socket不冒充真实600秒请求；未实际浏览器撤权；320px设置未生效不计通过。[BFF v2](candidate-bff-wait-v2.log)测试数0不计通过 |

各行是独立分范围证据，重叠检查不相加。暂存文件及原代manifest保持；公共namespace的import转换、新注册与JSON修复依实际各代证据绑定。

## 实际保存与恢复范围

[CLI HTTP v6](candidate-actual-http-v6.json)的inputs/preview/save均200，save响应耗时569.399秒；其后原键回放180秒ReadTimeout，整次报告保留FAIL，不能据超时判定未保存。[HTTP v7](candidate-actual-http-v7.json)原完整请求回放200、182.773秒，返回同一Receipt且响应SHA与v6保存响应完全相同；saved GET为200、129.222秒。v7绑定[341份运行源码](candidate-actual-http-source-v7.json)，source_stable=true；该恢复证明CLI原请求，不替代后来的浏览器请求恢复。

当前candidate-only延后首次validate只用于未命中新写：key命中、语义Receipt命中仍先完整当前重核，再冲突/返回/alias；新写由实际prepare_write独立核所有源/Current/调用者/专业/政策后才消费，消费后writer再次完整刷新，不跨phase缓存。[29项common纯检查](candidate-common-validation-check-result-v2.json)绑定这一变化。v6绑定原common版本，其569.399秒不能标成延后validate版本的速度。

新UI v5单次保存点击为`2026-10-03T14:36:01.084Z`，数据库核实第二候选保存钟为`2026-10-03T14:42:49.740097Z`；408.656秒是**点击到存储的时间**，不是HTTP回执耗时，不直接与v6旧版本的HTTP569.399秒计算加速百分比。[closeout-v1](closeout-v1.json)确认该候选已保存且未推进Issue/旧Run/旧占用。UI先显示UNKNOWN，保留原完整command/key；`14:48:03.442Z`只点击原请求恢复，`14:51:14.685Z`观察到已取得候选回执，`14:55:51.670Z`已读到两份固定历史。未再预览、生成新key或确认新候选。

实际Node25.8.1内置Undici7.22另有300秒header/body独立上限；旧UNKNOWN没有捕获具体cause，不唯一归因。[窄修](candidate-transport-fix-v1.md)固定显式undici7.22.0，仅候选命令opt-in同一个600秒header/body Agent，600秒总体Abort、同源/会话、原文单fetch、无重试、redirect:error/no-store保持，其他操作不带dispatcher。59项受影响检查包含真实短合成headers/body先于Abort拒绝、实际helper允许1.5秒等待及总体Abort仍生效；不是600秒实际业务请求证明。原55项stub与此次55项route范围重叠，不相加。v6已构建、重启并实际GET回读；没有再制造一次长新写来冒充本次验证。

最终web v6 `14:57:13.842Z` reload，`15:02:15.493Z`已显示两份历史且从本机恢复保存回执。恢复后的新表单先要求一次显式只读刷新；`15:02:42.405Z`点击内层“重试读取当前事实”，`15:05:19.085Z`观察成功，回执仍保留、表单可编辑，没有新业务写入。1280px亮/暗截图均保留，宽度与scrollWidth相同；320px viewport请求未改变实际1280px，已reset并恢复原亮色，不记手机验证通过。动态权限撤回后的父级清理与迟到回执只做[独立静态审阅](candidate-parent-access-review-v1.md)，本轮没有真实浏览器撤权场景。该审阅绑定v4父源，v5只改缺项文案，v6仅传输/测试/依赖窄修，父级与候选组件未再改。

保留的原错误与修复范围：

- [实际DDL v1](root-actual-ddl-rollback-v1.json)的driver ProgrammingError后由[DDL v2](root-actual-ddl-rollback-v2.json)在单回滚事务安装/撤销核对，未把v1记通过；[实际anchor v1 driver失败](anchor-actual-business-readonly-v1-driver-failure.json)发生在owner读取前，由上述业务只读v2单独替代。
- [public迁移v1](public-migration-result-v1.json)在步骤前KeyError；[v2](public-migration-result-v2.json)的四步实际均exit0，但postcheck把旧表物理列序当合同而标FAIL。v3只校正postcheck、绑定原四步日志，不重复迁移；按实际列名/类型核对，记录11表物理列序差异，原106表全行摘要保持。
- public review/row的DTO tuple不能直接写默认JSONB。仅把sources/readset逐元素转完整JSON数组，保原序/字段，不改通用json_value或领域规则；18项owned检查真调用writer并对13键review/所有JSONB列/扁平回执作无default=str的json.dumps。新增case两次ORM夹具状态失败原日志保留在[v2结果](candidate-write-prepare-check-result-v2.json)，不作生产或PG通过；原[v1 17项](candidate-write-prepare-check-result-v1.json)保持。
- [表单v1/v2范围/lint历史与v3冻结](candidate-form-source-manifest-v3.json)、[public界面原错误及最终分范围检查](public-candidate-ui-check-result-v1.json)、[SQL未应用独立复核](fact-sql-unapplied-independent-review.md)及[模型索引修复](fact-storage-index-ddl-v2.sql)均保持原代与限制，不覆写旧失败。
- [SQL病例v1](candidate-actual-sql-checks-v1.json)原fragment断言错误与[诊断修复](candidate-sql-tool-diagnostic-fix-v1.md)保留；v2明确标出3项复用，16项由新运行实际执行。19项中含一项合法完整SQL组，不把全部统称为拒绝负例，不将v1/v2叠加计数。
- Root首次worker回读误用`outbox/inbox`表名，在读出选定证据前UndefinedTable并rollback，保留[诊断v1](candidate-worker-ack-v1.json)。[v2](candidate-worker-ack-v2.json)只改为实际ORM目录的`outbox_events/inbox_deliveries`Core SELECT，无业务/迁移变更；两条候选事件均已投递、Inbox=ignored、workflow_id为空。worker已恢复；候选只走通用事件接收，没有专业核验/effectiveness workflow，不据异步投递变更宣称旧全库摘要不变。

## 最终检查点与剩余工作

| 项目 | 本轮结果 | 保留边界 |
|---|---|---|
| 浏览器原请求恢复 | [记录](candidate-browser-v1.json)与[最终检查点](candidate-final-checkpoint-v1.json)：两份候选/回执逐一匹配、saved在reload保留、显式GET后解除读锁、无UNKNOWN/额外确认 | 未导出浏览器原命令/token或完整网络响应；UI保存属于v5，最终v6新增的是只读回读 |
| 长请求transport | 59项受影响检查、v6类型/lint/构建通过；341运行/154web最终源码稳定，预览已用v6 | 原UNKNOWN cause未捕获；短合成不替代实际600秒新写验证；320px未生效不计通过 |
| worker与事件投递 | [实际ack v2](candidate-worker-ack-v2.json)：worker恢复，两条候选事件均delivered/ignored、无workflow | 通用接收，不触发独立核验/有效性/关闭；投递状态已合法改变 |

候选T1限定闭环已收口，原CLI v6超时、各代失败及分范围证据保留。下一业务接线为可信Rule出版→本人T1实际Observation→独立本人T2固定Review与七owner当前回读；可并行的写入、真实依据owner及前端文件归属见[交接与20条来源预盘点](next-professional-loop-handoff.md)。最终只读核对确认Rule/Observation/Review及两个Current五表仍为0行，尚未制造专业事实。候选仍indeterminate，七owner、真正规则、实际观察、具名复核及两个分别T2未接通；不扩大旧private受众，不改变原Run/占用/消费，不授真实资格、G3或人工Exit。本文件汇总限定证据，不替代唯一清单，不声明本波整树联合通过。
