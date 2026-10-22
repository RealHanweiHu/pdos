# 普通属主与生产属主方案

2026-10-09；仅本地合成候选验证，生产未执行。本方案响应 M3 G0 审查第 1 项。

原 `postgres` 超级用户属主检查不能证明 FORCE RLS 在普通属主下可用。新的验证从空数据库开始，应用全部现行 S0/B3 与 M2 迁移，再安装独立 M3 候选。数据库、schema、表及全部已安装 SECURITY DEFINER 函数统一由 `pdos_next_owner` 持有；该角色为 NOSUPERUSER、NOBYPASSRLS、NOCREATEROLE。本地测试连接需要 LOGIN，生产采用 NOLOGIN。

## 生产角色与迁移身份

- `pdos_next_owner`：NOLOGIN、NOSUPERUSER、NOBYPASSRLS、NOCREATEROLE、NOCREATEDB；持有业务 schema、表及 definer 函数。
- 专用迁移登录身份：由部署管理员管理，可显式 SET ROLE 到 owner；迁移必须在该角色下执行。迁移身份不进入应用配置。
- `pdos_next_app`、auth、dispatch、`pdos_agent`：均不得成为 owner 或迁移身份的成员，均为 NOSUPERUSER、NOBYPASSRLS。应用角色没有业务 schema CREATE 权限，AI 角色没有直接业务表 INSERT/UPDATE/DELETE 权限。
- 扩展、账号、数据库的初始配置由获授权的环境管理员办理；不会通过应用账号创建，也不把本地 bootstrap 超级用户配置带入生产。

## FORCE RLS 的显式内部政策

FORCE RLS 保留。普通 owner 不会自动越过它，因此每张启用 RLS 的业务表有 `owner_internal TO pdos_next_owner USING(true) WITH CHECK(true)`。这是可信迁移/definer 身份的显式访问政策，不是赋予运行账号 BYPASSRLS。

现有 AS RESTRICTIVE、TO PUBLIC 的政策也会限制 definer owner，并可能令品类/受众辅助函数递归或读不到授权根。本轮将这些政策的适用角色明确绑定为 app、auth、dispatch、AI 四种运行身份，谓词原样保留；owner 由单独的内部政策办理。运行身份不能继承或 SET ROLE 到 owner。

每个 definer 的 search_path 固定为 `pg_catalog,public,pg_temp`，且运行身份不能写 public schema；临时对象不会抢先于可信业务表解析。M3 的 definer 公共/AI 执行权限撤销，只对应用账号开放需要的可读守卫；原子触发器依然由数据库调用。

## 已有迁移的处理

不改写旧不可变迁移，也不只修 M3 的几张表。`tools/owner_policy.py` 是本地验证使用的明确属主政策步骤；它在现行迁移完成后统一处理已有 RLS 表和全部已安装 definer 的搜索路径。实际函数属主、角色成员关系、表 FORCE 状态及现行 head 见 [完整实库清单](definer-ownership.json)。

正式汇合时，在 B7/B8 的真实 head 上分配新的单调迁移，固化 owner 政策、M3 表/守卫与当前 T2 确认字段一致性；安装后核对函数和表属主。已有数据库如果对象仍属于 postgres 或其他管理员，需由有权部署身份明确转交业务对象及 definer 属主，随后再运行普通属主验证。不得用超级用户迁移通过来替代该出口，也不得给应用或 AI 增加 owner 成员资格。

2026-10-09 复核确认：`tools/owner_policy.py` 仍只是本地步骤，正式迁移尚未落地，不能据此关闭 B7/B8 的生产属主出口。生产账号创建和属主转交须先取得用户对相应目标环境与操作的明确授权；本方案或本地测试通过不构成授权。最新独立候选在 `s0_0719` 复验的 [52 个普通属主 definer 清单](../review-followup/definer-ownership.json)也只属于本地合成环境。

后续状态补注：共享 B8 现已有 `s0_0720_trusted_owner.py` 正式迁移，固化通用业务表/函数属主、内部 RLS 政策与运行身份边界；上段“尚未落地”属于此前检查点。M3 候选表/守卫仍未正式汇合，本页不代表生产账号创建或属主转交已获授权或已执行。P11 验证复用的是原 `s0_0719` 独立库，见 [P11 记录](../g0-p11/result.md)。

## 验证边界

[本轮结果](result.md)与 [实库清单](definer-ownership.json)证明这个本地候选的普通属主安装、权限边界及所列业务路径。它们不证明所有现有 definer 的每个业务分支都已全量回归，不代表生产角色已建立、正式迁移已合并或生产启用已批准。生产账号、数据库和部署仍遵守项目明确授权关卡。
