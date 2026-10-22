# 第十六波 · 根因、本人整改与独立复验回链

当前状态：根因v5、本人完成v6/awaiting_verification、新复验准备v1与正式草稿v1、固定CAPA回链均已在实际页面保存。回链于10:44:21UTC同存一次回执/审计/事件及实际T1消费；页面180秒等待超时后按同一原请求恢复成功，未另造命令或再次确认。12项只读收口核对通过，原报告/失败、历史/时钟和实际占用保持；新输出仍draft/planned，不证明新实物接收、Run或有效性。484份v4候选的9项替代PG已全部结束：8项通过、1项错误分类断言失败；只修精确断言的v5单节点复验已通过，原八项v4精确范围按未变业务代码保留；旧v3停止记录保持13项完成/11通过/2失败、6中断、1未启动。这里不是G3、真实资格或人工Exit通过声明。

- 公共三操作已接入共同命令与事务：具名根因 T2、原措施执行者实际完成 T1、固定真实输出回链 T1。批准 / 确认消费与业务事实同事务；独立有效性、问题关闭及正式变更实施未开放。
- 实际 `next_0024` 完成升级、降级、再升级和 schema 检查；106表与模型一致，两张新表强制RLS，Agent直接写权限为0，候选仅可读。此前104表完整行摘要及旧质量/变更事务守卫保持。见 [迁移结果](migration-result.json)。最初工具和SQL失败、修复证据与私有备份均保留；没有恢复或删除存续联验库。
- 实际GET发现合法Current Formal v7的共同回执挂在TestRun，直接Formal回执桥缺失。首段候选现在只列举具有精确直接canonical回执的真实Current版；独立owner、来源、权限和末端刷新均保留，不回退旧版本。恢复GET为200、问题仍v4、输出选项0；paired owner桥和候选持久化缺项明确返回。见 [原失败](http-current-read-initial.json)、[恢复读取](http-current-read-recovery1.json)、[独立审阅](direct-owner-filter-independent-review.md)。
- 修复后的478份后端与142份前端文件已冻结并核对实际摘要；33项公开读取/候选纯检查、54项实际BFF选集、43项UI辅助检查通过，前端lint / 构建 / 类型检查通过。分别见 [候选身份](candidate-v2-current-identity.json)、[读取检查](public-read-v2-pure-result.json)、[BFF](bff-selected-result.json)、[界面检查](ui-component-check-v4.json)、[公共构建](web-build-result-v2.json)。这些范围不相加冒充整树联合通过。
- 本地合成准备已登记三操作的用途限定职责/资格、待决定根因提议、实际调查完成事件及独立分类原文。原时间 `2026-10-03T08:08:20.788303+00:00` 保留完整精度，实际事件与服务器接收时间分离；登记不等于根因、完成或回链业务命令已经执行。
- 原v1四项事务运行因发现真实读取缺口而停止，退出-15、源码保持稳定，不能记作通过或业务失败；原日志留存。19项v2选集在明确隔离的 `127.0.0.1:62513/pdos_test` 启动后，因实际界面提交发现守卫错误而停止；首六项尚在上游准备，后十三项未启动，零项记作通过。见 [v1中断](priority-v1-interruption.json)、[v2中断](pg-v2-interruption.json)、[原选集](pg-v2-selection.json)。
- 实际具名根因POST在提交事务时报SQLSTATE22P02；回读问题仍v4、四个历史版本保持、根因回执为零、原批准未消费。见 [实际回滚核对](root-submit-rollback-observation.json)。已应用0024未被改写；新0025仅修复三处JSON取值括号，实际25→24→25/schema通过，106表完整行摘要保持，仅相应守卫函数变更。降级增加四表事务锁，已有新业务事实时保守拒绝。见 [修复迁移](guard-repair-result.json)、[降级锁复核](guard-downgrade-lock-check-result.json)、[独立审阅](migration-0025-independent-review.md)。原失败与私有备份保留，无数据恢复或删除。

