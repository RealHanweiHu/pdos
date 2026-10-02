# 产品经理闭环 · 派生产品与父版变更恢复（0407）

2026-09-30，归 N1-06，兼顾已批准 DC-13 的父版引用、三方对比和显式接受。补齐网页办理与异常恢复；原 N 项仍部分完成，真实资格、专业协审和人工出口保持原条件。

## 可用行为与修复

父版比较、显式接受或产品派生收到明确 401/403 时，清除比较正文、选择、接受理由、派生输入、待核对请求及结果提示，并隐藏原已接受历史。拒绝同时通知定义工作区，清除该页定义正文、证据原文、办理历史和编辑入口。范围或定义对象切换后使用独立状态；权限失效或离开页面后的迟到响应不再填回内容，也不再触发旧请求的页面刷新。

保存结果不明时保留完整原请求，包括版本、内容摘要、父版发布记录、比较摘要、勾选字段、理由、新产品输入和幂等编号。页面提供明确的原请求重试按钮，锁住原输入和新写入；即使重新比较父版，重试仍发送先前保存的请求。确认成功后解除待核对状态；明确的版本冲突等拒绝解除该状态并显示错误。已确认接受的回执与“已保存”说明不因后续页面刷新失败而重新变成待保存。

实际网页检查还发现，父版请求待核对时定义页仍能编辑草稿，可能刷新定义并丢失原请求。现待核对状态同步到定义页及工作台：暂时锁住新建、编辑、协审、责任调整、相关反馈写入、定义刷新、工作区刷新和选项切换，保留正文读取、父版比较及原请求重试。成功或明确拒绝后解除锁定；撤权后清除内容并恢复允许的重新读取入口。

派生仍引用原发布定义，父版不会自动覆盖。父版接受仅进入定义草稿，规格确认与专业协审仍须办理。未改变领域 API、数据库、专业角色、T2 发布规则或任何模型资格。本次原请求保留限当前页面内存，不宣称跨整页重载持久恢复。

## 候选与验证

本轮涉及两份组件和三份行为测试：`definition-inheritance.tsx`、`definitions.tsx`、`definition-inheritance.test.tsx`、`definition-inheritance-recovery.test.tsx`、`product-publication-access.test.tsx`。五份源在最终验证后与候选 SHA-256 一致。共享工作树的其他建设保留，本轮不构成全仓冻结或正式联合出口。

| 验证 | 结果 | 原始证据 |
|---|---|---|
| 修复前派生组件 | 5 项在目标断言上预期失败：三类明确拒绝、待核对原请求和输入锁定 | [原组件复现](../../../../output/pm-inheritance-recovery-0407/reproduction.log) |
| 定义页锁定缺口 | 2 项在“待核对仍可编辑”的断言上预期失败；发生在首轮派生恢复修复后 | [工作区复现](../../../../output/pm-inheritance-recovery-0407/workspace-lock-reproduction.log) |
| 最终受影响行为 | 同一次 6 文件、55 项通过；新增派生恢复 9 项及工作区联动 3 项，原 43 项保持 | [最终检查](../../../../output/pm-inheritance-recovery-0407/recovery-final.log) |
| lint / 类型 | 五份源零警告，独立类型检查通过 | [lint](../../../../output/pm-inheritance-recovery-0407/lint.log)、[类型](../../../../output/pm-inheritance-recovery-0407/typecheck.log) |
| 最终生产编译 | 工作区锁定修复后的生产编译含 TypeScript 检查通过 | [最终编译](../../../../output/pm-inheritance-recovery-0407/build.log) |
| 实际网页待核对 | 合成 503 后原请求及选择保持，重试可用，编辑/创建/刷新/选项/页签锁定 | [待核对 DOM](../../../../output/playwright/pm-inheritance-recovery-0407/pending-final-dom.log) |
| 实际网页原请求重试 | 第二次请求与第一次完整输入及编号相同；确认接受理由保留，编辑/刷新恢复 | [确认 DOM](../../../../output/playwright/pm-inheritance-recovery-0407/confirmed-final-dom.log) |
| 实际网页撤权 | 后续父版比较合成 403，定义名、原接受理由、本次理由及比较内容从 DOM 清除，编辑入口移除 | [撤权 DOM](../../../../output/playwright/pm-inheritance-recovery-0407/denied-final-dom.log) |

行为覆盖包括比较/接受/派生拒绝、重新授权读取、范围切换、迟到回执隔离、连续点击只发送一次、丢失派生回执的原输入重试、新父版比较后仍发送旧请求、确认接受后刷新异常及成功/版本冲突后的工作区解锁。权限拒绝检查包含实际父版组件向完整定义页传播，未使用父版组件替身。

网页运行最终生产前端，所有 API 由[合成路由](../../../../output/playwright/pm-inheritance-recovery-0407/setup.js)拦截，走“原父版/本地/新版比较→人工勾选与理由→503 待核对→原请求重试→确认接受→父版 403”。回执证据记录同一幂等编号、原版本和摘要、原发布版、字段及理由。仅合成 UI 路径，无实际服务端写入或模型调用。浏览器控制台仅两条注入的 503/403 资源失败，见[控制台](../../../../output/playwright/pm-inheritance-recovery-0407/console-final.log)。

三张桌面截图均已查看：[待核对](../../../../output/playwright/pm-inheritance-recovery-0407/pending-final.png)、[确认接受](../../../../output/playwright/pm-inheritance-recovery-0407/confirmed-final.png)、[撤权清除](../../../../output/playwright/pm-inheritance-recovery-0407/denied-final.png)。本轮未改变视觉设计，不声称重做完整亮暗/多尺寸矩阵。临时浏览器及 3104 前端进程已关闭。

[修复前摘要](../../../../output/pm-inheritance-recovery-0407/before-source-sha256.json)、[本轮原组件差异](../../../../output/pm-inheritance-recovery-0407/own-source.patch)、[最终候选摘要](../../../../output/pm-inheritance-recovery-0407/candidate-source-sha256.json)、[交付核对](../../../../output/pm-inheritance-recovery-0407/delivery-verification.json)记录具体范围。工作区锁定前的构建和候选另行保留，不作为最终版本证据。

## 剩余条件

前序[策略与定义权限恢复](publication-access-0407.md)、矩阵运行恢复及独立影子评测入口保持各自候选证据。此次没有访问或清理 57432、57433、57434 或其他数据库，没有重新探测未变化的外部条件；存续事故与 0377 恢复边界保留。

仍需允许的真实研究主题/原始材料与搜索服务、有效计量配置和实际调用授权、八能力独立人工参考集/原始调用证明、RFQ 四类原名称、具名专业协审与原人工 Exit。继续补已授权的闭环缺口，条件就绪后贯通真实研究到定义及矩阵。本次通过不授予资格，也不代表产品经理整链或全部原 N 项完成。
