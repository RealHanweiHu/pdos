# 快照定位旧夹具修复

原候选的 21 个快照定位失败共用 `test_snapshot_read_ledger.py` 的内存夹具：现行历史读取会核对实际提案权限，旧夹具既没有 `scalar()`，也没有绑定的 Proposal。上游异常被定位器转换后，10 个正例被拒，11 个特定错误原因断言被遮蔽。

只补齐测试夹具的 schema 查询、严格 tenant/category/id 的 Proposal 查询及对应记录，未修改运行时权限或覆盖守卫。`test_snapshot_read_ledger.py` 与 `test_snapshot_locator.py` 定向 **188 项通过**，见 [原始输出](snapshot-fixture)。

这不改写原全量的 1648 通过/24 失败/8 跳过结论，也未重新运行全量。剩余 3 项确认消费间歇失败仍待定位；S1 未验收。无真实模型/KMS 调用或性能采样。
