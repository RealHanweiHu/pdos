# N0-03 原子预算存储基础验证

2026-09-10。上轮普通路径rollout检查与验证是有效进展，本轮继续已批准DC-07的持久预算基础。N0-03仍部分完成，尚未将本账本启用到应用/受限Agent的真实模型调用入口。

## 实现与边界

新增`BudgetLedger`可信服务端持久化接口，以及0060迁移的三张cehub_ai表：budget_lineages、budget_run_links、budget_journal。没有新增namespace，没有扩展Agent业务写出口。

- lineage冻结完整RunBudgetProfile、内容摘要和绝对截止时间；重复创建同run返回原lineage，不刷新预算或日期，变化profile拒绝。关联run以真实tenant/run外键绑定同一lineage，不能重新绑定更大额度。
- 每次预留在同一PostgreSQL事务内取得tenant advisory lock，检查正在运行的run、单次输入/输出限额、lineage累计token及模型/工具次数、tenant当日token与占用调用的lineage席位。重试/席位使用不同attempt并共账；同attempt相同参数重放不重复预留，参数变化拒绝。
- 只有`dispatch_granted=true`取得一次派发许可。重复派发返回原回执且许可false，不能借幂等重放再次发请求。run完成后拒绝新预留/新派发，允许读取已结算attempt回执以及迟到用量对账。
- reserve→dispatch→unknown→settle等每次变化追加journal revision；不覆写历史。未知响应保持全额held_tokens，不能当作未发送取消。只有派发前取消才释放预留且charged_tokens=0；无来源价格保持NULL。配置金额硬限会明确拒绝，直到金额执行链就绪。
- 结算需要非空证据引用、非负实际token；实际超过预留也照实入账，后续请求因额度不足停止。同一结算可重放，不同数字/证据冲突。当前UTC日之外的未决预留继续占用tenant额度，跨日不能清空未知账；迟到结算计入结算日，lineage总量跨日累计。
- 三表拒绝UPDATE/DELETE；迁移回退在任何lineage/绑定/预算证据存在时拒绝，不抹去账本。测试TRUNCATE仅用于隔离测试库fixture。

这是服务持久化端口，不是模型tool，也不签发授权。tenant_daily_token_limit和profile只接受可信服务端调用；跨scope关联和settlement证据真实性须由接入层验证。当前只统计本账本，不宣称已经覆盖历史model_invocations。调用席位约束也不替代worker整个活动阶段的lineage租约。

## 实际验证

执行前再次确认本机127.0.0.1:57432的库为pdos_test，起始head0059；0060仅在此库迁移。没有生产/开发库迁移、真实模型、外发、共享登录角色或权限修改。

| 验证 | 结果 |
|---|---|
| budget ledger数据库组 | 15 passed；线程池+Barrier使用独立连接/服务实例同时争抢，验证同attempt仅一份预留/派发许可，以及tenant token/并行席位不超额 |
| 现有网关、表合同、迁移图与测试隔离 | 29项不同测试通过；0059安全往返兼容0060新head |
| 共同对象、产品计划、版本时间、运行政策、工具/采用、日历 | 160 passed |
| 完成后回执读取 | 追加断言复验1 passed，属预算组原测试，不重复计数 |
| Alembic metadata比较 | 新三表的列、默认值、索引和外键无差异；CHECK及不可变触发器另有数据库负向验证 |
| 质量检查 | Ruff/格式6文件，Mypy budget_ledger通过；本片diff无空白错误 |

本轮合计204个不同测试。测试用profile、用量证据和跨日/过期时钟偏移均明确为合成夹具；没有把证据字符串当作provider对账已接线的证明。

初轮19项通过后新增NULL负向测试，发现0060草稿DDL漏同步取消状态`charged_tokens IS NOT NULL`保护，出现41 passed/1 failed。已重生成静态DDL，在空预算表上安全往返并验证非法NULL被拒绝；最终预算15项全过。未修改已发布迁移，也未以应用层Pydantic检查替代DB约束。

源码/当前合同/获批原件摘要见[机器证据](evidence/2026-09-10-n0-03-budget-ledger.json)。N0-01及N0-02批准快照保持原样；当前物理schema和迁移映射更新到0060。

## 接入前仍需完成

网关每次实际provider attempt和工具handler的预留/派发/用量回执接线、模型资格窗口与实际输入计量、profile交集及活动时钟/租约、受限pdos_agent/worker的安全接口与租户范围绑定、存量model_invocations用量对账（避免漏算或重复计数）、真实价目/缓存meter及金额预算尚未完成。当前服务并未自动启用到运行装配，不宣称实际worker已受原子预算全面控制。

其他N0-03剩余仍包括持久政策/bundle与跨进程撤权、shadow评测管理路径、完整工具循环/来源ACL/checkpoint恢复。N0-06/N2-01及P/Q/Sprint出口状态不变；没有git push、生产或golden变更，已批准DC-06/07/08不重复询问。
