# 本地来源兼容修复检查点

独立目标为 127.0.0.1:53502/pdos_test，标记 f117bb5b-b3d7-4286-aaec-c54d9255e96b；当前已应用 s0_0848；0847仅修钉钉触发器局部变量，0848仅增可重建扫描目标缓存列。

- 0845：知识可见性沿实际十类来源刷新；三个可选 answer_sources 容器兼容 SQL/JSON null，Review/Gap 必需 proof 保留；钉钉服务通过限定原 Message 的 helper 取元数据行锁。备份/升降升、原函数 owner/ACL/历史计数保持通过，见 migration-0845.json。
- 0846：现场反馈加入既有派生清理函数类型列表。实际失败只涉及三条 field_feedback，旧函数在回滚事务复现 SQL22023；仅更正该列表，函数 owner/ACL 与原条件不变。备份/升降升通过，见 recovery-field-diagnostic.json、migration-0846.json。
- 23 项受影响知识纯测试通过。原生恢复/知识14项中，pg-run2 已有10项恢复功能通过；性能项失败（检索p95=1.2385秒、复核10/52项分别0.3911/0.4248秒、SQL5/4/4），尚不能声明性能通过。后续在扫描目标缓存候选上，原生缓存/重启恢复/现场答案保存知识/旧知识撤回4项实际通过，见 ../pdos-next-search-scan-targets-20261029/pg-cache-run3.xml。缓存专项首次两个失败均为新夹具问题：第二个已登记原件未索引、复扫误用旧epoch；已按实际索引与当前epoch更正，无产品守卫放宽。

没有调用真实模型、embedding 或外部服务。原十类性能失败不改写；后续已按 71 条实际来源 / 13 类完成新的正式性能复验，检索 p95 0.966349 秒、SQL 5/4/4，详情见[最终性能](../pdos-next-search-performance-20261029/result.md)及[三类原生来源与恢复](../pdos-next-role-native-sources-20261029/result.md)。本报告旧 head 和十类结果保留其历史候选范围。
