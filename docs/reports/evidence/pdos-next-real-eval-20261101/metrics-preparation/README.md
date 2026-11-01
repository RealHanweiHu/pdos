# 真实模型评测的离线指标准备

本目录只记录测量合同、离线工具与纯测试准备；不含数据库连接、服务商请求或真实模型结果。质量仍按 `docs/evaluations/xiaopai-v0/rubric.md` 的候选题规程审阅，不授予 golden-case、T0 或生产资格。

工具：`pdos-next/tools/xiaopai_real_eval_metrics.py`，仅 Python 标准库，无应用导入。执行方式：

```sh
pdos-next/server/.venv/bin/python pdos-next/tools/xiaopai_real_eval_metrics.py \
  --input /absolute/path/sanitized-export.json \
  --output /absolute/path/new-metrics.json
```

输出文件必须不存在。输出记录输入文件 SHA256，不复制模型正文、工具参数或任意 context 内容。输入方负责脱敏；不得导出密钥、连接串或凭据。

## 导出合同

根对象 `version="xiaopai-real-eval-export/v1"`：

- `cases`：可选但建议传入全部 52 题，形如 `[{"case_id":"ENG-01"}, ...]`；工具保留未产生 Run 的题数与编号。
- `runs`：`id`、`case_id` 必填；`suite` 建议 `rag40`/`context12`/`cache_probe`；附 `state`、`error_code`、`continued_from_id`、`elapsed_ms`、`first_visible_ms`、`focus`、`probe_phase`。相同题两档 F 或重复请求使用各自的真实 Run，不覆盖旧行。正文不需要传入本工具。
- `tool_calls`：脱敏的原生 AgentToolCall 行；`id`、`run_id`、`tool` 必填，导出 `created_at`、`state`、`error_code`、`provider_request_id`、`execution_binding`、`result.usage`、`result.context_budget`、`actual_input_tokens`、`actual_output_tokens`、`cost_state`、`cost_pricing`、`cost_reserved_micro_usd`、`cost_charged_micro_usd`。所有隔离域的实际模型行均保留。`tool != "model"` 的预先计数、业务和读工具不计为模型生成。
- `tool_calls[].elapsed_ms`：runner 对该次模型调用的显式耗时，可缺。原生行只有创建时间，没有完成时间；工具不推造模型耗时。
- `tool_calls[].raw_usage` + `protocol`：可选，值为实际服务商响应的 usage 对象及 `openai-compatible`/`anthropic-native`。仅保留 usage，便于分辨缓存字段缺失与显式零；须与归一化用量一致。无原始 presence 证据时，归一化缓存零为 `zero_or_unreported`。
- `events`：可选，脱敏 `[{"run_id":"...","body":{...}}]`。仅将 `context_observed` 与对应原生 `model_call_id` 关联。失败调用有明确 recorded 实际用量时可从这里恢复 input/output，失败缓存不补零。

每条模型行输出 route digest、模型版本、prompt digest、tool definitions digest、隔离域、provider request ID、真实 token、成本分桶和只含计量的上下文摘要；分 case、run、suite、隔离域、route、F、首轮/后续调用、首个/续接 Run、cache probe phase 汇总。`strata` 同时保留 case × run × isolation × route × F × 调用轮次，避免单维统计掩盖路线差异。创建时间缺失或同隔离域内相同时，调用轮次为 unknown，不用 UUID 顺序猜测。

## 计量口径

`input_tokens` 已包含缓存；不能再加 cache_read/cache_creation。OpenAI 兼容用量为 prompt_tokens/completion_tokens，缓存来自 prompt_tokens_details 的 cached_tokens/cache_write_tokens。Anthropic 原始 input_tokens 不含缓存，须加 cache_read_input_tokens 与 cache_creation_input_tokens 后与归一化 input 比较；缺字段时不凭空补出 inclusive 总量。

每种 token 均输出 known_sum、known_count、unknown_count、complete；未知结果与默认零列不冒充真实使用量。provider_cache_read 仅在有显式正 read tokens 时记命中，有显式原始零时记零，其余未知。读命中比率只有分子分母完整才计算。

`cost_state=actual` 只称“内部价卡实际用量计量”，不是服务商账单。`estimated_unknown` 的保守占账、`reserved` 的暂留分别列出；不混入实际费用。按价卡 currency × digest × configuration_version 分桶，无跨币种总和、汇率换算或估算降为零。原始价卡来源在逐调用行保留。

时延 p50/p95 采用 nearest-rank，同时列 n、缺测数、min/max。Run 端到端时延与逐模型调用时延分开。并行子任务的调用耗时相加不能当端到端耗时。`first_visible_ms` 必须说明采样端与事件；若 runner 只采到主循环首个文本事件，最终报告应称“主循环首段事件”，不能说浏览器已显示。没有采样则 null。

## 最小缓存与时延对照

