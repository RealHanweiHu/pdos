# V1 可用性与性能改善 · 本地验证记录

日期：2026-09-08。用户确认与“明确 V0 V1 验收口径”任务并行分工，本任务补现有 V1 可用性与性能缺口，避开 AI 测试项对话实现。

**本轮功能与运行验证通过；完整门禁仍待并行工作树的类型错误收口。V0/V1、Sprint 5 与生产出口均未据此通过。**

## 本轮改动

对应统一清单 V1-A2/A6 与 UX10 的既有读路径与口径补修，不引入后续 Phase 功能。

| 问题 | 修复后的行为 |
|---|---|
| 驾驶舱逐项目请求风险 | `GET /api/dashboard/risks` 一次请求返回 Top 8、全量总数、每个可见项目的数量与最高分；固定两次 SELECT，共享 REPEATABLE READ 快照。零风险项目仍返回摘要，Top 8 不影响项目卡计数 |
| 项目列表逐项目查询阶段 | 一次取项目、一次批量取可见 workflow 的阶段；空列表只查一次。保留阶段顺序、当前阶段、历史导入项目及原成员边界 |
| My Work 把未确认风险算入正式待办 | 仅计入 `draft_state=confirmed` 且未关闭风险。列表、全量计数与截断一致；确认后进入，撤销后移出 |
| 风险榜链接落到项目默认页 | 直接进入相应项目的 `work-items` 标签 |
| 锁文件审计有 9 条漏洞记录 | 仅升级 `pypdf 6.15.0→6.16.1`、`fast-uri 3.1.5→3.1.6`、`qs 6.15.3→6.16.0`，不增加直接依赖或改变原版本约束 |

权限沿用项目列表实际口径：Owner/Admin 可见本租户项目，其余内部角色仅可见本人直接所属项目；不在性能修复中扩大代理可见范围。风险接口复用 `WORK_ITEM_VIEW`，范围由服务端会话绑定；外部角色 403，未登录 401。没有新增业务写或改变 AI 人审规则。

本轮未增加迁移。隔离测试库执行到已有本地候选 head `0058_ai_test_plan_changes`，该迁移属于并行测试计划切片，不代表生产升级。

## 工程证据

为避免并行迁移、TRUNCATE 和 `.next` 生成物相互干扰，使用独立代码快照及临时 Docker 容器；数据库严格命名 `pdos_test`，仅绑定 `127.0.0.1:58432`，无持久卷。修复后的依赖安装到独立临时目录，没有替换另一任务正在使用的工作区依赖环境。复验工作区时按锁文件同步依赖。

本轮 16 个代码、测试和锁文件与验证快照 SHA-256 一致，见 [文件指纹](../../output/playwright/v1-improvement-2026-09-08/source-sha256.json)。

| 验证 | 结果 |
|---|---|
| 项目查询先失败后通过 | 5 个项目修复前 6 次 SELECT，修复后 2 次；阶段内容与顺序不变 |
| 聚焦后端 dashboard/projects/my_work/BFF | 36 项通过，含 0/1/25 项目恒定查询、租户/成员边界、并发快照、完整计数及确认/撤销 |
| 完整后端快照 | 693 项通过，1 项因快照没有 `.git` 导致发布打包失败；同一打包测试在原仓库单独复验通过，未修改或跳过测试。见 [输出](../../output/playwright/v1-improvement-2026-09-08/backend-full.log) |
| 新锁依赖下的后端受影响回归 | AI API（含 PDF 抽取）、dashboard/projects/my_work 共 42 项通过，见 [输出](../../output/playwright/v1-improvement-2026-09-08/backend-updated-dependencies.log) |
| 新锁依赖下的完整前端 | 70 个文件、305 项通过，见 [输出](../../output/playwright/v1-improvement-2026-09-08/frontend-full.log) |
| 后端静态/类型 | Ruff、format、compileall 通过；本轮 7 个后端文件 Mypy 通过。完整 Mypy 尚未通过，见下节 |
| 前端静态/类型/构建 | ESLint、`next typegen`、`tsc --noEmit`、`next build --webpack` 通过；浏览器运行实际 standalone 产物，见 [构建输出](../../output/playwright/v1-improvement-2026-09-08/frontend-build.log) |
| 依赖门禁 | OSV：916 个锁定 registry 版本、2 批次、0 条已知漏洞；pnpm frozen install 与 828 项供应链政策校验通过 |

