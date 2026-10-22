# 第二十五波：正式变更与制造准备实际接入

本轮完成新工程的受控变更、制造准备后端与界面接入检查点。此前隔离交付的代码已进入实际运行源，实际数据库为 `next_0028`、122 张登记表；正式业务保存、完整复验和人工出口仍未完成。

## 已接入与复用

- 正式变更接入共同命令、具名审批、实施输出核验及读取端口，新增八张变更/政策/选择事实表。工程与制造双线仍各自核对范围、固定版本、来源和专业依据；没有实际新批准或实施记录。
- 工艺作业指导、控制计划、制造基线三个 T1 对象接入不可变续版、Current、基线文档链接与共同消费事务，新增三张表。界面复用产品/项目、固定工艺、现有确认和历史机制，private 上游不扩围，缺项与未确认资格保持未知。
- 复用第二十二波 CAPA 文本入口与原十个质量动作；公共接线由主线统一处理。制造定义读取发现真实 DTO 不含暂存假定字段，已改为严格核对实际 `sources`、当前状态和完整来源，而不是缺字段时置空。
- 共享案例 Issue Current6、Rule1、候选1、Observation0、Review0 和 A2 planned1 保持；未改写已过去的计划窗口，未新增 Promise/Start。新十一张表在所选共享范围均为零，历史保存不代表当前专业资格或来源有效性。

## 按影响验证的证据

| 范围 | 实际结果与限制 |
|---|---|
| 最终源 | [v3 源清单](actual-core-source-v3.json)登记 591 个唯一路径：运行/迁移380、所选后端测试42、网页165、工具4；冻结后逐一核对哈希。 |
| 后端纯检查 | 去重257项：原变更/公共109、制造116、API查询7、新定义闭包25。见[初始实际布局](actual-layout-pure-v1.log)、[查询夹具定向复验](actual-query-7-recheck-v2.log)、[定义闭包影响检查](actual-manufacturing-definition-recheck-v3.log)、[过期边界单节点复验](actual-expiry-definition-node-v4.log)。不是整树联合验收。 |
| 数据库迁移 | [最终核对](migration-final-checkpoint-v1.json)采用已完成的26→28→26→28及schema检查，四步退出均0；111张原表全行摘要保持，26/28整目录分别恢复一致。新十一表强制RLS/门栓，全部122表Agent直接业务写权限0。 |
| 结构与拒绝 | [实际PG检查](actual-pg-negative-v2.json)去重47项＝变更37＋制造10，其中2项目录检查、45项实际负例拒绝。13项变更真实业务原子组等仍待材料，不算通过；真实行RLS、正向消费/撤回竞争未验收。 |
| HTTP | [实际选集](actual-http-final-v6.json)13次去重观察：限定列表、未知/重复参数、跨范围及资格不足拒绝；制造inputs从实际500修复为403 `QUALIFICATION_REQUIRED`。三代记录的17张表全行摘要保持；最终只修计数解释，没有重发接口或提交业务。 |
| 网页 | [39项实际辅助摘要](actual-ui-helper-summary-v2.json)仅重解原39/39通过日志，不重复测试；原v1未保留子进程退出码，不补造退出0。[实际生产检查](actual-web-checkpoint-v1.json)的165份网页源lint、构建与类型检查退出0。 |
| 浏览器 | [实际界面检查](actual-browser-checkpoint-v1.json)独立标签中打开三种未发送草稿，320/1280宽、亮暗主题均实际读取且无整体横向溢出，console错误/警告0。原用户标签、主题及草稿保留。未发送预览/保存，不能据此认定T1业务闭环或真实UNKNOWN恢复通过。 |
| 原共享历史 | [实际只读回读](final-shared-fixed-state-v1.json)确认Issue6、Rule1及A2仅planned1，三个Current Run/五版本保留，十一新增表为空。 |

[独立只读证据审核](evidence-audit-v1.md)核对上述去重口径和591份冻结哈希，没有新增数据库、HTTP、测试或构建。[末端源与服务回读](final-source-service-readback-v1.json)确认同一冻结源和当前API/网页服务可访问；健康读取不代业务验收。

