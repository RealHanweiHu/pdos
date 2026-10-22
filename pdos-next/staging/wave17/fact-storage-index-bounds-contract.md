# Wave17 五表索引宽度增量合同

本段只修改暂存 `fact_storage_models.py`，新增 `test_fact_storage_index_bounds.py` 与本文；不改 facts/codec、A/B prepare/writer、公开 server/web/SQL、原 38 项测试或旧合同/证据。不创建表、不授资格、不注册用途，不分配迁移号。原模型 `c5e19ebd…` 先保存于 `pdos-next/.local/wave17-fact-storage-index-before-v2/fact_storage_models.py`，文件 600、目录 700。

## 唯一增量

- RuleFact、RuleCurrent、ObservationFact 的 `issuer_key/issuer_version` 从 VARCHAR(2000) 收窄为 VARCHAR(100)，同时显式 `length(...) BETWEEN 1 AND 100`。可信签发方 v1 最长 100 字符；`external_id` 仍为 VARCHAR(200)。不截断、不重写事实，超长输入必须拒绝；冻结 facts DTO 与 codec 字段不变，不能因为旧纯结构 DTO 接受更长字符串就声称可存储。
- 语义 BINDING 保留 purpose，原 registry reader 的完整用途核对不变；新增仅用于物理索引/FK的 INDEX_BINDING，purpose 从这些 B-tree Unique/前版/Current FK 列组合移出。RuleCurrent 外部系列 Unique 也移除冗余 purpose，保留 SCOPE、已有完整 anchor SHA、issuer key/external identity。没有新增 purpose hash、列、第二个用途真值或新的默认值。
- 每表仍有非空 Text purpose、`length(purpose) BETWEEN 1 AND 2000`、`anchor_snapshot.origin.purpose=purpose`；三事实仍核 `fact_body.body.purpose=purpose`。完整 anchor/body/原文/共用摘要与原保存钟不变，scope/origin/owner/visibility/nature/anchor/requirement/series 的其余复合键仍保留。

旧合同关于语义 BINDING 包含 purpose 的描述仍成立；旧 FK/Unique 携带 purpose 的部分对应原 c5e19 候选。本增量明确仅改变索引/FK组合，不覆盖旧合同、旧检查和原 plan。Root 必须以新模型生成新组合 DDL，并保留旧候选身份。

## 用途关联必须继续由真实守卫保证

数据库字段和完整材料仍保留 purpose，不能由索引移出推定可换用途。Root 的实际 SQL 组合须继续：

1. 核 anchor.origin.purpose 与真实完成版 QualityIssueVersion.purpose 相等。
2. Current target 的真实 purpose 与 Current row 相等，Current identity 不可变；前版 Rule/Observation 的实际 purpose 不得改变。
3. Observation 固定 Rule、Review 固定 Rule/每个 observation child 的实际 purpose 相等；原失败/完整 anchor 与所有 host owner 门禁保留。

索引 FK 已不直接携带 purpose，不能再把该保证描述成纯 FK。已有 anchor SHA 包含完整 purpose，但 SQL 不假造 Python digest：实际完整 anchor/material/source/proof 仍由宿主核验。缺这些真实守卫时不能启用 writer。

## 最坏 UTF-8 字节宽度

计算基于 PostgreSQL 标准 8192 字节页、64 位 MAXALIGN=8、B-tree v4。保留页头、三个 line pointer、B-tree opaque 页尾和 heap TID 后，单索引项上限为 2704 字节。

所有 String(n) 均保守按 4 字节 varlena 头＋4×n 字节计算，包含实际上受十六进制/枚举约束的 SHA/状态列；不按字符数冒充字节数。不依赖压缩、TOAST、短 varlena、去重或已有值的 ASCII 性质。每个 datum 另向上对齐，额外计索引 tuple 头、NULL bitmap 和一个 line pointer；Integer/UUID 分别 4/16 字节。任何未声明长度的索引类型直接失败。

| 表 | 全部 PK/Unique/secondary index 中最大保守项（字节） |
|---|---:|
| capa_verification_rule_facts | 2476 |
| capa_current_verification_rules | 1580 |
| capa_observation_facts | 1156 |
| capa_current_observations | 116 |
| capa_named_verification_reviews | 332 |

31 个实际索引声明的全部列与上界见 `fact-storage-index-widths-v2.json`；最宽 Rule 键还留 228 字节余量。旧 2000 字符 issuer＋索引 purpose 的上界明确超过 2704，不再依赖“创建空表成功”来掩盖合法长值写入风险。该数学上界适用于指定标准页/对齐配置；其他 BLCKSZ/ABI 必须重新核定，不能默认通过。

离线编译同时输出五表 CreateTable 与五个 tenant_id CreateIndex，见 `fact-storage-index-ddl-v2.sql`。该证据不是已应用迁移。父 confirmations 的 `(tenant_id,id)` UNIQUE、五表 RLS/权限/生命周期/原子触发器仍由 Root 接线；本段未修改它们。

## 检查与剩余实际验证

最终 v3 新增 25 项纯检查涵盖全部索引字节上界、原宽键反例、100 字符 DB 类型/CHECK、不截断、2000 字符全文用途保留、实际前版/Current FK 与父 Unique 对齐、五租户索引离线编译，并调用原 registry._same_binding 证明 purpose 改变仍拒绝。最终 v3 只运行此 25 项与局部 Ruff/format/内存 AST，不相加成其他候选覆盖。

此前中间 v2（模型 d3df2e24、test 0da4264a）的语义 BINDING 也移除了 purpose，当时独立 24 项＋原 38 项实际合计 62 passed/2.21s；该日志/manifest/原→v2 delta全部保留。随后 Root 要求恢复语义 BINDING 并另分 INDEX_BINDING，所以该 62 不是最终 v3 全项通过。原 38 项中的两个 Current FK参数用例及一个 previous FK 用例引用语义 BINDING 断言物理键，已不符合新物理合同；保留原文件/结果，不偷偷适配、不把旧测试代通过声称最终通过。最终新测试直接核实际 INDEX_BINDING/FK/Unique 和原 reader 用途守卫，没有重跑已知不相容的旧声明断言。没有 DB/HTTP/public 检查。

Root 仍须用新组合候选实际验证标准 8KB 页下 100 个四字节 Unicode scalar 的 issuer、200 个四字节 external id、2000 字符 purpose，超 100 字符拒绝且零截断，原 purpose 不同的前版/Current/child 拒绝、合法连续系列/原子组、完整 schema/索引相容、RLS/权限与迁移回滚。纯结构/离线 DDL不等于真实专业资格、同 UOW 消费或 CAPA 有效性/关闭。
