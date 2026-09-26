# 事件Agent触发策略与截止时间

2026-09-10，N0-03，本地候选migration `0075_event_trigger_scheduling`。实际`run_dispatcher.py`入口采用已批准事件策略；尚未部署，原生产与P/Q出口不变。

## 当前接线

里程碑集合与N0-02登记一致：阶段改变、Gate批准、测试失败、Issue创建/状态改变、供方延期、Complaint/NCR创建、工程变更。运行在创建事务内完成预算冻结并立即queued，使用`event:<事件行ID>`去重；同一时间戳的不同事件不会互相吞掉。截止时间严格为原事件timestamp加180秒，包含队列和执行。事件来源时间取已有SoR记录，不采信模型传参。

Document上传与Development BOM创建/条目新增采用固定900秒窗口；明确保留分页批次的合并。窗口已经封口后的迟到事件生成独立去重键和运行，不丢弃新事件。当前仍是project与已有六Agent路由，没有新增模型触发或扩大capability rollout。

服务端创建时写入`dispatch_key / dispatch_policy / dispatch_deadline`，数据库检查来源、策略、期限与窗口；之后不能改写策略或来源锚点。旧run这些字段为NULL，继续原合同。直接构造`AgentDispatcher`默认legacy是旧调用兼容口；正式worker脚本显式采用approved，900秒政策不受旧debounce配置覆盖。新旧worker混跑的部署排空仍须原批准流程。

## 队列与租约

实际受限Agent领取时先清理最多1000条过期待运行记录，再优先领取里程碑、按截止时间/创建顺序排序，之后是背景事件。领取同时明确排除Owner主动请求；这些请求继续已有同步服务路径，不宣称已完成统一interactive队列。

过期且尚未开始的run记录`failed / AGENT_TRIGGER_DEADLINE_EXCEEDED`，`started_at`保持NULL；不是伪造一次零秒执行。该新兼容状态只允许具备milestone策略及截止时间的超时记录，旧失败规则不放宽。Worker周期也清理过期队列，停止计数包括这部分。

新lease及续租取`min(数据库当前时间+60秒, 原触发截止时间)`，当前lease校验同时检查deadline。旧token和逾期worker不能读取受限投影或发布Finding/checkpoint。模型结果已经产生但发布延迟越界时，保留既有trace和账本，候选发布失败。

恢复时已有Finding回执仍可按原事实收口；open/unknown会话及未决预算保留，明确`AGENT_RECOVERY_RECEIPT_UNKNOWN`，不释放额度、不重发调用。其余已超触发期限的运行不重新排队，记录超时原因。恢复不重置lineage、预算或deadline。

## 权限、观察与采用

Worker只新增三个调度字段的INSERT权限和过期队列窄函数执行权，不获得业务表写权限或运行策略UPDATE权限。Agent仍只能使用原claim/lease/恢复相关服务边界，没有新增模型工具。

`GET /api/ai/projects/{project_id}/runs`返回`dispatch_policy`和`dispatch_deadline`，保留既有项目/发起人权限。UI原状态/错误展示可读超时结果，本片没有增加实时轮询界面。实际worker轮询参数限定0.1～5秒（默认2秒）；这只是配置边界，不能证明积压负载下≤5秒可见或≤180秒成功的真实SLA。

数据库迁移、实际worker/Agent代码和DBA模板须配套采用。有新调度历史时禁止降级；空测试历史可往返。旧default预算仍legacy，预算模式切换与真实计量资格独立验收。本片没有真实模型请求、golden写入或生产操作。

## 继续建设

持久工具观察/分步checkpoint、waiting_input、Owner租约与统一队列、完整运行版本束、跨scope调度、在途网络请求即时取消、实时队列展示和积压负载下的SLA仍需继续。超时失败是诚实状态，不算SLA成功；调度代码接线不等于真实席位模型资格或完整N0-03验收。
