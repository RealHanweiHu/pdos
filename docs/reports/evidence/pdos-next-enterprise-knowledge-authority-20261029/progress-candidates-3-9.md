# 小Pai企业问答、上下文与相似历史共同检查点（2026-10-29 UTC）

本检查点覆盖新检索的权威依赖过滤、九类来源恢复、本人偏好、结构结果/受控续读、Issue相似历史及原T1办理。两份完整设计仍在建设；下一步复验准备接续暂存在独立目录，不计入本候选通过声明。全程未调用真实模型或embedding，未提交推送。

## 当前候选与回归状态

当前候选共969个输入，见[source manifest](source-manifest-candidate-9.json)。未知模型32k回退、64k聚焦和预算拒绝条件未放宽。

- [候选3前段](backend-candidate-3-final.xml)：39个完整文件、527项通过；随后Temporal合成模型未声明窗口被预算检查拒绝，已给合成配置补真实200k窗口。
- [候选4剩余段](backend-candidate-4-remaining.xml)：36项通过，随后测试误按第一页核对长专业评审引文失败；测试helper已改按真实有界分页核CID/版本/哈希/连续游标及完整引文。
- [候选5续跑](backend-candidate-5-remaining.xml)：54项通过，全部来源损坏恢复/重复消息/错误索引scope/撤权检查通过；正式性能检索0.849秒、9项复核0.388秒，48项复核1.097秒超过1秒门槛，失败保留。
- 同一失败58来源样本只读分解得到[原代码暖读](c5-same-fixture-before.json)：检索0.822秒、9项0.549秒、48项0.369秒。为减少重复Python构造/编译开销，当前候选仅缓存不可变权威SELECT语法，ID仍逐次绑定，租户/请求者/RLS仍每事务执行，不缓存行或授权事实。[48项metadata和body逐字段相等](authority-query-cache-equality.json)，[优化后同样本](c5-same-fixture-after-query-cache.json)48项p95为0.346秒；该分解不冒充正式性能用例通过。
- [候选6续跑](backend-candidate-6-remaining.xml)：新跨本人/peer/其他租户/撤权PG通过；48项复核p95为0.356秒，但检索有一次1.392秒观测，11个暖样本的exclusive估算p95为1.605秒，原失败保留。
- [候选7续跑](backend-candidate-7-remaining.txt)：生产代码与候选6相同，性能用例改为5次预热加40次实测、inclusive经验分位并保存全部原始耗时，保持1秒阈值及相同九类58来源、9/48批次和5/4/4 SQL；正式性能和Worker重启已通过；检索/9项/48项p95为0.745/0.284/0.303秒，全部原始样本见[正式指标](formal-nine-family-performance-candidate7.json)。本段22项通过后，旧8来源性能断言漏计`SET LOCAL jit=off`而失败；实际为固定4条SQL，尚未到时延断言，不属于时延超限。
- [候选8续跑](backend-candidate-8-remaining.txt)：仅测试明确首条JIT设置及4条总数，生产代码与候选6相同；保留629项无影响/等价证据，续跑209项，[依据](backend-candidate-8-resume-basis.json)。目标88文件838项，待剩余段结束后登记总结果；不将采样修正说成单独优化效果。
- [候选8的81项通过后](backend-candidate-8-remaining.xml)，生命周期实际覆盖检查发现0831/0833两类元数据漏登记；[只读诊断](candidate8-schema-diagnostic.json)确认仅`personal_preferences`与`similar_history_feedback`，无其他列或表差异。候选9在冻结目录补齐实际列并归入不采纳原件的个人元数据，不改表/来源守卫/权限；[128项续跑](backend-candidate-9-remaining.txt)包含实际覆盖、禁用守卫后拒绝、原件引用容器和未知列/表拒绝。保留710项通过证据，[依据](backend-candidate-9-resume-basis.json)。
- [既有六项及长结构定向组](original-six-and-long-final-focused.xml)：8/8通过，与共同回归重叠，不额外累计。

复验下一闭环的31个暂存文件未应用：组合副本203项纯测试通过；误放进离线组的17项PG在缺显式数据库变量时停止，已纳入后续PG队列，不重复203项。前端暂存694输入生产构建通过；这些结果不计入本共同候选。
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

先完成上述128项共同回归，再应用复验准备接续并集中验证完整业务闭环。领域适用性、I14/I22明确携带及复验两阶段、其他对象的相似历史、深入查/当场纠正、X2其余工作状态、X3、混合检索C、摘要E、钉钉G和D/F仍按[完整对照](../pdos-next-two-designs-20261028/task_plan.md)推进。人工问题集不由自动化写入可信golden-case；真实模型质量、embedding服务商调用、真实渠道发送和正式阶段验收未据模拟宣称通过。
