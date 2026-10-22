# Wave18 事实办理结果草稿

本波已接通可信宿主规则出版与部分观察 T1 的保存、原请求恢复和历史显示。当前结果限定于显式本地合成事实；**参与者完整回读、浏览器 v2 恢复预览尚待 Root 定稿，不能宣布本波完整验收通过**。本草稿仅整理主线既有证据，没有运行新检查，也不替代唯一活动清单。

## 已确认的业务结果

- 独立标记实例内保存 Rule v1、Observation v1 各一份；规则采用 host-only 出版，实际共同确认字段为空，没有公开 Rule 自授入口。[Rule 实际保存与原子组回读](actual-fact-rule-v4.json)
- 观察从已登记原记录保留实际发生钟、完整微秒和原时区，经 inputs 补齐 **19 个固定来源**，共同预览包含 13 键实质材料；HTTP 保存 200，用时 47.223 秒。[输入与预览](fact-actual-http-prepare-v1.json)、[实际保存](fact-actual-http-save-v1.json)
- 原完整请求恢复 200，用时 33.453 秒，返回同一 Receipt 和响应摘要；已保存历史 GET 200，用时 49.156 秒。读取仍是 Issue Current v6，没有追加 Issue 版本；观察的 `current_complete` 保持未知，采样与观察区间缺项未消除，原记录明确 `physical_retest_performed=false`。[原请求恢复](fact-actual-http-replay-v1.json)、[已保存事实读取](fact-actual-http-saved-read-v1.json)
- 存储回读 v5 已记录 Rule/Observation 精确 Current、完整原锚、各自唯一 Receipt/Audit/Outbox 组，以及观察原确认与保存钟；列举的 **24 张旧业务表全行摘要保持**。该文件整体状态仍为 FAIL，不能把其参与者读取部分报通过，也不能把 24 表保持推广为全库保持。[v5 回读原始结果](stored-fact-readback-v5.json)

## 分范围检查

| 范围 | 已有结果与限制 |
| --- | --- |
| 后端受影响纯检查 v7 | **244 passed / 3.31 秒**；属于选定替身与禁连接边界检查，不是 PostgreSQL 联合用例或全树验收。[原始日志](affected-backend-v7.log) |
| BFF | **29 passed**；核对路由、完整原请求、拒绝与 UNKNOWN 恢复规则，运输为测试替身，不冒充真实 API 权限。[原始日志](bff-check-v1.log) |
| 事实 UI v2 | **24 passed**；原完整选项、精确微秒时钟与共同材料核对范围。[原始日志](fact-ui-helper-v2.log)、[真实响应离线契约检查](fact-ui-actual-contract-check-v2.json) |
| Web v2 | **159 文件**，lint/build 均 exit 0，源稳定。[构建结果](web-build-result-v2.json)、[候选源](web-candidate-source-v2.json) |
| 浏览器 v1 | 已显示真实保存的 Rule/Observation 历史、实际时钟和安全默认值，亮暗截图已留存；未办理浏览器业务保存或独立复核。[读取结果](browser-fact-read-v1.json) |

这些范围互不累加为新的 PG/联合覆盖。`candidate-source-v2.json` 绑定的是当时 220 项 v6 与对应源差量，不能代替后续 244 项 v7 的候选记录；实际 Rule/HTTP 保存也按各自 manifest 和时间保留，不宣称它们在后续参与者修订下全部重新执行。[原 v2 源差量](candidate-source-v2.json)

## 保留的失败与待收口项目

Rule v1–v3 的 ValidationError、政策绑定失败和 SQL 保存失败均保留，v4 才取得实际保存结果；HTTP context v1/v2 与回读 v1–v5 原错误同样保留，没有覆盖为成功。[Rule v1](actual-fact-rule-v1.json)、[v2](actual-fact-rule-v2.json)、[v3](actual-fact-rule-v3.json)、[context v1](fact-actual-http-context-v1.json)、[v2](fact-actual-http-context-v2.json)、[回读 v1](stored-fact-readback-v1.json)、[v2](stored-fact-readback-v2.json)、[v3](stored-fact-readback-v3.json)、[v4](stored-fact-readback-v4.json)

**Root 定稿占位：**

1. 参与者 readback v5 当前为 `PARTICIPANT_OWNER_MISSING`，主线正在核对 native / uploaded / derived report 的真实登记谱系。SourceRef/DefinitionReference 与 Run 聚合/动作原子材料修订已有各自纯证据，仍须实际回读闭合；不得绕过真实原件或把原报告登记者漏出参与者集合。[来源形状差量](participants-source-shape-delta-v1.json)、[Run 原子材料差量](participants-run-atom-delta-v1.json)
2. 浏览器 v2 恢复预览正在验证。Root 将补精确新候选、原命令/读集、预览或恢复结果及是否实际提交；目前只有 v1 历史读取完成，不能提前写浏览器完结。

NamedReview 未保存，完整采样、实际配对、参与者独立性、七 owner 正向授权、有效性、关闭及 G3 均未通过。合成出版与本人的部分观察不授真实生产资格，不把旧失败材料当复验通过证据，也不改写原 Issue6、旧 Run 或既有消费/占用。下一段接线缺口与可复用边界见[真实配对交接建议](next-live-pair-handoff.md)。
