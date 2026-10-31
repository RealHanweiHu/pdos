# 小Pai企业问答、上下文与相似历史共同检查点（2026-10-29 UTC）

本检查点覆盖新检索的权威依赖过滤、九类来源恢复、本人偏好、结构结果/受控续读、Issue相似历史及原T1办理。两份完整设计仍在建设；下一步复验准备接续暂存在独立目录，不计入本候选通过声明。全程未调用真实模型或embedding，未提交推送。

## 当前候选与回归结果

共同检查点已完成：88文件、838项唯一用例均有实际通过证据；保留无影响/等价通过段与必要重跑，**并非一次全新完整组重跑**。[逐项去重与分段](backend-candidate-10-final-coverage.json)、[最终969输入](source-manifest-candidate-10.json)。最终输入逐项核对未变，六项既有失败与两项长结构定向8/8通过，与本组重叠不累计。

正式九来源58来源场景保持原1秒门槛，5次预热+40次实测、inclusive p95：检索0.745秒、9项复核0.284秒、48项复核0.303秒，SQL恒定5/4/4。[完整原始计时](formal-nine-family-performance-candidate7.json)。Worker重启续接实际通过。原先的慢观测和exclusive小样本失败均保留，不将采样修正单独宣称为优化效果。

本次集中修复还覆盖：合成模型配置明确200k窗口、真实渐进披露夹具；长专业记录按实际有界分页核引文；检索显式JIT设置的固定4条SQL；0831/0833个人偏好与相似历史反馈的冻结目录遗漏；非法齐套payload复用为开工/制造批准时精确422及零回执。未知模型32k、64k聚焦、预算拒绝、原件来源守卫、权限和T2审批规则保持。[原过程与失败记录](progress-candidates-3-9.md)、[最后14项](backend-candidate-10-remaining.xml)。

权威查询仅缓存不可变SELECT语法，ID每次绑定，权限/数据逐事务由RLS执行；[48项metadata/body与原实现逐字段相等](authority-query-cache-equality.json)，新跨本人/peer/其他租户/撤权PG通过。生命周期目录补齐两类实际个人元数据，实际覆盖、禁用守卫拒绝、未知列/表和原件引用检查通过。[诊断](candidate8-schema-diagnostic.json)、[114项续跑](backend-candidate-9-remaining.xml)。

Ruff沿用269文件范围，并补核[最终6文件](ruff-candidate-8-targeted-inputs.json)、[生命周期3文件](ruff-candidate-9-lifecycle-inputs.json)和[齐套测试](ruff-candidate-10-supply-inputs.json)；不宣称全仓库lint通过。前端29文件262项、类型/生产构建687输入及31文件ESLint通过，实际页面见下文。

本共同检查点冻结后，下一闭环31个复验暂存文件已独立合入（[进展](../pdos-next-verification-action-20261029/result.md)）：组合副本203项纯测试通过，另17项实际PG已排队；前端694输入离线生产构建通过。这些结果独立于本共同检查点，两份完整设计继续建设。

## 可用能力

检索在SQL计数和分页前核对知识引用实际依赖、扫描及当前版本，固定历史来源继续保留原版本和定位。九类来源的只读SQL复用同一普通RLS投影，消除重复授权计算；缓存仅保存无数据SQL别名，实际权限和数据每次由PostgreSQL执行。

实际派生索引支持固定manifest恢复、损坏/缺失分块与统计校正、重复Outbox及Temporal重启续接。维护角色不能读取原文/正文/哈希，实际原件仍须普通请求者RLS许可。修复共享Build供给保存时仍返回旧`product`可见性导致422的旧缺陷，沿用Build实际可见性与受众。[恢复专项与原始证据](../pdos-next-enterprise-recovery-20261029/result.md)

本人显式偏好按本人保存、运行内冻结；四类任务结构将分析与原文依据分开。超长工具结果保存完整账本并用受控分页句柄续读，必需上下文超限在模型调用前给出`context_incomplete`。长中文结构记录已走实际主图与续读，保存表格入口及换行显示已修复。[偏好](../pdos-next-personal-preferences-20261029/result.md)、[结构结果](../pdos-next-structured-answers-20261029/result.md)、[受控续读](../pdos-next-result-continuation-20261029/result.md)

Issue页相似历史按实际固定关系读取，支持原记录、本人反馈和小Pai短预填；原T1预览/取消/重新预览/实际确认归并已走通，不新增模型调用。结构结果可保存本人版本、保留AI原文并刷新恢复。[相似历史](../pdos-next-similar-history-20261029/result.md)、[实际页面证据](browser-final.md)

## 验证证据

- [相同58来源样本的优化结果](same-fixture-optimized-run9.json)：返回与原始SQL基线完整一致；暖读p95：检索0.743秒、9项复核0.326秒、48项复核0.647秒；分别5/4/4条SQL。正式恢复性能用例仍以共同回归结果为准。
- 前端表格最终版：[29文件262项](frontend-table-render-tests.txt)、[生产构建与类型](frontend-table-render-build.txt)、[31文件ESLint](frontend-table-render-eslint.txt)。构建输入687项，见[输入清单](frontend-table-render-build-inputs.json)；复用本地既有Geist字体缓存，不改字体配置、不访问模型。新增未挂载的复验卡片不计入该候选。
- [后端269文件Ruff](ruff-candidate-2-final.txt)及[范围](ruff-candidate-2-scope.json)，另[最终三项测试夹具Ruff](ruff-fixture-final.txt)。范围排除四个既有格式问题文件；其中执行绑定测试仅修改实际披露夹具，未清理其原有格式问题，不宣称全仓库lint通过。
- 合同[正确路径导出](contracts-export-corrected.txt)后[验证通过](contracts-validate-after-export.txt)：126 schemas、87操作、90事件、63验收场景。保留误用旧路径的失败日志。
- 独立`127.0.0.1:53502/pdos_test`已核对标记，head为`s0_0834`；0831–0834每步有备份与升级/降级/升级证据。真实非空反馈降级被原守卫拒绝并回滚，head/行数/权限/函数均保持，见[核对结果](migration-nonempty-feedback-rejected.json)。未读取.env或操作其他库。
- [浏览器与临时凭据清理](browser-cleanup.json)：本次专用页面、API/Web进程和六份临时凭据文件已清理，数据库、Temporal与备份保留。

## 剩余工作

共同检查点838项已完成；接下来应用复验准备接续并集中验证完整业务闭环。领域适用性、I14/I22明确携带及复验两阶段、其他对象的相似历史、深入查/当场纠正、X2其余工作状态、X3、混合检索C、摘要E、钉钉G和D/F仍按[完整对照](../pdos-next-two-designs-20261028/task_plan.md)推进。人工问题集不由自动化写入可信golden-case；真实模型质量、embedding服务商调用、真实渠道发送和正式阶段验收未据模拟宣称通过。
