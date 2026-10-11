# M3 从 B8 实际 head 固化（2026-10-10）

冻结基线为本地提交 `0eccfe0376d387de7a5211c2852f50f2432ca7b4`，B8 实际 head `s0_0728`。M3 仅在 iCloud 外工作树 `/Users/huhanwei/.codex/worktrees/pdos-m3-after-b8/ai-native-R&D-platform`、分支 `codex/m3-after-b8-20261010` 施工；原聊天独占 B8 验证，本聊天未再操作其测试库。

候选正式迁移为 `s0_0729`，12 表及守卫固化为静态 SQL，active revision 不导入实时 ORM。保留 B8 `direct_source_set_visible` 单根范围优化，只允许同品类无型号原件用于 G0 的新型号定义；降级恢复全部 3 个被替换的函数、共同策略与旧约束。降级先锁候选表，非空时拒绝删表。正式 ORM 补齐定义、目标价与项目来源列，G0 直接消费统一 `DefinitionSpecRow`，移除重复临时表定义。

必要验证：

- 新建自有 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`。原 B8、旧 M3 夹具均未操作。
- 基础新链空库 up/down/up，随后 `0728→0729→0728→0729`。降级和复升的表/列/约束/函数/触发器/策略/权限/索引目录摘要完全一致；全部 ORM 比较 `[]`，见 [schema.json](schema.json)。153 个业务表、52 个 definer 的普通属主无 LOGIN/SUPERUSER/BYPASSRLS；AI 零 DML、运行角色无属主继承。登录表保留 B8 已有 auth-only SELECT 可信根例外。
- [受影响回归](preproject-regression-1.xml)首次 151 通过、1 项旧夹具假设失败；该项改为实际 NOLOGIN 属主验证后[单项通过](ordinary-owner-regression-2.xml)。G0、封存、来源、T0/T1 绑定、P11、定义与派生路径覆盖共 152 个不同案例。
- [非空降级拒绝](downgrade-nonempty-1.xml)通过：已有合成提案时拒绝降级，事务回滚后 head 和公开文档保持一致。
- 受影响 Ruff 检查通过。第一轮遗漏函数/SQL 边界在执行前修复；首次目录往返的旧约束 ARRAY 表达式重解析差异修正后复验通过，初始结果保存在 `attempt-1/`。

用户 2026-10-10 后续明确取消 Claude 审查要求，改为 Astra 自审与必要验证。先前 OAuth 失败结果保留在[历史记录](claude-stage1-review.json)，不再是施工阻塞。Astra 复核中发现的三个迁移问题已修复并完成以上数据库复验。

该段本地验证通过，M3/S1 尚未完成。下一段为两份种子导入、规格字典与品类知识/PromotionProof；真实小Pai模型调用与资格未启用。没有 push、合并、生产操作或真实数据出站。合并仍须等原聊天将 B8 登记“通过（带 1 项已知性能例外）”。