1. 固定实际 route/模型版本、输出上限、prompt/tool digest、技能与生产前缀，留模型配置和价卡版本。上下文两档 F 仍只使用题集规定的隔离路线声明，不改真实连接或产品 prefix。
2. 选择少量既有稳定题，按“首次请求 → 同会话续轮 → 独立会话重复”保留各自 Run、顺序、间隔和 scope；各自单列 main 与隔离子任务的调用。仅初始顺序并不能证明 cache cold，命中以服务商 usage 为准。
3. 同题普通重复可作为延时/费用的描述性对照；不能因为更快或 token 总量相同就称 provider cache hit。若路线只返回零或不报告，明确写路线缓存指标不可判，继续报告已知实际 input/output 与价卡费用。
4. 服务商隐含跨请求缓存和小样本时延噪声仍可能存在；记录逐次原始数据，不从 12 题或少量重复推导稳定显著收益。不得为了制造缓存或 F 压力修改生产固定前缀、绕过隔离或扩大携带来源。

### MiniMax-M3 的透明观察位置

主会话已核对本次真实路线为 OpenAI 兼容 MiniMax-M3、`https://api.minimax.cn/v1`、自动 MiniMax codec、streaming=true；真实请求与费用由主会话控制，本准备工具没有发请求。

最小捕获点为 `pdos_next.providers.agent_client.parse_turn(body, route, request_id=None)`：`AgentProviderClient.turn` 在完整 SSE 聚合后调用一次，`body["usage"]` 尚未经 `_usage` 归一化。独立 runner 可透明包装该函数，只 deepcopy usage、body.id/参数 request_id、route.protocol/route.digest，再原样调用原函数并保留原返回或原异常。外层原 `turn` 包装器可通过 ContextVar 挂当前调用采样槽并测时，结束后按 request ID 关联到真实 AgentToolCall；异常未到 parse 时 raw_usage 缺失。不要记录 body 其余字段或 route 对象 repr；不要吞异常、重试、改请求或合成响应。并发情况下不能用一个未隔离的全局“最后 usage”。

不建议包装 `_usage` 作为“一次模型调用”计数：MiniMax 的 terminal usage 校验与最终 parse 可能各调用一次，容易双计；`parse_turn` 是合适的一次最终载荷观察点。此处观察的是经过服务器聚合但尚未填默认值的真实服务商 usage；不是全包网络抓取。

MiniMax 分支会屏蔽流中的中间 text_delta，完整解析后才 emit result.text；所以本路线的首段事件接近完整响应，不能称服务商 TTFT。必须在报告保留这个采样限制。

主会话本次使用用户已批的本地输出上限 524288，计划通过正常 T1 配置 W=576288/592288，对应 reserve=528288、F=48000/64000；指标按实际 context_budget 记账。候选 rubric 原配置的输出上限是 2048，因此最终报告须标注这项配置差异；两档之间保持相同实际输出上限与生产前缀。未修改候选题、rubric 或生产源。

## 质量的机械检查与审阅

可选 `runs[].mechanical_checks` 仅作已提取的 typed 值比较，结构如下：

```json
{
  "id": "F1-object-material-hardness",
  "kind": "fact_value",
  "expected": {"sample":"L-42","material":"EPDM","hardness":"70 Shore A"},
  "observed": {"sample":"L-42","material":"EPDM","hardness":"70 Shore A"},
  "observation_basis": "reviewed_extraction",
  "evidence": ["answer-and-review.json#/CTX-01/F1"]
}
```

kind 限 fact_value、identifier、source_binding、error_code、action；observation_basis 限 native_ledger、structured_output、reviewed_extraction。数值/编号/版本/来源/错误/真实动作需有实际锚点，不能以模型口头“已创建”替代业务回执。JSON 类型严格区分，例如 false 不等于 0。不从回答关键词、字符串出现或语言流畅自动判事实与语义正确。

缺 observed 或证据记 not_run；可明确标 blocked、not_applicable、needs_case_revision，均不当通过或零分。CTX-09 原题既有修订状态继续保留；CTL/CTX-10 在模型调用前正确停止只评价控制层。

开放语义保留可选 `runs[].review`：reviewer、method（human/agent_review）、rubric_version、status、dimensions、task_score、hard_fail、hard_fail_types、evidence、correction_cost。必须具名且有证据；未给审阅则 pending_independent_review。工具不使用 LLM judge；带硬失败的审阅任务分固定为 0，其余六维各自保留，不产出无法解释的加权总分。agent_review 是独立代理审阅记录，不可称真人审阅、真人修正时间或正式质量资格。真实权限、出站携带与业务动作仍以原生服务器证据为准。

参考：上下文设计 §8–9；日常问答与企业 RAG 设计 §14（指标）及 §12 A/B/C（时延观察）；候选题 rubric 的“执行层”“六维”“硬失败”“两档 F”“修正成本”。
