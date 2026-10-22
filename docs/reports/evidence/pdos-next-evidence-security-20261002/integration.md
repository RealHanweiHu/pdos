# 原件扫描与生命周期 · 主线接入合同

本包只是可调用的首版规则与受控 port。未修改公共模型、迁移、原件上传/解析、Outbox/worker、API 或页面；没有生产扫描器、持久生命周期适配器或真实资格。不能从本包检查推导 G0、AT 或 N/P/Q 全部完成。

## 扫描接口

入口：`pdos_next.evidence_security` 的 `bind_request`、`ObjectStoreScannerAdapter.scan` 和 `parsing_gate`。消费现有六字段 `ObjectRef` 与 `ObjectStore.read_original`；当前共享 ObjectRef 只支持不可变 v1，不在本包编造 v2。共享源码摘要见 `consumed-interfaces.json`，临近交付复核见 `interface-drift.json`。没有消费施工中的 Build DTO，也没有旧工程业务导入或算法复制。

| 主线提供 | 必要事实/行为 |
|---|---|
| `ScanGuardPort.current_configuration` | 服务器当前 `ScanConfiguration(ScannerIdentity, ScanPolicy)`，含扫描器、实际引擎版、规则版及有界预算/有效期。不能从模型或请求选择扫描器、传入身份或扩大出站范围。 |
| `ScanGuardPort.bind_for_scan` | 当前原件精确 ObjectRef、tenant/product/requester UUID、原件读版本、ACL 与受众读版本、有效来源；上传成功且可扫描、当前读取权限、生命周期 fence 均在服务器核验。 |
| `ScanGuardPort.is_current` | 必须返回严格 `True` 才可能放行；未知/错误/权限撤销/来源失效/生命周期阻止消费一律拒绝。需要共享事务锁中的当前事实，不是缓存。 |
| `ScanReceiptStorePort.stage_receipt` | 唯一 request_id，固定依据、同回执幂等/冲突拒绝；主线共同事务内重验来源与 ACL，原件安全状态、回执、Audit、Outbox 原子落地，不自行 commit。 |
| 真实 `ScanTransportPort` | 仅服务器注入的本地服务；完整扫描精确 bytes，实际观测 engine/rules 版本并核对回应，不只回显请求版本。返回 typed `ScannerReply` 与机器错误码。真实启用/资格及环境由主线核验。 |
| 当前 `ObjectStore` 适配器 | 按 ref hash/size 读取不可变原件，自身有字节上限和 I/O 超时。S3 客户端连接/读取超时须由主线配置；本包不读凭据、不建桶。 |

`ScanRequest` 固定 request UUID、服务器绑定、扫描器/规则、policy 摘要和请求时间；`ScanReceipt` 完整保留这些依据、clean/infected/unknown/unavailable/timeout/rejected、起止时间和受限机器码。规则、预算、来源字节、读版本、ACL/受众或有效期变化使旧 clean 失效。回执只允许从内部可信 worker 存储取得，不能通过公共 payload 提交“clean”。

本地默认 transport=None，因此通过类型/预算检查也只返回 `unavailable`。单纯 PDF 魔数、UTF-8、ZIP/XLSX 包络通过不证明可解析、内容真实或无恶意文件。现有 ParseResult 的 `not_scanned` 和成功解析均不升级为 clean。

## 上传、解析与工作流步骤

1. 主线为私有上传建立可信上传意图/日志和原件范围，保留精确 ObjectRef、存储回执、来源、受众、失败/未知状态及实际时间。`originals.upload` 当前同步 put 后建行；如果事务失败而对象已写出，必须有独立的权威上传日志/存储清单交叉核对，不能靠“UploadedOriginal 行不存在”判成孤立对象。缺日志时只能保留未知。
2. 上传保持隔离且未扫描。主线在自己的共同事务内登记扫描请求/去重与 Outbox；扫描字节和 transport 在业务事务外执行。本包前检核对类型/尺寸/完整性和解压额度，不把其当扫描完成。
3. worker 根据服务器 scope/ACL 获取请求，以固定 request_id 消费；内部 receipt 回到主线事务，在对象/权限/生命周期锁下核对当前读集，再写安全状态、ActionReceipt/Audit/Outbox。来源或配置变化时留历史并标 stale，不写当前 clean。超时/不可用重试策略由主线安排，任何迟到 clean 都不能覆盖新依据。
4. **必须接入 `originals.parse_uploaded` 两次门禁**：读取和解析前一次，派生 Artifact 写入的事务中再次。只读调用本包 gate 的 `allow_parse=True` 仍不授予权限；调用方必须持有同一原件/ACL/lifecycle fence 并复核当前 scanner configuration。没有有效 clean 不排解析任务、不提交派生 Artifact。不得仅检查原 `row.status == uploaded` 或静态 `ObjectRef.as_dict().scan_status`。
5. 主线处理原件感染、撤回、配置升级或新保护状态时，失效相关当前派生投影、索引与待执行任务；保留受控历史与已发生决定。既有成功解析不构成扫描资格。恢复字节也不自动恢复 clean/来源授权，需重新评估门禁。

