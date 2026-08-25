# 生产首用入口与项目任务体验修复报告

日期：2026-08-21

结论：**代码、本地隔离数据库、完整质量门禁和真实浏览器验收均已通过；生产 migration `0032`、镜像切换、管理员公网 smoke 和 43 分钟观察窗全部完成。本轮没有 Git push。**

## 用户可见问题与修复

- 项目任务列表此前只显示标题和操作，无法展开查看描述、所属阶段、计划日期、负责人和依赖。现在任务行支持显式展开，创建任务时也可补充这些字段。
- CEHub 历史任务把源任务 ID 当标题，导致列表内容看似错误。migration `0032_repair_task_titles` 只修复符合导入工作流、仍保持原始 ID 标题的历史任务，并从冻结的 687 项资产清单恢复规范名称；用户后续编辑过的标题不覆盖。
- 项目切换和工作区标签此前不进入 URL，刷新或分享链接会丢失位置。现在 URL 持久化 `project` 与 `tab`；项目概览默认只读，进入编辑需要显式动作，取消编辑不再退出项目。
- Gate 阻塞项只有技术名称且没有恢复入口。现在按任务、问题、风险、文档、构建/样机、测试/认证和专业签核分类显示中文原因，并提供跳转；Owner/Admin/Project Manager 可开启签核轮次，符合角色的成员可执行专业签核。
- 需求录入只能选择既有客户。现在具备 Requirement 创建权限的用户可在需求池新建客户，创建成功后立即成为当前表单选项；客户编码冲突稳定返回 409。
- 生产端账户管理缺少本人修改密码入口。现在所有已登录的本地账户都可从“账户安全”修改密码；校验当前密码、禁止复用、成功后递增凭据版本并撤销当前及旧会话，密码不进入事件或审计。
- AI Review / 驾驶舱空状态此前可能让用户误以为 Agent 正常值守。现在只陈述“当前无 Finding”，不再把空队列等同于模型可用；Owner/Admin 可直接前往模型治理页确认配置。

## 数据与安全边界

- migration `0032` 单调追加，当前唯一 Alembic head 为 `0032_repair_task_titles`；Docker 生产镜像显式携带冻结任务资产。
- Customer 创建继续走租户权限、Event/Audit 和同源 BFF；任务、Gate 和账户操作不放宽既有 RBAC。
- 修改密码使用认证服务现有哈希策略；成功更新与 `auth_version` 增长原子完成，旧 token fail closed。
- 本地自动化与浏览器验收只连接 `pdos_test`；生产数据库只执行本报告列明的已授权 preflight、备份、migration 和只读复核。没有修改 Nginx/DNS、钉钉配置或其他外部系统。

## 自动化验证

- Server：401 tests passed；Ruff、format、严格 mypy（217 source files）、Python compileall 全绿。
- Web：40 files / 144 tests passed；ESLint、TypeScript 全绿。
- Next.js webpack production build 通过，生成 37 个静态页及全部新增 BFF 路由。默认 Turbopack 在当前沙箱因内部端口绑定被拒，未将该环境限制伪记为通过。
- `git diff --check` 通过。

## 真实浏览器验收

- 任务行可展开并看见描述、阶段、计划日期、负责人、依赖和操作；项目/标签 URL 可刷新保留。
- 在隔离测试租户中新建客户后，需求表单立即可选。
- “账户安全”修改密码表单可访问；为避免破坏浏览器验收账户，只验证页面和合同，密码变更成功/失败及会话撤销由自动化 API/BFF 测试覆盖。
- AI Review 空状态与模型治理入口文案一致，不再显示虚假的“正在值守”。
- 新项目 Gate 从 `draft` 开启签核轮次后进入待专业签核状态并显示恢复动作；未执行最终专业批准。
- 桌面与 320×800 视口无横向溢出，交互按钮满足 44px 触达目标；console 0 warning / 0 error。超长 full-page 截图曾在预览中被压缩，普通 viewport 截图与 DOM 几何复核确认不是页面布局缺陷。

## 已执行发布步骤

1. 冻结待发布 Git SHA 和回滚 SHA，并在生产执行只读 preflight/备份。
2. 在单独生产授权下执行 migration `0031 → 0032`、构建与容器滚动切换、Agent 权限重施。
3. 使用真实管理员完成任务标题/详情、本人改密失败路径、AI fail-closed 状态和 Gate 读取的公网 smoke；避免创建测试业务数据或修改生产密码。
4. 观察容器健康、restart count、bounded logs 和公网入口并形成生产发布报告。

