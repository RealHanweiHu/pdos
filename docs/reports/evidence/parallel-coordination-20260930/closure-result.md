# 两条并行线联合收口检查点 · 2026-09-30

本轮交付候选已完成本地联合检查点：跨项目资源改期/接续、共享物料池占用与现货齐套、供方内部回复一次确认、成本单位校验与冻结历史。原两线 27 份候选文件未变，另加入 3 份真实 PostgreSQL 测试及协调修复的事件目录、无路由决策、0408 迁移，共 33 份范围文件，见[最终候选](closure-candidate.json)。产品经理主线继续独立施工；本检查点不是整个共享工作树冻结，也不等于原 N/P/Q 全部验收。

## 可用结果与修复

- 两项目当前负责人分别确认本项目影响，资源管理员复核当前来源/政策/占用后整批应用；原预约释放、新预约确认、应用回执和审计同事务保存。重复提交、来源或优先级变化、竞争占用、撤回竞争及中途失败均有真实数据库证据。
- 同池跨项目分配与待对账实际领料扣减同一原库存，不复制供给或超分；重复 BOM 行按同单位聚合，现货总齐套与关键齐套仅认实际分配/领用。成本 estimate/quote/actual 单位不一致拒绝写入或冻结；后续价格修订保留已具名批准的冻结历史。
- 已授权项目原件元数据预填供方首次响应/实际收样，经一次确认更新原事项，保留原承诺、历史版本、证据及具名审计。页面已实际办理收样 v1→v2，指标随当前有效事项更新。此能力是人工核对后的确定性预填；没有把它记作 AI 解析或真实原件内容验证。
- 实库首轮发现 `RESOURCE_PRIORITY_PUBLISHED` / `RESOURCE_REALLOCATION_RECORDED` 未登记，正式写入回滚；已补事件定义及显式无 AI 路由，不触发模型。[原失败](../../../../output/parallel-closure-20260930/resource-postgres-r1.log)保留。
- 实库第二轮发现既有资源预约触发器使用 `old` SQL 别名，与 PL/pgSQL `OLD` 记录冲突，确认预约报 `record old has no field start`；新增 `0408_resource_guard_alias`，只改函数内两处 legacy 占用别名，不修改旧迁移、历史数据、约束或权限。[原失败](../../../../output/parallel-closure-20260930/resource-postgres-r2.log)与[修复迁移](../../../../server/migrations/versions/0408_resource_guard_alias.py)保留。

## 集中验证

| 验证 | 当前证据与覆盖 |
|---|---|
| 真实 PostgreSQL | **33 项通过**：资源 13、供方回复 13、物料/成本 7。真实服务、约束、独立连接锁竞争、幂等、权限/版本漂移、业务+事件+审计失败回滚；唯一替身为实际写入后的故障注入。加事件目录/运行路由合同共 **48 项通过，42.92 秒**。[完整输出](../../../../output/parallel-closure-20260930/postgres-r3.log)、[排程覆盖](../parallel-schedule-20260930/postgres-test-plan.md)、[供给覆盖](../parallel-supply-20260930/postgres-test-plan.md)。 |
| 既有 NPI HTTP 回归 | 本轮专属数据库中 **2 项通过**。[输出](../../../../output/parallel-closure-20260930/npi-http-regression.log)。未将其扩大为所有业务 HTTP 验收。 |
| 迁移与相容 | 空库加受限 NOLOGIN 应用角色后升到真实 head 0407，随后应用 0408；0408→0407→0408 往返后函数定义与往返前完全相同。[升级](../../../../output/parallel-closure-20260930/migration-upgrade-with-roles.log)、[往返回执](../../../../output/parallel-closure-20260930/migration-roundtrip.json)。0408 下 `alembic check` 无新增升级操作；既有相互外键排序警告原样保留，不宣称完整 schema 门禁无告警。[相容输出](../../../../output/parallel-closure-20260930/schema-check-0408.log)。 |
| 协调修复静态检查 | 事件目录、无路由决策、0408 迁移 Ruff 通过；两个应用文件 Mypy 通过，范围差异无空白错误。[Ruff 回执](../../../../output/parallel-closure-20260930/root-static.log)、[类型回执](../../../../output/parallel-closure-20260930/root-types.log)。两线首轮纯计算/组件/静态检查文件摘要一致，复用[接收证据](candidate-reception.json)，没有无改动重复运行。 |
| 前端生产构建 | 当前 UI 与两线业务的独立源码快照，Next 16.3.3 正常生产构建通过；新回复 BFF 已登记。使用真实 Geist 字体，不使用字体 mock。初次字体连接受无响应本机代理影响，停止本轮构建后只清除该进程代理配置重建成功。[构建输出](../../../../output/parallel-closure-20260930/web-build-direct.log)、[源码快照](../../../../output/parallel-closure-20260930/web-source-manifest.json)。8 份本轮前端范围文件均与实际构建一致；同期后续产品经理改动不计入构建覆盖。 |
| 新回复 BFF | 实际 3040→8840 链：未认证 401、合法登录 200、非法操作/引用/JSON 400、领域输入 422；均 no-store，会话 HttpOnly/Secure，令牌不输出。[6 项回执](../../../../output/parallel-closure-20260930/bff-checks.json)。实际有效预览/确认各 200，见[后端 HTTP 日志](../../../../output/parallel-closure-20260930/api-r2.log)。 |
| 浏览器与对账 | 原生浏览器真实登录两位项目负责人及管理员，分别确认→整批应用；另一租户原件绑定→预览→一次确认供方 v2。资源有 2 份具名同意、1 份应用、2 份旧预约 released、2 份新预约 reserved，各改期一天；方案事件/审计各 6 条。供方保留 v1/v2、原承诺、收样时间/证据和同一事件审计关联。[数据库对账](../../../../output/parallel-closure-20260930/browser-database-reconciliation.json)。 |
| 页面矩阵 | 两结果页各 1280×720 / 390×844、亮暗主题截图，手机无页面横向溢出；供方四视图记录宽度与结果可见，浏览器控制台无捕获到的 error/warn。[记录](../../../../output/parallel-closure-20260930/browser-checks.json)、[资源桌面](../../../../output/parallel-closure-20260930/schedule-applied-desktop.jpg)、[资源手机](../../../../output/parallel-closure-20260930/schedule-applied-mobile-dark.jpg)、[供方完成视图](../../../../output/parallel-closure-20260930/supplier-result-proof.jpg)、[供方手机](../../../../output/parallel-closure-20260930/supplier-updated-mobile-dark.jpg)。 |

