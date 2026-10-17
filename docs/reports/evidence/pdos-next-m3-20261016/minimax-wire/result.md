# MiniMax M3 原生工具与私有协议续接

基于 `895cf52`，为小Pai补齐用户指定的国内 MiniMax M3 文本接线。官方 OpenAI 兼容地址使用版本化 `minimax-functions/v1`：原生 function schema 回传结构化结果，请求 `reasoning_split=true`，继续保留服务器结果校验。格式纳入路由及模型资格身份；其他地址原格式保持。具体取舍及[官方合同依据](https://platform.minimax.cn/docs/api-reference/text-chat-openai)见[联验草案](../../../../runbooks/minimax-cn-m3-validation-draft.md)。不将未列出的 `response_format` 参数当成已证明不支持。

原始 content、reasoning_content 与原生工具消息在私有调用账本和 LangGraph 检查点中保留，重启和账本重放后恢复原消息。内部输出 function 的回读只表示收到模型结果，不是批准或领域回执；它不能与业务动作混用。MiniMax 流式文本完整解析后才发布可公开内容，分离或内联思考片段不进入公开事件。现有取消、大小/超时、费用和不确定调用不重发规则保持，无新业务表或资格授予。

## 必要验证

| 覆盖 | 结果 | 证据 |
| --- | --- | --- |
| MiniMax 合成 HTTP/SSE、原两协议、网关、图和检查点 | 58 通过 | [minimax-pure](minimax-pure) |
| 上下文、短记忆、研究/抽取/MCP、资格、预算与模型配置 | 122 通过 | [affected-corrected](affected-corrected) |
| 私有续接的调用账本直接重放 | 1 项重叠补验通过，模型替身仍只调用一次 | [saved-call-replay](saved-call-replay) |
| 默认宿主、实际 Worker/Temporal/PG 与 T1 提案 | 1 个实际进程病例通过 | [进程验证](process/minimax-process)、[首次 Worker](process/minimax-worker-0.log)、[重启 Worker](process/minimax-worker-1.log) |
| 最终 Ruff | 通过 | [ruff-complete.log](ruff-complete.log) |
| 真实回执、草稿来源及技术收尾 | 通过 | [只读核对](close-status-corrected)、[结构化结果](runtime-status.json) |

合计 **181 个不同病例**，按[病例集合](cases)去重，不累加补验。[最初收集命令](affected-backend)写了不存在的测试文件，零病例执行；修正路径后上述 122 项通过。没有前端或迁移改动，本批未重复浏览器、前端构建或攻防，不称为完整 M3/S1 验收。

## 实际本地闭环

默认 API 与 Worker 不注入完整适配器，只将 KMS SDK 和模型 HTTP 替换为明确合成端口；生产请求构造、SSE 解析、图、账本及费用路径实际执行。三次合成原生 HTTP：提问 → 停掉 Worker → 离线提交本人答复 → 启动第二个 Worker → 提案候选 → 结构化完成。仍为同一 Temporal execution 和同一 PG 检查点线程，恢复后能核对原思考/工具消息及协议回读顺序。

本人预览/一次确认后，实际保存 **1 份私有草稿提案、1 份绑定原 Run 的提案回执**；同请求重放返回原回执。提案 `created_by_run_id` 保留 AI 草稿来源，负责人仍为本人，T1 回执具名确认人为本人。私有协议数据不成为业务批准。详情、事件、处理过程和 SSE 均未返回合成私有思考标记；原标记在私有模型调用与持久检查点中完整存在。

账本输入 90、输出 60（其中包含思考用量）、缓存读取 15，共 150 token；不把 reasoning breakdown 再加一遍。按合成费率计 **639 微美元**，属于本地已知用量测试账，不是真实费用。实际 Run 已完成、token/金额占用归零、专用 namespace 无运行中工作；两个自有 Worker 已结束，共用服务与合成历史保留。

独立目标始终为已核对 marker 的 `127.0.0.1:64245/pdos_test` 与同标记检查点库，head `s0_0772`；没有 `.env` 回退或数据迁移。只读收尾脚本[初次核对](close-status)把 T1 回执执行人误当成 AI 来源，修正为核对“本人确认 + 原 Run 的 AI 草稿来源”后通过，未改业务事实或规则。

## 真实条件仍保留

HTTP 为 `httpx.MockTransport`，KMS 为 SDK 替身；真实模型调用 **0**、真实 KMS 请求 **0**、golden-case 写入 **0**、push/生产操作 **0**。本批证明本地协议与持久恢复，不能证明真实 M3 对工具/schema 的遵循、线上兼容性、账号限额、实际费率或适用资格。

原 MiniMax 草案仍未登记/启用，价格仍过期且未核对，用户说明没有协议。实际凭据、价格/计费边界、适用资料协议或范围及对应外发授权、真实模型资格与三入口/完整 M3/S1 出口仍待完成，S2–S4 按冻结顺序保留。

源码与候选范围见 [source-manifest.json](source-manifest.json)、[checkpoint.json](checkpoint.json)。
