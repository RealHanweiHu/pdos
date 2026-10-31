# 0853 前身函数核对修正

初版误以早期 0701 源码重建 `kernel_agreement_atom`，遗漏后续的 `pg_catalog` 搜索路径加固，也没有保留实际函数 body 的原始缩进。主会话首次升到 0853 后的立即核对发现差异；当时没有运行新业务/PG用例。此问题说明早期迁移源码不能代替实施时真实 head 的函数定义，初版纯测也没有覆盖这条前身保护。

修正依据是主会话从升 0853 前完整备份提取的[原始 SQL](predecessor-function-from-backup.sql)和[canonical 定义](predecessor-function-canonical.json)。本分支只读这两份证据，没有执行其 SQL 或 `ALTER OWNER`。`PREVIOUS_ATOM` 现与 canonical `pg_get_functiondef` **逐字相等**，SHA256 为 `0b3a964b390e77ab24e9654f768e1b0145e1020dff5a79ab6732180de65632ac`。

`CACHE_ATOM` 从这一精确定义只追加缓存列与回执一致性条件，保留 `SECURITY DEFINER`、`search_path=pg_catalog, public, pg_temp`、其余原始 body 和结尾；SHA256 为 `f1e5d6c4805dac0d8a51858702ab9a0b68b215c4795834cfb88da5d014a15712`。升级在任何 DDL 前用 `require_functions` 核对已审前身，结束核对新 canonical；降级反向执行同样的前后校验。未知搜索路径或增加过其他守卫的函数会在锁表、改列或替换函数前拒绝。原有非空决定降级拒绝仍保留。

[修正后纯测](pure-migration-repair-run2.xml) **30 项通过**：9项迁移前身/双向顺序/未知定义拒绝/后置核对，加21项政策与输入检查。三文件 Ruff 通过。前轮28项是新增“未知额外守卫”两参数前的子集，不累计。

本分支没有数据库连接、函数修复、升降级或真实调用。主会话负责当前未验收 0853 的函数修复与完整降升重验、owner/ACL/search_path 精确恢复核对，相关实际结果须由其另列；上述纯测不替代数据库往返证据。[修正输入](migration-repair-manifest.json)与初版输入摘要分别保留。
