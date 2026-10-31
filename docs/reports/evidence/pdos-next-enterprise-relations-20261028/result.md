# 企业显式关联与当前对象入口检查点

日期：2026-10-28（本地）。本轮完成已登记业务来源的一跳读取与当前对象入口，完整两份设计仍在建设。前序[引用与资料比较](../pdos-next-assistant-material-workflow-20261028/result.md)保留；用户指定的原六项在本最终候选再次 6/6 通过。真实模型和 embedding 继续停用。

## 可用行为

- 直接命中 Issue/CAPA/Change、Build、TestRun 或供应记录后，只沿领域快照的固定引用、合并、聚合和实际父关系展开一跳；不根据文字相似、UUID 文本或模型推测建立边。
- 直接命中保持原上限，关联对象排在其来源之后，最多附加 20 个固定来源；两种数量分开记录。已直接命中的对象仍保留实际关系入口，不重复计数。同一固定来源只显示一次，不承诺列出所有路径或完整关系图。
- 两端都经权威来源、普通 RLS、当前品类/型号/项目/提案范围及原件扫描过滤；不可读目标不返回标题、ID 或计数。关联原对象的版本/hash 纳入不可变读取证明，撤权/撤回后不能借可读目标暴露原对象；原对象的私人/客户类别沿引用传播。
- 固定内部记录可以从显式引用读取，不等待目标索引；索引尚未完整时检索仍按真实覆盖返回 partial。检索恢复保留原证明；跨轮重新签发引用仍保留原关系约束。
- 来源卡片标明关系，保留固定引用版本，提供服务器生成的“查看当前对象”。问题/CAPA 解析到真实所属 Issue 与可读 Build；变更、测试、供应和试制入口沿真实范围。历史引用不会被替换为当前记录。
- 试制概览只从实际授权列表接受链接目标；手工改选保留，缺失/不可读目标不会触发对该目标的读取或任何写入。人用链接仅接受封闭的同源页面、范围和选择器，未知、重复或混合目标会被拒绝。

## 同一最终候选验证

| 范围 | 结果 | 证据 |
|---|---|---|
| 后端集中组 | 49 文件 388 项全部通过，0 失败/跳过，271 条既有运行时/依赖警告保留 | [日志](database-final.txt)、[JUnit](database-final.junit.xml)、[选择](test-selection.json) |
| 原六项 | 6/6 再次通过 | [逐项](original-six-reverified.json) |
| 新增业务用例 | 3/3，已包含在集中组 | 实际变更→问题一跳、禁止孙级 CAPA 扩展、类型收窄/他人拒绝、已直接命中关系保留、原对象单独依据撤回、真实父 Build、实际 HTTP→Temporal→注册图与跨轮重签 |
| 前端 | 83 全部通过；类型、生产构建和目标 ESLint 通过 | [测试](frontend-tests.txt)、[构建](frontend-build.txt)、[ESLint](frontend-eslint-final.txt) |
| 代码与合同 | Ruff、合同覆盖、目标 diff check 通过 | [Ruff](ruff-final.txt)、[合同](contracts-final.txt)、[差异](diff-check-final.txt) |
| 候选一致性 | 233 个受影响输入未变；661 个前端输入与构建副本/工作树一致（两组有重叠） | [源码](source-recheck-final.json)、[前端](frontend-source-recheck.json) |

首轮新测试把普通位置说明当作原文行证明，原守卫正确返回 422；按真实整行摘要修正夹具。[首轮日志](relations-first.txt)。随后发现未索引关联项应保持 partial，修正测试的 completed 断言，未放宽产品覆盖判断：[中间日志](relations-fixed-evidence.txt)。[首批 3 项](relations-current-navigation-temporal.txt)已通过，最终集中组还加入实际注册图断言；分散检查不与集中组累计。

## 时延与查询

新增关系的首轮暖读 p95 4.520 秒，暴露了直接与关联两次完整权威复核的开销。仅收窄目标、增加服务器绑定租户条件仍未达标（5.466/4.903 秒）；用轻量 ID 依赖收集降到 1.457 秒，仍保留为失败记录。最终将直接与关联来源合并到同一个 MATERIALIZED 权威关系，一次聚合返回两组有界结果，原件扫描复核仍在最终过滤前执行；RLS、来源版本/hash、作用域与当前状态未放宽。模型、用户与租户结果不缓存，缓存仅是静态 SQL 语法。[首次](native-related-performance-initial.json)、[收窄](native-related-performance-target-narrowed.json)、[租户](native-related-performance-tenant-filter.json)、[轻量依赖](native-related-performance-light-dependencies.json)。查询计划诊断中的 planner setting 只用于诊断，没有应用到产品。

最初集中组在独立关系性能检查暴露超限后主动中断，270 项已过；该记录单独保留，未与本最终集中组累计：[中断日志](database-initial-interrupted.txt)、[初次输入](source-manifest-initial.json)。

- 新关系读取：一个真实 Build 及其当前登记执行/TestRun 记录，12 次暖读，返回来源数 [6]，每次 SQL 数 [5]，p95 **0.982586 秒**。使用夹具实际扫描配置，纯数据库读取，不新增模型/扫描调用；不等于全来源规模性能。[数据](native-related-performance.json)、[原始日志](native-related-combined.txt)。
- 同一集中组关键词暖读：8 来源、12 次、3 SQL，p95 **0.332986 秒**，原 1 秒与 3 SQL 门槛未改。[本次记录](performance-final.json)。旧候选的一次 1.023 秒超限及诊断仍保留在[原证据](../pdos-next-citation-inheritance-20261028/performance-final.json)，根因尚未确定，本次通过不抹除该记录。

## 页面检查与环境

实际正式 AnswerSources 组件、合成固定来源及同源码生产 CSS：1280px 亮暗、390px 亮暗、320px 暗色共五张截图；无页面横向溢出，Tab 能聚焦当前对象链接，关联说明、历史/更新标注与键盘焦点已目视检查。[浏览器记录](browser-result.json)、[桌面](output/playwright/desktop-light.png)、[窄屏](output/playwright/narrow-dark.png)。该记录是组件 SSR 检查，未冒充带认证的完整产品浏览器跳转；实际 HTTP/权限、Temporal 和选择器不写入另由测试覆盖。专用浏览器与 57949 服务已关闭。

复用核对后的 127.0.0.1:53502/pdos_test，marker `f117bb5b-b3d7-4286-aaec-c54d9255e96b`，head s0_0830，四个角色连接显式提供，无 .env 回退、新建库或新迁移。原备份和运行时保留。[最终环境](database-target-final.json)。排序版本随一跳规则升为 v3，不改业务权限、资格、T0/T1/T2 或正式阶段状态；无提交/推送、生产或真实外发。

## 剩余范围

本轮只声明上述已登记业务关系和支持的对象入口，不推断外部等待 target 文本、知识或原件内的关联；这些来源仍可打开固定引用片段。完整领域当前适用性/继续执行、知识等依赖版本更新保留、同品类补查与背景条、显式 I14/I22 携带和行动故事、全索引恢复及全来源规模性能仍待补齐。is_current 表示当前版本指针，登记历史及其关系不构成当前执行许可。

X2 更多对象/候选、非 RAG 成果及批量证明，个人偏好、X3、C/E/G/D/F、真实岗位题集/人工评审和真实模型质量仍按[完整对照](../pdos-next-two-designs-20261028/task_plan.md)继续；不自动写 golden-case，不用合成结果替代生产、真实外发或正式验收。
