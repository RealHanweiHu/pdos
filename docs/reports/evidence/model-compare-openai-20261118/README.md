# OpenAI luna 接入与首轮对比（2026-11-18）

用户 11-18 提供 OpenAI API key，要求接入并做性能对比，默认使用 luna 模型。本目录记录接入改动、真实对比结果和剩余事项。登记项见清单 D614。

## 结论

- **默认 luna 模型取 `gpt-6-luna`**（该 key 可见的两个 luna 里较新的一个，另一个是 `gpt-5.6-luna`）。
- **必须关推理才能在现有网关上用**：`gpt-6-luna` 在 Chat Completions 上带函数工具时，只接受 `reasoning_effort: "none"`，否则 400（原文：Function tools with reasoning_effort are not supported … use /v1/responses or set reasoning_effort to 'none'）。网关原来不发这个字段，已新增 `openai_reasoning_effort` 选项。要推理和工具同时开，需要另做 Responses API 协议，见下文“是否值得做 Responses”。
- **速度和成本明显好于 MiniMax-M3**（同一首轮请求）：首字中位数 3.6 秒对 10.1 秒，单次 0.0007 美元对 0.0105 美元（约 1/14；luna 价格来自第三方，见“价格”）。OpenAI 自动缓存命中 87%，M3 30%。
- **行为差异大，质量没有人工评**：M3 对 24 道通用题里 21 道先查资料（`assistant.search`、`category.knowledge.list`），回答长而完整；`gpt-6-luna` 关推理时回答很短（摘要中位数 60 字），通用题直接回答 9/24。哪种更对，需要 D30 的人工审阅，这里不下结论。
- **出站路径是上线前最大的问题**：产品网关不走环境代理，在本机直连 OpenAI 连不上（见第 6 节第 2 项）；对比脚本经本机 `127.0.0.1:7897` 代理，96 次里仍有 8 次在建连阶段失败（M3 32 次里 1 次）。生产在阿里云杭州 ECS，能否直连 OpenAI 没有核实。

## 1. 接入改动

| 位置 | 改动 |
|---|---|
| `providers/types.py` | `ProviderRoute.openai_reasoning_effort`（`none` / `minimal` / `low` / `medium` / `high` / `xhigh`，缺省不设）。只允许 OpenAI 兼容协议；设置后进入路由摘要，缺省时旧摘要不变 |
| `providers/agent_client.py` | 设置时请求体带 `reasoning_effort` |
| `schemas/model_configuration/dto.py` | `ModelMetadata` 同名字段；`binding_metadata` 在缺省时去掉该键，已保存配置的绑定摘要不变 |
| `agent/kernel/qualification_binding.py` | 设置时进入模型资格身份：换推理强度不继承原资格 |
| 设置页 | 「添加服务商」高级选项和模型配置表单各加「推理强度」下拉，缺省“不发送”；切到 Anthropic 协议时清空 |
| 合同 | 重新导出 `openapi.json`、`payloads.schema.json`，目录校验通过 |
| 手册 | [租户模型宿主配置](../../../runbooks/pdos-next-tenant-model-runtime.md)接口选项表加一行 |

验证：`test_openai_compatible.py` 新增推理强度请求体 3 例，扩展旧配置兼容、资格身份和非法组合用例；模型配置、协议相关 342 项通过。另有 30 项需要 `TEST_DATABASE_URL` 的库测试没有跑；`test_context_x3_full_disclosure.py` 1 项失败，撤掉本次改动后同样失败，与本次无关（来自工作树里其他会话未提交的上下文改动）。前端模型配置 36 项通过（`render.test.mjs` 表单字段数 12 → 13，并检查新下拉）。Ruff、TypeScript、ESLint 通过。

密钥：存在本机钥匙串（本地开发 KMS 路径），服务名 `pdos-next-openai-cc94e32d-ea35-4115-860b-8a784645f61f`，引用 `acs:kms:local:0:secret/pdos-next-openai-cc94e32d-ea35-4115-860b-8a784645f61f`，版本 1。仓库和日志里没有密钥。

## 2. 对比方法

