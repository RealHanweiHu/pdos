# 生产端账户管理缺口收口验收报告

日期：2026-08-20
结论：**本地完整门禁与真实浏览器验收通过；生产 migration、ECS 发布、管理员创建及公网正反向 smoke 通过。**

## 已完成合同

- 保留空库一次性 `/api/setup`；初始化后不开放匿名注册。
- Owner / Admin 可在“治理 → 成员与角色”中查看租户账户、创建账户、分配允许角色、启停账户和重置他人密码。
- Owner 可管理七种角色；Admin 不能创建、修改或重置 Owner/Admin；其他角色无账户列表请求与管理入口。
- 用户名创建后不可修改；用户名和邮箱按租户唯一；跨租户目标返回 404；本人不能修改自身角色/状态或通过管理接口重置自身密码。
- 密码只以 `SecretStr` 进入请求，不进入响应、事件、审计或浏览器持久状态。重置后 `auth_version` 单调递增，旧密码和已签发 JWT 同时失效。
- `USER_CREATED`、`USER_UPDATED`、`USER_PASSWORD_RESET` 已进入版本化事件注册表；有效写操作与 audit 同事务提交，语义无变化的 PATCH 不写库。
- migration `0031_user_account_management` 为唯一 Alembic head，增加正整数 `auth_version`；存在已撤销凭据版本时 downgrade fail closed。

## 验证证据

- 后端账户/API/迁移/认证/事件聚焦：14 tests passed；no-op 写纪律复验：4 tests passed。
- 服务端完整回归：395 tests passed（全部数据库测试显式连接本机隔离 `pdos_test:57432`）。
- Web 账户交互与 BFF 聚焦：8 tests passed；完整串行回归：38 files / 133 tests passed。
- Ruff、format、严格 mypy（216 source files）、Python compileall、ESLint、Next typegen / TypeScript 全绿。
- Next.js 16 webpack production build 在 `/private/tmp` 的 FileProvider 隔离副本通过：编译、TypeScript、35 个静态页、build trace 与全部路由生成成功；包含 `/governance/users` 及 3 个 `/api/admin/users` BFF 路由。
- 真实 Chromium 仅连接本机 `pdos_test`：
  - Owner 通过 UI 创建账户，角色变更为 Project Manager，停用账户并重置密码；页面明确提示旧会话失效。
  - Admin 创建表单不出现 Owner/Admin 选项，Owner/Admin 行无管理控件，普通账户仍可管理。
  - 非管理员直接访问 `/governance/users` 显示“仅管理员可访问”，导航无账户管理入口。
  - 浏览器发现并修复 HTML `/v` pattern 连字符转义与密码表单 username 提示；新标签复验 console 0 warning / 0 error。
- 浏览器截图：`output/playwright/user-management-admin.png`、`output/playwright/user-management-forbidden.png`。

## 生产发布证据

- 人于 2026-08-20（PDT）明确授权本次生产部署与管理员账户创建；没有据此推断 Git push、Nginx/DNS、钉钉外发或 Sprint 5 全量切换授权。
- 生产旧 release 为 `82de9d215c5b0101aaba8cbff2d1adf6d751ceef`；新 release `64e2fd74c4035cc05e4e8ec74f5564c7fc89176d` 从校验通过的 Git bundle 克隆到全新目录，Git SHA、image tag 与 API/Web OCI revision 一致。
- 迁移前在 `/opt/pdos-backups/20260821T024854Z-pre-user-admin` 保存 mode `0600` 的 PostgreSQL 18 custom dump、生产环境快照、旧镜像身份与校验和；`pg_restore --list` 验证可读。
- 受控部署入口完成 `0030_phase_three_agents → 0031_user_account_management`、Agent 最小权限重施和 API/dispatcher/executor/DingTalk worker/Web 依次切换；五个容器均 healthy、restart count 为 0。
- 公网 `/login`、`/api/session/status`、`/governance/users` 与未知钉钉 callback 边缘探针通过；最近 10 分钟 bounded logs 未发现 traceback、fatal、panic、permission denied 或 connection refused。
- `beepump` 租户创建 active `pdos-admin`（role=`admin`，user id `f22be6d7-bb31-4116-899c-e5dbf18aabdc`）；创建动作由原 active Owner 作为 audit actor。随机密码不进入命令、聊天、日志或仓库，只保存在 ECS root-only `0600` 文件 `/opt/pdos-secrets/beepump-pdos-admin-20260821.password`，待人通过 SSH 安全领取。
- 新账户经公网 HTTPS 完成 login→me→成员列表；Admin 尝试停用 Owner 稳定返回 403。生产库核对 `USER_CREATED`、`user.create`、`user.sign_in` 各一条，密码/hash/token/secret 零留痕。
- 发布后 90 秒内四次采样均为五容器 healthy/0 restart，三个公网入口均为 200；约 5 分钟时再次执行完整 `deploy-ecs.sh status` 和日志门禁通过。

## 发布边界

- 本次没有修改 Nginx/DNS、没有开启钉钉 delivery、没有执行 CEHub inventory/apply/只读退役，也没有 git push。
- 新鉴权 token 强制携带 `auth_version`；发布前签发的旧 token 不含该 claim，会要求用户重新登录。
- 应用回滚目标保留为 `82de9d215c5b0101aaba8cbff2d1adf6d751ceef`；migration `0031` 对旧应用前向兼容，事故处理中不执行 Alembic downgrade。
- 本缺口收口不改变 canonical 当前指针：S5-1 真实钉钉应用 Exit Gate 与 Sprint 5 生产切换仍保持未通过。

## Error ledger

| 现象 | 处理 |
|---|---|
| 前端完整套件与 395 项后端套件并行时，6 个 UI 用例统一触发 5 秒超时 | 后端结束后以单 worker 复跑，38 files / 133 tests 全绿，确认是资源争用而非断言回归 |
| macOS FileProvider 与重叠 `.next` 构建产生带 ` 2` 的冲突目录 | 停止构建、原子隔离并清理纯生成产物；在 `/private/tmp` 单次 webpack build 完整通过 |
| 本地 `.env` JWT 占位值不足 32 字节 | 不修改用户环境文件；本地验收进程显式使用 32+ 字节测试密钥 |
| 真实浏览器报告 username pattern 正则错误 | 将字符组连字符按 `/v` 规则转义，并加入密码重置表单的隐藏 username；浏览器复验零错误 |
| 首次生产备份使用缓存的 PostgreSQL 16 client，被 RDS 18.3 版本门禁拒绝 | 未迁移、未切换容器；改用 ECS 已缓存的 PostgreSQL 18 client 覆盖未完成 dump，并通过 `pg_restore --list` 与校验和验证 |
| 迁移后附加只读检查把 SQL 字符串常量误写成标识符 | 服务状态与 `0031` 已通过；改用 SQLAlchemy 绑定参数重跑，确认列存在且目标用户名创建前为 0 |
