# 当前权限下的向量召回、来源去重与实际计划

本次修复固定分块池导致来源不足的问题，并对同一权限集合执行精确对照。使用确定性合成向量，没有模型或 embedding 服务调用。

## 已修复

- PG16 的内层 KNN 按原始距离排序，稳定来源/分块次序放到外层。
- 完整权威权限集合在同一快照物化；tenant/profile/dimensions 与 chunk/hash/category 匹配均在近邻 LIMIT 前执行。
- 授权匹配分块不超过 1000 时使用精确扫描；本次 top10 的大集查询按 200→400→800→1000 的有界池递增，目标为 top10 及一条分页判断来源。达到上限仍不足时明确返回 shortfall，不声称全集已穷尽。
- 逐轮来源 ID 仅用于内部观测；对外响应只保留计数和策略。

前三轮原始结果保留在 `native-run1/2/3`：当时测试断言通过，但自然计划没有 HNSW，固定 200 池去重后仅 4–5 个来源。这些记录不作为 ANN 通过证据。

## 8192×384 完整矩阵

128 份合成资料各由实际 projector 产生 64 个分块。普通 `pdos_next_app` 在同一权限快照分别执行 exact 与请求 iterative；撤回受众时不重建向量。

| 权限场景 | 可见来源/分块 | 查询数 | 最终 recall@5 / @10 | 来源不足 | 最终 HNSW |
|---|---:|---:|---:|---:|---:|
| 本人 | 128 / 8192 | 4 | 1.0 / 1.0 | 0 | 0/4 |
| 同事：公开32＋受众32 | 64 / 4096 | 4 | 1.0 / 1.0 | 0 | 0/4 |
| 同事：撤回16个受众后 | 48 / 3072 | 4 | 1.0 / 1.0 | 0 | 0/4 |

12 组均扩池到 800，最终返回 11 个去重来源；所有阶段均未返回当前不可见来源。24 次策略捕获、48 份 nearest 实际计划均与原 SELECT 的 backend PID、完整归一化 SQL、条数和顺序匹配。实际计划没有 HNSW，因此这里只确认同权限结果一致及去重修复，不计 ANN 收益。

实际运行 `native-auto8192` 为 **34 passed / 597.22 秒**，其中仅 1 个原生测试承载上述 12 组控制，其他为纯检查，不按 34 项原生测试累计。此前集中纯检查为 69 项。89 项冻结输入在该轮结束时一致，见 `checkpoint.json`、`ann-authority-n8192.json`、`tests.xml` 和 `frozen-auto-inputs.json`。

## 计划归因与较大规模续验

独立再次执行的 EXPLAIN ANALYZE 只能解释重放，不能替原返回结果归因。测试观察器只在目标 SELECT 周围启用 auto_explain；只有匹配到同次实际执行的 HNSW 才能赋予该阶段 ANN recall。最终阶段与前序阶段分别记录。

`eligibility-live` 的 47 项检查表明 canonical 原始距离查询可规划 HNSW，完整权限 SQL 在该规模选择较低成本的其他路径。canonical 和管理员诊断计划不计 ANN 结果。

32768×384 同形状候选 `native-auto32768` 在第4个本人查询出现连续执行后的严重计划退化，主会话中断该轮并保留失败。此前完成的14个 nearest 实际计划中8个使用HNSW；没有完成一整组权限阶段，故不计完整矩阵或来源级 ANN recall。记录见 `interruption.json` 和脱敏的 `pre-interrupt-actual-plans.json`。该轮512份资料/32768分块保留，原生T1停用后自有profile向量为0，观察配置及SET权限完全恢复，90项冻结输入在结束时一致。

