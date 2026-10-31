# 上下文恢复与延续技能收口

两处设计实现已补齐并通过受影响验证。预算停止后可明确选择“保留工作状态另开会话”：服务器复制最新可信版本，保留本人原话证明、删除墓碑、排除/纠正条件，以及候选与引用的原始证明；新会话不携带旧消息和检查点。普通新建会话仍从空状态开始。

恢复状态携带全部已读资料的权限依赖，包括未引用的检索候选。受理和模型前仅批量复核 metadata，撤权拒绝，内容更新允许继续；内部 ACL 不进入公共界面或模型投影。两次恢复及中间普通续聊仍只可使用封闭的原始引用和候选，不能靠 session ID 取得跨会话读取权。

延续技能按上轮实际加载的最近两个版本显示，可在发送前移除且不补第三个；当前停用、版本或 digest 改变会明确拒绝并保留可编辑输入，人工可改选当前版本。受理后再次复核。恢复入口保存完整固定技能选择，即使为空，也不会被默认预载补回。

| 验证 | 实际结果与证据 |
|---|---|
| 后端纯检查 | [133项](restart-pure-final-v3.xml) + [35项](skills-restart-cross-checks/pure.xml)，去重168项；另有[1项真实脚本类型检查](restart-fixture-model-copy-offline.log) |
| PostgreSQL/API | 去重60项通过：run2中4项不变的恢复用例，加[run4的56项](native-run4/tests.xml)，299.58秒；不是同一进程全量重跑 |
| 前端与BFF | [35项交互/请求恢复](restart-ui-run3.log) + [5项技能选择](skills-independent-checks/invocation.json)；[88项实际BFF handler](restart-bff-run2.log) |
| 构建与静态检查 | TypeScript、Ruff、目标ESLint零警告、目标diff检查通过；[758输入生产构建](frontend-build-result.json)通过，使用既有真实字体文件离线构建 |
| 合同 | [目录一致性](contracts.log)通过；[实际离线OpenAPI导出](contract-export-result.json)成功，仅同步StartInput的两个新字段，[差异与SHA](openapi-sync.json) |

原生复核使用已核对的53502/pdos_test，marker f117bb5b-b3d7-4286-aaec-c54d9255e96b，head保持s0_0854，无迁移。两轮之间生产输入不变，153项原生候选输入及758项构建输入均已核对；[标准库独立复算](recompute-checkpoint.py)、[逐项结果](independent-summary.json)、[结束SHA](native-run4/input-verification.json)可复查。原生组的10个warning为已有SQLAlchemy Session.flush弃用提示。

新增夹具的三次失败保留：[run1](native-run1/native.log)试图恢复withdrawn来源，被终态守卫正确拒绝；修为两组独立来源后，[run2](native-run2/native.log)暴露ToolCall误用dataclasses.replace，已改真实Pydantic model_copy并离线执行检查；[run3](native-run3/native.log)已到达预期撤权拒绝，但把reason当成canonical code，现同时核对FORBIDDEN_SCOPE及CONVERSATION_HISTORY_REVOKED。只修改夹具/断言，生产守卫未变；末次目标与未执行的回归组全部通过。

这里的通过是机制与本地合同验证。所有provider均为脚本控制，真实模型、embedding、渠道和生产均未调用；未新增提交或推送。原六项既有失败的修复证据保持在[此前检查点](../pdos-next-slice-a-x1-20261028/result.md)，不把历史通过计成本轮重跑。

52道候选题与24份合成资料见[题集入口](../../../evaluations/xiaopai-v0/README.md)；原28道HTTP关键词题的24道正向macro recall@5为97.92%、@10为100%，来源加权为96.43%/100%，4权限负向和4编号控制通过，QUA-04报告仍为第10。来源权限物化和ANN诊断见[实测](../pdos-next-ann-quality-performance-20261029/result.md)：四配置无稳定ANN收益，默认继续关键词。

尚未完成：CTX-09同绑定3→6/9分页场景仍partial；CTX-12低预算真实停止不算最终回答完成，[四项定向结果](../pdos-next-context-fixture-completion-20261029/result.md)不改写旧24格。题集人工审阅、真实岗位/真人试点、真实模型/embedding同题质量，以及长会话正确率、缓存、成本和时延仍待相应条件，不能据此宣布两份设计正式验收全部完成。
