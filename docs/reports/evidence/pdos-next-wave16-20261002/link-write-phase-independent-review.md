# Wave16 Link write phase · 独立只读复核

本次只读审阅B明确冻结的3个新增暂存文件，未执行pytest、数据库、HTTP、浏览器、公共检查，也未改业务或测试源码。旧v3联验已由Root停止，Root正在修改公共候选；以下不能作为旧480文件仍冻结或新公共联验通过的陈述。

| 初次审阅文件 | SHA256 |
|---|---|
| `pdos-next/staging/wave16/link_write_phase.py` | `a6d119ecce5d49691db337a0915ceaab7f79b9279853656ed721519e03cd4511` |
| `pdos-next/staging/wave16/test_link_write_phase.py` | `3fb4c69f516579328811ac20c9f2eee088bc15ac60bf2cb278b6167733ae7c9e` |
| `pdos-next/staging/wave16/link-write-phase-contract.md` | `b8d22e24a9fa7a2d2f5ee4f4812f6d4a42907a8fe12252032b43ed164570f281` |

## 发现与真实保证

实现定向复核未发现新增明确的proof、UOW、精确材料或原写入门槛阻塞。**初版合同第40行对COMMIT瞬间TTL的描述超过现有SQL保证**：0024 `assert_quality_followup_proof`以传入NEW.created_at核 `c.expires_at<=saved_at`，不取guard执行瞬间或COMMIT时钟。最后纯阶段已核有效，随后flush／COMMIT前发生时间推移，不代表此SQL必然拒绝。此观察已报告Root／B；Root同意只修合同说明，不改SQL、TTL或新增commit-clock政策。新文档冻结后在下文追加其准确SHA，旧文本及发现保留。

真实实现保证为：全部owner／bytes IO结束后再次核当前材料、资格／政策与UOW，捕获当时真实服务器保存钟；随后实际共同proof IO完成以及row构造结束后再次取fresh钟核Proof有效期／专业政策期限，不使用prepare或Confirmation旧钟回填created_at。数据库继续核该保存钟、实际False→True消费及完整目标／回执组。此阶段尚未公开接通；无DB纯检查不证明实际COMMIT成功，也不能说明pg-v3-08的合并guard失败已被唯一定位或已修复。

## 精确实现核对

1. `link_write_phase.py:101–133`只接受当前完整Command／Payload中的原确认token。实际Link._load后original存在即REPLAY_REQUIRED，不能把旧回链作为新写；实际_new_write及其产品／Issue Current CAS、独立末端_refresh仍真实调用。完整原_review深副本及其hash从服务器产生，不能由客户端传snapshot、Bound或proof。
2. `:22–98`使用与PreviewPhase不同的内存类型；同Session、活动主／nested事务、宿主连接与真实persistent Product identity绑定。Context全部5字段、Command全字段／原readset顺序／key／token／payload／水位、typed payload、Product全部映射、Bound全部nested材料、实际callback及runtime／issuer stamps仍绑定。先检查UOW后访问ORM，关闭／rollback／切换SAVEPOINT不能重载旧phase后继续。任一apply尝试先消费phase，失败后不得重用；不能copy／pickle／HTTP传递，没有新增Session.info或其他跨阶段缓存。
3. `:187–202`apply先核原phase，再真实Link._refresh，保留全部原失败、output owner、bytes／source／专业／policy重核。结束后再次核完整Bound／命令／UOW／runtime与专业政策期限，才捕获saved_at；这与原apply在较早proof callback之后继续漫长owner刷新不同。
4. `:136–173`仍调用Bound真实proof callback；必须返回UUID且等于真正host.require_consumed_proof返回的UUID，不能以bool、任意UUID或历史consumed=True代替。host实际marker绑定当前Session、主／nested UOW、完整context／command／readset／material／token与ORM真实False→True历史。该phase不生成、消费或删除proof，真实common消费仍由Root独占。
5. `_proof`另以exact tenant/product/subject/actor/op/revision锁定实际Confirmation，要求同Session persistent、consumed=True、原token hash、实际material_digest以及snapshot hash==本次server review。proof查询IO之后再核phase／UOW／资格政策／runtime，并fresh检查expiry；构造row后再核一次。不能拿prepare阶段时钟回答最后读取的当前有效性。
6. `:211–244`返回transient RemediationLinkRecord，精确复制basis／resolution／sources／readset／source_basis，保留最窄受众、series scope、writer／owner及原action。created_at显式为第3步捕获的真实钟，input.shared_proof只保存真实UUID＋T1，没有明文token。authority/policy/readset/safety复制防止后续nested材料alias改写。不自行s.add／flush／commit／Receipt或推进Issue Current，共同原子事务仍承担持久化。