浏览器夹具仅使用合成租户/项目/原件注册；无对象存储下载或真实文件内容。排程夹具最初缺页面所需 current_stage，补阶段与项目更名后触发已保存来源漂移拒绝，随后通过现有领域服务撤回旧方案并按当前来源重新提交；这是夹具调整及守卫验证，不计作项目入口产品修复。日期控件用原生编辑提交，没有修改 DOM/React 状态。隔离认证服务重启明确上游后恢复；开发/存续服务未更改。

## 环境与恢复边界

仅新建 `pdos-parallel-closure-20260930-pg`、127.0.0.1:**57440** 的独占临时 `pdos_test`，每次数据库命令前核对数据库、实际端口和 head，显式设置 TEST_DATABASE_URL，无 `.env` 回退。[核对记录](../../../../output/parallel-closure-20260930/database-verification.json)。57432/57433/57434/57439 未连接、清理、迁移或停止。测试的 own-tenant 追加历史清理只用于本库资源夹具，不禁用正常业务验证约束。

本轮 3040 前端、8840 后端及浏览器已停止/关闭，视窗恢复。最终临时库完整备份与迁移前备份留在 `output/parallel-closure-20260930/`，数据库容器停止、数据保留；没有删除容器或存续数据。私有环境文件不纳入证据候选或输出。没有启动模型/worker/真实外发、生产操作、git push；没有授予 AI 写入资格。最终环境回执见[环境收尾](../../../../output/parallel-closure-20260930/environment-close.json)。

## 原项未完成与下一步

本轮本地候选检查点收口，不关闭两条完整 N 项闭环或人工出口。ERP 新快照对账、归还/报废及共享失效后再采用、完整短缺 Issue 恢复/复核关闭、Cost Gap 超标恢复与降本工程/产品定义反馈的新联合证据仍沿 N5 原判据补齐；PIE 后批共同对象与 G1/D14-04 汇合保持主线归属。本次资源检查不替代四时间、正式基线/承诺或所有排程能力的全量联合验收。

真实供方/ERP材料及业务效果、AI 回复抽取与共同运行回执、逐能力真实 AI 资格、生产启用及 Q0–Q6 人工 Exit 本轮未验。依赖真实材料/权限的部分等待对应材料和有效授权；其他独立建设保持可推进。65 项原勾选与“2 完成 / 51 部分 / 12 待完成”不变。状态已原位回填[唯一清单](../../../../tasks/ai-native-integrated-todo.md#current-queue)，本报告不是新活动清单。
