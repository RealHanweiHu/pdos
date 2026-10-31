# 三类原生业务来源检查点

项目具名状态、制造草稿/正式发布文档、物理交接固定事实均已进入当前普通 RLS 来源查询、原生事件投影、引用和目标页面导航。制造新草稿不替代原正式发布文档；原件撤回后相关来源不可用。

- 真实来源用例 **3/3** 分段通过：[项目状态](pg-role-run2.xml)、[制造文档](pg-role-run4.xml)、[交接](pg-role-run5.xml)。
- 迁移 **s0_0849** 真实 up/down/up、函数精确比对、权限与历史计数保持：[迁移](migration-0849.json)。
- 三个原 B 项目上下文用例在 [首轮](pg-project-role-run1.xml) 通过；自动依据与显式材料分离的后续修复另按最终候选复验，不用旧结果替代。
- 实际失败及修复保留：原生确认关联、内部生命周期函数角色和两处测试夹具，见 [修正说明及源码哈希](native-corrections.json)。

- 13 类混合功能恢复 **3/3** 同轮通过：[XML](pg-thirteen-recovery-functional-run1.xml)，覆盖全派生损坏重建、重复 Outbox 和固定批次 Temporal worker 重启恢复。
- 正式性能 **1/1** 通过：71 条来源，5 次预热 + 40 次实测，检索/13项复核/59项复核 p95 分别 **0.966349/0.514729/0.674571 秒**；SQL **5/4/4**。[完整数值](performance-final.json)、[正式 XML](pg-thirteen-performance-run3.xml)、[修复与相关回归](../pdos-next-search-performance-20261029/result.md)。

首轮性能在计时前遇到制造夹具 issuer 生命周期失效，第二轮真实计时检索 p95 1.025914 秒失败；两份原 XML 保留。仅更正组合夹具的 issuer 生命周期/实际原件存储，再根据实际计划优化普通 RLS 元数据重复读取；不缩减样本、不放宽门槛，交接按真实固定历史纳入复核。

原始日志位于相邻 assistant-combined 证据目录。未调用真实模型或 Embedding，未向真实服务外发。
