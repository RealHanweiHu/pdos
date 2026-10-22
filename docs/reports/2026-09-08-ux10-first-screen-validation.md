# UX10 三页首屏本地工程验证（2026-09-08）

本轮按既有 V1 改善分工处理 My Work、项目概览和 AI Review 的首屏读取与可用性，不涉及并行任务的 AI 测试对话功能。性能口径来自 [验收与试点合同 §6](../design/2026-09-08-v0-v1-acceptance-and-pilot-contract.md)。以下是隔离合成数据的工程证据，不替代 D14-04 真实试点、手机真实网络采样、生产部署或任何 Sprint/Phase Exit。

## 测量环境与口径

- Apple M1 Max / 32 GiB / macOS 26.5.1；Chrome 152.0.7977.76，Next.js 16.3 Webpack standalone 生产构建；CPU、loopback 网络均不加人工限速。
- 主计时视口 1440×900；中文 locale、America/Los_Angeles 时区、设备像素比 1。390×844 与 320×568 另做视觉/交互检查，没有把桌面 P95 外推为手机 P95。
- 单独创建、无持久卷的 PostgreSQL `pdos_test`（127.0.0.1:58432）。不接开发或生产数据库。没有后台扫描器改变数据；没有 LLM 调用或真实外发。
- 固定合成 Owner、25 项目、1,460 任务、2,820 依赖、500 Issue、200 Risk（125 confirmed / 75 draft）、100 Finding（75 pending / 25 archived）、200 未读通知。主项目 500 任务、20 Issue、5 正式 Risk。迁移为 `0058_ai_test_plan_changes`。
- 完整文档导航从 `about:blank` 开始，已有测试登录，不计手工登录。终点要求正确业务数据、可用主控件、全部必需接口成功且完成，再等待两帧绘制；不使用标题出现、DOMContentLoaded 或 networkidle 冒充可操作完成。
- 每页热缓存 2 次预热后 30 次正式记录；冷缓存每次建立新 context、复用测试身份，30 次。每页/缓存分别计算 nearest-rank P95（第 29/30 个值）。失败保留，10 秒计时上限，不补抽样替换。首屏可见性另按元素矩形检查，不先滚动再截图。
- 修改前后使用同一份数据、同一冻结基础代码。优化版仅叠加本轮文件，避免把另一个活动任务的后续修改混入对照。

[采样协议](evidence/2026-09-08-ux10/protocol.json)、[环境](evidence/2026-09-08-ux10/environment.json)、[数据清单](evidence/2026-09-08-ux10/dataset.json)、[种子脚本](evidence/2026-09-08-ux10/seed.py) 与逐次原始记录均保存在同一 evidence 目录。

## 修改内容

1. Task 列表从任务查询后逐条读取依赖改为任务＋批量依赖两次查询，空列表一次查询。两次读取使用同一 REPEATABLE READ 快照，保留 readiness、依赖排序及租户/项目范围；单条 get 和写入行为不变。
2. 通知未读统计由 SQL GROUP BY 完成，列表＋分组共两次查询，不把所有未读历史拉回应用层。
3. 增加只读 `GET /api/ai/risk-candidates`，复用原 RiskResponse。Owner/Admin 限本租户，其他内部角色限直接项目成员，外部角色拒绝；单次查询覆盖所有可见项目。
4. AI Review 身份确定后并行读取项目、Finding、摘要和一次候选汇总，辅助队列有独立错误与重试；主 Finding 内容提前，候选与归档保留计数及展开入口。
5. My Work 的通知有独立加载/错误/重试，列表默认折叠，个人待办不再等通知才能处理。主加载和辅助加载均限制只有最新请求可更新状态，防止重试后的旧响应覆盖新结果。
6. 已选择项目后折叠项目列表，保留重新选项目入口；工作项与活动仅在需要的标签读取，保留深链、角色与错误门禁。

## 实测结果

桌面正式对照共 **360 次有效导航，全部成功**；另外保留中间布局版 180 次记录，不混入最终 P95。单位：毫秒。

| 页面 | 修改前热缓存 P95 | 修改前冷缓存 P95 | 最终热缓存 P95 | 最终冷缓存 P95 | 最终成功率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 我的工作 | 133 | 396 | 134 | 229 | 60/60 |
| 项目概览 | 1138 | 1245 | 254 | 317 | 60/60 |
| AI Review | 387 | 501 | 148 | 245 | 60/60 |

各页/缓存组最终 P95 均低于 1,500 ms。My Work 热缓存几乎持平；项目概览和 Review 读取链明显缩短。AI Review 的业务 HTTP 请求由 29 次降至 5 次（均含会话确认）；My Work 保持 3 次、项目概览保持 7 次。任务领域服务从 501 次 SELECT 降到 2 次，查询预算另由数据库回归证明。