- 脚本 [`scripts/compare_run.py`](scripts/compare_run.py)，汇总 [`scripts/compare_analyze.py`](scripts/compare_analyze.py)，汇总输出 `output/summary.txt` 按 `.gitignore` 留在本机，用汇总脚本可从逐次记录重新生成。逐次记录在本机 `.local/model-compare-20261118/`，不进仓库。
- 直接调服务商接口，不经注册执行图。每个配置收到相同的系统提示（提示词 1.0.0）、67 个工具定义、信封和 `proposal_drafting` 技能正文，取自 11-16 缓存探针的 `002-A` 请求，即当时产品实际的摆放；只换问题。
- 16 道合成题 × 2 轮 × 4 个配置，128 次，输出上限 16,384（与产品 `OUTPUT_BUDGET` 相同）。题目：11-16 探针的 12 道通用题，加 4 道工具题（竞品、参数、知识库，以及“直接替我批准 G0”，期望不调用 `proposal.g0.decide`）。
- 只看首轮：模型调了业务工具就记“调工具”，后续轮次和最终回答不在本次范围。
- 配置：

| 代号 | 模型 | 接口 | 推理 |
|---|---|---|---|
| M3 | MiniMax-M3 | Chat Completions（现行） | 开（`reasoning_split`） |
| L6 | gpt-6-luna | Chat Completions | `none` |
| L56 | gpt-5.6-luna | Chat Completions | `none` |
| L6R | gpt-6-luna | Responses API | `medium` |

## 3. 结果

| 指标 | M3 | L6 | L56 | L6R |
|---|---:|---:|---:|---:|
| 调用 / 网络失败 | 32 / 1 | 32 / 2 | 32 / 3 | 32 / 3 |
| 首字时间 p50 / p90（秒） | 10.1 / 20.3 | **3.6 / 4.2** | 3.3 / 4.2 | 4.4 / 6.1 |
| 总时长 p50 / p90（秒） | 10.7 / 21.3 | **4.2 / 5.5** | 5.4 / 11.0 | 5.2 / 7.8 |
| 输入 token p50 | 41,010 | 28,755 | 28,756 | 28,673 |
| 缓存读取占比 | 30% | 87% | 87% | 87% |
| 输出 token p50（其中推理） | 708（599） | 67（0） | 273（0） | 140（75） |
| 单次费用（美元） | 0.0105 | **0.0007** | 0.0017 | 0.0008 |
| 本批费用（美元） | 0.336 | 0.023 | 0.054 | 0.024 |
| 通用题直接回答 | 3/24 | 9/24 | 18/24 | 10/24 |
| 工具题调到期望工具 | 5/6（1 次网络失败） | 6/6 | 6/6 | 6/6 |
| G0 题未调用决定工具 | 2/2 | 2/2 | 2/2 | 2/2 |
| 收尾结果格式错误 | 0 | 0 | 1（把收尾 JSON 当正文输出） | 0 |
| 直接回答摘要长度 p50（字） | 925 | 60 | 39 | 47 |

- 同一请求 OpenAI 计 28.7k token，MiniMax 计 41.0k：分词器不同，比较费用要看美元，不看 token。
- 通用题上 M3 先调的工具：`assistant.search` 20、`category.knowledge.list` 12、`category.read` 5、`skill.load` 4。L6 只调 `assistant.search` 11、`skill.load` 2。
- G0 题：三个 OpenAI 配置都直接说明“不能代你批准，须具名评审人本人办理”；M3 先查对话历史和平台信息，找“刚才那份”提案。
- **L6R 有 1 次在通用题（“怎样把大任务拆成子任务”）调用了 `work.stage.decide`**。这是 T2 操作（`governance/schemas.py:77`），服务器不会让 AI 执行，守卫成立；但模型选错到决定类工具，接入推理版本前要盯住。
- 网络失败全部发生在建连阶段（SSL 握手超时或代理断开），请求未发出，不计费；集中在开跑后 4 分钟内。回答并排见 `output/summary.txt` 后半部分。

## 4. 价格

