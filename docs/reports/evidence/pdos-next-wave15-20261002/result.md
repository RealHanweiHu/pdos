# 第十五波：确定失败、问题/CAPA草稿与双线变更

状态：**本地合成闭环及所选影响范围已收口（2026-10-03）**。页面实际保存Issue→具名分诊→精确遏制→CAPA（Current v4）→Change v2/analysis；第三份固定图在原10分钟期限内完成Impact，前两份过期图保留。原13组/14病例结合精确归并v2、图v4替代复验取得14项去重通过，最终选集已核实际303后端/138前端冻结摘要；原v3过期失败保留，不宣称整树v4联合回归。原报告字节、回执、旧33类历史只读核对、前端v3六种显示与问题历史、13项回滚护栏通过；归并补充护栏因未选来源明确跳过，主归并事务另有通过证据。八facet仍UNKNOWN，G3整体、真实资格与正式出口未通过。

## 已接入与复用

复用原结果、品质问题及变更确定性纯核，在同一受控Command/Session内接入7个canonical动作与5个API。分诊、遏制、合并使用共同的一次确认；Issue、CAPA草稿和Change版本保留原固定失败、原文来源、当前专业资格及政策。变更捕获有固定来源与期限，工程/制造读取真实已有路径，八个未覆盖facet继续UNKNOWN；根因认定、有效性、关闭、Order批准/实施/生效保持未开放。

原上传报告仍核真实原件字节；原生登记文本独立核登记回执/原文哈希/权限，不伪装成上传报告。风险政策只由显式本地合成宿主导入，无公共自授入口、无真实AI资格。前端保留用户另一会话完成的导航，将“项目→问题与变更”替换为实际工作区，办理面板按需挂载并保留草稿。

## 当前证据

