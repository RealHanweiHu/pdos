# Wave17 Rule／Observation／NamedReview · 独立只读复核

本报告仅读取明确冻结的三个暂存文件、其已有77项纯检查记录及对应只读合同／类型。不执行pytest、数据库、HTTP、浏览器或公共检查，不修改源码。旧Wave16 v3联验已由Root停止，公共修复正在进行；本文不声称当前server公共候选仍为480份不变源码。

| 文件 | SHA256 |
|---|---|
| `pdos-next/staging/wave17/facts.py` | `5b711db84275b2c9e88d633a6e782fca63bee90f41207a1116a94f24676a017d` |
| `pdos-next/staging/wave17/test_facts.py` | `bb676aa2cd1a0008c0c2100360515469ef8894dccc3ac6c9be54403d35b411d3` |
| `pdos-next/staging/wave17/facts-contract.md` | `fbcf3b5bb959a556e8b801ab9436e4180700c6a9b54ef39769a9407b8f2292e1` |

## 结论与一项迁入前边界

固定材料核验与结构／宿主权威的分离保持。没有发现这些DTO直接创建VerificationEvidence、Current、公开审批／消费或有效性／关闭结论的路径。真实Rule出版、Observation T1、Review T2及七类实际owner、各Current／回执／同事务消费与持久原子组仍未接通；77项纯检查不能代替这些条件。

**真实活动UOW的强制责任需在迁入前明确。** `facts.py:886–900`的`_uow/_check_uow`仅调用get_transaction/get_nested_transaction，比较对象identity并要求主事务非None；没有验证SQLAlchemy Session、主事务is_active或SAVEPOINT is_active。`load_verification_facts:980–995`据此进入首次reader IO。`test_facts.py:349–359`明确用object占位Session／事务，证明的是协议identity，不能证明真实活动UOW。一个仍返回同对象的inactive真实事务不会在此包装层被提前拒绝；实际Reader若缺自己的活动事务守卫，接口本身不足以履行合同中的“实际Session／Transaction／SAVEPOINT”要求。

最小建议是：Root迁入时在真实入口显式检查实际Session与活动主／嵌套事务，或由实际Reader协议强制并验证该检查；每次IO后的identity核对仍保留。不得让fake占位、可自组的HostFactProof、hash或consumed字段成为真实UOW依据。此观察已发送Root与A；当前没有公共入口，故不是已发生的业务越权，也不推断真实owner会返回假阳性。除了这一宿主边界，在本次指定范围内未发现应放宽旧核或重设计DTO的理由。

## 已核对的具体边界

- `FactBase:155–199`重新验证完整模型，版本是不可变行ID＋连续版＋摘要，首版v1；原purpose不trim改值。完整sources/readset/source_basis核闭包，private来源禁止提升受众。`FactAtom:97–152`固定human actor=requester、exactReceipt主体／操作／writer、Audit／Outbox、token/material/readset摘要、真实proof标识和T2 Invocation.decision_id对应关系。内部host_import不伪造T1/T2消费。它们仅核错绑，真实provenance callback仍必须从受保护持久组核原子事实。
- `inspect_fact_material:469–562`保留原StableCapaAnchor／requirement／nature／scope／用途，检查已保存时钟非未来。private原调查要求全部companion仍private且原owner，当前消费人只能原owner（`load:1020–1026`）；共享场景允许不同具名writer，由真实authority及participants owner核独立性，不把ProductGrant视为专业职责。
- 全部原FailureRef及ActionBinding（action摘要排除completion，completion另完整摘要）精确保留；Rule／Observation／Review各自distinct command、Receipt及T1/T2 proof，不把存在UUID或结构重密封视为真实消费。额外或漏掉原失败、替换完成映射、不同policy/anchor/purpose/nature均明确拒绝。
- `:588–667`实际观察起点晚于最后措施完成，观察区间与记录覆盖不足是missing；unknown／not_applicable的专业复核与unknown措施履行仍missing。规则／Review到期不返回完整宿主证明。采样和参与者完整性仍由实际owner判定，不从自由文本补数值阈值，不复制旧有效性／独立性规则。
- `:673–764`复用B的完整paired核，禁止任何原失败logical Run；新Run实际Start与已知测量发生钟不得早于完成。具名复核不能先于实际新结果。每个失败映射精确绑定不可变Run版行、样件版／ActualConfig版、item、Measurement、Projection、方法／判据，不能凭ref存在代替适用性；新结果indeterminate显式missing，普通pass也不直接授予CAPA有效性。
- `:773–810`并集含原锚、Rule、各Observation、Review及全部paired读集，canonical_reads超20明确拒绝；source safety同ID不同hash／epoch／owner材料拒绝，最终basis必须完整覆盖并集。没有截断、只取首来源或把注册文本冒充仪器原件。原native登记及uploadedOriginal安全epoch材料继续由真实sources owner核bytes／ACL／撤回与issuer。
- `load:1028–1089`必须具备read、refresh、七个gate及refresh_proofs回调，无任一项即missing；逐次IO后核原事务identity。两轮完整材料＋七类owner指纹／期限必须相同，随后post-all-owner refresh独立再核整个当前闭包；末端IO完成后再次核UOW，再取真实fresh clock，重算结构时效并校验每个opaque proof的reader／Session／主和nested事务／Scope／当前requester／material／kind／nature／deadline。末轮资格或源ABA／后一个owner撤回前一个证明不能仅靠前一轮positive返回成功。

