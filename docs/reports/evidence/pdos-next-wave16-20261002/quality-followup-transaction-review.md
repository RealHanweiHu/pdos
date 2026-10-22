# Wave16 后续品质事务候选审阅

仅新增 `server/tests/quality_followup_transactions/{__init__,fixtures,test_transactions}.py`。当前为主线可执行候选，不是 PG 已通过：离线 Ruff、三文件 AST/compile 和 `--noconftest --collect-only` 通过，收集 10 个测试函数、18 个参数化节点；未执行 fixture、数据库、HTTP、公共测试或浏览器。

## 必须先完成的主线接线

- 三操作真实注册：`quality.issue.root_cause.decide` 为共同 T2、`quality.capa.actions.complete` / `quality.capa.followup.link` 为共同 T1，配精确包装 PAYLOADS/handler/current professional operation matrix。
- 共同 consumer 在 `confirmation.consumed=True` 后、任何 SQL/flush 前，实际同 Session 调 `record_consumed_confirmation(s,ctx,command,payload,module,confirmation)`；不得通过历史 consumed bool、测试 monkeypatch 或第二消费补证明。
- 原 Issue ORM CHECK 与真实单调迁移须允许 rootcause/complete 及 `awaiting_verification`；保留同 Issue Current CAS/连续版本、不可变历史、RLS/agent 零写。B `capa_remediation_links` 必须真实创建并具原子回执门禁，不能借 collection 的 metadata 判断数据库已迁移。
- API 共同 preview/execute，以及 `GET /v1/products/{pid}/quality-followup?issue_id=...` 和 `POST .../quality-followup/inputs`（完整 Command）须实际挂载。inputs.allowed 和 required_source_read_set 沿冻结合同，不在测试内补 router/角色/正向输出。
- 新 `configure_integration(engine,synthetic_completion_profile=...)` 必须使用 A append/proof、B consumed-proof 和真实只读 owner options；分类 callback 只按显式已核测试目标开启。原质量 result bridge/refresh、实际原件 store/security runtime 由已交付夹具沿真实接口配置。
- 事件精确为 `issue.root_cause_decided`、`capa.actions_completed`、`capa.followup_linked`；rootcause/complete 的 Receipt subject=`quality_issue` 新不可变版行，link=`capa_remediation_link`，Issue Current 不推进。

候选的 autouse prerequisite 只离线检查注册/矩阵/ORM 合同，缺少时明确报 Root integration required；它不是数据库检查，不 skip 为成功，不代替真实 head/migration/权限验证。

## 复用与真实数据路径

复用 `quality_execution.fixtures.quality_work` 的已实际开测、真实上传测量报告和固定 definite-fail Projection；不重建第二套执行真值、不把旧失败当整改通过。新增独立三操作 duty/qualification series 在 Issue 初版前导入，当前 Root retained 端口独立重核原 Start 签发者；新操作不改旧 Run、样件消费或资源占用。

新 Issue 经真实 T1 triage/containment→T0 CAPA v4，包含两项本人调查措施。完成九字段整行由真实 `/originals` 上传、显式 synthetic scanner 回执和真实 parser 派生；分类十二字段是另一实际登记 native immutable text publication。source position 均绑定实际 Artifact 版本和整行 SHA，不由 Run 回填发生时间，不假设 Product Grant 即专业资格。synthetic scanner 是明示测试 port，不宣称真实扫描/生产资格。

fixture 只调用新 host integration，恢复自身 Runtime/profile，未改任何冻结 A/B/host/bootstrap/public 源码。所有 DB/HTTP/真实等待都留给 Root guard runner；collection 没有执行这些路径。

## 有意义的事务节点

1. 具名 T2 真 Confirmation UUID → kernel Invocation.decision_id → 实际共享证明 → 新 Issue、Receipt/Audit/Outbox 恰一组；旧根因/原版本保留。
2. 真实 persistent False→True 消费，marker 记录无 SQL gap；同 Session/事务可核，rollback 后另一事务绝不能拿历史布尔替代证明。
3. partial 完成保持 actioning，再 allComplete→awaiting_verification；原实际发生时钟、本人、原文与服务端接收时钟分开，效力/关闭仍未开放，原 Run/Formal/消费保存不变。
4. 三操作同键和别键重放返回原 Receipt，不再次消费或追加 Issue/link；RequestKey alias 的合法新增单独区分。
5. 实际九字段的执行者、发生时点、文字在 review 后改变均拒绝，原 token 未消费、计数/Current 不变。
6. 当前完成原件与分类来源撤回阻断旧 T1；撤回保持物理字节与旧 Issue 历史，不假设来源可复活。
7. 同 phase 实际 security epoch 双推进（字节/source_state 不变）使旧 clean 证明失效；真实政策 publication v1→withdrawn v2→active v3 通过 trusted importer/同事务共同回执，最终重核不接受 ABA，整条失败回滚。
8. native 分类真实读取过程中撤回并以同内容重配 profile，旧 closure/profile epoch 不能复用为肯定证明。
9. link 精确固定现存 owner-created Build 输出和 Issue/CAPA/action 的同范围绑定；只保存事实回链、不推进 Issue、不称措施满足或有效。错误版本拒绝。
10. rootcause、complete、link 各在末端真实 Outbox before_insert 故障，版本/Current/proof/Receipt/Audit/Outbox/link 全回滚；同原 prepared command 正常重试必须新事务真实消费，不能复用已结束 marker。

同 phase 原件 epoch 改变预期先命中 `ORIGINAL_SECURITY_BLOCKED`；合法政策新版使当前完整政策摘要改变预期 `SOURCE_STALE`。这些代码是当前真实守卫预期，尚需 Root PG 确认，不放宽为任意异常。故障钩子只调用实际 reader/importer 后推进当前事实，不替换正向资格或 source 结果。

## 最小执行顺序与边界

优先真实 T2 UUID 节点、partial/allComplete 节点、Outbox[complete]；成立后再跑三重放、link、撤回/ABA 和其余末端故障。完整参数化选择见同目录 `quality-followup-transaction-selection.json`。

未增加效力/关闭、新真实复核 Run 创建、正式 Change 实施证明测试。link 当前是信息回链；实际新 Run 必须由真实 owner 新建，不能把上述既有失败 Build/Run 的引用当整改已有效。完成来源此候选证明上传/parse/current security/精确原文门禁及撤回保留，不宣称逐 phase 仪器原件字节 verifier；固定测量失败仍由原 result bridge 真实 bytes 验证。

运行地址、备份、真实 head、集中并发/完整检查仍由 Root 统一确定；当前只能使用既有显式核对的隔离 `62513/pdos_test`，禁止回退其它数据库或 .env。原 frozen A9/host3/bootstrap3 哈希仍保持；任何未来接线或 PG 修复应单独记录候选 delta，不能把这次 collection 当事务通过。