## 旧运行来源失效

旧质量页面实际读取失败，原历史仍可见，操作保持禁用。使用原确切具名人和原固定Run的[接口核对](old-quality-exact-actor-denial-v3.json)返回409 `SOURCE_STALE`；此前默认预览身份误配的结果保留，但不作为浏览器身份结论。

[权威实际只读诊断v3](actual-retained-diagnostic-v3.json)以与服务一致的已配置Engine为Session绑定，核对实际安全运行环境和两范围签发人配置；返回 `current=false`、原原因 `RETAINED_EXECUTION_CHANGED`。原资源摘要与当前摘要不同，当前bundle按原Start保存钟重核为READY、原预约存在，固定签发人key/范围/版本/nature/epoch匹配；仍不能由此认定“新增无关配置”是唯一实际原因，也不授当前开测或消费资格。诊断前后122张租户表全行摘要一致，外层回滚，原拒绝保持。

原[v2](actual-retained-diagnostic-v2.json)的Session绑定Connection，没有继承实际owner直接从Engine读取的配置；其SOURCE_STALE不能作为线上底层原因。[绑定纠正记录](retained-diagnostic-bind-correction-v3.json)明确取代该解释，保留其零写入/全行保持证据。首次[v1](actual-retained-diagnostic-v1.json)在owner调用前因登录表无`id`列预检失败；摘要排序和Session绑定分别仅在Root诊断runner修正，没有改运行源。未按错误子因继续执行来源basis探针。

## 原失败与修复边界

迁移28回退LOCK语法已在实际迁移中修复；原回退失败保留。目录复核发现旧ALTER新增列顺序与ORM声明顺序不同，最终按列名/类型/可空性及整目录一致性判断，没有重排旧表或重跑DDL。原记录见[首轮](migration-roundtrip-v1.json)、[恢复v1](migration-recovery-v1.json)、[恢复v2](migration-recovery-v2.json)。

SQL辅助工具八项DELETE缺FROM、HTTP预检表名/探针DTO/计数形状、两处测试夹具及Node摘要解析的失败均保留，分别只复验受影响节点或重解原记录。定义闭包修复为运行代码修改，随后制造影响检查及同一原请求体实际接口复核；格式调整不重跑已通过检查。没有把阶段包、替代复验或历史结果重复相加为新候选完整联合通过。

## 下一步与仍待满足的条件

1. 针对已定位的原资源摘要不一致，准备严格的版本兼容方案；先证明差异与所有依赖，不删新签发人配置、不改原Start/资格/来源，原预约/消费及当前撤回守卫仍须完整通过。未证明可恢复时保持重核拒绝。
2. 制造三种T1对象需同范围有效专业职责/资格与完整固定Definition/Process/Source，随后才办理首存、续版、Current/历史链接及原请求UNKNOWN恢复。当前缺资格只阻断实际业务保存，独立实现可继续。
3. 正式变更需真实政策选择、八facet材料、独立具名T2批准与实际领域输出，才能验收实施回链和完整数据库原子组。
4. A2完整复验需新合法未来窗口及不超过20条的完整来源方案；完整观察、独立Review、有效性/分别关闭、制造试产/放行、真实资格、全量G/N/P/Q和人工Exit仍未通过。

[制造首次保存材料方案](manufacturing-first-save-plan-v1.md)已独立准备：作业指导与控制计划可以并行整理，制造基线必须等真实保存/回读后选固定Current引用，并列出现工艺的全部工序；其他工序缺资料如实留空。该方案不授资格或生成真实来源，三对象最小联验也不代表所有工序资料齐备。

所有数据库业务验证仅用已核对 `127.0.0.1:62513/pdos_test`，marker `916f950f-2d2b-405d-b809-c15db75dc20c`；私有迁移前备份保留。没有模型调用、真实资格授予、生产操作、外发或push。本轮不操作原存续57432；9/27恢复基线0377及备份后部分登录/序列记录无法完整重建、不能宣称零丢失的边界保持。当前活动进度只更新[唯一清单](../../../../tasks/ai-native-integrated-todo.md#pdos-next-queue)。
