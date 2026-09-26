# 风险建议后台队列

0092 为风险建议增加 POST /api/ai/risk-suggestions/requests 和 GET /api/ai/risk-suggestions/requests/{run_id}。提交仍要求 concern、真实 evidence_event_ids 和稳定 request_id；返回 202 运行收据，不在提交请求中等待推理。原同步 create-risk-suggestion 保留。

新的风险请求显式保存请求号和发起人，使用 risk-suggestion-request-v1 标识，与事件 Agent 队列分开；不改写旧历史。提交事务冻结原预算及用户授权，再进入 queued，排队期间没有执行租约。只有配置完整预算工厂时可使用此入口。

运行现有 python -m scripts.run_application_worker 即可处理 Chat 和风险队列。每轮分别尝试两种任务，避免一类持续积压时饿死另一类。领取在租户事务内校验原授权、用途、版本和预算，并产生唯一持有者；推理在事务外执行。

完成后查询返回 finding_id；候选仍是 pending_review，接受与应用保持两个独立人工动作。模型结果已持久保存但进程退出时，worker 复用该结果接续，不重发模型调用。取消使用公共 POST /api/ai/runs/{run_id}/cancel；原链记录与预算保留。

这是风险建议现有 HTTP 能力的后台适配。统一对话中的发起交互按 N3-01 接入，测试计划/报告映射队列及完整 RunControl 按 N0-03 继续。本地迁移和模拟供应商验证不代表生产部署或真实模型资格发布。
