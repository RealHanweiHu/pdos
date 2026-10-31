# 本地开发期 MiniMax 限额策略

状态：用户 2026-10-23 明确批准。原话：“现在开发阶段，不设 MiniMax 上限和费用限制和次数限制”。本记录只细化本地开发运行，不改变生产、试点资格、权限或业务写入档位。

本地独立 `pdos_test` 中，经服务器宿主为指定租户的 MiniMax 模型明确设置 `development_unlimited_budget: true` 后，费用、调用次数、输入/输出 token 配额及单 Run token 配额不再阻止开发调用。不会把大整数伪装成无限额度，也不反复建立预算。原预算额度、历史用量和原回执保留；活动记录继续承载真实计费和停止控制，停用后不能继续发出调用。

仍按真实价格卡预留、结算实际用量；结果未知保守记账，不盲目重发。服务器要求显式测试地址、独立端口、数据库名及匹配环境标记；普通宿主配置默认继续执行预算上限，模型或 HTTP 参数不能开启此策略。策略进入模型路由摘要与运行/费用记录，旧运行不静默改绑。

输出使用服务商当前支持的技术范围。2026-10-23 核对的 [MiniMax Chat Completions 官方参数](https://platform.minimax.cn/docs/api-reference/text-chat-openai)说明 M3 的 `max_completion_tokens` 最高 524288；开发配置使用该值，替代先前临时 2048。该值是接口技术上限，不是平台费用或调用配额。思考 token 也计入生成额度，见[官方兼容说明](https://platform.minimax.cn/docs/api-reference/text-openai-api)。

本策略不新增真实业务材料出站授权，不授予技能资格或 T2 执行权，也不恢复此前被拒绝的浏览器来源访问。UI 联验继续仅使用自建合成说明，经既有 Temporal → LangGraph → 模型网关运行。