实际Product门栓及当前本人／SourceRead检查仍是公共调用前提。Root公共接入须只在准确Link的新写分支使用server-prepared review，保留current-first validate、key／commonsemantic／domain replay门槛和原old/moduleapply fallback。consume仍对真实Confirmation核material／snapshot，实际False→True后立即记录marker，再把本次局部phase交apply。server review参数不能公开成为客户认可的任意review，也不能用于其他operation绕开原reviewed_view。

## 50项纯证据边界

B报告本新增test的50项通过0.85秒，Ruff／format／AST通过；本审阅仅读源码，未重跑。用例使用真实无连接SQLAlchemy Session／事务／ORM变化及原host marker函数，但owner loader／refresh／Principal与Confirmation SQL返回是明确fake。它们核精确review、单load／new_write、末端refresh／时钟、markerUUID、材料／source／issuer／Current漂移、proof到期与最后IO、readset顺序、跨Session／UOW、一次attempt和old replay拒绝。未接真实原件、专业、数据库commit或public caller，不能据此授予资格、声称速度改善或新回链已经保存。

## 新合同冻结追加

待B按Root仅文档授权冻结修正的contract SHA后，追加实际hash与限定保证复核；两源码SHA保持上述值。未增加commit-clock规则。

## 追加：最终合同与公共接线观察

B按Root仅文档授权修正第40行，最终contract SHA为 `e236aa72e3f71916e0ccade7141822e558b29388d27222a3af69c1f797d75c54`。两个Python SHA仍分别a6d119ec…／3fb4c69f…，未因该文案修正改变。新文档明确：现SQL只按NEW.created_at／saved_at检查expiry，不读取COMMIT clock；最后fresh guard到flush／COMMIT之间的延迟不保证另被SQL按提交瞬间拒绝。本报告先前合同发现已按实际保证澄清，没有改SQL、TTL或新增commit-clock要求。

随后按Root新增只读任务读取其公共接线；此时公共源码正在修复，以下只是具体4文件瞬时内容观察，不是冻结清单，也不是137项公共pure／static的独立验证。本审阅没有运行测试。

| 公共观察文件 | SHA256 |
|---|---|
| `pdos-next/server/pdos_next/service.py` | `a710834b172d33de60f713333fd63a5d2d6bab3c39d5a7002b03c7d3d2982686` |
| `pdos-next/server/pdos_next/domain/capa_verification/commands.py` | `7b05a392c1897632d2e41b4812500401dd0a326bf6fdbcdd51cc165855741e84` |
| `pdos-next/server/pdos_next/domain/capa_verification/preview_phase.py` | `5f22ff9ebc0d4945eae7dbf0548397e34e91285d5d7cb703621c4166a056429d` |
| `pdos-next/server/pdos_next/domain/capa_verification/write_phase.py` | `daebc415ae668ffe9e897dbca1a077600341ef2426d74be92b96a349cc78b394` |

公共两个phase与所审staged实现的差异仅import排序／相对import，无业务逻辑差异。四个commands wrapper懒加载真实phase，不使用HTTP对象或Session.info正面缓存。

`service.preview_command`在正常Product FOR UPDATE／access锁／本人human／完整SourceRead门栓后，只有准确quality.capa.followup.link采用prepare_preview＋preview_prepared；其余validate＋reviewed_view保留。共同Confirmation仍在真实末端review后创建，snapshot／material与原prepared command返回规则不变。

`execute`仍先current-first validate，再依次原RequestKey／common semantic／domain replay。只有三路均未返回、准确新Link才准备server内部write review，交consume的prepared_review，然后同调用栈applyphase。非Link没有传prepared_review，仍原消费和module.apply；consume明确拒绝为其他op传非空prepared_review，仍先核原Confirmation、material_digest短路，再核snapshot并进行真实False→True和原host marker。没有客户端review字段入口。

`replay_subject`在共同当前门栓／Product锁之后，仅当准确_saved domain intent不存在才快捷None；存在时仍完整_load／旧材料核验，不把旧proof重新消费或新写CAS用于合法重放。`legacy apply`已把完整owner_refresh置于实际callback之前，捕获其后的fresh created_at；新公共execute使用更严write phase，原fallback并未被用于跳过phase门槛。

在上述定向接线中未发现新增明确实质阻塞。实际新候选、API重启、原proof与共同Receipt/Audit/Outbox/deferred guard、同scope旧回执重放及真实保存仍由Root统一PG／HTTP验证；本报告不替代其结果，也不把旧v3失败覆盖成通过。

