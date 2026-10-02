# 产品经理闭环 · 独立评测网页入口（0407）

2026-09-30，接续[后端影子评测](shadow-evaluation-0407.md)。本轮完成管理员网页入口，不改变模型资格、预算政策、领域数据或人工出口。

## 可用能力

产品工作台新增仅owner/admin可见的“能力评测”：读取当前租户已选模型，导入独立人员提供的UTF-8候选参考文件，按当前市场空间逐样例核对来源与执行版本，再提交影子评测。文件原始字节摘要及换行保留，参考答案由服务器验证且沿原后端与模型输入分离。支持原编号重试/刷新后继续、本人原回执查询、报告与冻结来源下载；导出前再次核对当前权限。来源漂移、模型/计量不可用或权限撤回可见，不授予资格、不生成业务动作。

网页中转原先拒绝全部评测路径，[3项失败复现](../../../../output/pm-evaluation-entry-0407/bff-reproduction.log)后接通严格限定的prepare/runs/suite及本人回执GET；保留登录、请求大小、长调用超时和上游拒绝。后端API、迁移、模型调用链与可信根未改。

## 验证与范围

- [53项功能检查](../../../../output/pm-evaluation-entry-0407/affected-tests-delivery.log)通过，覆盖原件摘要/CRLF、范围与版本变化、原请求响应丢失恢复、权限撤回及导出前复核、管理员/员工入口和已有产品分析/矩阵恢复。[lint](../../../../output/pm-evaluation-entry-0407/lint-delivery.log)通过。最后仅调整表单宽度和长字符串换行，复用功能覆盖，按影响补[生产构建](../../../../output/pm-evaluation-entry-0407/build-workspace-final.log)与实际浏览器复查。
- 浏览器使用明确合成身份、材料和接口响应；验证文件导入、来源核对、503响应丢失后同输入/编号重试、原回执与两类JSON下载。[报告](../../../../output/playwright/pm-evaluation-entry-0407/downloaded-synthetic-report.json)及[回执](../../../../output/playwright/pm-evaluation-entry-0407/downloaded-synthetic-receipt.json)资格均false，回执保留冻结来源且业务动作false。此项是网页行为验证，不是HTTP/数据库/真实模型联验。
- 最长128位版本/样例编号曾将320像素页面撑到[829像素](../../../../output/playwright/pm-evaluation-entry-0407/mobile-dark-size.log)，调整后[页面320、评测区286](../../../../output/playwright/pm-evaluation-entry-0407/mobile-size-delivery.log)。最终四图均已查看：[手机亮](../../../../output/playwright/pm-evaluation-entry-0407/mobile-light-delivery.png)、[手机暗](../../../../output/playwright/pm-evaluation-entry-0407/mobile-dark-delivery.png)、[桌面亮](../../../../output/playwright/pm-evaluation-entry-0407/desktop-light-delivery.png)、[桌面暗](../../../../output/playwright/pm-evaluation-entry-0407/desktop-dark-delivery.png)。
- 本轮修改4个既有前端文件、增加2个组件/测试文件；[2802份源快照及同期变化](../../../../output/pm-evaluation-entry-0407/candidate-transition.json)保留。研究搜索/采集/引用的同期修改未覆盖，另以[22项检查](../../../../output/pm-evaluation-entry-0407/concurrent-product-tests.log)及[当前工作树类型检查](../../../../output/pm-evaluation-entry-0407/typecheck-current-workspace.log)验证；[构建前核对](../../../../output/pm-evaluation-entry-0407/source-pre-build-verification.json)仍发现采集组件同期变化，本轮6个源与后端未漂移。不能将此共享工作树称作全量冻结候选，也不拼接历史检查冒充正式联合出口。

## 剩余条件

[实际配置只读核对](../../../../output/pm-evaluation-entry-0407/configuration-check.json)：两个服务商可识别，搜索未配置，预算仍legacy，无计量路径/摘要，八能力均SHADOW。仍待允许的研究主题/材料、有效计量与真实调用授权、独立人工参考集/原调用证明、RFQ四类原名称、具名协审及人工Exit。原N项维持部分完成，目标未完成。

本轮无数据库操作、真实模型调用、业务出站、资格/`.env`修改、git push或部署；保护57432/57433和57434既有基线。临时浏览器与网页进程已关闭。