HostFactProof是由宿主注入Reader返回的服务端对象，dataclass身份／字段不自行授予安全性。末端refresh必须实际读取Current、完整runtime／issuer／source／资格闭包，不能原样重密封已有proof；候选自身真实版本／Current／保存来源及同事务T2也由provenance owner核。现协议未实现这些owner，不能启用公开决定或关闭。

## 证据范围

A提供的 `facts-source-manifest.json` SHA `491911ce14dac89f7ab9ef85620ed6fb2810cf8153e927ceb44eddeb316f6b9e` 与 `facts-check-result.json` SHA `73aeedc1298096951d0a981ca9cd488260af0b08d021736524ce140dc28b6f5c` 绑定上述三文件。原始 `facts-pure-tests.log`记录77 passed in 4.30s；本报告未重跑或累计旧58／57／51项。用例覆盖错scope／原固定材料／来源ABA／mapping／未知／观察期／distinct消费／最后IO撤回／SAVEPOINT identity及TTL，但Reader和Session明确是synthetic fake。

实际宿主、Current、forced RLS／生命周期、真实bytes与可信Rule出版、T1/T2原子写入、独立复验／观察／专业事实及公共页面仍须Root在未来明确候选统一办理。本文仅是暂存三文件的只读复核，不是G3、生产资格、人工Exit或性能验收。

## 追加：Root授权的v2真实活动UOW修正

A已明确承认初版wrapper缺口，并按Root授权只修上述3个暂存文件。旧77原始证据与本报告前段保留；下表为新冻结v2，源码／测试／合同SHA已逐项读取核对。

| v2文件 | SHA256 |
|---|---|
| `pdos-next/staging/wave17/facts.py` | `a9c06b974300729fe8953f1c7b85ec5a5c3ceb57416bc4d81c0c79f708083f50` |
| `pdos-next/staging/wave17/test_facts.py` | `0e7351bf6edc93c23005e9b352545b32eb1679c6f6e297e33b216618b251f94f` |
| `pdos-next/staging/wave17/facts-contract.md` | `1e0e393fcc86466737b0f20bd4352bc77106943b0dff03d7756b5e893c6dcb0f` |

`facts.py:887–917`现在首先限定SQLAlchemy Session及Session.is_active；主事务须为实际SessionTransaction、同Session、active、非nested且parent=None。全部nested祖先须是实际active SessionTransaction、同Session、nested、无循环，并最终准确到原root。每次IO后的原UOW identity检查仍保留。初版占位／inactive主或子事务接受缺口已在该包装层关闭，不需要等待Reader自行补救。

新增用例使用无engine／bind／连接的实际Session.begin／begin_nested，涵盖duck-type占位拒绝、关闭／失活主和子事务、owner IO中关闭、合法无SAVEPOINT、SAVEPOINT回滚保持outer但旧nested证明拒绝，以及无bind flush的真实UnboundExecutionError造成partial rollback。后者不执行SQL或数据库，只观察真实Session失活状态，不能被称为事务持久化通过。其余实际source／资格／participant／provenance owners仍是synthetic fake。

A的v2 manifest SHA `f0fd5f4893130396848a61cbb3e5a71e8c39c3df49f405d46d978453cc7436d4`，check-result SHA `168f206763a1208cd6cb8b0163400b9858e23d70f88cc81e3e3bb78736d6a7a5`；原始facts-pure-tests-v2.log记录88 passed in 5.00s。本审阅未重跑，不把旧77与新88相加，不据此宣称public host已接通、当前资格／字节或CAPA有效性通过。在本次限定修正和先前材料范围内，未发现新增明确阻塞；实际companion／Current／原子组与七owner仍为公共接线缺口。

