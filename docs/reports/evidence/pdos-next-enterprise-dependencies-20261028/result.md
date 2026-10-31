# 知识依赖历史、原固定片段与当前权限检查点

日期：2026-10-28（本地）。本轮补齐固定知识引用的依赖身份、依赖更新后的历史保留，以及旧根撤权/撤回/扫描失效的当前复核。两份设计完整目标仍在建设；真实模型与 embedding 按用户要求暂不调用。

## 形成的业务行为

- 知识检索签发引用时，服务器把实际 Artifact/原件、Claim 根或登记网页快照的固定身份、版本、摘要及原件身份附入同一不可变读取账本，并纳入 citation 签名。该足迹不含原文，也不缓存受众或权限。
- 读取历史时，所有旧根仍须经当前普通 RLS、当前 Claim 状态、原件扫描及同品类绑定复核。新根或新正文不能替代原依赖；Claim 的原来源不可改写，原具名撤回守卫保留。
- 仅依赖版本发生变化时，历史回答保留原正文与引文，标记“资料已更新”与 `needs_recheck`。原固定 KnowledgeEntry 的版本/摘要未变且旧根仍可读时，可继续读取其原固定正文；继承的引用在新 Run 中重新签发，回答标为历史并提示当前适用性待重核。
- 当前运行新读到的来源发生变化时仍拒绝恢复为原读；主来源版本/摘要变化时，不向前端宣称原固定正文可用。服务器下发 `fixed_body_available`，页面只在严格为 true 时给已更新引用提供“查看原固定片段”，片段读取仍重新授权；撤权后清除正文。
- 旧根撤回、Claim 经原 T1 预览/具名确认撤回、品类撤权或扫描规则失效后，相关历史回答与引用隐藏；不会为恢复历史发起模型、重检索或重新扫描。

## 同一最终候选验证

| 范围 | 结果 | 证据 |
|---|---|---|
| 后端集中组 | 61 文件 **476/476 通过**，0 失败/跳过，348 条运行时/依赖警告保留 | [日志](database-final.txt)、[JUnit](database-final.junit.xml)、[选择](test-selection.json) |
| 原六项既有失败 | **6/6 再次通过** | [逐项](original-six-reverified.json) |
| 新增功能 | 8 项，已包含在集中组；Artifact/Claim/真实上传扫描/登记快照、历史正文续接、主版本拒绝替换、真实 HTTP→Temporal→注册图和恢复 | [汇总](verification-result.json) |
| 前端 | 14 文件 **137/137 通过**；TypeScript/生产构建、目标 ESLint 通过 | [测试](frontend-tests.txt)、[构建](frontend-build.txt)、[ESLint](frontend-eslint-final.txt) |
| 静态与合同 | Ruff、87 操作/90 事件/63 场景覆盖、目标 diff check 通过 | [Ruff](ruff-final.txt)、[合同](contracts-final.txt)、[差异](diff-check-final.txt) |
| 候选一致性 | 258 个受影响输入未变；665 个前端输入与工作树/新构建副本一致，两组有重叠 | [源码](source-recheck-final.json)、[前端](frontend-source-recheck.json)、[与前轮差异](source-delta-from-previous.json) |

批量复核：6 份不同知识、2 条 Claim 根，1 个与 6 个引用的 SQL 数相同，12 次暖读 p95 **0.040220 秒**，每次 **3 SQL**。版本/权限仍来自权威表，无逐条授权查询或权限缓存；原 1 秒门槛未放宽。这是当前合成规模，不代表所有来源规模。[本轮性能](performance-final.json)。旧关键词候选的一次 1.023 秒波动及根因未定记录保留，未以本次通过抹除。

## 实际页面与环境

带认证的实际生产前端接入独立库 RLS API，使用本轮合成账号，推理派发明确禁用。页面确认资料更新提示、旧引文和“查看原固定片段”可用；片段仍是原 KnowledgeEntry 正文。随后仅在该合成租户撤回测试根来源，刷新并重开会话后显示“资料已不可读取，原内容已隐藏”，旧回答、引文和片段均无残留。前后模型账本与业务命令回执数未增，原 Run 保持 completed/个人范围。[浏览器记录](browser-result.json)、[计数/权限记录](browser-authority-history.json)。

