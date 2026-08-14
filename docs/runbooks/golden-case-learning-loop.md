# Golden-case 人工学习环

运行时只读 `server/golden/` 下已审核的可信根。任何 Agent、worker、Web/API 进程及 CI 都不得自动改写 golden case、通过阈值或模型资格；自动化只允许产出候选报告。

## 人工修正积累

1. Reviewer 在 AI Review 中作出 Accept/Edit/Reject；Finding、Finding Action 与 `AI_FEEDBACK_RECEIVED` 是原始事实，不自动进入可信根。
2. 定期由人抽样修正，将候选 JSON 放入 `server/golden/correction-candidates/`。候选必须去标识、保留最小结构化上下文与明确期望结果，不复制原文、密级字段或对象存储键。
3. 人按失败归因顺序判断载体：事实进入 verified memory；策略变化形成 prompt 最小 diff；确定性约束进入代码/schema。不得把所有修正堆进 prompt。
4. 两人审核候选后，才可手工并入版本化 golden suite；更新 suite version/digest 并全量重跑。运行时和 CI 不提供“自动晋级”写接口。
5. Prompt 或模型发布前必须全量 100% 通过；失败即不发布。`model-qualifications.json` 只能由授权人基于评测报告手工更新。

## 只读与门禁

- `python -m scripts.evaluate_model --provider <provider>` 只输出报告，不写资格文件。
- `server/golden/phase-one-agents-v1.json` 固定 Phase 1 Agent 的正例、无据拒答与输出类型。
- `server/golden/model-gateway-v1.json` 的 `pass_threshold` 固定为 `1.0`。
- 代码评审必须拒绝：运行时代码写 `server/golden/`、自动 prompt 重写、自动降低阈值、基于未经人验文档固化经验。