8192原件中，iterative与exact分别恰在第11次相同查询时切换到高循环次数的计划。该时点与默认自动prepare及PostgreSQL随后选择generic计划的规则吻合，属于强推断；该轮没有保存prepared counters。通用计划下，绑定维度还无法证明分维度 partial-index 谓词。[PostgreSQL partial index规则](https://www.postgresql.org/docs/16/indexes-partial.html)与[prepared plan规则](https://www.postgresql.org/docs/16/sql-prepare.html)支持这一结构判断。

已实施服务器查询级修复：仅两类昂贵semantic Select通过psycopg的 `prepare=False` 保留每次按当前参数规划；其他SQL、所有参数绑定、RLS和planner成本保持原路径。[psycopg单次执行选项](https://www.psycopg.org/psycopg3/docs/api/cursors.html#psycopg.Cursor.execute)与[SQLAlchemy执行事件](https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.DialectEvents.do_execute)支持该窄实现。此前维度literal草稿未应用，因为它不能解决authority内部的generic基数误估。中断时已关闭连接的observer也已修复，保留原KeyboardInterrupt。最终101项纯检查、11文件Ruff与独立代码复核通过；92项输入冻结于 `frozen-custom32768-inputs.json`。

较大规模记录的 `strategy_elapsed_ms` 是本次实际 production read 的墙钟时间，含观察器 SET 回调，不含观察器初始化、日志解析和独立重放。两种重放模式之间的时延不作严格规模因果比较。

## 最终32768×384结果：机制通过，ANN质量与收益未通过

`native-custom32768` 完整执行三权限×四查询，**5 passed / 700.24秒**，其中1个原生测试承载12组控制、其余4项为已在纯检查中计过的检查。24次策略捕获全部匹配到同次SELECT，39个实际nearest计划包含12个exact与27个iterative阶段，后者23个实际使用HNSW。12组都有前序或最终HNSW，8组最终为HNSW，4组最终自然选择Seq Scan。

| 权限场景 | 可见来源/分块 | 最终HNSW | 全部四题来源recall@5 / @10 | exact/iterative策略中位墙钟 |
|---|---:|---:|---:|---:|
| 本人 | 512 / 32768 | 2/4 | 0.850 / 0.675 | 9.50 / 21.13秒 |
| 同事：公开32＋受众32 | 64 / 4096 | 3/4 | 0.350 / 0.325 | 3.22 / 6.38秒 |
| 同事：撤回16个受众后 | 48 / 3072 | 3/4 | 0.300 / 0.300 | 2.94 / 5.89秒 |

所有阶段均无私有/撤权来源泄漏、无重复来源、无来源数量短缺。24次观测中，目标nearest prepared条目均为空，driver的prepare_threshold仍为5；17–25条其他SQL仍自然prepared，证明修复没有全局关闭预编译。此计数证据只覆盖nearest，不扩大为eligible probe的独立计数证明。

**来源数量足够不等于近邻正确。** 独立按实际source IDs复算，8组最终实际HNSW的宏recall@5/@10仅 **0.25/0.15**；全部12组混合最终计划为 **0.50/0.4333**，其中最终Seq Scan的4组均为1.0。该合成压力集合没有提供ANN质量或加速收益证据，关键词继续为默认。不得将这些几何数据与52题题集的97.92%关键词基线解释为同题混合收益。

原始JSON顶层的 `ANN_not_exercised` 使用旧的“所有低权限查询最终均HNSW”判据，原件保留；它不表示本轮零HNSW。新 `native-custom32768/checkpoint.json` 明确记为 `natural_hnsw_observed_with_mixed_final_plans_and_low_synthetic_recall`。查询级退化、权限与同集合实际对照已收口；ANN质量、默认启用和性能收益未验收通过。以上墙钟是四样本插桩策略观察，不是生产API p95。

## 收尾与范围

8192、中断32768及最终32768夹具均通过原生T1停用自有profile，剩余各自profile向量为0；资料、分块、回执、审计和Outbox保留。临时auto_explain配置及SET权限与原基线完全恢复，见各轮 `observer-state.json`。最终92项输入及此前项目上下文120项输入哈希均保持一致。

未关闭顺序扫描，未强制索引、改变成本、RLS 或业务权限。合成几何集合的一致率不代表语义质量；关键词仍为默认路径，真实混合收益、模型答案、费用和默认启用资格待真实同题测量。
