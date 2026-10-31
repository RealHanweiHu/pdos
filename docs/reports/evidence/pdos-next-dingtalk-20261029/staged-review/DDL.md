# 未编号 DDL 与 wrapper 顺序

不要盲执行拼接 SQL。`review/alembic-wrapper.py.template` 是可审阅模板，无 revision/down_revision；root 读真实 head 后分配，按现有迁移的 exec_driver_sql(no_parameters=True) 方式执行，不把 `%` 当参数。`migrations/candidates/` 两文件只有静态常量，不安装迁移。

## 依赖与前置

- 已有四 runtime roles、普通 NOLOGIN pdos_next_owner、原 principals / tenant_administrators / agent_runs / agent_tool_calls / agent_run_events；不改变这些业务/根表的 owner 或既有 FORCE RLS。
- 已有 scope_actor(), scope_requester(), category_access(uuid,uuid,boolean)、kernel_release_call(uuid,uuid,text,boolean,integer,text)。新 maintenance role 只获得实际所需谓词/取消元数据权限；没有业务来源正文权限。
- F `assistant_source_lifecycle_links(uuid,uuid,jsonb)` 已由 schema839 提供，ordinary pdos_next_owner SECURITY DEFINER，runtime 无 EXEC。本层不重定义 typed 映射、不新增 runtime EXEC。
- 两个旧函数 `m3_lifecycle_nodes(uuid,uuid,uuid[])`、`m3_lifecycle_source_links(uuid,uuid,text,jsonb)` **以当前 schema839::NATIVE_FUNCTIONS 的精确字符串为旧 pin**，不是更早 before-F 版本。已逐字比较，并核 schema841 不改两项，见 evidence/native-function-pins.json。wrapper 每次 upgrade/down 都再 require_functions；后来共享函数变化须重基线，不能强覆写。
- 旧 m3_lifecycle_roots / clock / gate 和 category/product epoch 元数据路径须存在。G lifecycle owner SELECT 路径只取保留元数据。readset 表 owner_internal 依据静态核对，不代替实际 PG 证明。

## 升级顺序与具体 owner

1. 使用已获授权的 **administrative migrator**，RESET/SET LOCAL ROLE NONE。CREATE ROLE、现有跨表列 GRANT/取消 policy、将新函数 ALTER OWNER 给新维护角色均需要此管理权限；不得为了迁移把 owner/maintainer 成员授给 app/agent/auth/dispatch。新 maintenance role 若已存在，fail closed，不复用不明角色。
2. `ordinary_owner()` 先验证普通 owner 无危险 flags/runtime 成员，并 `require_functions(PREVIOUS_FUNCTIONS)`；再 SET LOCAL ROLE NONE 回管理者。
3. 管理者执行 `BASE_SQL`（135 条，精确来自 delta base；含新角色/6表/FORCE RLS/权限/9函数/trigger）。角色 `pdos_next_dingtalk_maintenance` NOLOGIN/NOSUPERUSER/NOBYPASSRLS/NOINHERIT/NOCREATEROLE/NOCREATEDB/NOREPLICATION，最终仅保留 public USAGE，不保留 CREATE，不授 runtime 成员。
4. 九函数最终 owner 均为 maintenance：dingtalk_admin(uuid)、dingtalk_service(uuid,uuid)、dingtalk_callback_application(uuid)、dingtalk_message_service(uuid,uuid)、dingtalk_pending_references(uuid,integer)、dingtalk_cancel_lost_run(uuid,uuid)、dingtalk_control_guard()、dingtalk_mark_dispatched(uuid,uuid,uuid)、dingtalk_run_identity_guard()。每条 ALTER OWNER **之后**恢复内部 pdos_next_owner EXEC，再撤 PUBLIC/四 runtime 并仅授该函数明确 runtime 调用方；trigger 函数不暴露 runtime EXEC。helper 间调用在维护 role 自身/内部 owner，不能凭 SECURITY DEFINER 标签跳过其真实 ACL。
5. 管理者执行 `TRANSFER_TABLES_SQL` 6 条，六表最终 owner=pdos_next_owner，维护 role 不拥有表。既有根/业务表 owner 均不改。保留 runtime 原有限 DML、FORCE RLS 与完整 guard。
6. 调 `ordinary_owner()`，执行 `LIFECYCLE_UP_SQL` 14 条：Delivery 专用 owner metadata policy/显式四列 grant → 两个 m3 CREATE OR REPLACE → 两个 G clock/gate 函数及精确 ACL → 两个 dedicated triggers。新 clock/gate owner=pdos_next_owner、固定 search_path，ALTER OWNER 后恢复内部 EXEC，PUBLIC/四 runtime 无 EXEC。原两 m3 函数 CREATE OR REPLACE 保留原 owner/ACL，不重新替换 resolver。最后 SET LOCAL ROLE NONE。

完整人读顺序：sql/01-dingtalk-base-up.sql → TRANSFER_TABLES_SQL → sql/02-delivery-lifecycle-up.sql；sql/combined-up.draft.sql 已按此拼接。不能先普通 owner 执行 CREATE ROLE/向新 role 转移函数。trusted owner 的固有表权限不被误称列 ACL 限制；metadata-only 来自实际查询投影，maintenance/runtime 仍无正文提升。

## 降级顺序与非空保护

1. 管理者 SET LOCAL ROLE NONE，并确认能越过 FORCE RLS 看到全租户历史。`EMPTY_HISTORY_SQL` **第一步**按固定表序 ACCESS EXCLUSIVE 锁六表，再检查六表任一实际记录，非空抛错；禁止仅用普通 owner 可见子集判空，禁止清空表来通过 downgrade。事务持锁到结束，不在检查后释放竞态窗口。模板检查 superuser 或具备 BYPASSRLS+CREATEROLE 的管理者最低能力；实际既有对象管理/角色转移资格仍需 root 核对。
2. `ordinary_owner()` + `require_functions(NATIVE_FUNCTIONS)` 核当前新 m3 精确 pin；执行 `LIFECYCLE_DOWN_SQL` 8 条：移除两专用 triggers / functions → 恢复精确 schema839 m3 nodes/source_links →撤四列显式 grant / 新 owner policy。其他 FORCE RLS、F resolver、既有 policy/ACL 不动。此时 G 表仍在，避免函数悬空。
3. SET LOCAL ROLE NONE；管理者执行 `BASE_DOWN_SQL` 66 条：先移除现有 agent_runs 的 G trigger、六表 G policies/triggers → 删除九 G helper/functions（先 policy 依赖后函数）→ child-first 删除空六表 → 移除五个既有表上的 G policy/表级 grant → 逐列撤销全部 SELECT/UPDATE grant →撤 kernel_release_call/普通谓词 EXEC 与 schema privileges → DROP maintenance role。不使用 CASCADE、DROP OWNED 或临时关闭 RLS。

精确列撤销是本 integration 追加修复：原冻结 delta DOWN 的 REVOKE ALL ON TABLE 不会撤 column ACL；没有这一步角色可能仍因依赖无法 DROP。sql/04-dingtalk-base-down.sql 与 candidate::BASE_DOWN_SQL 都已补，原冻结包未漂移。完整 down：EMPTY_HISTORY_SQL → sql/03-delivery-lifecycle-down.sql → sql/04-dingtalk-base-down.sql，见 combined-down.draft.sql。

以上均静态审阅，未在 PG 编译或执行；root 负责真实角色能力、函数 ACL、up/down/up、非空拒绝及历史 counts。正式安装前不得将本包称为已启用 G。
