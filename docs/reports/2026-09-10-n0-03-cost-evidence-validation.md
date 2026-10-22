# N0-03 费用真实性第一片验证

2026-09-10。前置N0-02已由用户“确认 继续”批准，DC-06/07/08以1.0.0冻结，见[生效记录](../contracts/pdos-runtime-v1/freeze-record.md)。本片是N0-03实际网关与数据库接线，N0-03整体保持部分完成。

## 实际行为

此前应用与受限执行器的装配均注入`ProviderRateCard(0, 0)`，缺少费率时网关也回退到零。现在两个实际装配入口传入空费率表，未知费用存SQL NULL，`cost_status=unknown`；旧调用者继续传无来源卡也不会被当作已知零价。

显式费率须对应调用provider/model，并具备非空版本和来源；网关固定装配时的卡片映射，留痕保存不可变费率快照、USD、每百万token的microUSD单位及向上取整算法。仅有具名来源的真实零价才可记录`priced/0`。测试中的价格与来源都是合成夹具，未填写或调用任何真实模型价格。

缓存计价尚未有完整meter定义，带cache usage的调用保留用量、金额未知。provider错误包括重试中响应丢失：此前收到的token继续记录，整次金额仍未知，不将部分响应算作总账结清。服务端预算拒绝、实际零次请求时记录`not_invoked/0`，与未知费用区分。

新增迁移`0059_invocation_cost_evidence`（前置0058）与SQLAlchemy同步：费用允许NULL、移除默认零、新增cost_status与JSONB费率快照及组合约束。旧记录原值不重写，统一带`legacy_unverified`标记；旧版本程序继续写入时沿用该标记。原append-only触发器保留。仅有旧记录可往返；有新费用证据或NULL费用时拒绝降级，防止抹去未知/来源事实。迁移仅在测试库执行，开发与生产尚未迁移。

## 验证

本机Docker只读核对：`pdos-postgres-1`属于compose项目pdos，绑定127.0.0.1:57432。随后只读确认`current_database()=pdos_test`、角色pdos、PG16.14、起始迁移0058。测试显式覆盖TEST_DATABASE_URL到该地址；55432的旧CEHub库未连接。沙箱本机TCP限制经自动审批允许后执行；未改数据库登录角色或权限。

| 检查 | 结果 |
|---|---|
| 网关、表合同、迁移图、测试库隔离（4个测试文件） | 29 passed；包含新增14个参数化/行为用例 |
| 事件→dispatcher→LangGraph→假provider→调用留痕 | 1 passed，保留现有事件闭环 |
| 共同对象/产品计划/时间、运行政策/工具/采用、日历、工厂与provider adapter（9个文件） | 177 passed |
| budget_exceeded额外断言 | 复验确认not_invoked、金额0、无费率快照；属前述29项内同一测试，不重复计数 |
| Ruff | 本片8个代码/测试/迁移文件通过 |
| Mypy | gateway/application_gateway/runtime_factory三个文件通过 |

本轮207个不同测试通过，模型均为假适配器；没有真实模型调用。覆盖未知费率、无来源零卡、有来源零卡、普通/微额价格、错误模型、缺版本、缓存未知、部分重试失败、SQL非法状态、迁移历史保持/安全往返/拒绝失证回退及append-only。未将这些测试等同于受限pdos_agent账号回归；该项及完整公共运行回归随N0-03后续切片继续。

合同当前导出与获批原件的摘要复核见[机器记录](evidence/2026-09-10-n0-03-cost-evidence.json)。获批N0-01及N0-02快照不变；当前源码/物理兼容映射按新迁移更新，字段和政策冻结范围没有扩展。

## 剩余工作

本片不完成原子tenant/lineage/attempt预算账本、未知响应的预留与对账、费率发布/缓存meter、模型工具循环、ACL撤权复检、shadow/disabled全边界强制、checkpoint/等待恢复或领域应用。现有token日预算仍是原行为，不声明金额硬限或并发预算已接通。新能力资格与领域真实模型样本依各自N项验收；N0-03保持[~]，N0-06/N2-01及P/Q/Sprint出口状态不变。没有生产部署、真实外发、git push或golden写入。