1280px 亮/暗、390px 亮/暗、320px 暗色与撤回态共 6 张截图已检查；页面无横向溢出，Tab/Shift+Tab 可聚焦固定片段。此处是重新读取时的当前权限复核，不宣称浏览器在未刷新时能即时接收到外部撤权事件。[桌面](output/playwright/updated-knowledge-desktop-light.png)、[手机](output/playwright/updated-knowledge-mobile-light.png)、[320px 键盘](output/playwright/updated-knowledge-narrow-dark.png)、[撤回后](output/playwright/withdrawn-knowledge-desktop-dark.png)。专用 API/Web/浏览器与临时登录文件已收尾；共享服务、测试库和备份保留。[收尾](browser-closeout.json)。

新生产构建使用同一产品源码和前一成功构建中的实际 Geist/Geist Mono 二进制作离线构建输入；未改产品字体配置，也未宣称公共字体网络恢复。11 份原二进制 SHA 和新构建的 11 个自托管字体文件均已核对。[字体证据](font-assets-verified.json)、[来源](frontend-font-cache.json)。

仍复用核对后的 127.0.0.1:53502/pdos_test，marker f117bb5b-b3d7-4286-aaec-c54d9255e96b，head s0_0830；四角色连接显式注入，无 .env 回退、新建库或迁移。71,300,987 字节旧备份保留。[环境](database-target-final.json)。无真实模型/embedding、生产、真实业务外发、提交或推送；未改业务写档位、资格或 golden-case。

## 修复过程保留

- 初次合成客户端错误地用 dataclasses.replace 复制 Pydantic ToolCall，随后误把上下文摘要当作完整知识引文；分别修正夹具复制方式与真实摘要断言，未放宽产品守卫。[第一轮](knowledge-first.txt)、[摘要断言](knowledge-fixture-fixed.txt)。
- 夹具试图改写 Claim 来源，被数据库“仅允许具名撤回”守卫拒绝；删除不适用的可变 Claim 假设，测试转为确认该守卫仍拒绝改写，并使用真实 T1 撤回命令。[守卫记录](knowledge-memory-assertion-fixed.txt)、[修正后](knowledge-authority-fixed.txt)。
- 六次相同知识登记被业务幂等正确合并成两份；性能材料改为六份不同内容，随后批量查询与 Temporal 通过。[原断言](knowledge-snapshot-performance-temporal.txt)、[修正](knowledge-batch-and-temporal-fixed.txt)。新主版本负向用例曾因标题不含查询词而未命中，修正合成标题，没有修改过滤规则。
- 实际浏览器发现“资料已更新”通用 UI 隐藏了仍可读取的原固定知识正文；中断旧集中组，补齐服务器可读标志与明确入口，再以新构建/新候选完整验证。[中断日志](database-initial-interrupted.txt)、[旧输入](source-manifest-initial.json)、[定向结果](knowledge-ui-eligibility-fixture-fixed.txt)。分散通过与被中断组不与最终集中组累计。

## 剩余边界与下一步

旧读取账本没有依赖足迹且依赖已变化时仍按原守卫拒绝，不推测旧原件身份或扩大权限；不能把当前根的可读性当作旧内容的授权。当前领域适用性/继续执行、知识依赖在检索计数/分页前的统一权威过滤、其余来源/对象入口、显式 I14/I22 携带及复验准备→请求行动故事、全索引损坏恢复与全来源规模性能仍须继续。

RAG 的结果结构、深入查和完整纠正流程、本人偏好、人工维护问题集 v0/召回评价；X2 的更多对象/候选、非 RAG 成果与批量证明、result.read/必需内容超限；X3 固定缩减与长运行评测，以及 C/E/G/D/F 仍按[完整对照](../pdos-next-two-designs-20261028/task_plan.md)建设。真实模型质量/时延/缓存、真实 embedding/钉钉和人维护题集保留对应条件，不用合成测试替代正式验收。
