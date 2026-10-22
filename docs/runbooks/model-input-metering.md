# 模型输入计量资格与只读核验

适用：N0-03、DC-07 的逐次模型预算。实现位于 `server/app/ai/input_metering.py`，由 `ModelBudgetController.from_publication` 显式装配。默认运行工厂尚未采用，本文不代表真实模型已获计量资格或真实租户已切换预算模式。

## 资格包的信任边界

计量资格与 golden 功能资格分别成立。加载器只接受已经通过同一可信 golden suite 的 provider/model；不会写 golden、执行模型评测或自行发布资格。资格包根 JSON 的 SHA-256 必须由服务端受信配置提供，不能把模型或请求提供的摘要当成批准。

根文件是 `MeterPublicationSet`：`schema_version=1`、`golden_suite_version`、`golden_suite_digest`、`models`。每个模型须提供：

| 字段 | 内容 |
|---|---|
| `key`、`provider`、`model`、`protocol`、`base_url` | 唯一资格键及精确调用路由；协议、模型或端点改变须重新核验 |
| `implementation` | `hf_text_template.v1` 或 `anthropic_count_tokens.v1` |
| `window_tokens`、`output_token_limit`、`output_parameter` | 有来源的上下文窗口、实际支持的输出上限及参数名 |
| `max_qualified_input_tokens` | 本次证据覆盖的输入上限；加输出上限不得超过窗口 |
| `input_margin_tokens`、`input_margin_percent` | 根据供应商回执核定的保守余量，不以字符数经验公式替代计量 |
| `source_ref`、`reviewed_by`、`valid_from`、`valid_until` | 来源、审核者和明确有效期 |
| `evidence` | 相对路径与文件 SHA-256 |
| `tokenizer`、`chat_template`、`tokenizer_config` | 本地计量必需的三个固定资产，各自提供相对路径与 SHA-256；原生计数方式不设置这些资产 |

资产路径必须位于资格包目录内，拒绝绝对路径、父目录及符号链接逃逸。资产有大小限制，加载过程不下载模型、不加载远端 Python。JSON tokenizer 的 padding/truncation 被关闭；固定聊天模板在不可变沙箱中渲染完整文本，避免截断造成少算。

证据文件是 `MeterEvidence`：`schema_version=1`、匹配的 `qualification_key` 和 `cases`。每个样本记录唯一 `key`、`category`、完整合成 `messages`、`counted_input_tokens`、供应商回执的 `observed_input_tokens`、唯一 `provider_request_id` 及 `observed_at`。必须覆盖短文本、Unicode、结构化 schema 文本、接近输入上限四类；接近上限样本至少达到获准输入上限的 80%。观察时间不得晚于资格生效时间。

本地样本必须能用固定资产重算出完全相同的 counted 值；供应商观察值不得高于含余量的预留量。预留量公式为：`raw + margin_tokens + ceil(raw × margin_percent / 100)`。原生计数的历史回执由发布者核验，加载器不会在线重放。文件完整性验证不能证明回执真实性；四类样本也不能证明任意输入的误差上界，发布者须根据端点和请求形态确定保守范围、余量及有效期。

## 两种计量路径

`hf_text_template.v1` 只支持当前 `ChatMessage` 的文本消息，不支持新增多模态或 API tools 请求形态。模板渲染和 tokenizer 是本地操作。使用官方权重仓库的模板仍须对照实际托管 API 回执；两者可能有不同的封装开销。

`anthropic_count_tokens.v1` 使用精确配置端点的 `/v1/messages/count_tokens`，与生成适配器共用模型、system 和 messages 的序列化函数；禁止重定向、重试，超时 10 秒，响应上限 64 KB，计数必须是非负整数。资格加载不调用此接口；显式计量时才调用。Anthropic 官方将计数描述为估计值，可能与实际生成用量有差异，因此仍须经真实回执核定余量和覆盖范围。[官方计数说明](https://platform.claude.com/docs/en/build-with-claude/token-counting)

每次计量前后，以及预算预留后、派发前，都会复核根文件摘要、有效期和精确路由。若预留之后资格失效，取消未派发的预留，不发送生成请求。超过证据覆盖输入上限时拒绝调用，不静默截断。资产内容在加载时固定于内存；撤销已加载资格应撤销或替换根文件，不能仅改动未再读取的资产文件。

## 只读核验命令

从 `server/` 执行，传入经过审核的资格包及独立记录的根摘要：

```sh
.venv/bin/python -m scripts.verify_input_metering \
  --document /absolute/path/to/publication.json \
  --sha256 APPROVED_SHA256
```

核验器读取实际目录及 golden 可信根，检查资产、证据、路由和有效期，仅输出模型与资格摘要。不会发送计数或生成请求，也不会写入资格文件。空包返回 `verified: 0`，不代表任何模型可用。

## MiniMax-M3 候选证据采集

本次官方资产固定在 MiniMaxAI/MiniMax-M3 的提交 `f0e1c1e04d40177e4673a22097036854f536e9c0`，只下载 tokenizer、配置和聊天模板；固定文件摘要见[本地预检](../reports/evidence/2026-09-10-minimax-m3-meter-preflight.json)。[官方模板](https://huggingface.co/MiniMaxAI/MiniMax-M3/blob/f0e1c1e04d40177e4673a22097036854f536e9c0/chat_template.jinja)

下面命令只做本地预检，向 stdout 输出四个合成样本的 token 数，不写 `--output` 指定文件：

```sh
.venv/bin/python -m scripts.probe_minimax_input_metering \
  --tokenizer-dir /private/tmp/pdos-meter-m3 \
  --output ../docs/reports/evidence/2026-09-10-minimax-m3-meter-probe.json
```

只有明确批准此次真实外部调用后才可添加 `--execute`。脚本最多四次生成调用，每次输出参数上限 32 tokens，不重试；首个未知用量错误立即停止，供应商实际输出超限也停止。输出文件必须不存在；执行中逐次保存已知状态，崩溃或未知响应不能视为零消耗。报告只保留合成输入摘要及用量回执，不保存凭据或模型正文，不修改 golden 或生产。

即便四次调用完成，报告状态仍为 `observed_not_qualified`。它是候选观察证据，不是可直接装配的发布包；还需核验实际输入差额、输出参数、窗口来源和请求 ID，形成覆盖范围及余量并经人工发布。本地预检的 16,604 tokens 是估算输入量，128 tokens 是请求的累计输出上限，均不冒充供应商已确认的实际用量。

截至 2026-09-10，自动批准审查拒绝了本次四次真实请求，理由是存在外部服务和计费副作用、缺少逐次明确授权。真实调用尚未执行，等待此项授权；本地实现和验证已继续完成。
