# 企业检索恢复与九来源性能检查点 · 2026-10-29

**当前结果：恢复专项12/12项具备实际通过证据**，按生产无影响/响应等价分段保留并必要重跑。正式58来源检索/9项/48项p95为0.745/0.284/0.303秒，SQL5/4/4，真实Worker重启通过；[最终共同去重证据](../pdos-next-enterprise-knowledge-authority-20261029/backend-candidate-10-final-coverage.json)。下文保留各轮实际失败与修复过程，不能把早期失败状态当作当前结果。

依据：RAG v0.4 §10.2、§13。恢复实现仅修改现有本地全文派生索引；不调用模型、embedding、对象网络或外部服务，不改业务事实或 golden-case。验证通过真实领域命令创建经授权的自有合成记录。

## 实现

- 普通投影的幂等判定核对确定性 chunk ID、正文、定位、哈希、计数和实际 PostgreSQL tsvector；相同工作键和行数不足以判定索引完好。
- `plan_rebuild` 在真实调用者 RR/RLS 快照内一次枚举九种来源，冻结 source type/id/category/revision/hash 与来源水位。`rebuild_batch` 逐批重核当前权限及固定版本；来源变化或不可读保留失败，不换成新的来源版本。
- `EnterpriseRebuild` 通过 Temporal 持久化同一清单及批次 Activity 输入/输出。丢失提交回执后重试相同切片，Worker 重启不重新枚举来源。相同 request ID 使用同一工作流。
- 0832 的 metadata-only helper 在 tenant 锁内重算完整 tenant 派生 corpus/DF，包含调用者不可读其他品类已有的 chunk。维护角色为无 runtime 成员的 NOLOGIN/NOBYPASSRLS 角色，仅有派生 metadata 列权限，不读业务来源正文。
- 0834 的内部 source clear primitive 仅清理当前 tenant 固定 source、服务器计算的工作键/确定性 ID。project 先普通 RLS 读取并核 category/revision/hash，再调用清理和正常写入；用来恢复错误 category/source ID/type/work key/chunk ID。批次末尾一次重算统计。
- 失败行记录若也受损，以批次回执保留实际失败并继续独立来源；不以清理未知行来获取越权来源，也不把批次完成称为全 tenant 来源已恢复。

入口与文件：`enterprise_search/indexing.py`、`recovery.py`、`recovery_workflow.py`、`events.py`，以及 `workflows/worker.py` 的两项 Activity 与工作流注册。schema 与正式迁移分别为 0832、0834（0833 归页面反馈）。模型和公开 API 均未新增清理权限。

## 验证状态

本代理运行：

```text
.venv/bin/python -m pytest tests/enterprise_search/test_recovery.py tests/enterprise_search/test_dispatch.py tests/enterprise_search/test_keyword.py -q
22 passed in 0.79s
```

所属恢复代码、测试与迁移 Ruff 通过；12 项 PG/Temporal 用例收集通过。迁移由主代理执行；随后主代理授权本代理接管同一已核对 runner 做实际恢复联验，runner 每次核对 53502/pdos_test 的 marker，显式注入测试角色，不回退 `.env`。

主代理实际迁移证据：

- [0832 升级/降级/升级与权限验证](../pdos-next-enterprise-knowledge-authority-20261029/migration-0832.json)：独立库 53502/pdos_test，marker `f117bb5b-b3d7-4286-aaec-c54d9255e96b`；备份 84,900,846 bytes，既有八表数量不变。
- [0834 升级/降级/升级与权限验证](../pdos-next-enterprise-knowledge-authority-20261029/migration-0834.json)：当前 head 0834；备份 85,252,814 bytes，既有十表数量及 0832 函数字节不变。维护角色无 LOGIN/BYPASS/membership，新增 source_id/work_key metadata 可读，text/content_hash 不可读；FORCE RLS 保持。

真实 PG/Temporal 联验累计 **11/12 项通过**；混合规模性能仍未达到 `<1s` 门槛，由主代理继续实际 SQL/EXPLAIN 诊断。数据库租约已交回，本代理停止 DB 操作。

接管后的 [verified-run1 日志](../pdos-next-enterprise-knowledge-authority-20261029/recovery-full-verified-run1.txt) / [逐项 XML](recovery-full-verified-run1.xml) 有 **5 项通过**：四种九来源损坏恢复，以及全部已注册 Outbox 重放。四种恢复均使用真实可读的 33 个来源：Artifact 16、Build 4、Issue 4、TestRun 4，以及 CAPA/Change/ExternalWait/Knowledge/Supply 各 1，实际跨越每批 20 项的边界。

[run2 日志](../pdos-next-enterprise-knowledge-authority-20261029/recovery-remaining-verified-run2.txt) / [XML](recovery-remaining-verified-run2.xml) 新增 **5 项通过**：九类来源全部五种 scope/ID/key 错误恢复；其他 source/tenant 不变与无实际来源读取权拒绝；text/locator/实际 PostgreSQL tsvector 幂等核验；来源变化/撤回及隐藏损坏 state 的 partial；跨品类完整统计与正文/SET ROLE 隔离。错误类型保持每类不同的错误字符串，因 Issue/CAPA 可共享版本 ID 而不能人为撞唯一键。合成规模记录也使用独立标题，避免把领域幂等返回旧回执当作规模增长。未放宽生产约束。

