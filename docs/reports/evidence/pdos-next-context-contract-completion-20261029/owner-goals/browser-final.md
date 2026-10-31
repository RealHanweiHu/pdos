# 本人原话投影的实际页面验证

使用本轮757输入生产构建，连接53502/pdos_test中的新合成租户。经原生来源登记、开始Run与生产finish保存结果，再撤回该来源Audience；撤权前本人可读结果、撤权后GET仅返回原话，peer拒绝。

实际Chrome独立会话从业务深链打开撤权记录，再刷新：原话、隐藏说明与真实“记录时间”保持；原回答标记、运行继续/撤回/保存/反馈/来源动作不显示。1440×1000亮色及390×844暗色已逐图检查，窄屏scrollWidth=390，无横向溢出，独立新对话入口保留。

- [桌面截图](browser-desktop-hidden.png) · [窄屏暗色截图](browser-390-dark-hidden.png) · [DOM核对](browser-dom-check.json)
- [原生结果与请求计数](browser-result.json)：目标Run实际2次GET均200；events/candidates/process/continuation等子资源请求0，写入请求0；18张保护表count+digest不变，新增Run/模型/embedding均0。
- [实际夹具](browser-fixture.xml)：1通过，170.79秒（含人工浏览器操作等待，不是性能样本）。
- [清理](browser-cleanup.json)：新合成登录过期，私有storage/state删除；浏览器Cookie清除并关闭，59901Web/62415API已停止，测试库与Temporal保留。

初次控制台仅既有favicon.ico 404，刷新未出现应用错误。没有真实模型、embedding或渠道调用。
