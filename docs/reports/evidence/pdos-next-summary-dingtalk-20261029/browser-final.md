# 本人摘要钉钉投递浏览器验证

实际使用最终 [757 输入生产构建](frontend-final-candidate1-build-result.json)和独立 `53502/pdos_test` 的原生账号、项目事实、摘要 Run、绑定及 T1 命令。[fixture XML](pg-browser-run1.xml)、[数据库结果](browser-result.json)、[本人核验](browser-web-verified.json)均通过。

- 新建“浏览器：本人钉钉工作摘要”，默认仅站内；明确选择本人项目与已验证绑定，保存草稿后，预览显示“站内及本人已验证钉钉单聊”。[选择](browser-channel-selected.png)、[预览](browser-summary-preview.png)。
- 原确认按钮只提交一次 activate，实际 v2 已启用，未受理新运行。刷新、读取规则并编辑新草稿后，保留同一个绑定。[启用](browser-summary-active.png)、[刷新](browser-binding-refreshed.png)。
- 原类别绑定 Run 完整显示变化、本人关系、下一步/具名记录人及继续办理链接。[桌面](browser-original-summary.png)、[390 暗色](browser-summary-390-dark.png)、[320 暗色](browser-summary-320-dark.png)。手机按原会话层级点击“返回对话”。摘要页面宽度为390/390、320/320，组件为350/350、280/280，无横向溢出。
- 原投递 unknown、登记1次；页面“只查询原回执”后 delivered，刷新重读仍保持。MockTransport实际 body send **恰1次**、lookup **1次**。[未知](browser-receipt-unknown.png)、[送达](browser-receipt-delivered.png)、[刷新320暗色](browser-receipt-refreshed-320-dark.png)、[布局测量](browser-layout.json)。

原生 finish 核实新规则1、真实版本2（draft/activate）、具名已消费 Confirmation/Receipt及 ServiceGrant1；原 Run结果hash、原投递身份/来源hash保持，Artifact/Run/ToolCall/模型预算/技能/入站Message/旧GDelivery均无新增。实际UI只有草稿、预览、一次确认和一次回执查询写请求。真实模型、KMS及渠道请求均为0。

初次自动化定位曾遗漏设置子页、误用包含额外文本的精确标签，并在手机会话列表层等待正文；纠正脚本定位后通过，产品源码未因此修改。未配置真实安全存储的模型连接元数据 GET 显示不可用，favicon为既有404，均未触发调用。[本次API/Web/浏览器和临时登录收尾](cleanup.json)，共享测试库及Temporal保留。
