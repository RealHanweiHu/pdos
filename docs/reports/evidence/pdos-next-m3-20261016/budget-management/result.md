# 本人模型预算建立、更换与停用

按冻结 v1.1 §06 的运行预算、回执、取消/恢复与 §08.11 一致性要求，补齐实际预算管理入口。这个闭环可用；完整 M3/S1 出口仍未完成。

- 「设置 → AI 运行与费用 → 我的模型预算」显示本人跨品类、跨运行的活动预算、费用/占用、调用尝试和 token 用量及分页历史。沿用原 RLS 的本人预算范围，普通成员只读；当前管理员本人一次 T1 确认建立/更换或停用全部活动预算，不新增替他人配置的权限。
- 新预算采用新记录，原限额和累计用量不回写。旧运行保留其固定预算绑定，进行中调用继续在原记录结算；停用时不再为新调用预留。默认 Bootstrap 实际读取新活动预算，不依靠前端参数选择钱包。
- 复用 COMMON 的当前授权、一次确认、RequestKey 与 Receipt/Audit/Outbox 原子事务。本人控制锁、连续配置版本和索引化状态摘要防止跨品类并发覆盖，也使「全部停用→同额度新建」形成新意图。仅计费/占用变化不会使更换意图失效。
- 断线保留本人已确认的完整原请求，重开先执行只读回执查询。已完成的过期原请求直接恢复；新副作用仍须当前权限与有效确认。金额全程按整数微美元转换，保留六位小数精度。

## 候选与验证

[源码摘要](candidate.json)承接 `cc4ede3`。只使用已核对的独立 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`。最终 head **`s0_0765`**。

- `s0_0764` 新增配置版本/回执；[迁移往返](migration-result.json)保留全部旧额度、用量与 Run 绑定。`s0_0765` 增加配置版本和活动预算索引；[索引往返与最终 ORM 对齐](index-result.json)同时保留已存在的新控制版本和回执，ORM 差异为空。原始日志为 `checks/migration-*.log`、`checks/index-*.log`；最终元数据只保留其他旧表的既有循环排序提示。
- [73 项后端检查](checks/budgets-final.log)通过，覆盖建立/更换/全停、默认 Run 预算绑定、进行中预留后的更换与原预算结算、两品类并发首版、T1/权限/旧回执、历史分页、零费用额度及原账本/执行绑定回归。
- 初轮把完全相同语义的新提交误期望为版本冲突，已修正为按合同返回原回执。进一步[实库复现](checks/stop-reallocate-reproduction.log)确证「停用后同额度新建」会误回旧预算；连续控制版本修复后已纳入上述通过组。
- [1 项实际 HTTP 测量](checks/interaction-timing.log)包含 20 次建立/停用、逐步核对连续版本：p95 **265.13ms**，中位数 106.89ms，最大 313.06ms，每次 **26 SQL**（含鉴权与领域）。[结构化测量](interaction-timing.json)仅代表一个合成人员的本地交互，不代替完整 S1 性能验收。
- [52 项前端/BFF](checks/frontend-final.log)、[类型](checks/typecheck-first.log)、[Ruff](checks/ruff-final.log)、[lint](checks/lint-final.log)及包含最终 TypeScript 检查的[生产构建](checks/build-final.log)通过。lint 0 错误，未修改的忽略生成文件 `verification/contracts.js` 保留 2 处既有警告。共 **126 个不同病例**，重复复核不累计。
- 页面验证后只细化旧运行预算停用的错误提示与 `budget_inactive` 原因，[18 项受影响检查](checks/stopped-run-final.log)复核原结算、零新增预留及原价格/取消路径；与上述病例重叠，不作新增计数，未重复全量验证。

## 实际页面结果

[1280px 亮色](desktop-allocated-light.jpg)建立精确 **1.250001 USD** 的第 1 版预算，再本人确认停用第 2 版；以相同额度建立第 3 版时仅替换一次成功响应为 503。[页面保留原请求](unknown.ax.txt)，[320px 暗色重开](mobile-recovered-dark.jpg)恢复[同一第 3 版回执](recovered.ax.txt)，[历史](history.ax.txt)保留第 2 版停用记录。

[HTTP 记录](browser-http.jsonl)只有 3 次预览、3 次实际业务 POST 和 1 次只读恢复，重开没有第二次分配。[实库结果](browser-business-result.json)确证 2 份不同预算、3 份具名 T1 回执及各自一份 Audit/Outbox；原预算停用、新预算活动，额度均为 1250001 微美元，费用/占用/调用均为 0。没有充值、真实模型调用、真实支出或资格授予。

## 剩余与收尾

[运行手册](../../../../runbooks/pdos-next-tenant-model-runtime.md)已补办理和恢复步骤。下一步继续资格材料及适用准入入口；真实协议/KMS/价格材料、真实模型与实际 Worker 联验、正式性能/恢复和完整 M3/S1 验收仍保留。本轮没有新增攻防、修改 golden-case、push、生产或云资源操作。

本轮预览关闭、临时登录失效、专用合成管理员停用，[收尾核对](browser-cleanup.json)保留全部合成事实。测试库、共用运行时和 Temporal 保留；后续从 `s0_0765` 核对实际 head。
