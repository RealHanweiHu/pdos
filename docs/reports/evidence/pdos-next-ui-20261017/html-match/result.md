# HTML mockup 界面对齐 · 2026-10-17

接续指针：同日已补[品类矩阵](../category-matrix/result.md)、[提案用户声音及实际BFF](../proposal-voices/result.md)，随后接通[我的工作本人G0待决定](../g0-inbox/result.md)，随后补[本人开测承诺记录](../test-start-promises/result.md)，随后补[竞品固定细分、知识续版与矩阵](../competitor-segments/result.md)，随后补[项目Builds真实轮次与固定测试摘要](../project-builds/result.md)，随后补[真实持久会话列表、搜索与逐轮继续](../pai-sessions/result.md)，随后补[已登记来源选择、固定绑定与原意图恢复](../pai-sources/result.md)，随后实施[新文件上传及原请求恢复（浏览器余项待授权）](../pai-upload/result.md)，随后接入[项目关键承诺读取](../../pdos-next-ui-20261018/project-commitments/result.md)和[关键承诺独立履行读取](../../pdos-next-ui-20261018/commitment-fulfillment/result.md)，随后补[Builds实际产出与样件登记摘要](../../pdos-next-ui-20261018/build-output/result.md)，随后补[制造准备资料与项目动态位置](../../pdos-next-ui-20261018/preparation-activity/result.md)，随后补[Build固定工程配置与项目运行接线汇合检查](../../pdos-next-ui-20261018/engineering-preparation/result.md)，随后补[固定发布包与专业决定](../../pdos-next-ui-20261018/release-packages/result.md)，随后补[试产记录与原始统计](../../pdos-next-ui-20261018/pilot-statistics/result.md)，随后补[外部交接与原回执读取](../../pdos-next-ui-20261018/external-handoff-reading/result.md)，随后补[制造资料历史翻页与基线固定正文](../../pdos-next-ui-20261018/preparation-history/result.md)，随后补[全局知识入口与固定规则读取](../../pdos-next-ui-20261018/knowledge-library/result.md)，随后补[Build保存时准备检查](../../pdos-next-ui-20261018/build-readiness/result.md)，最新实施候选为[本人会话改名、置顶与归档恢复（实际页面复核待授权）](../../pdos-next-ui-20261018/session-presentation/result.md)。矩阵此前遗漏的BFF已在声音候选修复；本文件保留首批界面对齐的原始范围与验证截点。

按用户指定的 `docs/design/2026-10-13-pdos-v1.1-ui-mockup.html` 修改 `pdos-next/web`，承接前一批功能接线。此次完成的是界面结构与当前实际能力的接入，不是 S1/S2 完成或正式阶段验收。

## 已完成

- 框架：224px侧栏、48px顶栏、橙底P、新建/⌘K、13px字号与20px内容边距、亮暗token、橙色小Pai入口，保留移动抽屉和触屏尺寸。
- 我的工作：最近访问、分诊chips、工作卡、今日/本周/稍后任务与右侧运行通知/承诺区。任务仍进真实项目，Run待答复不充当正式决定。
- 项目：紧凑工具栏、可折叠分组表、三视图和筛选；8标签工作区及下一Build、办理、承诺、动态面板，实际链接保留项目范围。
- 品类：品类头、提案路径/管道、六个知识标签和紧凑表格；标准品匹配保留。原币种、工况、性质与未知原因不混写。
- 提案：接入同一AppShell、8标签、叙述与规格表、常驻本案助手；原G0、来源/版本、权限和原请求恢复逻辑保留。
- 小Pai：完整展开工作区、260px历史、范围/实际技能条、独立线程及底部编辑器；缩回/转后台保留同一Run。修复重复搜索、FAB遮挡编辑器、范围UUID和纯黑边框。

## 最终验证

78项组件 + 26项库检查 = 104项通过，见 `components.log`、`libraries.log`。最终生产构建和类型检查通过。全量基础lint及最后修正文件lint通过，保留`verification/contracts.js`的2条既有warning。第一次构建发现两个当前Phosphor未导出的图标，已改用Archive/Tray；最后一项旧测试对scope文本的UUID断言按友好名称更新，保留原Run路径/零重复写入检查后78项通过。

最终候选及每个输入SHA见 `candidate.json`，最终源文件比较无差异。候选构建期间未运行后端数据库/模型；浏览器使用本地生产构建与只读合成GET代理，161次GET、0次非GET（截点），不冒充真实PG/RLS/资格或人工验收。API原始记录见`browser-api-requests.jsonl`。

浏览器检查含项目三视图/筛选，8标签及范围链接，品类/提案跳转与返回根页面，亮暗切换，320px抽屉/各主屏无页面横向溢出，小Pai同Run展开/后台返回。详细项目见`browser-observations.json`。图片在`output/playwright/pdos-html-match-20261017/`，最终重点为`final-my-work-dark.png`、`final-proposal-dark.png`和`final-pai-run-dark.png`。

## 剩余差距与接续

| 范围 | 尚未接入 |
|---|---|
| 项目 | 实际阶段模板/门禁健康度规则、冻结点、具名状态更新与完整动态流；不得由计划推断 |
| 我的工作 | 正式决定/接收/验证/外部回复队列、完整承诺与通知投影 |
| 小Pai | 本人持久会话改名/置顶/归档恢复及附件固定选择已接；新生命周期实际页面、上传携带新Run余项待恢复浏览器授权，语音/手动技能仍缺 |
| 品类/提案 | 品类矩阵、提案独立用户声音与部分摘要；竞品统一换算须有实际口径事实 |
| 工作区 | 部分标签仍进入现有办理页；工程/制造准备、正式评审与独立项目资料包尚未完整汇入 |

演示规格条和外层画布不进产品；P16角色预览与P20会话删除沿用用户后续决定，不复制。完整差距/图像核对见`pdos-next/web/design-qa.md`。唯一清单原位更新，自动续工`pdos-s3-s5`已更新为以这份HTML及本候选为续接入口；正式业务缺口按自身前置继续，不改变原阶段出口边界。

本地只读合成预览：`http://127.0.0.1:55169/?area=work`，保留最终预览；旧对照服务已停止。无push、部署、生产操作或真实出站。