OpenAI 官方定价页本次无法读取（developers.openai.com 断开连接，openai.com 返回 403）。分析用的是多家第三方汇总一致的数：`gpt-6-luna` 输入 0.10、缓存读取 0.01、缓存写入 0.125、输出 0.50 美元/百万 token；`gpt-5.6-luna` 0.20 / 1.20，缓存读写按 10% / 125% 估。以 OpenAI 账单为准，进价格卡前要再核对一次。来源：[eesel](https://www.eesel.ai/blog/gpt-6-luna-pricing)、[LLM Gateway](https://llmgateway.io/models/gpt-6-luna)、[braindetox](https://braindetox.kr/en/posts/gpt6_sol_luna_release_2026.html)。

## 5. 是否值得做 Responses

本次 L6R（推理 `medium`）比 L6（`none`）多用约 70 个推理 token，首字慢 0.8 秒，费用几乎相同，回答在部分题上更具体（如“风险清单排序”给出了分级规则）。差别不大，且样本只有首轮。先用 L6 接入；要不要做 Responses 协议，等真实多轮评测看出关推理是否掉质量再定。

## 6. 剩余

1. **在设置页添加连接**（租户管理员本人办理，T1 一次确认）：「设置 → 小Pai与模型 → 模型配置 → 添加服务商」，Base URL `https://api.openai.com/v1`，模型 `gpt-6-luna`，高级选项：响应格式“工具调用”、输出参数 `max_completion_tokens`、推理强度 `none`；价格按第 4 节填写并核对。保存后「切换使用」。本次没有代填：页面要求在专用输入框提交真实 Key，且切换会改变共用预览环境的当前模型，其他会话的评测在用。
2. ✅ **出站代理已接（11-18 同日，用户同意）**：宿主配置新增 `egress`，按精确主机名指定代理（不带凭据，只认 http/https），每次调用重读；模型网关按目标主机选代理，其他服务商仍直连，环境变量代理仍不生效；经代理的调用在 `egress_checked` 记 `egress_via`。改动在 `model_configuration/host.py`（`EgressProxy`、`egress_for`）、`providers/agent_client.py`（按代理各建一个客户端）、`kernel/gateway.py`、`kernel/host.py`、`kernel/bootstrap.py`（只加传递）。新增 `test_egress_proxy.py` 18 例，模型配置与协议 186 项通过。实际验证：临时宿主配置 `api.openai.com → 127.0.0.1:7897`，经 `TenantRuntime.egress_for` 与网关客户端调 `gpt-6-luna` 成功，3.2 秒返回工具调用。本机预览用的 `.local/comprehensive-minimax-20261023.json` 已加同一条目（原文件备份在会话临时目录），当前没有运行中的进程读取这份文件。说明见[手册「出站代理」](../../../runbooks/pdos-next-tenant-model-runtime.md)。以下为原记录：
   **产品网关在本机连不上 OpenAI**：`AgentProviderClient` 有意设 `trust_env=False`（`agent_client.py:450`），不走环境变量里的代理，于是直连 `api.openai.com`，本机三次都在建连阶段超时（MiniMax 可直连，所以以前没暴露）。只在验证脚本里显式传入 `httpx.HTTPTransport(proxy="http://127.0.0.1:7897")` 后，同一网关客户端对 `gpt-6-luna` 流式、非流式各 1 次都成功：解析出工具调用 `category.read`、用量 203 输入 / 15 输出、请求号和计时（首字约 3.9 秒），证明请求体与解析可用。要在产品里用，需要一个由服务器配置、按模型记录的显式出站路径（代理或海外 OpenAI 兼容网关），不能改成信任环境变量。经注册图的真实多轮评测在这之后做。
3. **生产出站**：阿里云杭州 ECS 到 `api.openai.com` 的可达性与合规没有核实；OpenAI 是否允许该地区使用由你确认。
4. **建连失败被记成“结果未知”**：网关把 `httpx.ConnectTimeout` 等请求未发出的错误也按未知结果占账（`agent_client.py` 末尾的 `except`）。和 D612 一起处理。
5. **上下文校准**：`context_calibration.json` 没有 OpenAI 路线的实测，按 1.15 缺省；OpenAI 分词更省，缺省偏保守，不阻塞。
6. 本次不授予 golden-case、T0、模型白名单或生产资格。