## 生命周期接口和原子性

入口：`pdos_next.original_lifecycle` 的 `LifecycleService` 与 retention rules。DTO 是主线原件/上传日志/引用的固定消费快照，不建立第二个原件事实所有者。`LifecycleAuthorityPort` 绑定当前 actor/scope/ACL；`ReferenceGuardPort` 完整枚举权威消费与正式历史；`LifecycleStorePort` 持有调用方事务的共用 object fence。`RetentionPolicy` 必须由服务器显式提供，测试保留期不等于生产政策已获批准。

主线需提供：ObjectRef、tenant/product；生命周期/库存读版本；创建与观测时间；注册状态；上传终态与时间；当前解析状态；权威 retention_until 与 hold（未知不可回收）；权威引用数量/正式历史及读版本；当前物理 disposition/隔离时间；待执行意图。预览固定这些事实、政策摘要、原因、期限和 digest；公开响应只返回候选必要字段，不暴露 storage_key。已引用、正式历史、注册原件、保留期未满、正在上传/解析、已形成派生物或无法确认者不成为可回收候选。

主线接线顺序：预览→保存实质候选→人员一次确认精确候选及 digest→同事务共享 fence 下重验当前授权、引用/hold/保留/状态及固定版本→保存意图、pending 防消费状态、两级幂等键、ActionReceipt/Audit/Outbox→worker 当前授权与保护重验→先提交单次 effect permit→受控可恢复隔离/恢复→凭精确观察回执对账落地。模块从不 commit。

`LifecycleService` 提供 `preview/confirm/begin_effect/validate_effect/record_effect/mark_unknown/cancel_pending`。`begin_effect` 严格匹配确认后的预期原件读版本，不能通过 hold 修改后再改回来复用旧候选。`EffectPermit` 绑定 operation/lease UUID、attempt=1、named_decider、scope、精确 ObjectRef、当前授权版、**post-begin lifecycle_revision / inventory_revision / reference_read_version / policy_digest** 和时间期限。实际 adapter 调用 `validate_effect` 时取得的主线共用 gate 必须持续到字节动作，不能在核验后释放再移动。已完成观察采用同 lease 去重；UNKNOWN 不释放 pending 防消费保护；异常保护写入 `LifecycleIntent.recovery_required/protection_reasons`，主线须接恢复提示。

**共同 fence 必须覆盖全部引用、正式历史、上传、解析和 hold/retention/撤回/权限保护更新。** permit 提交到实际存储动作之间仍有并发窗口，存储适配器必须原子重验/消费当前保护许可，保护变更必须能使未执行许可失效。不能只相信过期前的 permit 或先查引用再无条件移动/删除。主线持久适配器须验证这个协议后才激活 effect；当前不可用 adapter 不做物理动作。

外部结果 unknown/超时/重启时保留 pending fence，禁止盲目重发；先 `observe` 同一原件与单次 token 的持久记录，确证字节和状态才记 APPLIED/NOT_APPLIED。已发生的观察事实与当前回收资格分开：如果应用隔离后发现新保护，记录恢复需要与具体原因，不能宣称安全回收。NOT_APPLIED 后也重新预览/授权新意图，不复用旧许可。恢复只恢复精确保留字节和原件可达性；ACL、引用、hold、扫描状态与历史不被覆盖。

本包只提供 purge **资格规则**，没有 physical delete 代码、删除命令或可授予 AI 的 purge 权限。正式回收需要主线单独的具名批准、再次核验与删除结果/恢复期限协议；任何保留/引用/hold 未知均阻止回收。本轮检查只使用明确自建、内存或临时合成 store。

## 由主线集中验证的病例

- 公共 schema/迁移/实体注册；RLS 与真实权限；来源/ACL变化在 scan/parse 两个事务之间发生；clean 回执去重与冲突；Outbox/Inbox 重启和迟到结果。
- 当前规则升级和扫描器服务不可用时实际 HTTP/页面阻止解析，旧 parsed 原件仍明确未扫描；恢复后不恢复 clean；失败状态/重试可见。
- 真实上传失败但对象已写出，与缺失/不完整 inventory/journal 的区别；新引用、hold、保留延长、撤回、权限撤销发生在预览/确认/permit/实际效果的各边界。
- 主线 DB 锁/CAS 的竞争与同事务 Audit/Outbox 回滚；effect 提交后的 worker 崩溃；未知结果先观察；已知未应用后新预览；恢复字节 hash/size 与权限；引用保护异常的恢复提示。
- 实际本地扫描服务及规则升级验证，S3 I/O 超时、存储版本/隔离标记/持久 transport journal；OS sandbox 和恶意文件验证另待环境。本包没有这类资格证据，也没有 OCR、浏览器整链或业务真实文件检查。

这些集中检查必须由主线在其已核对的隔离条件内执行。本包不读取 `.env/.local`、不运行 DB 测试、不启动服务、不改共享 `.next` 或依赖锁。
