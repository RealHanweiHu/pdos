# N0-03 Provider 用量与受限调用验证

2026-09-10。继续已批准 DC-07 的预算接入。N0-03 仍部分完成；本片交付真实协议适配器、Gateway 的显式受限调用接口与失败用量记录，不代表预算账本已接入默认运行装配。

## 实际变更

- Anthropic 输入 token 统一为普通输入、缓存读取、缓存创建之和；缓存字段仍保留为分项。原来 9 普通输入 + 5 缓存读 + 3 缓存写会记录 9，现在记录总输入 17。依据 [Anthropic 官方用量定义](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)。OpenAI 兼容响应保留 prompt_tokens 总量，不重复加 cached_tokens，并拒绝缓存量超过总输入的非法用量。
- 两种适配器先解析可核验用量，再验证正文。正文缺失、空内容或输出截断时，错误携带本次用量与请求标识。Gateway 将其与此前结构化重试用量相加一次，追加到现有 model_invocations；错误金额继续为 NULL/unknown。无有效 usage 或传输失败时，不伪造已知用量。
- OpenAI `finish_reason=length`、Anthropic `stop_reason=max_tokens` 会降级且不重试；即使截断正文恰好是可解析 JSON，也不作为成功业务候选。
- 新增 `ProviderCallLimits` 与 `complete_bounded`。OpenAI 兼容协议必须由可信服务配置明确选择 max_tokens 或 max_completion_tokens；Anthropic 使用 max_tokens。上限必须为正整数，不能由指令正文覆盖。参数支持须由具体 provider/model 资格决定，不能仅凭协议名推定。MiniMax 文档存在 [max_completion_tokens 接口](https://platform.minimax.io/docs/api-reference/text-chat-openai)，这不是任何本地模型的资格证据。
- Gateway 可接收以 provider/model 为键的受限配置，复制后固定；每次结构化重试都走有上限接口。显式启用后，模型配置缺失、协议字段不匹配或适配器不支持均在调用前降级；不回退到旧接口。默认应用/Agent 工厂尚未传入此配置，旧方法保持兼容。
- 0061 仅扩展费用一致性约束：`PROVIDER_OUTPUT_LIMIT_UNCONFIGURED` 且零调用次数、零普通/缓存用量、零金额、无价格快照可记为 not_invoked。已有数据不重写。有此类新证据时拒绝降级；空表可往返。Schema 与迁移同步，不修改 0059/0060 原迁移。

## 验证

本机 `127.0.0.1:57432/pdos_test`、PostgreSQL 16.14，起始 0060，测试后 head 为 0061_provider_admission。仅该测试库迁移；HTTP 用本机模拟服务，未调用真实模型或访问开发/生产库。

| 范围 | 结果 |
|---|---|
| 适配器、用量与上限单元测试 | 38 passed |
| Gateway、真实 HTTP、费用 Schema/迁移、原子预算账本 | 53 passed |
| 共同对象、产品计划、版本时间、运行政策、工具、采用与日历 | 160 passed |
| 合计 | 251 个不同测试全部通过 |
| Ruff / 格式 | 11 个本片相关文件通过 |
| Mypy | provider_adapters、gateway、schema 三个实现文件通过 |
| 当前合同导出检查 | N0-01 四产物、N0-02 五产物通过；获批快照校验未变 |

测试覆盖两个协议的缓存统计、有效用量但非法正文、截断的合法 JSON、非法/缺失 usage、真实 HTTP 请求中的限额字段、逐重试限制、正文诱导无法改限额、配置被调用者修改后不漂移、无配置零调用和失败用量持久化。DB 负向覆盖非零普通/缓存用量、非零调用次数、NULL 金额和普通传输失败不能冒充未调用；迁移覆盖旧费用历史、预算历史与新证据的降级保护。

初轮数据库验证为 17 passed / 3 failed：旧费用约束仅接受预算耗尽的 not_invoked，阻止新配置拒绝留痕。随后新增 0061 与明确的零调用证据约束，最终上述 53 项全过。机器摘要、执行文件与当前/获批合同摘要见 [证据](evidence/2026-09-10-n0-03-provider-metering.json)。

## 接入剩余

预算账本仍需实际 provider/tool 的逐 attempt 预留、派发和回执对账；模型上下文窗口与输入计量资格、运行 profile 的交集、存量 model_invocations 与新账本防重复计量、受限数据库角色服务接口及活动租约尚未完成。HTTP 错误或丢失响应没有可信 usage 时仍需要账本 unknown 持有及后续对账，不能按当前聚合 trace 释放预算。已记录的历史 Anthropic 用量不反写，采用预算账本时必须显式处理历史计量差异。

持久 rollout/bundle 与跨进程撤权、完整工具循环、来源 ACL/checkpoint 恢复仍按 N0-03 推进。N0-06/N2-01 及 P/Q/Sprint 出口状态不变，无生产部署、真实外发、git push 或 golden 变更。
