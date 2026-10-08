# Wave17 未应用事实 SQL 计划独立复核

本报告只读核对冻结 `2a10c092` 生成器、Root v1 字符串计划、六份实际函数观察以及五表/既有 Candidate 声明。C 没有连接数据库、调用 HTTP、执行 SQL/测试或修改源码；没有将 SQL 计划生成、函数文本观察或本静态复核声明为迁移/办理通过。Root 后续实际解析、回滚 DDL 观察及业务负例须另绑定其实际候选。

## 应在正式安装前处理的发现

1. **既有 Candidate 的继承身份没有完整 SQL 约束。** `fact_sql_guards.py:340–355` 读取 `stable_anchor` 后没有令 Candidate `owner_id/visibility` 等于实际 origin；`:382–384` 调用 origin 守卫仅传 audience 与 writer。origin 守卫 `:237/:250` 已核 anchor 的 owner/visibility 等于真实 IssueVersion，且阻止 private origin 外扩或非原 owner 写入，但没有核目标 Candidate owner。旧 Candidate 模型也没有新三 fact 的 `anchor_snapshot.origin.owner_id/visibility == row` CHECK。因此，在引用均为 product 的情形，原 private Issue 由原本人写成另一 owner 的 private Candidate，或者 product origin 写成 private Candidate，可以符合这些 SQL 关联；冻结 `candidate_storage.py:238–264` 的实际 basis/row 继承比较会拒绝回读。其影响是产生不符合已定 v1 身份继承、无法正常回读的候选；本报告不声称公开 API 已可触发。最小修法是在 Candidate 分支显式核 row owner/visibility 与 `anchor.origin` 一致，再由现 origin 守卫核实际原行，writer 保持独立。不能默默降级受众或改旧原件权限。

2. **原 Issue 用途只与传入 anchor/target 相等，未与实际原行相等。** `assert_capa_fact_origin:236` 仅核 `raw.origin.purpose=purpose_value`；实际 `QualityIssueVersion` 有独立 `purpose` 列，但此函数没有核它。新模型 CHECK 也只把 row purpose 与 anchor purpose 相连。保持实际 issue/input/authority/policy JSON、原 id/rev/snapshotSHA 不变，一起改 anchor purpose 和新目标 purpose，当前 SQL 条件仍可成立；真实 anchor reader会拒绝这种替换。最小补齐 `purpose_value=original.purpose`（并保持 raw purpose 相等）。nature 没有对应原表独立列，不能猜一个 SQL 字段来替代实际原失败/来源核验。

3. **来源函数存在 PL/pgSQL 变量/SQL 名称冲突候选，须以实际调用确认。** `SOURCE_SQL:170` 声明 JSON 变量 `x`，`:177–180` 两个聚合同时使用 `jsonb_array_elements(...) x` 与 `x->>`。单列函数的 whole-row 别名和同名 PL/pgSQL 变量可能在默认 `variable_conflict=error` 下产生 42702；创建函数或只解析外层 CREATE 不一定会走到此语句。窄修可将 SQL 别名改为 `read_element(value)` / `basis_element(value)` 并显式引用 `.value`，保留 `FOR x` 的变量，不依赖会话冲突设置。这里是静态运行时风险，不是 C 已复现的数据库错误。

4. **Root v1 五表 DDL 不含模型声明的五个租户索引。** `root-unapplied-ddl-plan-v1.json.parent_unique_and_tables` 只有父 UNIQUE 与五个 CREATE TABLE；各模型继承 `models.Row:30` 的 `tenant_id(index=True)`。`wave17_ddl_preparation.py:62/:77` 只编译 CreateTable，没有编译 table.indexes。正式迁入若原样使用该列表，会留下 ORM/schema 差异。补齐五个 `ix_<table>_tenant_id` 的实际 CreateIndex，保留五表和既有表的权限约束；不能用空表 DDL 成功代替完整 schema 相容。

另有待主线边界验证的可用性风险：`fact_storage_models.py:225–230/:260–262/:316` 的宽 B-tree UNIQUE/FK 键直接含最长 2000 字符的 purpose，Rule 另含各最长 2000 字符的 issuer key/version。合法高熵长值合计可能超过标准页的单索引项上限，空表 DDL 不会验证这个边界。可用实际合法长值验证后选择明确长度合同或固定长度身份键＋完整值一致性守卫；不可截断事实。当前短合成演练不据此断言必失败。

## 已静态核定的保留和隔离范围

