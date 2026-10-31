# 本人显式偏好闭环 · 2026-10-29

范围：小Pai日常问答与企业RAG设计 §6.5、上下文设计 S3。此报告仅记录本子任务；公共汇合、数据库和浏览器证据由主会话统一保存。

## 可用能力

- 设置页“个人偏好”中可以显式保存回答语言、详略、岗位、部门和常用品类/项目，并可一键清空。没有岗位资料时保持“未设置”，不从名称、聊天或行为推断。
- 本人账户偏好独立持久化，登录人和租户来自服务器认证。读取不创建默认记录，保存不创建领域命令或T1/T2确认；小Pai没有偏好写工具。
- 保存有版本冲突守卫；丢失响应后相同值重试返回已保存状态。界面保留未保存填写；冲突时可读取最新版本而保留填写后再次显式保存。
- 常用范围只生成导航候选。保存时新加入的ID须当前可读，返回和运行上下文中的名称、URL都从当前RLS权威对象读取。历史收藏可供本人移除，撤权后不再投影其名称或导航。
- 个人小Pai欢迎页读取已选岗位的默认示例。点击只填输入框；不会发消息、切换范围或取得动作权限。收藏显示为可点击导航候选，进入对象后仍走原访问校验。可选读取失败保留原欢迎，窗口重新获焦时清除旧投影并复核。
- `context_preferences(session, scope)` 仅按受控Run的requester提供封闭格式，标记 `source=explicit_user_settings` / `use=personalization_only`，不改变固定提示前缀、模型、技能或权限。主会话的上下文代理负责接入动态信封、按Run冻结和预算。
- `recheck_context_preferences(session, scope, frozen_value)` 只批量复核冻结候选的当前可读ID，不重新读取偏好或名称；偏好/名称更新不打断运行，撤权则返回失败供现有partial路径使用。

## 存储和接口

- 新表 `personal_preferences`，迁移 `s0_0831`，前继为实际磁盘head `s0_0830`。每租户×本人一行；更新须保留身份并单调增加版本。空表可降级，非空表拒绝降级以保留设置。
- RLS读取绑定当前requester；受控host可在运行事务中读取该requester的设置。INSERT/UPDATE只允许本人human，`pdos_agent`没有直接SELECT/INSERT/UPDATE/DELETE权限；不授予额外schema权限。
- `GET /v1/personal/preferences`，`POST /v1/personal/preferences`，`GET /v1/personal/preferences/options`。专属Next BFF保持同源写入、有限字段、会话凭据、no-store和原错误状态，不修改公共catchall。
- `/options`按当前RLS分页查名称，返回轻量权威元数据；每类最多选择10项。

## 本子任务验证

| 检查 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q tests/test_personal_preferences.py` | 16项通过 |
| `node --test src/lib/personal-preferences.test.mjs src/components/personal-preferences.test.mjs` | 9项通过 |
| `tsc --noEmit --incremental false` | 通过（本次候选类型检查时点） |
| 8个受影响前端源码/route文件目标ESLint | 通过 |
| 本子任务后端源码、迁移、专用测试Ruff | 通过 |
| 主会话集中执行 `tests/test_personal_preferences_pg.py` | 14项通过，见主证据 `preferences-and-task-pg.txt` |
| 冻结前端候选实际本人浏览器 | 保存/刷新/清空、角色欢迎、手动导航、1280明暗/390与320暗、键盘与溢出通过；见[浏览器证据](browser.md) |

纯测试覆盖有限字段、伪造权限/自动学习拒绝、本人/事务范围、运行上下文排除不可读ID、冻结候选仅按ID复核、显式保存/清空、响应丢失重试、冲突保留填写、收藏分页/搜索/上限、欢迎示例只填输入、获焦撤权刷新、BFF身份与错误透传。

专用PG文件 `tests/test_personal_preferences_pg.py` 共14项由主会话统一执行并全部通过，覆盖真实API保存/清空/冲突、跨用户和跨租户、撤权、受控Run读取、AI身份写入和直接SQL权限、SQL身份/版本guard、冻结配置复核及非空降级保护。本子任务未自行连接或操作数据库。主会话已反馈空表0830→0831→0830→0831往返、表结构/RLS/权限检查通过；首次13项PG中9过4失败仅因负例未限定schema导致42P01，已改用 `public.personal_preferences`，未扩大权限。最终14/14日志为主证据目录的 `preferences-and-task-pg.txt`，该日志另有的图预算失败不属于偏好PG结果。

## 文件归属与边界

后端：`pdos_next/personal_preference_models.py`、`personal_preference_schemas.py`、`personal_preferences.py`、`personal_preferences_api.py`；`migrations/schema_s0_0831.py` 与 `versions/s0_0831_personal_preferences.py`；专用两份后端测试。

前端：`lib/personal-preferences.ts`、`personal-preferences-proxy.ts`及库测试；两条专属BFF路由；`components/personal-preferences.tsx` / `.module.css`、`personal-preference-welcome.tsx`及组件测试；设置页和个人小Pai欢迎入口的必要接线。

公共 `models.py` / `api.py` 导入和上下文信封/预算/逐调用复核由主会话与对应代理统一汇合。未修改唯一清单、golden-case、真实模型或embedding配置；未调用真实模型、外发、提交或推送。主会话已冻结前端构建并集中完成专用PG，本子任务随后对同一前端候选补齐实际浏览器亮暗/窄屏验证，详见[浏览器证据](browser.md)。完整两份设计、其他图预算测试和正式阶段验收仍由主会话按总目标记录，不由偏好子任务声明完成。
