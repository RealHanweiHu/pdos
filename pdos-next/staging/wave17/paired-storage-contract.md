# Wave17 paired 实际存储结构读取层（暂存合同）

本交付只有 `paired_storage.py`、`test_paired_storage.py` 与本文档。没有迁入公开 API，没有新增表、当前指针、回执、占用或授权。用户已授权连续建设；此段暂存与主线冻结候选分开。后续公开接线由主线统一办理。

## 1. Python 接口与调用条件

```python
read_storage_pair(
    s: sqlalchemy.orm.Session,
    ctx: pdos_next.service.Context,
    product_id: UUID,
    output_ref: paired.FormalRef | dict,
    *,
    at: datetime,
    write: bool = False,
) -> paired.ServerPairRead

StoragePairReader.read(s, ctx, product_id, output_ref, *, at, write=False)
StoragePairReader.refresh(s, ctx, product_id, previous, *, at, write=False)
```

`at` 是宿主已经到达的 aware 读取时点。当前主体/Grant 总是按实际服务器当前时钟核验；不能用过去的 `at` 追授读取权限。`write=True` 只要求当前写权限并在已有共同顺序内锁 Product、Principal/Grant 和两个 Current，不写任何事实、消费或证明。普通只读使用默认值。

调用者必须是真实 `Session`，有活动主事务且 `Session.is_active=True`；主事务与完整 nested 祖先均为实际 `SessionTransaction`、属于同 Session 且活动，主事务 `parent=None/nested=False`，每一层 nested 链准确落到该主事务。检查先有界遍历实际 Session 内部链（最多64层），避免 SQLAlchemy `get_transaction()` 对损坏循环链无限遍历，随后交叉核对公共 getter。末端比较完整祖先对象链、存储 bind、全部 Context 字段与起点相同。失败子事务/换事务/换 caller/循环或外国 Session 不得继续返回结构。

该层不 begin、flush、commit、rollback 或修复 UOW。读取在 `s.no_autoflush` 内进行：调用者 pending ORM 对象不作为已保存材料，不能由此读取层自动落库。调用者若需要读取本事务刚建立的正式事实，须由实际 owner 自己先按其合同 flush。

## 2. 先读取真实范围和 ACL

当前 Context 必须 `actor_id == requester_id`、`run_id=None`，实际 Principal 为当前 active human。使用现有 `require_access`，并 fresh 读取当前 Product/Principal/Grant；缺行、跨租户、过期或缺所需 write 权限直接403。没有 owner Context，也不代入历史 writer 办理。

选定的不可变 Formal 先经真实 `front._row`/`front._snapshot`；实际 Build 使用既有 `builds._build` 私有门禁，双配置通过实际 scoped `_row` 门禁读取，并核真实 id/revision/产品/项目与制造配置关联工程版本。Run origin、before/after、真实 RunIdentity 和 Projection 都分别经过当前 caller 的实际私有门禁。当前用户有 ProductGrant 也不能读取其他人的 private 祖先。

这只关闭直接身份/版本/私有范围门禁。Artifact ACL、精确来源/原件安全、历史专业与保留执行仍须未来 HostGate 真实重核；本层不能以直接行可见替代完整 source 闭包可见。

## 3. 实际表与 typed 归一

| 实际表 | 精确读法及 DTO |
|---|---|
| `verification_formal_requests` | id+tenant/product，真实快照/完整SHA、logical request/revision、前版、owner/visibility、operation/domain intent、读集、保存钟；`authority_actor_id` 取真实 `authority_snapshot.subject_id`，不取系列owner。 |
| `verification_current_formal_requests` | exact tenant/product/logical request → 当前版本 id/revision；必须等所选输出。 |
| `verification_run_identities` | exact logical run + 当前 caller 私有门禁，核 project/build/request/owner/visibility。 |
| `verification_run_versions` | exact tenant/product/id+revision，真实 `launch._snapshot` 核快照/计划SHA与确定性结果；固定 origin 为 `request_version_id/request_revision`，不是 Formal Current。 |
| `verification_current_runs` | 同 logical request 的 exact current Run，核 run_id/id/revision。末端重新读取两个 Current，不能在读取途中换版而返回旧成功。 |
| `verification_launch_facts` | exact tenant/product/project/build/request/run/next_request id+revision/current run id+revision；最多取2条用于拒绝非唯一。 |
| `test_result_actions` | 同样 exact scope/next_request，并要求 next_run id+revision 等当前 Run；不能按时间选择一条或先 limit 再在 Python 丢弃错误范围。 |
| `test_result_projections` | ResultAction 真实 projection_id 经当前 ACL；保留实际 revision、project/build/request/run、固定投影 Run/SHA、basis/rules SHA、原确定性结果和读集。其固定 Run 再实际读取；不能从测量显示反推旧版本。 |
| `action_receipts` | exact tenant/product/真实operation/实际subject family/id+revision，唯一。保留原 actor/requester/command/result/request digest/intent/received clock。 |
| `request_keys` | 至少存在一条 exact tenant+原 Receipt.actor+receipt_id+`digest == Receipt.request_digest` 的真实关联。其他跨key aliases 可以有不同摘要；不要求所有aliases相等，也不借一个异值alias证明原请求摘要。 |
| `audit_entries` / `outbox_events` | exact tenant/receipt，实际读取并要求各唯一一条；writer/op/type/subject/correlation/schema 与真实 Receipt 精确配对。 |