[真实 Temporal run4 日志](../pdos-next-enterprise-knowledge-authority-20261029/recovery-temporal-only-run4.txt) / [XML](recovery-temporal-only-run4.xml)：**1 passed，97.37s**。33 来源只规划一次；首次 Activity 提交后丢失回执并停止 Worker，第二 Worker 用同 manifest/cursor 重试、继续后续批次；权威来源不变、相同请求同一工作流，工作流历史无正文。

[性能 run3](../pdos-next-enterprise-knowledge-authority-20261029/recovery-performance-temporal-run3.txt) / [XML](recovery-performance-temporal-run3.xml) 检测到 search warm p95=3.2077467s、SQL 恒定 5 次。主代理随后将既有 `prepare_read` 前移至复杂 RLS 来源预检查之前，未变权限、阈值或统计语义；该调整不足以达到性能门槛。

[修复后 run5 日志](../pdos-next-enterprise-knowledge-authority-20261029/recovery-performance-fixed-run5.txt) / [XML](recovery-performance-fixed-run5.xml) 为 **1 failed，183.41s**。真实混合 corpus 共 58 个来源：Artifact 21、Knowledge 6、Issue 4、CAPA 1、Change 6、ExternalWait 6、Supply 6、Build 4、TestRun 4；非空覆盖全部九类。每项读取 12 轮，排除首轮后计算 warm p95：

| 读取 | p95 秒 | SQL 次数 | `<1s` |
| --- | ---: | ---: | --- |
| search，limit 50 | 2.8351136 | 恒定 5 | 未通过 |
| 当前来源复核，9 条 | 0.8219968 | 恒定 4 | 本次测值达标 |
| 当前来源复核，48 条 | 1.0617036 | 恒定 4 | 未通过 |

首轮无凭据 SQL/绑定/实际上下文保存在 `/tmp/pdos-enterprise-recovery-performance-context-run5.json`，0600，779,565 bytes，供主代理继续 EXPLAIN。结构为 `context/request/family_counts/authority_batch_sizes/first_sql[{mode,sql,parameters}]`；无 DSN/token/正文，未发现 Jsonb 适配器字符串。trace 各模式额外包含 RR 事务声明和身份 set_config 两条，计时与 SQL 计数从进入 session 后开始，因此表中为 5/4/4。请求为 `query=synthetic, limit=50`。

九来源准备还查出一个实际生产缺陷：[debug1](../pdos-next-enterprise-knowledge-authority-20261029/recovery-fixture-debug1.txt) 中 Supply `_visibility` 对共享 Build 返回已停用的 `product`，违反现行 `supply_source_captures_check`（SQLSTATE 23514）。经主代理扩归属批准，仅修为保留 `build.visibility`，既有 private 收窄继续生效，audience 不转为 category，未放宽数据库约束。之后所有九来源功能与 Temporal 通过项都实际使用共享 Build 供给路径，构成该修复的真实回归证据。

## 真正的九来源合成场景

现有真实领域命令构成 Issue/CAPA/Change/TestRun 链；品类共享的项目、双配置从登记时确定受众。Build/readiness、Supply 和 ExternalWait 由真实项目 owner 办理；另一个具名 quality 请求者通过现有 category 读取路径读取它们，同时读取其本人私有 Issue/CAPA/Change。Artifact 和 Knowledge 由该 quality 本人登记。没有修改根 owner、ACL 或私有来源内容。

`test_recovery_pg.py` 覆盖：九类混合索引全部派生表删除、仅 chunk 删除、仅统计删除、相同行数内容损坏；五种派生 scope/ID/key 损坏；全部已注册来源 Outbox 重放；无实际来源读取权不能触发清理；其他 source/tenant 不变；来源更新或撤回维持 partial；跨品类完整统计及正文/SET ROLE 负向。另有普通重复投影对 text/locator/tsvector 的实际核对。

`test_recovery_temporal_pg.py` 使用同一九来源场景，真实 Activity 提交后丢失确认、停止第一个 Worker，再由第二个 Worker 接续同一清单；不以纯模拟替代该持久恢复证据。

性能用例通过合法命令增加混合 corpus，记录每一来源 family 的实际数量、9 条与扩展来源复核批量的 SQL 数，以及 search/两档复核的本地 warm p95。阈值保持 `<1.0s`，复核两档 SQL 次数须相等。它只证明所记录本地规模，不据此声称生产大规模容量、端到端模型时延或 embedding 表现。

## 边界

可恢复范围是普通调用者当前可读、且仍匹配固定清单的权威来源；不可读来源既有派生行保持原状。清单水位、已确认批次水位与失败项均显式返回。无证据可归属的跨 tenant 或全部身份关联同时抹去的孤立派生行，不通过猜测清理；这不赋予读取任何业务正文的权限。

人工题集/语义质量评测、向量/embedding 恢复、真实模型时延不在本次已验证范围。

