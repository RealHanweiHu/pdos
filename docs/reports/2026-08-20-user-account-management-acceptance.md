# 生产端账户管理缺口收口验收报告

日期：2026-08-20
结论：**本地代码、迁移、完整质量门禁和真实浏览器验收通过；生产部署未执行。**

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

## 发布边界

- 未连接或修改生产数据库，未运行 production migration，未部署 ECS/Nginx，未 push。
- 生产启用仍需单独授权：备份/迁移 `0031`、部署 API/Web、Owner smoke 与观察窗。
- 本缺口收口不改变 canonical 当前指针：S5-1 真实钉钉应用 Exit Gate 与 Sprint 5 生产切换仍保持未通过。

## Error ledger

| 现象 | 处理 |
|---|---|
| 前端完整套件与 395 项后端套件并行时，6 个 UI 用例统一触发 5 秒超时 | 后端结束后以单 worker 复跑，38 files / 133 tests 全绿，确认是资源争用而非断言回归 |
| macOS FileProvider 与重叠 `.next` 构建产生带 ` 2` 的冲突目录 | 停止构建、原子隔离并清理纯生成产物；在 `/private/tmp` 单次 webpack build 完整通过 |
| 本地 `.env` JWT 占位值不足 32 字节 | 不修改用户环境文件；本地验收进程显式使用 32+ 字节测试密钥 |
| 真实浏览器报告 username pattern 正则错误 | 将字符组连字符按 `/v` 规则转义，并加入密码重置表单的隐藏 username；浏览器复验零错误 |