所有事实选择在 SQL `WHERE` 内限定完整 scope 与固定版本，之后才 `LIMIT 2`。缺唯一 Fact/回执/原 RequestKey/原 semantic 为503明确 missing；实际身份、版本、原值或原子组冲突为409/403。存储 JSON 不满足封闭 DTO 时 `PAIR_STORAGE_INVALID` 503，不能回填缺失字段造 positive。

## 4. 六种实际推进

| operation | Formal | Run | 共同 subject |
|---|---|---|---|
| `test.run.plan` | 原已接收版不推进 | 创建计划v1，无 before Run | `test_run`（实际计划版本） |
| `verification.schedule.promise` | 真正推进一个承诺版 | 不推进，同一个计划版本 | `verification_request`（真正承诺版） |
| `test.run.start` | 真正推进开始版 | 真正推进开始版 | `test_run` |
| `test.results.import` | 每次真实 partial/final 推进 | 每次真实 partial/final 推进 | `test_run` |
| `test.run.review` | 保留原 Formal | 推进具名复核版 | `test_run` |
| `test.disposition.decide` | 完整正式结果才推进；部分未完保留 | 推进处置版 | `test_run` |

归一后调用冻结的 `verify_paired_material`，不重造第二状态机。固定 accepted 全范围、每次原 measurement/partial prefix、实际观察时钟、原值与事件、Plan精确 command-source（command_id/revision1/receipt/实际actor/UTC/occurred=received/effective=null）、真正的 next refs、Receipt/Audit/Outbox 及完整读集1..20都沿该核验证。compute projection 自身不是 paired 六步。

## 5. common/domain 意图分别闭合

领域事实的原 `input_snapshot` 必须能用本操作真实 typed Payload 解析，且真实 `verification_launch.semantic` 或 `verification_results.semantic` 输出逐值等于保存语义。存在确认token、丢失必要输入、额外字段或不能恢复默认闭合语义，均明确 missing。不能从 `Receipt.result` 的三字段反推原请求。

CommonIntentMaterial 使用真实 handler、operation/Product、上述实际semantic、原 Receipt.requester 与领域当次actor（两者必须相同）、`source_revision=None`，并按这六个现有 Payload 无visibility时共同默认private分支保留实际 requester 的 `private_owner`。领域意图仍用真实领域 actor/operation/payload 单独核；二者各自重算，不能互判相等。

`Receipt.request_digest` 无法在丢失token/完整原Command以后重算。本层只保留真实值并核原 RequestKey 关联，不能排读集、换key或补一个假的摘要证明。后续宿主若需要原完整 request digest 证明，缺实际原材料须 missing，不能从别的alias恢复。

## 6. 没有 HostGate，公开适配必须保留 missing

`StoragePairReader` 刻意没有 `attest`。直接交给冻结 `read_paired_formal_output` 会返回 `INTEGRATION_REQUIRED`（无结构授权结果、无 HostGate），而不是因为 storage pure正例通过就公开放行。刷新只是完整重新读取真实材料，不签发 opaque gate。

主线未来真实 PairedOutputReader 必须组合此 read/refresh，并另在同一个真实 Session/UOW 内实现真实 `attest`：

1. 原测量来源 `UploadedOriginal` safe bytes/hash/size/security epoch、逐字段定位与 ReportBinding；不能用 native text 冒充原仪器报告。
2. 当前全部 source ACL/范围/版本/终态withdraw、安全epoch；真实 Fact/Run/Projection 的完整 source_basis 可按精确refs另读，并绑定当前门禁 stamp。
3. 历史实际 signer/executor 专业事实、原fixed refs/epoch、当前撤回/恢复ABA与 runtime/issuer profile；不以当前消费者身份覆盖原作者专业。
4. 原 Start retained proof、真实资源/样件使用/实际配置与 fixed_run_sha；不新增占用或消费，不将自然窗口已结束误当原实绩不存在。
5. 固定 Projection 的实际 basis/rules、MeasurementRecord/原件逐值回读；现 `_snapshot` 算术相等不能单独证明原报告真实。
6. 所有 owner/bytes IO 后独立 fresh读/真实clock/门禁stamp重核，签发绑定当前 reader、完整材料SHA、caller、scope、main+nested UOW 的 opaque HostGate。

本段没有上述 host hooks，也不装 Candidate/effectiveness/close、不授独立性或批准、不扩 private ACL。原 Draft Link 仍是 planned 历史，公开选项仍由 Root 未来明确 direct/paired dispatch；不能用此层去掉旧direct Receipt守卫。

## 7. 局部验证与复现边界

测试使用真实 Session/SessionTransaction、真实 ORM类与实际 owner `_row/_snapshot`/common权限/handler semantic；SQL返回由显式 SELECT 等值替身提供，原件/专业资格/真实数据库从未被假装通过。包括六op、原writer与caller分离、aliases原摘要、各私有祖先、完整子事务链、Current/Grant读取漂移、原子组/语义缺失、no-autoflush、真实SQL限定在limit之前。无数据库连接、HTTP、公共测试或构建。

```sh
PYTHONPATH=pdos-next/staging/wave17:pdos-next/server:pdos-next/server/tests \
  pdos-next/server/.venv/bin/pytest --noconftest \
  pdos-next/staging/wave17/test_paired_storage.py -q
pdos-next/server/.venv/bin/ruff check \
  pdos-next/staging/wave17/paired_storage.py \
  pdos-next/staging/wave17/test_paired_storage.py
```

最终结果及哈希由交付消息给出。局部结构pure通过不等于真实PG、SQL/RLS验收、实际原件/专业/retained门禁、公开接线、性能改善或完整目标完成。
