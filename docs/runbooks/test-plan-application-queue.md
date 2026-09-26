# 测试计划建议后台队列

0093 增加 POST /api/projects/{project_id}/npi/test-plans/{plan_id}/suggestion-requests 和同路径 GET /{run_id}。提交保留现有 message、request_id、previous_finding_id 和 sources 参数，返回 202 运行收据。状态查询不依赖模型网关。

提交事务固定原预算、发起人、计划/依据版本、消息及前一候选摘要，保存请求后进入 queued。应用 worker 领取时重新检查这些输入；排队期间发生变更会停止，不根据新事实悄悄替换原请求。主动请求显式保存身份，与事件 Agent 分开。

运行现有 python -m scripts.run_application_worker，逐轮处理 Chat、风险和测试计划队列。带问题的成功候选进入 waiting_input，保存问题并释放执行资源；用户补充后，在新请求创建事务关闭原等待并沿原预算链排队，无需空持执行租约。最终候选仍须独立接受与应用。

PDOS_AI_TEST_PLAN_ASYNC=true 将现有页面提交转到队列，默认 false；队列入口要求已配置完整预算工厂。页面识别 202，轮询状态并加载已保存建议；刷新后从当前项目/计划的 sessionStorage 运行号恢复。存储中没有消息或文件内容。查询失败提供重试，取消使用公共应用任务控制接口。旧同步响应仍兼容。

已保存模型结果可在持有者退出后复用，未知回执不重发。报告映射队列、其他等待点、事件控制及完整 RunControl 继续按 N0-03 交付。本地验证未启用生产开关或发布真实模型资格。