修改前各页关键内容/动作均被长列表挤出首屏；最终桌面每组 30/30 的目标元素完整落在视口内，包括项目编辑与 Finding 接受按钮。最终 390/320 的六个初始视图均无横向溢出，主要任务行/项目概览/Finding 标题可见；390/320 的位置分别为 My Work 456 px、项目概览 509 px、Review 441 px。手机仍需按正常滚动阅读完整字段及操作区，这份检查不冒充手机网络 P95。

- [汇总数据](evidence/2026-09-08-ux10/summary.json)、[最终移动视图数据](evidence/2026-09-08-ux10/after-mobile.json)。
- 截图保存在 `output/playwright/ux10-2026-09-08/`：`after-{my-work,project,review}-{warm,cold}-1440.png` 和 `after-{my-work,project,review}-{390,320}.png`；修改前与中间版也保留。


最终代码 SHA 与冻结对照分别保存在 [前端源文件](evidence/2026-09-08-ux10/frontend-source-sha256.json)、[后端源文件](evidence/2026-09-08-ux10/backend-source-sha256.json)、`baseline-runtime-sha256.json` 和 `after-runtime-sha256.json`；运行快照与工作区本轮文件已逐一核对一致。

## 真实浏览器错误与交互补验

在最终生产构建中，分别由隔离浏览器临时拦截通知、候选和项目任务读取并返回 503；每种场景都先观察失败态，再撤掉拦截并点击产品现有重试按钮：

- 通知失败时已加载的任务仍可处理，提示通知未取到；重试后未读数恢复为 200。
- 候选失败时 Finding 详情和接受按钮保留，明确提示未知而非空队列；重试恢复 75 候选和 25 归档。
- 项目任务失败时指标显示 `—` 和重试提示，不当作 0；重试恢复 400 进行中任务 / 20 Issue / 5 正式 Risk。
- 320px 导航验证展开、Escape 收起并回焦点、Enter 重新展开、点“我的工作”后菜单收起与真实待办载入。没有执行 Finding 接受/应用或通知确认。

见 [浏览器功能记录](evidence/2026-09-08-ux10/browser-functional-validation.json)。最终 [数据复核](evidence/2026-09-08-ux10/dataset-after-validation.json) 确认业务数量与 Finding/通知状态不变，25 条种子伪模型调用记录无新增，outbox 为 0。

## 验证与边界

- Task / 通知相关后端回归 58 项通过，含 500 任务、约 1,500 依赖、2,000 未读通知、跨租户/收件人和并发源状态变化；[验证记录](evidence/2026-09-08-ux10/backend-task-notification-validation.md)。
- 汇总候选新增合同及隔离测试连同候选生命周期/RBAC 共 36 项通过，含真实 JWT 双租户、0/1/25 项目单查询及与原响应逐字段一致；[验证记录](evidence/2026-09-08-ux10/backend-review-candidates-validation.md)。
- 最终前端 72 文件 / **339 项测试通过**，正式 Next standalone 构建与 TypeScript 检查通过；聚焦 125 项测试、ESLint、代码 diff 检查通过。见 [前端验证](evidence/2026-09-08-ux10/frontend-validation.md)、[完整测试原始日志](evidence/2026-09-08-ux10/after-frontend-full.log) 与 [构建原始日志](evidence/2026-09-08-ux10/after-build.log)。
- 真实 D14-04 的人员单日走查、手机网络 P95、获批冻结候选联合门禁及各阶段用户签核继续按活动清单推进；本轮没有部署、Git push、模型资格发布或真实钉钉操作。

## 验证过程中的恢复记录

- 首次独立构建因沙箱无法解析 Google Fonts 域名失败；以同一冻结源码在允许的网络构建环境重跑成功，没有替换字体或改动设计基线。
- 种子脚本初版误将 SQL NULL 编为 JSON null，随后暴露租户级 Agent subscription 唯一约束；只重建本任务的空白合成 fixture 后修复。正式数据清单生成后未再改变数据。
- Playwright CLI 的 Node VM 没有全局 URL，初始仪器校验中的 response 回调导致会话退出；修正 URL path 解析后重新建立合成测试身份，正式采样开始前完成仪器校验。保留启动日志，不将仪器启动失败伪记为产品成功或计入正式样本。
- 修改前 180 次记录均校验所有必需 API 成功且已完成 resource timing。复审后为优化版并行读取显式加入“等齐必需资源再停表”，原指标的可操作完成条件不变；原版记录未出现因辅助接口稍晚而被错误记成超时的样本。

## 清理

本轮专属 Playwright `pdos-ux10` 会话、3312/3314 的前端和 8812/8814 的 API 已关闭；`pdos-ux10-test` 容器已停止并由 `--rm` 自动移除。保留两份本地冻结源码快照及全部计时/截图证据，以便复核。没有停止其他任务的服务或数据库。
