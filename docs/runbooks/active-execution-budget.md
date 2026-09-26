# 累计活动时间与模型出口

2026-09-10，N0-03，本地候选migration `0072_active_execution_budget`。三档获批活动额度仍为120/600/900秒，不修改获批profile。默认预算模式仍为legacy；以下控制随已有显式budgeted入口生效。

## 计时真值

新lineage创建时由数据库生成计时覆盖记录。预算绑定的run进入running时生成活动区间，离开running时关闭；排队没有活动区间。应用入口在创建运行/冻结预算的同一事务内开始，事件入口在实际领取时开始。数据库使用`clock_timestamp()`，调用方传入的started_at/completed_at不作为扣时依据。运行绑定与结束并发时先锁定运行行，防止结束与新计时互相遗漏。

同一lineage全部区间按秒累计，包含关联run、再次进入running和不同lease的执行；并行席位区间分别累计，不用墙钟并集抹去执行时间。重复持久上下文或正常续租不重置区间起点。带worker租约的区间最多计到最后有效租约期限，失联后不会无限扣时；没有worker租约的主动请求持续计到其持久运行结束，崩溃后仍需可信恢复服务处置。

父运行结束至后续运行开始之间不扣活动额度，累计值和绝对截止保持。当前只验证已有对话续写及运行状态边界；`waiting_input`控制、持久checkpoint和恢复调度仍未接通。不能把本片视为已经交付完整人工等待流程。

`budget_activity_coverage`、`budget_activity_spans`只有生命周期触发器维护，直接插入/更新/删除被拒绝；Agent没有这些表的读写权限。Agent可执行的新增函数只有`agent_check_active_budget()`，从服务端绑定租约取得范围，不能传入任意tenant/run查询。

## 额度检查及费用

SQL预算预留和已绑定模型attempt派发检查活动额度，等锁后重新读取数据库时间；Owner端普通未绑定request的预算派发也复核。重放旧回执和未派发取消保留原幂等行为，不因额度耗尽伪装为新调用。

实际ModelBudgetController在成功收到provider响应后先提交真实用量，再检查活动额度和绝对截止。超限返回`BUDGET_ACTIVE_TIME_EXHAUSTED`或`BUDGET_LINEAGE_EXPIRED`，Gateway保留known用量/trace并关闭已知调用，不交付输出。Finding插入还在数据库写入边界复核，不能拿之前的成功响应越过时间限制。已派发未知回执继续保留预留；耗尽额度不会阻止可信服务有据结算。

这些是准入和输出边界控制，尚未实现对在途HTTP的即时取消或对租约期限按剩余活动额度裁剪。期间provider可能继续运行，实际费用仍须照实结算。工具预算循环、工具取消及主动请求lease仍属于后续工作，不声称所有CPU/网络工作都会在额度最后一毫秒终止。

## 迁移与存量

0072不为此前lineage追填0秒或推测历史。存量lineage缺计时覆盖时返回`BUDGET_ACTIVE_HISTORY_UNAVAILABLE`；新关联run不能给旧lineage重新开额度。真实采用前必须识别仍需恢复的旧运行及在途费用，使用后续具备证据的恢复/对账方案；不能删除原绑定或另开lineage绕过限制。

只要存在活动区间，降级就拒绝移除计时历史。空测试库往返已验证，不能类推为有历史环境允许降级。生产迁移、旧执行器排空和预算模式切换仍需原有逐次批准；本次未执行。

Owner `BudgetLedger.open_lineage`仍是已有的受信底层准备端口，只从绑定当下开始计时；它不证明绑定前的历史。真实应用工厂继续使用创建时冻结和ExistingRunBudgetLedger，事件工厂继续使用预绑定预算，不能借底层准备端口在调用时补旧额度。

验证见[验收记录](../reports/2026-09-10-n0-03-active-execution-budget-validation.md)。
