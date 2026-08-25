# 生产驾驶舱历史项目读取 Hotfix

日期：2026-08-20（PDT；生产执行时间为 2026-08-21 UTC）

结论：**根因已修复并发布；生产驾驶舱、4 个历史项目、风险集合与 AI 简报验收通过。**

## 现象与复现

- 用户登录生产后，驾驶舱显示“驾驶舱暂不可用 / 无法读取项目组合”。
- 使用同一 `pdos-admin` 会话稳定复现：`/api/session/me = 200`，`/api/projects = 500`。
- API traceback 定位到 `ProjectService.list → _record_from_row → ProjectNotFoundError`。

## 根因

- CEHub 迁移器按合同迁入全部历史项目，但源系统没有 PDOS 的 Requirement / Development Case 前置链，因此 4 个生产项目合法保留 `development_case_id = NULL`。
- 数据库 schema 和迁移器允许该历史形态；领域读取模型、API response 和前端运行时校验却仍把 `development_case_id` 当成必填字符串。
- 新 Admin 可见全租户项目，项目列表读取第一条历史记录时即被误判为“不存在”，导致整个 `/api/projects` 返回 500。Owner、Workflow、Current Stage 与项目数据本身均完整。

## 修复

- `ProjectRecord`、`ProjectResponse`、前端 `Project` 类型与运行时 validator 接受历史项目的 `development_case_id = null`。
- `_record_from_row` 继续对缺失 Owner 或 Current Stage fail closed，只移除错误的 Development Case 非空读取断言。
- 项目审计快照对历史 `null` 保持真实值，不再序列化为字符串 `"None"`。
- `ProjectCreateRequest` / `ProjectDraft` 仍要求非空 Development Case；新项目的获批 Case 硬闸没有放宽。

## 验证

- RED：后端生产形态集成测试稳定抛出 `ProjectNotFoundError`；前端同形态测试稳定进入截图中的错误态。
- GREEN：项目 API 5 tests、Server 全量 396 tests、Web 全量 38 files / 134 tests 通过。
- Ruff、format、mypy、ESLint、Next typegen / TypeScript、Python compileall 全绿。
- ECS production build 完成 35 个静态页和全部动态路由；Git SHA、image tag 与 OCI revision 一致。

## 生产发布

- Hotfix release：`1f73cce8f5377398e82c35491d4d2ce1b0cfddc2`。
- 回滚 release：`64e2fd74c4035cc05e4e8ec74f5564c7fc89176d`。
- 无 schema 变化；Alembic 保持 `0031_user_account_management`，部署 migrator 为 no-op。
- 五个容器均 healthy、restart count 为 0；Agent 最小权限重施通过，bounded logs 无 fatal pattern。
- 同一生产管理员会话验证：`/api/projects = 200`，C4s / D14-04 / D15-05 / S18-01 共 4 项且结构合法；4 个风险集合、AI brief 与驾驶舱页面全部 200。

## 范围边界

- 未修改生产数据、Nginx/DNS 或钉钉配置，未开启 DingTalk delivery，未执行 Git push。
- 本 hotfix 不改变 S5-1 真实钉钉应用 Exit Gate 或 Sprint 5 全量切换状态。
