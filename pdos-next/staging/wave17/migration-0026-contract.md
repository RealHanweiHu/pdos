# next_0026 暂存公共迁移准备

状态：独立暂存迁移，未挂载 `server/migrations/versions`、未执行 DB/HTTP/迁移。主线已经核实真实仓库与独立数据库 head 为 `next_0025`，在当前实施点单调分配 `revision=next_0026/down_revision=next_0025`；没有复用旧预留号。当前已经绑定 Root 最终 v3 静态计划，`FINAL_PLAN_BOUND=True`；它仍须由主线统一迁入与实际验证，暂存导入不会执行。原未绑定骨架及检查保存在独立证据，未覆盖旧结论。

冻结来源：`root-unapplied-ddl-plan-v3.json` SHA256 **a5c1426f3d136d2fcd122d0cfed529dee3babeb120b0be5633a706ae4f680f80**；模型 **a7b5f65137f5456f72aa32e9b50d8749ea7a62003f699dedf596495b0a174162**；生成器 **2f625ce1f8ee4df701a7c900b4becaf72db6310fc2836e735148d477cd799bf7**。本文件运行时不读这些外部来源；精确内嵌十组 SQL 的 canonical SHA 为 **bc51f22f4e730cd1f3b45f4df67f1be9cd252f481adc607335bb1581cbf6d656**。statement 数分别为 **6/5/3/4/6/15/41/2/23/4**，静态检查逐句相等，不只是计数。

## 不变接口与静态材料

迁移仅导出标准 Alembic `upgrade()`/`downgrade()`；导入无 SQL、文件读取或连接。运行时不读取 mutable models、staging generator、报告、profile、旧私有 seed 或配置，不创建提交/新的连接。所有表 DDL、约束、五个 tenant indexes、四份旧函数替换、六个新函数、十五个触发器、四十一条权限语句及准确旧函数恢复定义最终均静态内嵌。

绑定 Root 实际 `sql-actual-functions-v1.json` 的六份完整 `pg_get_functiondef` SHA256；升级会在调用者活动 PostgreSQL 事务中重新查询 **public 精确签名**，不以旧报告代替现场检查。`require_quality_followup_atom()` 保留 head25 JSON 修正版，`assert_quality_followup_receipt(...)` 原样保留。其余旧合并/Change/失败映射守卫与事实不变。迁移前须实际单头精确匹配，版本行 `FOR UPDATE` 保持至调用者迁移事务结束；只允许 public schema。

## 升级顺序

1. 核完整内嵌 SQL/hash/count、真实 Connection/PostgreSQL 活动事务、公有 schema、单一 head25 及六份实际定义全 SHA。
2. 拒绝收养任意已存在的五张新表。持旧 `confirmations/action_receipts/capa_verification_evidence` 迁移表锁；仅检查新 Candidate、四个新 operation 的回执及新三人工操作已消费 proof 必须为空。旧 RootCause/Complete/Link 保存历史允许保留，绝不调用 head24 禁止全部旧已消费的预检。
3. 添加 `confirmations UNIQUE(tenant_id,id)` 供新 proof 复合 FK；建立五张新表及五个 tenant indexes，再核父唯一键。静态模型必须绑定 C 冻结的窄索引版：purpose 仍完整保留在语义/真实 SQL 对等检查，仅物理 INDEX_BINDING 的大索引/前版 FK 排除长 purpose，issuer key/version DB100 上限保留。
4. 安装四旧函数精确扩展、六新函数、十五 triggers、四十一 RLS/权限语句。Rule 仍 host-only trusted importer，无公开 PAYLOAD/自授许可；Observation T1、Review T2、Candidate T1 各自只可准确真实 target+Receipt/Audit/Outbox+初始 key+共同消费组。app 新事实零 UPDATE/DELETE，两 Current 仅精确字段 UPDATE；Agent 新业务表零写。Candidate 原 immutable/RLS/lifecycle 复用，仅新 atom 后扩 INSERT。
5. Root 同步实际公共 model imports、父 Unique、lifecycle 覆盖目录、consumer/专业矩阵/real owner 门禁。SQL 保存快照不得充当资格；两个有效性/关闭 T2 Issue append 尚未支持，不扩大旧 Issue 状态守卫。

SQL 逐条通过 SQLAlchemy `text` 编译执行，避免 PL/pgSQL `%ROWTYPE` 被 client 参数插值误解。不用客户端 SQL/字符串格式化，不读取 token。全部由外部 Alembic UOW 原子执行；失败由外部事务回滚。

## 安全降级

仅允许精确单头26及同一活动事务。先锁新五表/Current、Confirmation、Receipt、Candidate，与关联旧 `quality_issue_versions/quality_current_issues/capa_remediation_links/audit_entries/outbox_events/request_keys`；锁跨全部降级保留。

有任何新保留事实/新 Current/Candidate、相关四 operation 回执或新三人工用途 consumed proof 则明确拒绝。不得清数据或先删新 facts 来通过检查。旧 root cause、completion、Link 任何字节不修改。

随后移除本段十五 triggers/六函数、恢复准确 head25 四定义、Candidate 恢复仅 SELECT；再真实复核六定义（含两原样函数）。依 FK 删除五张**空**表：两 Current → NamedReview → Observation → Rule，末尾仅移除新增父 Unique。无 `CASCADE`，不替代 head25 原 Issue/merge/change 守卫，不 DROP 旧 candidate 表/旧 lifecycle/RLS。不得在已有新 retained 业务数据后承诺可回退。

## 检查与真实前置

本段只有 owned Ruff/format/AST/import/静态计划一致性检查，未跑镜像字符串断言 tests、PG/HTTP/角色查询。Root v2 的真实 DDL rollback 证据属 v2，不冒充最终 v3/next26 迁移运行通过。主线统一最终计划与模型内嵌绑定、pre-business 26→25→26/schema/权限和真实正负 atom 检查。

实际 owner/专业/issuer/原值原件、安全 ABA、跨 preview 首锚恢复、共同 False→True marker 仍依真实宿主接线。数据库守卫只在已核定模型和 SQL 范围保障连续性、不可变与原子性，不以任意 JSON 或 bool 授专业资格、有效性或关闭。
