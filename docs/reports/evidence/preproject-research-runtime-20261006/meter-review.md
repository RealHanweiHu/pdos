# MiniMax-M3真实计量与本地预算采用候选

2026-10-06（本地日期）。四次已授权校准和候选核对完成；用户随后确认正式发布，实际加载器核验通过，预算配置已固定摘要。主预览切换被3条旧未知用量阻塞；最新状态见[发布与采用记录](meter-adoption.md)。下方保留原候选参数和候选阶段说明。

## 真实结果

用户在已说明“最多4次、仅合成输入、每次输出最多32token、无自动重试”的调用范围后回复“好的”。[授权记录](meter-call-authorization.json)与[供应商观察](meter-observations.json)保留该范围和四次实际用量/request_id。没有第五次调用。

| 样本 | 本地输入计数 | MiniMax实际输入 | 输出用量 |
|---|---:|---:|---:|
| 短文本 | 187 | 187 | 32 |
| Unicode | 198 | 198 | 32 |
| 结构化schema文本 | 222 | 222 | 32 |
| 接近输入上限 | 15,997 | 15,997 | 32 |
| 合计 | 16,604 | 16,604 | 128 |

四次响应均为`provider_output_truncated`，包含实际用量及独立request_id，没有未知用量。这是到达已授权32token输出上限的采样结果，不是完整回答或产品研究质量通过。MiniMax[官方OpenAI兼容说明](https://platform.minimax.cn/docs/api-reference/text-openai-api)说明`max_tokens`包含思考token，设置较小时可能出现`length`及空正文；它同时给出MiniMax-M3的1,000,000上下文窗口。

四条完整合成输入已从脚本重建，逐条输入SHA-256、tokenizer计数与真实观察相同；证据符合`MeterEvidence`结构，固定资产摘要重新核对通过。见[候选检查](meter-candidate-check.json)。四条样本一致并不能证明任意输入的误差上界，资格范围保持为当前确切端点的纯文本消息。

## 待确认的采用参数

| 项目 | 候选值 |
|---|---|
| 模型/端点 | MiniMax-M3 / `https://api.minimaxi.com/v1`，维持本次实测路由 |
| 输入形态 | 纯文本ChatMessage；不覆盖多模态或原生API tools |
| 输入上限（含预留余量） | 17,000 token；本次最长实测15,997，加入余量后16,861 |
| 输入预留余量 | 固定64 token＋5%；为试用提出的保守余量，未宣称统计误差上界 |
| 输出参数/上限 | `max_tokens` / 4,000 token，按现有研究档位提出；实测仅覆盖32token参数生效，4,000未另做真实测试 |
| 有效期 | 拟从具名批准起7天；到期须复核，不自动延长 |
| 运行预算档位 | 现有获批`research_discussion`：最多10次模型/40次工具调用、900秒活动时间、同一研究总额360,000token；沿原并发、重试与续接守卫 |
| 本次采用范围 | 本地API应用模型通道；不等同生产启用、产品八能力资格或人工Exit |

本候选只提出上述参数，不更改已冻结的预算政策。预算档位内的32,000输入上限仍受较小的计量覆盖限制；有效输入按17,000含余量执行。现有预算以token为硬限，没有新增金额硬限。

## 具体文件与验证

完整候选放在本机私有目录（目录700、文件600）：

- [计量候选JSON](/Users/huhanwei/pdos-preview-config/input-metering/minimax-m3-20261006-candidate/publication.candidate.json)
- [四条可重算证据](/Users/huhanwei/pdos-preview-config/input-metering/minimax-m3-20261006-candidate/evidence.json)
- [预算配置候选](/Users/huhanwei/pdos-preview-config/input-metering/minimax-m3-20261006-candidate/budget.env.candidate)
- [完整复核说明](/Users/huhanwei/pdos-preview-config/input-metering/minimax-m3-20261006-candidate/review-plan.json)

原候选JSON中的`reviewed_by`、`valid_from`和`valid_until`为空；候选检查点时正式`publication.json`不存在、预算摘要标为待审核，实际加载器拒绝这些空字段，见[候选边界检查](meter-candidate-boundary-check.json)。用户确认后独立正式文件已发布并只读核验；主预览私有配置仍legacy，详见[最新采用记录](meter-adoption.md)。

## 采用前剩余动作

由具名人员核对上述真实回执及候选参数，并明确批准发布。随后按批准的署名和有效期生成正式文件，将最终摘要作为受信部署配置固定；运行时不能自行计算待加载文件摘要后信任。

正式包已通过只读核验；沿[模式切换手册](../../../runbooks/application-budget-adoption.md)核对目标租户后发现3条旧未知用量，见[切换前检查](adoption-preflight.json)。用户已确认本地启用及一条合成公开研究验证，授权保留；仍未切换租户、改私有`.env`、重启主预览或再次调用模型。真实搜索→原文→引用候选→保存整链和公开DNS仍待阻塞恢复后验证。