关键复验入口：`pytest tests -q`；原仓库单独运行 `pytest tests/test_production_deployment_contract.py::test_release_packager_creates_a_commit_exact_verified_git_bundle -q`；新依赖回归 `pytest tests/test_ai_api.py tests/test_dashboard_api.py tests/test_projects_api.py tests/test_my_work_api.py -q`。数据库 URL 必须由隔离测试环境注入并通过 `app.db.test_safety` 校验。

## 真实 HTTP 与浏览器

仅使用合成数据：25 个项目、33 条已确认开放风险、1 条未确认候选及 1 个零风险项目；其中一个项目含 10 条正式风险。与真实 D14-04 资料无关。

- 浏览器登录后只有一次 `/api/dashboard/risks` 请求，显示“Top 8 · 共 33 项”；项目卡正确显示 0/1/10，Top 8 外风险没有漏计。见 [1440 桌面截图](../../output/playwright/v1-improvement-2026-09-08/dashboard-1440.png)。
- 从风险榜真实点击进入对应项目 `work-items` 标签，显示该项目全部 10 条正式风险。
- 在隔离浏览器模拟聚合接口 503，风险区显示不可用与重新汇总，项目卡显示“风险待确认”，不伪装零风险；解除模拟后重试恢复 33 条。见 [失败状态](../../output/playwright/v1-improvement-2026-09-08/dashboard-error.png)。
- 320/390 宽度下 `documentElement.scrollWidth` 分别为 320/390，均无横向溢出，恢复后仍为 8 条排名。见 [320 截图](../../output/playwright/v1-improvement-2026-09-08/dashboard-320.png)、[390 风险区](../../output/playwright/v1-improvement-2026-09-08/dashboard-risk-390.png)。
- 真实 API/BFF 结果相同：Owner=25 项目/33 风险；工程师=1 项目/10 风险，My Work 也是 10，未确认候选不进入；Supplier 两端 403，未登录两端 401。
- 本机单客户端、各 30 次 BFF 请求：Owner P50 16.7ms、P95 21.0ms；工程师 P50 16.6ms、P95 22.7ms。见 [计时汇总](../../output/playwright/v1-improvement-2026-09-08/http-metrics.json)。这是本地端点计时，不是生产负载或 UX10 三页首屏 P95 的正式验收。

## 未完成与接续

1. **完整 Mypy 尚未通过**。2026-09-08 19:24 UTC 工作树检查为 3 个并行测试文件、8 个错误：`test_test_templates.py:49`、`test_test_report_mapping.py:57` 及 `test_ai_test_plan_changes.py` 的集合/返回值注解。早先固定快照为 6 个错误；并行任务仍在修改，不能宣告当前工作树全绿。见 [输出](../../output/playwright/v1-improvement-2026-09-08/current-mypy.log)。本任务未修改这三个文件，待该任务收口后重验完整门禁。
2. **提醒周期调度缺口已在后续本地增量补齐**（2026-09-08）：独立 app-role 风险/提醒/派发周期进程、提醒生命周期与并发保护、开发/部署模板已通过本地专项与真实进程/HTTP 验证，见 [后续记录](2026-09-08-v1-reminder-scheduler-validation.md)。没有提升 `pdos_worker/pdos_agent` 权限，也不表示已部署或联合门禁通过。
3. V0 冻结、真实 D14-04 数字链/单日工作流、UX10 三页正式验收、S5-1 真实钉钉和各人工 Exit 按原合同继续。本次没有生产操作、外发、远程 push 或出口代签。

回退仅涉及本轮聚合 API/UI、项目批量加载、My Work 过滤及两份锁文件，无 schema 或业务数据迁移需要回滚。
