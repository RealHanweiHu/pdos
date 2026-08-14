# Sprint 5 CEHub 导入 Project API 发布阻断

日期：2026-08-13（America/Los_Angeles；发现时间 UTC 2026-08-14）

结论：**release `2ccefa1d2fe6567be4af8370b67aed9164aadd1d` 已失效，不得部署或用于生产 apply。CEHub 保持只读，目标库未发生新写入。**

## 1. 发现与生产证据

在全量 dry-run 后执行候选 release 的只读 `deploy-ecs.sh status` 时，有界 10 分钟日志门禁正确拒绝继续，并定位到线上旧 release 的真实请求：

- `GET /api/auth/me` 返回 200；
- 紧接着 `GET /api/projects` 返回 500；
- traceback 从 `ProjectService.list()` 进入 `_record_from_row()`，最终抛出 `ProjectNotFoundError`；
- 线上仍运行 `a34c7eb06aaba036bef8c257c30a841c1ec6be0d`，五个容器 healthy、Alembic `0027_dingtalk_hardening`，候选容器数 0。

虽然异常发生在旧 release，`2cce...` 包含相同的 Project 读模型，因此也受影响。该发现发生在部署、migration 与 apply 之前；没有修改生产 PDOS 数据或 CEHub 数据。

## 2. 根因

CEHub v1 迁移项目没有原生 PDOS Requirement / Development Case，数据库 schema 因而有意允许 `project.projects.development_case_id IS NULL`，迁移器也按此合同写入。Project API 读模型却错误地把该合法状态与“项目不存在”混为一谈：

1. `_record_from_row()` 同时要求 current stage、owner 和 Development Case 非空；
2. 任一租户只要含有合法导入项目，Project 列表就会整体抛错；
3. 即使服务端放行，Web Project 解码器仍错误地只接受 string Development Case ID。

这是跨迁移/API/Web 合同缺口，不是源数据漂移、半迁移或数据库损坏。

## 3. 修复边界

- `ProjectRecord` 与 `ProjectResponse` 的 `development_case_id` 改为可空；
- `_record_from_row()` 继续强制 current stage 与 owner，唯独不再拒绝合法导入项目；
- Project audit snapshot 对导入项目保留 JSON `null`，不写成字符串 `"None"`；
- Web Project 类型和运行时解码器接受 `string | null`；
- 原生 Project 创建请求仍必须提供 Development Case，Case→Project 一次性转换及数据库约束不变。
- 部署入口新增候选镜像只读 Project readiness：migration 前与部署后均用附加 `default_transaction_read_only=on` 的独立连接列出并序列化目标 tenant 全部 Project；非只读连接或任一响应不兼容都 fail-close。

回归先在旧代码精确失败：真实迁移 apply 后 `ProjectService.list()` 抛 `ProjectNotFoundError`，Web 解码器返回 false。最小修复后两项 focused 回归均通过；本地完整门禁为 Server 388 tests、Web 37 files / 126 tests、Ruff/format 246 files、mypy 213 source files、ESLint/TypeScript 与 webpack production build 33 pages 全绿，PR CI 继续提供独立复验。

## 4. 发布与迁移 Gate 影响

- 先前 inventory capture、写冻结、verify、dry-run 与目标零变化证据仍是真实历史证据，但只绑定已失效 release，不能直接授权 apply；
- 修复合并后的最终 merge SHA 才能成为新的 release；必须重新构建并验证 Git/OCI revision；
- 在 CEHub 继续只读的前提下，用新 release 重新执行 inventory verify、全量 dry-run 与目标前后快照；source fingerprint 即使保持不变，也要与新 release 一起由 Data Owner 重新批准；
- 新 release 的部署、migration 0028～0030 和生产 apply 仍是两次独立授权；不得因本次修复自动执行。

CEHub 当前仍为 `default_transaction_read_only=on`，真实新连接可读 4 Project、零行写探针返回 `25006`、assigned-XID 会话为 0，activity-log tailer 保持关闭。