限定恢复实现只在同Product锁内三层去重后核原proof未消费/已过期、material及Current精确匹配，返回绑定完整原命令仅删token的恢复标记；普通409仍保持锁。见[实现绑定](expiry-recovery-implementation.json)、[独立恢复审阅](recovery-proof-review.md)、[新候选](backend-candidate-source-v3.json)、[20项运行选集](pg-v3-selection.json)。这些是实现和运行登记，不是实际保存或事务通过声明。

实际页面按原请求恢复，取得精确未保存回执，刷新当前v4后以同标识重新预览并具名提交。根因实际v5、决定时间09:04:26.389428Z，一次Receipt/Audit/Outbox与实际T2证明同存，原过期proof仍未消费，失败/CAPA/旧历史保持。见[实际恢复](browser-expired-recovery-observation.json)、[实际根因保存回读](root-saved-observation-v3.json)、[v5界面恢复检查](ui-component-check-v5.json)、[新142份构建](web-build-result-v3.json)、[新33项读取](public-read-v3-pure-result.json)、[精确BFF结果复用](bff-v3-retained-binding.json)。

本人完成实际已保存为v6/awaiting_verification，原发生时点08:08:20.788303Z及UTC保持，服务器接收时点09:11:15.351734Z分别记录；一次Receipt/Audit/Outbox、实际T1消费及旧v5空完成记录已回读，见[完成回读](completion-saved-observation-v3.json)与[完成实质预览](browser-completion-review-v3.txt)。新独立复验准备v1也已实际保存，固定旧Build、图纸/方法/判据，物理样件与接收/开测/结果保持空，见[准备预览](browser-new-preparation-review-v3.txt)。

原修复检查点（已由末段实际保存及只读核对取代）：当时固定CAPA回链尚待完成。480份v3候选的20项事务选集于10:23UTC停止：13项完成、11通过、2失败，6项运行中断、1项未启动，见[精确停止记录](pg-v3-interruption.json)。两项失败分别是等价UTC时间的文本断言及Link首次保存的COMMIT证明拒绝；不能把后者归为断言问题，原日志和诊断保留。实际Link路径确认存在共同证明核验后继续owner读取、末端不再次核验确认时效的间隙，但未恢复该次回滚行的实际saved_at，不能宣称已唯一证明本次失败原因。原“等20项全部结束再修复”的安排在此检查点撤销，开始窄修复并准备替代影响选集；UTC断言保留完整微秒/原时区，投影按真实Start时钟判断，SQL守卫及有效期保持。旧11项通过是原v3局部证据，不冒充新候选完整通过。八类facet仍UNKNOWN，真实复验、观察期、有效性与分别关闭仍未完成。

实际新正式草稿入口暴露旧结果状态兼容缺口：GET200含reported v7，但前端封闭状态表未覆盖，legacy零占用字段也与保留的实际Start矛盾。前端现在保留全部七状态，以完整Start时钟显示结果后历史占用，缺时钟明确未知，原字段不篡改；写能力仍按各固定对象服务器caps。20项专业辅助/类型/局部lint与新142份公共lint/build/type通过，见[实际读模型观察](professional-read-compatibility-observation.json)、[专业UI v6](ui-professional-component-check-v6.json)、[公共web v4](web-build-result-v4.json)、[未变BFF精确复用](bff-v4-retained-binding.json)。旧候选停止后，主线已按真实Start时钟修正后台legacy投影字段，尚待新运行时实际回读核对；不以UI兼容冒充后端验证。

