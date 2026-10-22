# G1.2 派生算法包首版结果

日期：2026-10-02。完成范围为三方派生**纯计算首版**，不等同于 G1.2 业务闭环或人工出口完成。

可用模块位于 `pdos-next/server/pdos_next/engines/derivation/`，提供 typed DTO、固定父/新父/子快照适配、三方五类差异、冲突与缺项，以及绑定摘要的选择性采用候选。现有两方版本历史 `difference(previous,current)` 未修改。

保留稳定规格 key、Decimal 值型/单位/测试条件和精确引用；明确缺失/删除/None/未知。选中规格需重新确认，父责任、批准、发布身份与决定不被继承；受众、跨客户权限和适用性仅由主线权威 port 检查。无 port 时明示预览待校验，拒绝/未知结果不采用对应路径。父子输入对象不被修改。

## 候选与验证

冻结候选 SHA-256：`f250d18deeddb1bad6f1cfce40facc7a31c57a85e4d8a37057b9f6de74a13650`。

| 检查 | 结果 | 原始日志 |
|---|---|---|
| 独立冷导入，无旧 app/业务服务/数据库模块加载 | 通过 | [cold-import.log](cold-import.log) |
| 本包纯算法/负例 | **52 passed** | [pytest.log](pytest.log) |
| 本包 Ruff | 通过 | [ruff.log](ruff.log) |
| 本包格式 | 4 files already formatted | [format.log](format.log) |

检查前后 4 份归属源码/测试及 2 份公共类型依赖哈希稳定。[candidate.json](candidate.json)记录全部文件哈希、精确检查命令与退出码；[verification.json](verification.json)提供结构化检查结果。通过 `--confcutdir=tests/derivation_engine` 排除公共 DB fixture，测试进程不提供 DATABASE_URL/TEST_DATABASE_URL；未运行数据库用例、完整构建、模型调用或浏览器联验。

检查覆盖五类比较、父删子改冲突、双方删除、子新增/删除、section 缺失/None/显式删除、未知值与重新确认要求、来源/规格/条件重排、低 Decimal 运算精度和浮点拒绝、版本/范围/路径/重复 key/摘要负例、权限与适用性 port 拒绝/未知、不可继承决定、未选覆盖保留，以及输入不变。独立审查发现的冷导入公共类型循环、来源删除/None 与采用后残留缺项提示已修复并验证。

## 抽取来源与剩余接入

抽取来源为旧 `server/app/domain/definition_inheritance.py` 的 `merge_paths / three_way / accept_changes`：复用稳定路径、三方比较、选择性复制思路，重建 `specs/key` DTO、五类比较、删除/缺失与安全候选，不导入旧 app。原文件 SHA-256：`bd4ab5e8e7ae55357fe25b9a6618055b33cc2bbf481986003a7284c54229cb7c`。函数行号/哈希、现行 Definition/view 与设计来源哈希见[source-summary.json](source-summary.json)。

主线接口、字段映射、快照语义、权威 port 和共同命令接线顺序详见[mainline-handoff.md](mainline-handoff.md)。仍未接入 Platform/Variant 权威关系、正式来源/受众校验服务、业务命令与页面、事务/回执及发布；这些属于主线范围，不是本算法包的外部阻塞。没有新增依赖需求。

本轮只新增分配的引擎、测试、证据目录文件；未改公共父包、现有产品包、迁移、配置/锁、web、唯一清单或设计方案，未提交/push。全部无关脏工作保留。