当前 canonical 指针不变：S5-1 真实钉钉应用 Exit Gate 与 Sprint 5 生产切换仍待人确认；本次发布不自动通过这些 Gate。

## 生产发布

- 授权：人于 2026-08-21 明确授权生产只读预检，并在通过后发布 migration `0032` 和本次修复；该授权不包含 Git push、MiniMax golden-case 数据出站、钉钉外发或 Sprint 5 Exit Gate。
- 旧 release：`1f73cce8f5377398e82c35491d4d2ce1b0cfddc2`；新 release：`905e888fb3b183be8f14d9fad13b20535569c1d7`。新 release 来自本地 commit 的完整 Git bundle，双端 SHA-256 一致；ECS 从 bundle 克隆到全新目录，HEAD、镜像 tag 和 API/Web OCI revision 精确一致。
- 生产预检：原 migration 为 `0031_user_account_management`，五容器 healthy；公网登录、session status、未知钉钉 callback 边缘探针与最近 10 分钟日志门禁通过；磁盘余量 23GB，环境文件为 root:600，钉钉 delivery 继续为 false。
- MiniMax：生产环境已存在默认供应商凭据且 `provider=minimax`，但仓库审核资格文件仍为空。未取得把可信 golden-case 提示词发送给外部 MiniMax 的单独授权，因此真实评测没有执行、没有外部请求，生产治理 API 继续返回 0 个 eligible model，系统保持 fail closed。
- 数据影响预检：只读事务确认 117 条 CEHub 导入任务仍为源 ID 标题、0 条已为规范标题；没有命中用户自定义标题。
- 迁移前备份：`/opt/pdos-backups/20260821T170914Z-pre-first-use-remediation`，包含 mode 0600 的 PostgreSQL 18 custom dump（520,445 bytes）、环境快照、旧镜像身份和校验和；`pg_restore --list` 验证可读。
- 唯一受控入口完成 `0031 → 0032`、Agent 最小权限重施和 API/dispatcher/executor/DingTalk/Web 依次切换；脚本内置公网与 bounded-log 验证通过。
- 部署后数据库只读复核：migration head=`0032_repair_task_titles`，117/117 条导入任务为规范标题，源 ID 标题残留 0。
- 管理员公网 HTTP smoke：login→me 成功；4 个项目可读；抽样项目 21 条任务具备完整详情字段，4 个 Gate 可读；账户安全页 200；错误当前密码稳定返回 400 且原会话仍有效；未创建客户、未修改密码、未批准 Gate。
- 观察窗从部署后持续 43 分钟；最终 `deploy-ecs.sh status`、公网 callback 边缘、bounded logs 与 migration head 全部通过。五容器始终 healthy，restart count=0，revision 全部为新 release。

## 生产发布 Error ledger

| 现象 | 处理与边界 |
|---|---|
| MiniMax 真实 golden-case 评测需要把可信评测提示词发送给外部供应商，当前授权不足 | 评测在请求发出前被拒绝；没有数据出站，模型保持不可选。需人单独授权后才能运行、人工复核并通过代码变更发布资格 |
| 首个候选 `3aa89d9…` 的 API 镜像构建找不到任务资产 | 构建阶段 fail-close，未迁移、未切换线上容器；根因是 `.dockerignore` 排除了已跟踪资产。增加精确 include 与发布合同测试，形成新 release `905e888…` 后从干净 bundle 重建通过 |
| 第一次 bundle 上传的本地路径未引用 `&`，shell 在发起网络前拒绝 | 使用单引号引用完整路径重试，双端 SHA-256 一致；没有产生半上传远端文件 |
| 两条生产只读统计脚本分别遇到 f-string 引号和 SQLAlchemy 驱动名错误 | 均在建立写事务前退出；改用无转义格式和仓库 `psycopg_database_url` 后重跑通过，生产数据未变化 |
| 部署后规范标题 join 初次得到 144 | 同名规范标题造成 join 重复，不是额外任务；改为 `count(DISTINCT task.id)` 后与 117 条导入任务精确一致 |
| 发布后补跑完整后端套件时，沙箱拒绝本机 PostgreSQL/socket | 中止无效运行；授权访问本机隔离 `pdos_test` 后以同一命令重跑，401 tests 全绿。未连接开发或生产库 |
| 长观察会话在第 23 次健康采样后被远端关闭 | 第 23 次采样本身为 healthy/0 restart；新会话在已超过 40 分钟时再次采样并运行完整 status，43 分钟最终结果仍全绿，无应用故障或回滚触发 |
