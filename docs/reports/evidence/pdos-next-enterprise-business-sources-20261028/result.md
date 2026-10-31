# 小Pai首批业务记录检索与输出撤权传播

2026-10-28。完整目标仍是日常助手/企业 RAG v0.4 与上下文 v0.2；当前状态统一见[唯一清单](../../../../tasks/ai-native-integrated-todo.md#current-queue)。本轮继续扩展来源与读取控制，不宣称完整 B/X2、两份设计或阶段验收完成。真实模型、embedding、业务外发、生产和提交推送均未执行，golden-case 未写入。

## 已接入的能力

- `assistant.search` 接入 Issue、内嵌 CAPA、Change、外部等待、供给快照中的供应承诺、Build 计划和 TestRun。加上原来的原件与品类知识，共 9 类。版本行 ID 用于固定引用，`object_id` 保留业务身份；精确业务 ID 可命中当前版本，历史由实际 Current 指针判定。
- 只投影显式白名单中的内部登记字段。问题根因、临时措施、CAPA 措施/完成记录，变更计划/具名审批/实施/生效/验证记录，等待与承诺状态、数量与时间均保留原语义。不读取完整输入/权限快照，不把 SourceRef.position、外部回复原话、供应备注或 EventTime 的原文来源位置交给主循环。
- 每个分支连接原有 RLS 的领域版本、Current、Project 与 Product；根原件连接权威来源，按版本和当前权限核对。原件扫描配置仍在同批 SQL/本地规则中复核，原件撤回后派生记录在元数据返回前退出；索引不复制受众。
- 现有 Outbox→Temporal 投影扩展到这些原生事件。Actual Receipt 绑定先核对，再按真实命令历史或固定主体/修订确定受影响版本；Issue merge 可以覆盖实际同命令改变的版本。重复事件保持幂等。
- 内部字段直接形成服务器证据行，包含 `as_of`、固定版本与定位，不调用隔离提取模型。可读的逐字字段优先作为引文，不能把模型改写当原文。项目/提案 Run 自动按服务器绑定收窄，实际查找范围出现在未找到提示中；同品类补查仍待后续接线。
- 补齐 RAG 输出的事件流与私有成果读取入口：原始流式事件、保存/读取/修订成果均重新核对来源；成果列表合并实际来源后批量查授权，撤权的成果不返回。更新保留历史正文和人工修订并显示来源更新提示；撤回/撤权拒绝正文和修订，不删除已有历史。

## 性能与修正

多来源 RLS 计划触发了 PostgreSQL 的 JIT：实际计划成本约 493162.77。仅在这些读取的当前事务/保存点关闭 JIT，不改持久配置或权限；只缓存无用户、范围、结果和权限数据的 SQL 语法。合并分页、索引健康和事务时间，再把租户/范围/Current/时间过滤移到共享来源物化前，减少重复 RLS 处理。性能样本为个人入口、未额外指定对象范围且无原件依赖；检索方法内为 3 条 SQL（含一次事务设置，不含事务身份初始化），授权与扫描没有逐条调用。

[计划实测](source-profile.txt)记录了 JIT；[定向修正后](native-third.txt) 4 项通过，8 份来源、12 次暖读 p95 约 0.886 秒。后续以最终候选指标为准，旧结果不代替最终候选。

- `sources-first` 属于旧关联/JIT候选，确认缺陷后中断，退出 130；随后确认子进程退出。它不是通过证据。
- [native-first](native-first.txt)：事件 0 命中来自领域 intent 与通用 receipt intent 的口径不同；改用实际命令历史/主体绑定。p95 约 1.011 秒未通过，门槛没有放宽。
- [native-second](native-second.txt)：native-only union 的 JSON 类型未显式声明；改为 JSONB。p95 约 1.100 秒仍失败，随后合并查询。
- [business-complete](business-complete.txt)：22 通过/2 失败；一项为知识单分支同类 JSONB 类型，另一项测试把正常英文 disposition 误当 position 字段，合成模型断言失败后实际网关正确保留对账状态。修正字段判断，没有清除不确定调用或重派同一调用。
- [temporal-and-compatibility](temporal-and-compatibility.txt)：5 项通过，含原生问题/文档的实际 HTTP→Temporal→注册 LangGraph 与来源读取，内部记录 3 次合成主模型调用、无提取子模型；原件保持物理隔离提取。

- [首次集中候选](database-final.txt)：353 通过/1 失败，原六项通过。新增项目作用域整链揭示旧读取证明兼容路径移除型号后仍触发项目型号要求；现将原双方品类授权与实际读取者的型号/项目普通 RLS 核对分开，同时验证原 Run 的精确 tenant/category/product/project 绑定。[定向修复验证](scoped-proof-repair.txt) 16 项通过，含项目问答、本人结果读取、普通读取证明和 Human T1 采用及原身份撤权拒绝。项目受众和权限没有放宽。

- [第二次集中候选](database-final-proof.txt)：353 通过/1 失败，项目证明与原六项通过；唯一失败是暖读 p95 1.038674 秒。计时插件[修正前复现](performance-before-scope.txt) p95 1.108702 秒，分页/健康 SQL 中位 0.614 秒。把两个消费处原本相同的租户/范围/Current/时间过滤前移到共享权威来源 CTE 物化之前，[修正后](performance-after-scope.txt) p95 0.398994 秒、分页/健康 SQL 中位 0.067 秒；仍为 3 SQL，原 RLS、固定版本/hash、原件扫描与完整索引健康检查保留，门槛未放宽。

## 最终验证

- [最终集中回归](database-final-scope.txt)：39 个文件、**354 通过，0 失败/错误/跳过**，696.41 秒。224 条运行时/依赖及 pytest 属性等警告完整保留；[JUnit](database-final-scope.junit.xml)与[机器结果](verification-result.json)可逐项核对。
- [原六项逐一复验](original-six-reverified.json)：全部通过，包含四项运行详情/字段投影、渐进技能披露与恢复零重复调用、实际注册页原件读取引用恢复。原修复原因与直接差异见 [A/X1 六项修复记录](../pdos-next-slice-a-x1-20261028/result.md#六项既有失败修复用户追加授权本轮最终候选)。
- [最终性能](performance-final.json)：8 份来源、12 次暖读，p95 **0.422547 秒**，检索方法内固定 3 SQL；p95 <1 秒门槛保持。真实计划仍可触发 JIT，事务内关闭后的独立暖读最大值 0.407841 秒。该样本不代表真实模型或生产规模时延。
- [前端 53 项](frontend-tests.txt)全部通过，0 失败/跳过；目标 [ESLint](frontend-eslint.txt) 0 错误/警告，[最终隔离生产构建及 TypeScript](frontend-build-final.txt)通过。首次构建受公开字体网络阻塞的日志 [frontend-build.txt](frontend-build.txt) 保留，最终使用同一源码副本完成构建。
- [目标 Ruff](ruff-final.txt) 与目标 `git diff --check` 通过。[最终冻结清单](source-manifest-scope-final.json)中的 **205 个受影响输入**及构建对应的 **660 个前端源码输入**核对未变（两组有重叠，不能相加）；仅排除 Next 自动生成的 next-env.d.ts，见[最终指纹核对](source-recheck-final.json)和[构建输入](frontend-build-inputs.json)。前两次失败候选的日志和各自指纹保留，不累计通过数量。


## 数据库与合同

复用[已核对的 127.0.0.1:53502/pdos_test](database-target-final.json)，head 保持 s0_0829。本轮没有建库、清库、迁移、新依赖或权限豁免，原备份保留。离线合同导出只扩展 SearchInput 的来源类型；路径、payload、operations、acceptance 与导出前相同，见[导出核对](contract-export.json)。[设计覆盖校验](contracts-final.txt) 87 operations / 90 events / 63 acceptance IDs 通过，不代表实际资格。

## 尚未完成

1. B 的一跳关系、个人化与同品类补查/背景条、跨轮引用身份重签、资料三入口/比较、结果结构与回答转行动三条故事、显式 I14/I22 携带、整体索引故障恢复与人工问题集审阅仍待继续。
2. 本轮固定内部登记字段不代替领域读模型的当前适用性检查；Build 当前投影是计划与固定配置，实际开工/执行事实以及完整专业结论还须补齐。导入记录/客户与现场原文继续按隔离资料处理，不借“内部记录”扩大范围。
3. 新增输出守卫覆盖已接入 RAG 的实际读取及携带来源；X2 其余已读对象、候选状态、非 RAG 读取的缓存成果与更完整的跨 Run provenance 批量读取仍须补齐。来源授权已合批，来源证明读取不等同于已完成全部 X2 性能优化。
4. 个人偏好、X3 的全局缩减/续读/进度与 C/E/G/D/F 保留[完整范围](../pdos-next-two-designs-20261028/task_plan.md)。未做本轮真实浏览器多尺寸/亮暗验收。
5. 真实模型/embedding、真实角色题、人工 golden-case、试点与真实钉钉凭据/发送保留其材料与授权条件；合成证据不授予 T0/T2 或实际模型资格。
