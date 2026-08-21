# 生产账户管理 v1 合同

> 日期：2026-08-20
> 规格出处：RBAC_and_Audit、UI 基线“治理 / 成员与角色”、S0-4 `USER_MANAGE` 权限。
> 性质：补齐已拍板治理入口的生产可操作性；不改变 7 角色、租户边界或 Sprint 5 外部 Gate。

## 1. 目标与边界

- 已初始化租户不开放匿名注册；新账户只能由当前租户的 Owner/Admin 创建。
- 提供租户内账户列表、创建、资料/角色/启停更新和管理员密码重置。
- 用户名创建后不可修改；密码、密码哈希和会话凭据永不进入响应、Event、Audit 或浏览器存储。
- 本工作项只交付代码、迁移与本地验收；生产迁移和部署仍需单独授权。

## 2. API

- `GET /api/admin/users`：Owner/Admin 列出当前租户账户。
- `POST /api/admin/users`：创建当前租户账户；输入 `username/display_name/email/role/password`。
- `PATCH /api/admin/users/{user_id}`：更新 `display_name/email/role/is_active`，拒绝空 patch。
- `POST /api/admin/users/{user_id}/reset-password`：设置一次性临时密码并递增 credential version，使旧 JWT 立即失效。

所有响应只返回公开账户字段：`id/tenant_id/username/display_name/email/role/is_active/last_signed_in_at/created_at/updated_at`。

## 3. 权限与不变量

- Owner 可管理全部 7 角色；Admin 只能创建/管理 Project Manager、Engineer、Quality、Supplier、Customer。
- Admin 不得创建、修改、停用或重置 Owner/Admin。
- 任何人不得改变自己的角色或停用自己；管理员重置密码不得以自服务入口替代“修改本人密码”。
- 当前租户必须始终保留至少一个 active Owner；最后一个 active Owner 不得降级或停用。
- 路径中的用户必须属于当前租户；跨租户统一按不存在处理。
- 用户名在租户内唯一；email 可空，非空时在租户内唯一。

## 4. 数据、事件与会话

- migration `0031_user_account_management` 为 `cehub_core.users` 增加 `auth_version INTEGER NOT NULL DEFAULT 1` 和正数约束。
- JWT 带受签名的 `ver` claim；每次受保护请求均与数据库 `auth_version` 比较。
- 密码重置同事务更新 Argon2id hash、递增 `auth_version`，写 `USER_PASSWORD_RESET` 与 `user.password_reset`。
- 创建写 `USER_CREATED` / `user.create`；资料、角色或状态变更写 `USER_UPDATED` / `user.update`。
- Event/Audit 只保存非敏感差异；不得保存密码、hash、token、secret。

## 5. 前端

- Owner/Admin 导航新增“成员与角色”；其他角色无导航，直接访问显示明确 403 状态且不请求成员 API。
- 页面包含账户总数/启用数、成员表、创建表单、角色与状态操作、密码重置表单。
- 提供 loading、empty、error、success 状态；320px 起可用，所有控件有 label 且可键盘操作。

## 6. 验收

1. Owner 创建 7 角色账户并可用租户标识/用户名/密码登录；跨租户不可见。
2. Admin 的权限提升与管理特权账户尝试全部 fail-close。
3. 最后 active Owner、自停用/自降级、重复用户名/email、空 patch 均稳定拒绝。
4. 密码重置后旧密码和旧 JWT 均失效，新密码可登录；任何持久化证据不含秘密。
5. Alembic `0030→0031→0030→0031`、metadata 零漂移、单 head 通过。
6. Server/Web 聚焦与全量门禁、真实浏览器 Owner 正向和 Engineer 负向路径通过。
