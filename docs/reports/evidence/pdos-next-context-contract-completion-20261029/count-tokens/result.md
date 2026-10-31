# Anthropic 近阈值计数与缓存事实传递

上下文设计 §6.1 的近阈值预先计数已接入登记的小Pai网关，真实服务商调用保持关闭。仅使用 `httpx.MockTransport`；不是服务商资格、真实窗口、缓存命中率或模型质量验收。

## 行为与边界

- 先执行生产 `fit_messages` 的现有估算、15% 余量和可恢复缩减；仍超预算则停止，不借远程计数绕过原准入。
- Anthropic 路线已准入内容的 `admission_tokens >= 90% × focus` 时，正式模型预约后执行 `POST <已配置base_url>/messages/count_tokens`。传入与实际生成相同的 native model/system/messages/tools/output_config，仅去掉生成专用 max_tokens/stream。
- 计数也是资料出站：沿用同一 host 绑定、注册执行图、当前主体/范围、取消 epoch、已加载技能、路由、数据类别及协议；计数预约后、计数返回后与生成前复核。计数失败、响应无效、重定向、计数超过 F 或权限/配置变化，均不调用生成端点，不走错误路径模型降级。
- `model.count_tokens` 是独立技术 ledger，`kind=unbound`、`dispatch=anthropic-count-tokens/v1`，内嵌同一完整 ModelBinding；结果仅 `input_tokens`，reservation/usage 为零，无业务 READ、引用、候选或领域 Receipt。成功计数的 call ID 与 `provider_counted_input_tokens` 保存在模型上下文预算中。
- 计数不是生成实际 usage，不写入实际 input/output tokens，也不作为上下次估算校准。后续校准仍只取生成端点真实返回 usage；测试中的计数900与生成输入30分别保留。
- 三处 Anthropic `cache_control`（固定 system、首个信封、最新消息）仅按服务器 `EgressDecision.prompt_cache_allowed` 写入；False 时全部省略。生产 wire/hash 与实际发送通过相同的 host policy 上下文绑定，旧 synthetic client 的显式 `turn` 参数保持兼容。模型文本及 retention_terms 自由文本不授予缓存许可。
- True 使用既有默认 wire/hash 表示，保持旧调用 key 可恢复；False 明确加入请求 hash。缓存许可变化时，在当前受限且加锁事务仅查同一 run 的当前/相反缓存状态两个精确 model key，再由原 claim 恢复已完成结果或拒绝 started/unknown。回放不生成新调用，不以改变缓存字段绕过未知结果守卫。

官方说明：计数端点接受与消息相同的输入并返回 input_tokens，不创建回答；计数本身不使用 prompt caching，官方仍将其称为预先估计，不能冒充生成的计费 usage。[Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)、[Count tokens API](https://platform.claude.com/docs/en/api/typescript/messages/count_tokens)。

OpenAI 兼容接口没有本实现可通用控制的显式 cache_control；本次没有宣称能关闭服务商自动前缀缓存或所有留存。具体服务商是否支持计数、实际窗口及数据处理资格仍须按原授权另验。

## 已验证

最终离线受影响组 **119 passed in 32.17s**，原始输出见 [offline.log](offline.log)；五文件 Ruff 与差异检查通过，见 [ruff.log](ruff.log)。

覆盖：同 native 输入预先计数、90%F 触发/远离阈值不计数、登记图限制、同 host endpoint、严格非负整数、429/无效响应/重定向停止、超 F 停止、计数预约后路由变化、计数后的类别/许可/取消变化、所有缓存标记开关、旧显式 client 接口、生成 usage 与计数分离、成功回放不重发，以及缓存 True→False 后 completed/started/unknown 的原 key 守卫。其余既有检查覆盖 native协议、上下文预算、完整初始披露与模型执行绑定。

供主会话统一运行的 PostgreSQL 案例：`tests/agent_kernel/test_anthropic_context_count_pg.py`。通过原生具名协议 v1 True→v2 False 修改服务器许可，检查同 run 重放同一 model call ID、仅两条 ledger、技术计数 usage0、模型累计37 tokens及0新增 HTTP/计数/费用。**本子代理未执行数据库；PG 结果以主会话集中证据为准。**

## 复现

在仓库根目录使用现有 server venv，以下离线组无需数据库变量或 `.env`：

```sh
PYTHONPATH=pdos-next/server:packages/pdos-agent-runtime/src \
  pdos-next/server/.venv/bin/python -m pytest -q \
  pdos-next/server/tests/agent_kernel/test_anthropic_context_count.py \
  pdos-next/server/tests/agent_kernel/test_native_protocols.py \
  pdos-next/server/tests/agent_kernel/test_context_admission.py \
  pdos-next/server/tests/agent_kernel/test_context_budget.py \
  pdos-next/server/tests/agent_kernel/test_context_x3_full_disclosure.py \
  pdos-next/server/tests/agent_kernel/test_execution_binding.py
```

主会话核对独立 `pdos_test`、升级到包含协议缓存列的真实 head 后，再集中执行上述 `_pg.py`。未执行真实 count/message/embedding 请求、迁移、生产操作、git push 或业务外发。

## 主会话实际验证补记

主会话统一缓存/计数PG组12项全部通过，见[最终PG XML](../pg-cache-count-run3.xml)。其中本文件准备的原生计数恢复案例通过；最终受影响纯组236项通过包含上述119项，不重复累计。没有真实服务商调用。
