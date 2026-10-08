# 小Pai思考与处理过程 · 2026-10-06

依用户“不只显示根据上下文，需要像ChatGPT一样展示思考过程”授权，普通会话和品类/提案对话改为可展开的过程面板：公开处理思路摘要、思考阶段、实际搜索关键词/来源读取、资料覆盖与组织回复、实时耗时。生成时展开，完成后收起并随原回复回执保存，刷新或查询原请求可再展开；停止冻结时间，连接中断显示等待核对，撤权清除当前过程，来源变化回执不保留旧私有摘要。

新增公开`approach`字段，仅要求1～3句目标、资料与检查方法的摘要。同一次模型调用先输出摘要、再输出答案，没有新增摘要模型调用。普通会话与立项前固定prompt分别升至`xiaopai-reply-v3`和`preproject-dialogue-v2`，不在固定前缀插入动态状态。旧模型输出和历史回执仍兼容。OpenAI兼容`reasoning_content`/`reasoning`、Anthropic `thinking_delta`及原MiniMax `<think>`只用于阶段信号；内部推理原文不进入过程面板，公开字段的流式解析继续拒绝隐藏前缀和嵌套字段。

过程步骤由服务器观察实际动作，搜索/读取进度仍在原运行准入之后发送，结果依据工具观察记录标为完成、部分或失败。现有预算、租约、停止、来源/权限、快照与T1/T2关卡保持。没有数据库迁移、预算启用、模型资格授予、系统DNS变更、真实模型调用或业务数据写入。

| 检查 | 结果与范围 | 证据 |
| --- | --- | --- |
| 流式协议、公开字段解码、过程状态 | 27项通过；上限调整后3项状态检查另复核，不重复计数 | [协议/状态](stream-tests.log)、[最终状态复核](progress-final.log) |
| 会话、搜索、新品对话PG/API | 30个不同案例通过：首批29通过，1个迁移head静态断言因共享源升至0429失败；改为核对操作前真实head后单项通过。没有重新声称30项同批全过 | [串行回归](conversation-tests-recovery.log)、[head保全复核](head-preservation-final.log) |
| 前端过程/会话 | 最终2文件13项通过；包含摘要先于答案、刷新恢复、停止计时、撤权清除 | [最终前端](frontend-tests-final.log) |
| 类型/规范 | 前端tsc及4文件eslint通过；8份受影响后端ruff、新增过程模块mypy通过 | [前端类型](frontend-types-final.log)、[前端规范](frontend-lint-final.log)、[后端规范](backend-lint-final.log)、[过程类型](progress-types.log) |
| 浏览器合成UI | 实际组件、真实样式；桌面1440px亮色、手机320px亮/暗，流式展开及完成后展开通过，手机scrollWidth=320无横向溢出 | [桌面亮色](../../../../output/playwright/xiaopai-process-20261006/desktop-light.png)、[手机亮色](../../../../output/playwright/xiaopai-process-20261006/mobile-light.png)、[手机暗色](../../../../output/playwright/xiaopai-process-20261006/mobile-dark.png)、[手机几何](../../../../output/playwright/xiaopai-process-20261006/mobile-geometry.log) |
| 原API存活 | 本地8000 `/healthz`成功；只核对进程存活 | [存活回执](api-liveness.json) |

初次尝试复用旧隔离测试容器时发现其已在运行，因此未共享会清理租户的夹具，未停止该容器。另建自有`pdos-pai-process-test-20261006`，明确核对`127.0.0.1:53744/pdos_test`后仅使用显式`TEST_DATABASE_URL`。新库缺少旧迁移所需的`pdos_agent`角色，首次setup失败后中断，日志保留于[初次检查](conversation-tests.log)；只在自有测试库补建NOLOGIN测试角色后恢复，不修改业务环境或迁移合同。同期真实共享head已升为`0429_preview_legacy_usage_holds`；本轮仅适配相关历史保全测试的静态head断言，没有实施该新迁移的业务建设。

自有测试库已私有备份并停服，卷保留；原57432与旧运行测试容器未操作，[收尾记录](environment-closeout.json)保留备份摘要。临时3058合成页面及专用Playwright浏览器已关闭。合成页面的工具与模型事件不代表真实研究或真实摘要质量；初始浏览器操作遇到CLI参数/旧ref及热重载，已重新取快照并保留核对过的截图，误标亮暗截图已移除。唯一浏览器控制台错误是合成页面缺少favicon。

70个不同受影响检查通过不代表全系统验收。没有重跑完整构建、正式红队或人工Exit；当前真实联网研究、预算与DNS条件沿原队列继续，真实模型的摘要措辞/时延与登录后的操作仍待对应实测。最终源码范围及摘要见[source-manifest.json](source-manifest.json)，其他会话的共享源变更不纳入本轮完成声明。
