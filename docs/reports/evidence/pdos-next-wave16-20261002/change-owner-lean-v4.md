# Change owner lean v4 局部冻结核对

该交付只覆盖授权的三个既有领域文件和一个既有纯测试文件，属于 Wave15 v4 修复；Wave16 新目录没有计入 Wave15 候选。

保留 get_issue 默认完整行为，新增 get_issue_for_change 精简口只省略与 Change 无关的质量写能力评估。固定失败真实读取、原值证明、精确失败身份、Current、当前 ACL、来源/风险政策及其完整读集仍逐 phase 核对。Issue/CAPA 同一固定版本在一个 OwnerReader 内共享一次已核 wrapper；_seed 缓存仅存在于单次调用。末端 post-IO Reader 独立创建，继续真实重读，不跨 phase 复用。

同时补齐安全绑定：Issue/CAPA 图节点 source_basis 现在分别保存 issue_source_basis 与完整 current_policy。已核 policy.assess 返回中没有 checked_at/now；版本、issuer、epoch、negative/current 与有效性边界全部保留。新政策 epoch 即使重新为 positive，fresh Reader 仍拒绝 SOURCE_STALE。该项是安全指纹修复，不仅是性能变化。

旧 v3 图捕获和日志均保留。其安全基底形状与 v4 不同，需重新捕获并复核；不得复用旧捕获或延长原 exact-key TTL。

最终局部候选 43 pure passed in 0.91s；Ruff、format-check 与四文件 AST 均通过。第一次局部纯检查 38 通过/5 失败属于新增测试夹具错误（TestRun 无 executor_id）；已用真实 FailureRef.executor_id 修正并保留原失败日志。没有放宽生产门禁。

v3 公共 pg11 通过（2341.51s），pg12 因真实 GRAPH_CAPTURE_EXPIRED 失败（2234.64s）。这些结果没有被隐藏或累加冒充新候选通过。v4 公共验证尚待主线执行上述两个精确节点；没有在本子任务运行数据库、PG、HTTP、浏览器、公共构建或迁移。

具体 hash、选集和历史证据见 [change-owner-lean-v4-checks.json](change-owner-lean-v4-checks.json)。原 303 路径只做该已冻结集合的当前摘要比较，不扩大为旧工作区全量不变结论。

公开调用：quality_execution.service.get_issue_for_change(s, ctx, product_id, issue_id, revision=None, *, write=False)；既有 Change 默认 loader 接此函数，宿主显式注入 loader 仍优先。