新正式草稿v1已在实际页面建立，固定新准备v1，只有请求建立时钟，实物、Run、接收、开测及结果仍为空；见[实际保存页面](browser-new-formal-saved-v4.txt)。旧reported v7全部历史和已发生占用仍可回读，见[旧正式请求历史](browser-reported-history-v4.txt)。原办理tab的Workspace读取失败后缺少重试入口；同一合成身份的直接API及BFF只读请求均200、约0.3秒，未证实服务端超时，见[API观察](workspace-read-observation-v4.json)、[BFF观察](bff-workspace-read-observation-v4.json)。只读重试及取消读取后的加载状态已在web v5修复，局部类型/lint和新142份公共构建通过，原tab重载后正常读到Workspace；该次未出现错误重试按钮，不能宣称浏览器点击过该按钮。见[修复检查](ui-read-recovery-v7-check.json)、[公共构建](web-build-result-v5.json)、[未变BFF范围复用](bff-v5-retained-binding.json)。

随后实际页面已读取问题v6及新Formal v1并选择同一措施；inputs为200，实质预览及按原请求恢复均在BFF时限内未返回。10:09UTC只读快照确认问题仍v6、回链和对应回执均0、两份未消费预览证明；尚未点击T1保存。见[预览状态](link-preview-timeout-observation-v5.json)。原完整命令、读集与标识保持，不再无条件重试或重新建立已保存草稿。单次[运行活动观察](preview-activity-observation-v5.json)不证明具体瓶颈；预览重复owner读取与保存末端证明时效正在新候选中修复，旧480候选及日志保持为历史证据。

新增Link提交失败的原日志已保留并核对摘要，见[提交证明诊断](pg-v3-08-link-proof-diagnosis.json)；当前尚未证实是哪一条证明条件不符，不能直接归为超时。数据库拒绝守卫不放宽，preview-only复用方案不代表此项已修复。

新v4候选已在公共接线后冻结为484文件；137项阶段/owner/选项纯检查及静态、格式通过，见[接线绑定](public-phase-repair-binding-v4.json)、[纯范围复用](phase-pure-retained-binding-v4.json)、[写入审阅](link-write-phase-independent-review.md)。9项替代PG（两项失败＋七项未完成）曾用6路独立租户运行，见[实际启动](runtime-and-replacement-v4.json)。实际原预览恢复成功后只点击一次T1保存，等待返回超时，10:48UTC快照取得实际Link/唯一Receipt；同一原执行恢复返回保存成功。旧两份过期proof仍未消费，当前proof消费一次、Issue保持v6、Formal v1输出仍draft/planned。见[实际回链与恢复收口](actual-link-recovery-closeout-v4.json)及[保存页面](browser-link-saved-v4.png)。

[实际只读收口](actual-closeout-v4-seed-codec.json)12项通过：精确根因/完成版及原值时钟、原失败/报告字节、唯一原子回执组、新草稿零实物/Run、Link不推进Current或授有效性，以及原件读取后新快照保持。初次工具错误源于旧浏览器seed不含capa_action_id字段；已仅纠正输入codec，实际存储的动作UUID/执行者/完整摘要跨三版校验保留，原失败报告与[修复绑定](closeout-seed-codec-v3.json)保持。该只读检查不重构本次false→true UOW、不替代仍运行的PG、真实专业资格或人工Exit，不据此宣称实际提速。


替代批次[最终结果](repair-v4-result.json)为8通过、1失败，九项前后484份源码摘要全部稳定；原失败log保留。失败节点在Link保存/镜像/Issue保持/唯一保存组核对后，错版请求实际正确返回403/FORBIDDEN_SCOPE，原测试误期待409/VERSION_CONFLICT，末尾计数尚未运行，不能将该函数计为通过。见[分类复核](wave16-link-scope-failure-review.md)。已保存v4原测试，并在[新v5候选](backend-candidate-source-v5.json)仅改line425两个期待常量；[完整AST与文件差异绑定](scope-assertion-fix-v5.json)确认其余测试行为、业务代码、迁移和配置均相同。原失败单节点v5已通过（1182.03秒，实际进程退出0，484份源码稳定），末尾保存计数也已执行；原八项通过仍分别绑定v4。九项所需替代影响范围现已补齐，见[精确范围复用绑定](replacement-v4-v5-retained-binding.json)，不扩大为同一候选整树联合通过。