## 后续关系查询优化候选（已由下述共享源候选替代）

主代理在 run5 的 EXPLAIN 中定位到关系图不同方向重复扫描同一原生表并重复执行其父 RLS。后续只改 `enterprise_search/relations.py`：每个实际表源用 `relation_readable_<table>` 的 MATERIALIZED CTE，在数据库实际绑定 tenant 内按普通 RLS 读取一次，复用于所有方向。仅选择关系所需 identity/scope/固定引用 JSON 列；Issue、Change、Current、Build 及六个执行表在全方向查询 SQL 中各有一次原生 FROM。

所有原 tenant/category/product/project、固定 revision、CAPA key、merge Current version ID、Build parent identity 条件保持；`related_page` 的两端 authority、原件扫描、历史和一跳规则未改。`edges/graph_for` 签名保持，直接调用 edges 的 similar-history 路径无需接线变化。CTE 前缀与主代理 catalog 的 `enterprise_readable_` 独立。

新增 `tests/enterprise_search/test_relations.py` 的三项纯查询合同回归，覆盖复用边界、固定版本与双向 scope。与四项 keyword 纯测试合计 **7 passed in 1.04s**，两文件 Ruff 通过；该候选未由本代理访问数据库或宣称新的性能通过，交主代理以原 58 来源普通角色统一 profile。

## Catalog 与关系图共享普通 RLS 源候选

前述局部 CTE 虽然减少了关系内部的重复扫描，catalog 与 graph 仍各自读取相同表。经主代理进一步授权，将两者统一为 `readable_sources.readable(model)`：`lru_cache` 的唯一 key 为静态 ORM model class，值为全列 `shared_enterprise_<tablename>` MATERIALIZED CTE 的 ORM alias。缓存仅保存 SQL 语法对象，不接收 session、tenant、principal、scope、行结果或授权事实；每次实际 SQL 执行时重新解析 `pdos.tenant_id`，普通表 RLS 继续适用。缓存不淘汰别名，避免既有缓存 catalog 持有旧 CTE 时产生两个不相关的同名 CTE。

`business_sources.py` 的 Product/Project/Build、原生版本及 Current 指针，`business_execution_sources.py` 的 BuildStart/ActualConfiguration/BuildLot/TestResultAction 及测试 Current，均与 `relations.py` 复用同一 alias。Change、ExternalWait、Supply 同样走此路径。完整列保留 catalog 的登记事实、读取依赖和 current 指针；没有删改原 tenant/category/product/project、精确版本、CAPA key、根读取核对、正文/hash、扫描或最终两端 authority 条件。主代理此前加入的混合 catalog 结构 JSON 单次计算保持。

精确 identity selector 仍使用原 ORM model 和原表索引条件；执行记录的 `BuildStart` 特有事实判断改为检查原 model class，避免 alias 导致 `execution_scope` 内容遗漏。共享只发生在 SQL 构造层，不把读取权限复用到别的请求。

本候选仅访问本地源码，**没有访问数据库、创建夹具或迁移**。实际原 58 来源普通角色响应等价与 `<1s` 性能由主代理统一复测；本段不能替代真实 PG 证据，也不改前文 run5 的失败结果。

所属五个文件 Ruff 通过；关系与 keyword 纯测试 **9 passed in 1.03s**。新增编译检查覆盖 catalog+graph 同一语句 15 张原生表各一个 MATERIALIZED CTE/原生 FROM、执行时 tenant、登记执行字段保留、固定版本关系与 scope 条件，以及 identity 路径不物化。[原始检查输出](pure-shared-sources.txt)。代码候选已冻结交回主代理。

主代理随后用原 58 来源、普通角色对共享源候选实际复验：**完整响应逐字段一致**，search warm p95 **0.743464s**、verify 9 条 **0.325514s**、verify 48 条 **0.646244s**，SQL 分别恒定 **5/4/4**，均在既有 `<1s` 阈值内。该证据为同 fixture 的真实 profile，正式性能原用例仍随冻结 967 输入候选 2、86 文件共同 PG/Temporal 组统一执行；本段不将 profile 代称为原用例已通过。共同组进行期间，本代理未改生产/测试源码或访问 DB。


## 根统一正式性能复验（2026-10-29 UTC）

恢复用例现累计12/12具备实际通过证据：10项损坏/索引/权限功能沿用共同候选5的通过段，候选7再次通过真实Worker重启及正式九来源性能。证据按生产未变或语法缓存响应等价分段保留，并非一次全新12项重跑。正式性能使用相同九类58来源、9/48条复核，5次预热+40次实测、inclusive p95，原1秒门槛不变：检索0.745151秒、9项0.283514秒、48项0.302904秒，SQL恒定5/4/4。[XML](../pdos-next-enterprise-knowledge-authority-20261029/backend-candidate-7-remaining.xml)、[全部计时](../pdos-next-enterprise-knowledge-authority-20261029/formal-nine-family-performance-candidate7.json)。前述失败日志及实际慢观测继续保留，采样修正不单独作为优化效果。共同88文件回归还在续跑，本节只声明恢复专项证据完成。