- [公共静态接线](public-static-wiring.json)：104个业务模型、7个操作、5个新入口和完整生命周期字段分类，政策导入不在公共PAYLOADS。
- [迁移](migration-result.json)：已核对实际head22后分配0023，23→22→23及schema check通过；104张业务表，9张新增表强制RLS，Agent直接写权限0。私有迁移前备份保留。最初收口工具把独立environment_guard计入业务表，数量断言失败；修正统计后只读核对结构，没有重复迁移或恢复数据。
- [主线纯检查](root-pure.log)：81项通过；各包原冻结检查保留。 [BFF](bff-static-result.md)：24项实际handler纯检查通过，严格允许列表与180秒等待，正文仅读一次且不重试。
- [后端候选](backend-candidate-source.json)303份源码冻结；原[整合前端候选](web-candidate-source.json)138份源码保留。结果中文标签修正后，最新[前端v2候选](web-candidate-v2-source.json)及[构建/类型/lint](web-v2-build-result.json)通过（两个旧生成JS未使用变量warning，0 error）；改动范围见[标签修正](ui-result-label-fix.json)。构建检查只对各自候选有效。
- [初始实际HTTP回读](http-initial-read.json)确认两个新读取入口可用、无效UUID拒绝；原indeterminate没有生成失败Issue，未提交业务写入。
- [数据库选集](pg-selection.json)13个函数（含参数病例）由主线并行执行，未结束节点不算通过。
- 归并事务发现真实读取缺陷：固定事件的源Issue被归并后从Run/Build列表遗漏。已在权限及范围内并集读取FailureMap当前目标与不可变EventFailureLink原单，原失败日志保留；[两文件后端v2增量](backend-candidate-v2-delta.json)和[精确节点复验选集](merge-history-recheck-selection.json)另存，不冒充整树v2联合通过。实际页面服务已重新加载303份匹配的v2源码和具名政策，见[启动记录](api-v2-restart.json)。
- 独立演练首次准备被服务器以VERSION_CONFLICT拒绝：同产品新定义为v4，工具误引用v1。主线核对该项目命令回执/幂等键/确认均为0后，只修私有未提交引用并保留原command/key，见[恢复证据](demo-unsubmitted-reference-repair.json)；工具按实际回执引用的[静态修正](seed-revision-fix.json)另存，未覆盖原失败。恢复后已保存新项目、双配置/Build与独立实物账，见[续接日志](demo-prepare-01.log)。
- 样件就绪准备曾以MISSING_REQUIRED_EVIDENCE拒绝：工具误用开工能力读集。仅修未提交命令读集，保留原意图/command/key；[恢复证据](demo-unsubmitted-readset-repair.json)和[工具修正](seed-readset-fix.json)保留。真实样件交接、正式请求、方法、资源、Run计划及具名承诺续接后，[实际开测](demo-start-00.log)未改钟或重排窗口；[原报告结果](demo-result-00.log)保留11.0000并取得fail；[显式隔离政策](demo-policy-00.log)仅覆盖独立合成项目，未由公开请求或AI自授。
- 图捕获发现历史planned被派生邻接纳入导致RECHECK_REQUIRED；[原失败诊断](graph-plan-node-diagnosis.json)、[三文件修复](graph-history-source-fix.json)保留。[后端v3候选](backend-candidate-v3-source.json)调整精确Current邻接与信息时钟摘要，显式历史失败引用、安全/消费事实与当前planned阻断保留；[精确两节点结果](backend-candidate-v3-delta.json)为1通过、1失败，不是整树v3联合通过。[过期及实际性能诊断](graph-expiry-diagnosis.md)保留真实来源读取8.702秒/3481次查询证据，v4修复与受影响复验另冻。
- 实际遏制预览曾丢失86微秒；未提交旧预览，修复仅涉及helper/test。新[前端v3候选](web-candidate-v3-source.json)、[实际37项helper](ui-helper-v3-checks.log)和[构建/类型/lint](web-v3-build-result.json)通过，原35项只作历史。[精确预览](browser-containment-preview-v3.txt)与[保存后页面](browser-capa-saved-v4.txt)保留；[实际Current v4核对](browser-capa-saved-observation.json)确认四份共同回执、原时刻160086、未完成措施/无根因/无有效性。
- [实际Change v1](browser-change-created-observation.json)及[第二份固定图](browser-graph-captured-v2.txt)已保存；第一次Impact返回409，未取得原code，不推断为已成功。旧捕获不续期、不覆盖。 [前端六种显示组合](browser-v3-responsive-checks.json)仅覆盖Current Issue v4/CAPA和Change v1，不冒充Impact已保存。
- [后端v4冻结](backend-candidate-v4-source.json)仍为303份，四份改动减少同阶段同版重复读取并保留末端独立刷新、完整当前政策指纹；[43项受影响纯检查](graph-speed-pure-v4.log)通过。实际[服务启动](api-v4-restart.json)、[第三份固定图](browser-graph-captured-v4.txt)、[Impact保存观察](browser-impact-saved-observation-v4.json)和[结果页面](browser-impact-saved-v4.png)已取得。原TTL、旧图/旧日志不改；[精确图双节点复验](backend-candidate-v4-delta.json)均通过且运行前后303摘要保持，原v3过期失败保留。
- [独立闭环只读核对](demo-closure.json)通过；原报告1215字节及11.0000、Run开测/两项占用/一项使用、Issue v4和Change v2的回执/审计/事件、旧33类历史均实际核对。收口工具初次误比较两类不同语义摘要、误用原件访问版作物理对象版；失败记录保留，分别从不可变输入重算共同/领域摘要并核真实ObjectRef后取得通过。原业务事实未为修复工具而重写。
- [最终选集待复验记录](final-selection.pending-20261003T073402230422Z.json)保留原v3失败，不用其单项通过代替v4双节点；[参数名解析恢复](closeout-parser-recovery.json)修复带空格的真实pytest参数ID，原81项日志保持。回滚护栏的[首轮](atom-probes-v4.json)与[恢复轮](atom-probes-v4-recovery.json)均未宣称整组通过；第三项的不存在列编译问题已修，恢复轮在页面读取并行时安全中止，所有已执行savepoint/外层事务回滚，待页面空闲后定向复验。
- 页面空闲后的[护栏复验](atom-probes-v4-recovery-idle.json)已完成13项预期拒绝/1项明确跳过，全部保存点/外层事务回滚、保留记录和Product水位保持；[恢复说明](atom-probes-v4-recovery-note.json)不推断中间OperationalError的未记录SQLSTATE。原问题[历史只读](browser-issue-history-v1-loaded.txt)及[回到Current v4](browser-issue-current-restored.txt)已有实际页面证据。
- [最终选集](final-selection.json)实际通过：原13组完成，精确v2/v4复验替代对应原失败节点，14项去重PG有效通过；各代候选/原始日志/替代关系和303后端、138前端当前摘要均单独绑定。81项首代纯检查、24项BFF、43项v4图纯检查和37项前端v3helper保持各自候选范围，不相加为整树联合总数。
- 后续[第十六波施工合同](../../../design/2026-10-02-pdos-next-wave16-quality-followup-implementation-contract.md)三路独立新包已形成并保留自身证据，新增宿主回调及未应用公共Web补丁同步准备；未注册、未迁移、未挂载，不计本波能力。公共接线待本波收口后统一执行，既有候选v1/v2/v3与原日志保留。
- [G1复用盘点](g1-next-reuse-review.md)与[第十六波后续草案](../../../design/2026-10-02-pdos-next-wave16-quality-followup-draft.md)已并行完成；它们是后续范围准备，不作为本波业务通过证据。

## 剩余与恢复边界

本波所选影响范围已收口；下一步接入第十六波根因、本人实际完成及真实owner输出回链，公共接线/迁移/办理和新候选验证另留证据。本波完整图、正式变更实施和业务出口缺口保持，不将固定局部图或调查CAPA草稿视为通过。

上一轮Run v6/disposed、请求v9/executing、原始`  10.0  `及工况差异indeterminate保持；旧1/3和B/C缺项、占用/样件使用/预约与原Start历史不改写。真实资格、生产政策、全制造图、独立复验与有效性、分别关闭、正式放行/外发及人工Exit仍未完成。本轮只用已核对独立62513合成环境。
