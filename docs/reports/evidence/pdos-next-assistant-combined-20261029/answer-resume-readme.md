# 回答受理后继续轮询：独立冻结 delta

2026-10-29。只写本 `/tmp/pdos-answer-resume-stage-20261029`；真实源码及 `/tmp/pdos-assistant-combined-next-20261029` 冻结树均未改，2661 原组合输入 SHA 全部复核不变。未执行 DB、Temporal、模型、外发、构建或浏览器。

## 实际问题与语义

原 API `/answers` 先保存具名 AgentInput，再 signal_workflow，返回 202 `{run_id,answer_ref,status:"resume_requested"}`。record_answers 不先把 AgentRun 从 waiting_input 改 queued/running，因此紧接着 GET 仍返回同一个旧 needs_input 是合法状态。

两个原入口在 POST 成功后清空 answers，随后只轮询 queued/running；旧 waiting_input 不再推进，UI 看起来重新等待答复，第二个新 key 可能与已继续的服务器状态冲突。服务端受理和 T1/权限守卫无需修改。

## 交付与基线

只应用 `deliverable-files/` 下四文件，或相对工程根 `answer-resume.patch`，**不要复制整份 web**。其余内容只是验证副本。

- 修改 Xiaopai，基线来自组合冻结：`153623c68f1abbdff6af8245b91c99f7d4f3a5595f05da11848445d791392660`。
- 修改 PersonalXiaopai，基线来自组合冻结：`3034fff1a6ce1bf4e26c92d05d050ac7dab4738e3bb0784e27c5143f580db645`。
- 新共用 `components/pai/use-answer-resume.ts`。
- 新两入口实际父组件事件测试 `components/pai/answer-resume.test.mjs`。

`manifest.json` 给前后精确 SHA。补丁 dry-run、独立 `/tmp` 实际应用后，四文件输出 SHA 与候选全部匹配。该补丁须在组合冻结的 corrections UI 已叠之后合并；不覆盖其它未完成 stage 的文件。

## 修复行为

按实际 Run ID 和完整事件读取中最新 needs_input 的 sequence 记录已受理标识。只有匹配实际 run_id/resume_requested/answer_ref 的 ACK 后才进入等待恢复；不把202当 completed。

- 同一旧 waiting_input 期间保留已填答复，表单禁用；同步 ref 也阻止旧回调重复 POST。状态显示“答复已提交，等待继续执行”。
- 原 GET 轮询同时识别该已受理标识；紧随的 GET 503 即使清空显示 Run，也能通过所选实际 Run ID 继续轮询，不重新 POST。
- 实际状态离开 waiting_input、Run 撤回，或最新问题 sequence 改变时解除；同 question.id 的新问题也清空旧答复并开放新输入。普通运行 queued/running 与 reconciliation 轮询保持。
- 只有 HTTP 受理未知时保留原 pending request/body/idempotency_key，原“重试原请求/同一请求”仍明确重试原体；GET 失败不会把已受理 POST 变回待重发请求。
- 同一本人组件中切换其它 Run 不丢原已受理标识，返回旧问题仍不能重复答复；切换本人/API 的组件边界保持隔离。权限拒绝清空内容与这些标识、停止旧轮询。
- Personal 原问题弹窗、已见中断与后台显示规则保留；Xiaopai 也使用同一问题 identity 清理新问题的旧答复。

标识只是当前本人组件内的临时显示/轮询控制，不是权限或业务事实，没有新数据库、服务账号、消息、持久答复 journal 或推理调用。重新挂载仍走原读历史入口，不会自动 POST。

## 已验证

`evidence/affected-tests.txt`：**82/82** 受影响前端纯测试通过，包含两个入口各六项新回归（共12）：

1. 202 后多个 GET 仍同旧 waiting_input，答复保留、重复 submit 无额外 POST，随后实际 completed 停止轮询；
2. 同 question.id 但新 needs_input.sequence，开放新空答复；
3. POST 回应未知后手动重试，body/key 精确相同；
4. 202 后 GET503，继续 GET 恢复且不重发；
5. 后续 GET403 隐藏旧表单并停止恢复轮询；
6. 切换其它 Run 再返回，不能重新回答已受理旧问题。

现有 Xiaopai、Personal 原入口、复验准备流程、原 start journal 恢复测试也在这82项内。新测试执行真实父组件与真实共用 hook，调度/时钟、无关子组件和 HTTP 为受控替身；不将其称为浏览器、数据库或 Temporal 通过。

整份暂存 web **716 输入** TypeScript `tsc --noEmit --incremental false` 通过；四交付文件 ESLint --max-warnings=0 通过。未构建；主会话补新候选真实浏览器验证。

## 根浏览器复核

在本人或项目的实际待答运行提交一次明确数量，放慢随后 GET 或保留旧 needs_input 一轮，确认显示已提交且表单禁用、3秒左右继续查询，实际运行到终态后显示结果。另核新问题解锁、POST/GET 响应丢失分流、原 key 重试、切换 Run 和撤权清理。无需第二模型或新的批准流程。
