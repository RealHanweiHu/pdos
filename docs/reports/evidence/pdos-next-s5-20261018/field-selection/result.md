# Field 正式选择 → 批准实施 → 新 Run

本候选的服务端功能闭环已在同一保留病例恢复完成，并经真实 UI 保存三条固定结果回链；自然表单 T2 选择、丢响应后的原请求恢复、双主题窄屏检查及环境清理备份均已完成。PG7 末尾测试辅助断言失败，原 pytest `exit=1` 保留，未重复运行上游整链。

实际序列为：初始未知影响 → 固定 Field 材料与 T2 逐项选择 → 逐对象处置原文 → 当前可信 coverage → 重捕图并重算影响 → 准备固定计划 → 工程/制造各自具名批准 → 实际新配置及 FieldOccurrence 实施记录 → 新 Build、样件、Request、新 Run 计算结果 → Field 固定结果回链。选择材料不是已执行的现场处置台账；新原件登记后重捕实际依赖水位，不放宽来源、版本或 coverage 守卫。本例保留批次未知、不创建 Issue/CAPA，最终变更仍未关闭。

已有检查按各文件的候选 manifest 解释，不把不同候选或重叠检查累加：

- [最终后端纯检查 531 项](pure-final-recompute.json)，早期 [366 项](pure-final.json)和 221 项不另加；[静态检查](static.json)通过。
- [前端 helper 136 项](web-lib.json)、[组件 16 项](web-component.json)及最终候选的 [BFF 定向 79 项](web-bff.json)通过，共 231 个不同用例；未变字节按下述候选说明复用，三组来源不同，不代表同次全仓回归。[typegen](web-typegen.json)、[tsc](web-tsc.json)、[lint](web-lint.json)、[生产构建](web-build.json)在最终前端候选通过，[旧构建](web-build-prior-1.json)证据保留。
- 0806/0807 初始候选升降往返通过：[0806 升](migration-upgrade-s0_0805.json)、[降](migration-downgrade-s0_0806.json)，[0807 升](migration-upgrade-s0_0806.json)、[降](migration-downgrade-s0_0807.json)。[元数据检查](storage-final.json)记录 Field 表 ORM 零差异；已有历史后，[降级守卫](history-guard.json)按预期拒绝降至 0806，保留实际 head `s0_0807`。

PG 失败证据全部保留；本轮最近一次为 PG7 `exit=1`，没有整条 pytest 通过结论：

| 尝试 | 实际阻点 |
|---|---|
| [PG1](pg-chain-1.json) | 夹具把 T0 Field 创建送入人工预览，被正确拒绝。 |
| [PG2](pg-chain-2.json) | Field 根的可信覆盖 owner 接线缺失。 |
| [PG3](pg-chain-3.json) | SQL coverage 固定引用尚未接 Field kind。 |
| [PG4](pg-chain-4.json) | 新原件登记推进依赖水位，prepare 正确拒绝旧捕获。 |
| [PG5](pg-chain-5.json) | 过早发布的 coverage 已失效，返回 `COVERAGE_OWNER_STALE`。 |
| [PG6](pg-chain-6.json) | 图引用与本次固定捕获不一致，返回 `FIXED_REFERENCE_MISMATCH`。 |
| [PG7](pg-chain-7.json) | 双 Field 选择、prepare、双专业 T2、两条实施、新 Build/样件/Request 及新 Run 的 pass 结果已执行；末尾测试以 `tested.final.request.build` 访问列快照，触发 `AttributeError`，真正的请求 DTO 位于 `request_snapshot`。 |

早期静态格式、组件及 TS 失败文件也保留，未由后续通过记录覆写。

自然表单首测被旧 BFF 仅接受 source-backed 材料的校验拦为 [422](browser-material-failure.json)，当时尚未登记原文或预览/保存 T2，原 pending 请求保留。修复后，[重新打开](browser-reopen.json)已恢复 UI 原请求；该脚本同时带出先前两个孤儿 response-wait 超时，进程 `exit=1`，不能将它记为脚本通过。后续独立的选择验证成功如下。

同病例恢复及最终实库核对已完成：

- [配置读回](resume-configuration.json)以普通 app-role 解析真实 `request_snapshot`，核对新 Build 的双配置绑定两条实施输出，新 Run 计算结果为 `pass`；Run 状态仍为 `results_pending`，Request 为 `reported`，独立复核未完成。
- [浏览器保存](browser_link.json)通过真实 UI 的 T1 确认保存两条实施及一条计算结果的原回执引用，父反馈保持 v2；[最终读回](resume-final.json)核实 2 条选择、2 条批准、2 条实施及 8 个共同组各有一条 Audit/Outbox/RequestKey，未创建 Issue，Change 为 `implementing` 且未关闭。
- [自然表单选择](browser_selection.json)沿 BFF 422 时保留的原 pending 恢复，登记实际原文并完成本人 T2（`expires_at:null`），保存 1 条 Field selection。实际响应 200 后注入客户端 503，刷新产生 0 次 POST；显式使用同 command/key/token/payload 重放得到同一回执，154 条未知项原样保留。该选择用于独立未来计划，未改写此前结果回链。
- [来源与权限](provenance-final.json)核实两条 Field 选择绑定实际反馈版本、两条 FieldOccurrence 绑定反馈与 Selection，相关三表的 `pdos_agent` 直接 DML 权限均为零，实际函数属主为 `pdos_next_owner`。
- [最终候选](candidate-final.json)的服务端相对 PG7/531 项纯检查仅修正测试 DTO 提取一文件，运行源码完全相同；相对[前次候选](candidate-final-prior-1.json)，前端仅改两个 BFF 文件的校验，已用定向测试、新构建及实际页面验证，最终前端与构建和预览同源。修正表达式在同一保留病例实际读回通过，未重复上游整链，也未将 PG7 改记为 pytest 通过；foreign `history_cursor` 在途行已排除，未声明全仓回归。
- [双主题检查](browser_visual.json)记录亮色 1440px、暗色 320px 的文档宽度均等于 viewport；主会话用 `view_image` [检查两张实际 viewport 截图](visual-review.json)，文字、控件与动作可读，无横向溢出。旧 Locator 长截图导航重复叠入的[先前记录](browser_visual-prior.json)保留，最终结论采用实际 viewport 截图。
- [清理核对](cleanup.json)确认自然表单仅保存 1 条选择、真实反馈与执行人绑定、CAPA 列为空、选择与证明无到期时间、human actor=requester，两共同组各有一条 Audit/Outbox/RequestKey；唯一短登录已删除，专属浏览器和 62090/62091 预览已关闭，共享 DB/Temporal 与部分测试历史保留。
- [0807 独立备份](backup.json)已生成，75,738,002 字节，SHA-256 为 `bb37655b15a9c00b4e6d59a349519ec7dcc7b22a90045450f6b14a4a5c8977b2`；旧备份保留。

本报告只记录功能闭环的建设与验证。独立复核、Change 关闭及阶段验收未在本轮完成；新 Run 的计算结果不替代这些结论。

本轮使用本地合成材料和具名测试身份，真实模型调用 0、业务外发 0；不扩大私有或 foreign 对象受众，不从 owner 推断审批人或资格。本轮不证明真实模型服务商联验或真实资格授予。S1/S5 未验收，性能验收暂缓；本报告不构成阶段验收或生产启用。