- 六份观察定义的实际文本 SHA 与 JSON 所记 SHA 一致；生成器要求全部六份精确身份。四个替换只增加闭集操作/tier、消费目标 union、事件 CASE，未替换 `assert_quality_followup_receipt` 或 0025 修正版 `require_quality_followup_atom`。原 `require_quality_change_atom`、merge/failure map、Issue/Link 触发器仍保留。迁入时仍须在真实迁移锁内重读，不能凭旧观察证明现场没有变化。
- 新三人工用途 Candidate T1 / Observation T1 / Review T2 加入旧三用途 False→True 保护及 reciprocal union。目标 guard 要求一个实际 consumed proof；反向 UPDATE guard 要求本转移恰好一个同 Product/writer/operation 的目标；proof 跨新旧表计数，已消费不可改，新插入不能 true。配对沿 deferred trigger，不增加 xmin/top-xid 假设，结构上保留 SAVEPOINT 回滚。规则出版为 host_import，没有人工 T2 token 旁路。
- 四种 target 分别要求精确 family/version/status、common intent 与一个 Receipt/Audit/Outbox/初始 RequestKey。Receipt 还有新反向 deferred target guard；事件 CASE 对应四个冻结名字，没有新增 effectiveness/close 分支。Candidate Receipt 只含 binding/inspection 两个非循环摘要；三事实 Receipt 只含 kind/body payload SHA。SQL 不重建 Python canonical digest，也没有把这些局部摘要当 full Fact/Candidate SHA。
- 父 `UNIQUE(confirmations.tenant_id,id)` 与事实复合 proof FK 列顺序一致；五表 scope/origin FK 引用既有精确 Project/IssueVersion 唯一键。Rule/Observation predecessor、Current、Rule issuer 系列与 Observation 固定 Rule/executor 都有对应复合键。Current 首版 rev/epoch=1、后版 exact predecessor/+1，identity/原保存钟不变；同一系列一 UOW 只允许一次追加是本合同的显式限制。
- 五表计划均 ENABLE/FORCE RLS、tenant policy、撤销 PUBLIC/agent 权限。三个事实只有 app SELECT/INSERT；两个 Current 只额外开放 fact_id/fact_revision/epoch，Rule 再开放 issuer_version 的列级 UPDATE。Candidate 复用 head24 RLS/lifecycle/immutable，只在新 atom 安装后从 SELECT 扩为 SELECT/INSERT，未开放 UPDATE/DELETE。六新函数为固定 search_path 的 invoker，非 SECURITY DEFINER。生命周期五表目录及所有列仍须 Root 真正注册。
- `created_at` 有限，proof 捕获钟与保存钟顺序受核；TTL 比较是实际 saved_at 与 proof expiry，不是另取 COMMIT 时钟。Rule/Observation 的实际保存时钟、观察区间/原记录时点与 Review 顺序保持；原事件微秒/时区字符串没有由本计划重新写成 now。

以上数据库结构只能核持久关联，不授专业资格/issuer，不证明 uploaded bytes/security/runtime ABA/七 owner 当前闭包或实际 host material/消费 marker。来源 SQL 核 1..20 完整 Artifact read-set/basis、当前版本/状态/hash/owner/受众；精确原文位置、字节与原失败/完整子 FactRef SHA 仍由实际宿主端口核。任意 Product can_write 或存储行不能被 UI 当作可办理/qualified=true。

## 尚须 Root 实际验证

定稿时 Root 已确认 owner/visibility 继承、实际 purpose 绑定和五索引遗漏需要窄修；alias 冲突仍待实际调用核定，索引宽度仍是待 PG 边界风险。Root 另报告 v1 回滚 DDL 观察在 `replace_functions[0]` 出现 driver ProgrammingError（SQLstate=None，疑为 `%ROWTYPE` 参数解析），DDL 已回滚、没有业务写入。此失败不是 C 运行/诊断所得，也不能用它证明来源函数的 alias 风险已复现；原生成器、计划和失败证据应保留，新修订另绑定。

除了上述窄修，正式单调迁入需要重新绑定实际六定义和旧触发器、完整模型/索引/生命周期相容，验证四种合法 atom 与 target/Receipt/proof 双向缺失、旧 proof 复用/跨表多目标、错误身份/用途/受众、Current 回退、SAVEPOINT/Outbox 回滚和真实来源/issuer/专业撤回。回退需先锁表并证明新事实/Candidate/新用途 Receipt/consumed proof 均空；不能删除 retained 行。effectiveness 与 close 两个 T2 的 Issue append/Current/companion 不在此计划中，不得宣称 G3 出口已接通。

## 本次读取绑定

| 材料 | SHA256 |
|---|---|
| staging/wave17/fact_sql_guards.py | `2a10c092daa00ee3c2bd7a8ffce0d2d7d2545b7bcc4224f866240c1842286267` |
| staging/wave17/fact-sql-guards-contract.md | `3b4c56190be38474559866b424681e87700a9f684323260c92a7f604c2f38176` |
| staging/wave17/fact_storage_models.py | `c5e19ebd676ebca70421897a2ada1e3214d6fd1d6e7905bdb9a57d7be39f9a56` |
| staging/wave17/fact-storage-contract.md | `eb020013ea6f10c7ca8ee6959bc361ef878679317fe1ea485d9a5a6c6e9f9f85` |
| server/pdos_next/domain/capa_verification/models.py | `321a721fd5b90d9857f8e29603ef057f6b7cc1cf62e29ba27b036c3296952ef4` |
| server/pdos_next/domain/quality_execution/models.py | `c8dab50b927abe5fbb63fb05fc0fe2d9d0ae67b78b0ef5115a3595ef7a092537` |
| root-unapplied-ddl-plan-v1.json | `caf30059f734c269d25cc4e94964b374a0e92a8fa5bed0a808b479edde230f96` |
| sql-actual-functions-v1.json | `73bf23b81d3824418a0b0cffed9cdeddd11a8874ca1e4d35e07c8342e6d4907a` |

六个实际函数文本的 SHA 已由该观察 JSON 逐项绑定；本报告没有把观察文件中的只读数据库状态延伸为当前安装或授权结论。原 v1 材料与本报告保留，不覆盖后续修订证据。
