# 13 类来源搜索性能修复

正式相同规模检查通过：71 条实际原生来源 / 13 类，5 次预热后每种模式测量 40 次，inclusive p95。检索 **0.966349 秒**，13 项复核 **0.514729 秒**，59 项复核 **0.674571 秒**；SQL 恒为 **5 / 4 / 4**，全部低于原定 1 秒门槛。[完整计时与规模](../pdos-next-role-native-sources-20261029/performance-final.json)、[正式 XML](../pdos-next-role-native-sources-20261029/pg-thirteen-performance-run3.xml)。

前轮同 71 条 / 13 类正式检索 p95=1.025914 秒失败，原[失败 XML](../pdos-next-role-native-sources-20261029/pg-thirteen-performance-run2.xml)继续保留。实际 SQL 计划表明同条查询重复扫描来源元数据；最后改动仅将 `SearchSource` 换为既有 `readable(SearchSource)`，让普通请求者 RLS 元数据在该条 SQL 中物化一次，原 join、扫描与最终 catalog 条件保持。无迁移；[补丁](query-state-materialization.patch)、[输入哈希与增量](query-state-delta.json)。先前扫描目标缓存仍只是可重建提示，不是权限缓存。

[26 项纯测](pure-state-metadata-run1.xml)、[5 项真实数据库回归](pg-state-metadata-run1.xml)及 [Ruff](ruff-query-state.txt)通过：计数前范围过滤、无重建撤回/成员变化、损坏派生、NULL/错误缓存与当前扫描，以及原来源撤回后的关系隐藏。两份同规模诊断结果另存 [优化前](thirteen-family-search-profile-run1.json) / [优化后](thirteen-family-search-profile-run2.json)，诊断不替代正式用例。

本地测试库 `127.0.0.1:53502/pdos_test`，head `s0_0850`。未调用真实模型或 embedding；本地合成规模通过不代替真实材料质量及生产负载结论。
