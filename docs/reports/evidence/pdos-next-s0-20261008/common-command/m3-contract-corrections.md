# M3 合同核对的公共修订（2026-10-08）

用户提出的六项问题已回补 S0 的 B1–B3 公共实现；公共修订核对时主库 head 为 `s0_0410`，当前主库 head 为 `s0_0421`，M2 独立候选为 `s0_0716`，统一迁移与 Agent 实际执行接线保留在 B7。

| 问题 | 当前实现与检查 |
|---|---|
| 普通授权不强制过期 | `Grant.expires_at`、成员授权输入可空；新建品类的负责人授权不设期限。显式委托/临时授权仍验证未来期限，登录与真实资格等独立期限保留。 |
| NULL 范围去重 | Receipt 唯一键采用租户、品类、型号与意图，并使用 PostgreSQL `NULLS NOT DISTINCT`；LifecycleIntent 采用品类与实际对象范围。真实数据库重复插入被拒绝。 |
| 品类/提案 T1 | 预览与消费绑定注册 owner 从真实 RLS 对象解析的主体类型、ID 与版本；已接品类、实际 PlanProposal、Claim、AgentRun。未来 M3 Proposal owner 接同一端口，不伪造尚未落库的 G0 主体。 |
| 品类原件与 Artifact | 允许没有型号，并以真实 category_id 绑定上传、扫描、解析、下载、安全指针和生命周期。NULL 父对象组合通过额外真实父键守卫核对；不可借 NULL 绕过型号/受众权限。 |
| product_manager 能力 | Grant 新增独立布尔能力，仅通过现有 Human `category.member.grant` T2 授予；省略更新值保留已有能力，can_write 不自动获得它。M3 G0 评审消费与 reviewer_not_eligible 场景属于 M3。 |
| 整次运行撤回 | Human T1 预览解析真实运行与完整回执；业务撤回、运行技术回执、确认、Receipt/Audit/Outbox 同事务。当前可逆 owner 为 Claim 与独立 Artifact，其余操作或下游消费整次拒绝；历史执行结果保留。 |

必要证据：

- [品类原件、普通授权、NULL 去重、共同命令与实际提案确认：63 passed / 44.98s](../execution-resource/category-root-proof-verified.log)。
- [品类级无期限生命周期 HTTP 正例：1 passed / 1.63s](../execution-resource/category-lifecycle-http-verified.log)。其前一候选中的拒绝来源于生命周期技术表仍要求型号，已用 `s0_0410` 修正；不把前一候选的失败记为通过。
- [品类原件被型号消费及请求证明：17 passed / 6.35s](../execution-resource/0421-category-reference-recheck.log)。包含真实上传、扫描、解析、型号 Claim 采用，以及品类引用计数和实际水位增加；跨品类/跨型号直接 SQL 引用被拒绝。
- [待隔离品类原件的型号引用负例](../execution-resource/0421-category-fence-and-named-reason.log)：该项通过，具名放弃上传、保留决定及待隔离状态来自真实端口，另一成员不能读取私人生命周期行，新增型号引用仍被数据库拒绝，四组写入和品类水位无变化。同日志中的品质拒绝分类复验失败另行修复，未将整份日志计为通过。
- [M2 冻结候选与撤回边界](../../pdos-next-m2-20261008/candidate-boundaries.md)：217 passed / 1 public-schema comparison deselected，含 6 项真实 FastAPI→独立 PostgreSQL 撤回检查（型号与品类正例、重放、普通和私有下游消费拒绝、末尾技术写入与 Outbox 失败全事务回滚）。这些检查使用合成运行历史，真实模型调用 0 次，不代表模型资格或正式出口。

B4–B8 尚未完成。上述证据只覆盖本次公共修订；B7 将统一主库 AgentRun 迁移、实际运行命令权限与 HTTP→Temporal 接线，B8 才验证最终候选。迁移降级往返使用核对的空独立测试库，不为已经存在的无期限授权补造过期日期。
