# 后续性能候选：同阶段重复读取与验收夹具

本次仅静态、定向源码审查。未修改 server/web/任何测试或当前 480 份候选；未连接数据库、HTTP、执行 pytest、系统采样或读取私有环境。主线报告首六个事务病例约 30–40 分钟，其余仍运行；本文没有独立测量阶段耗时、SQL 数量或锁等待。主线瞬时 `ClientRead` 观察不足以区分应用计算、下一次查询间隙或其他原因，不能据此认定瓶颈。

源码能够确认的是重复调用关系，最有价值的后续候选为 **精确 Run/报告分组核验、回链单阶段依据去重、来源集合批量初读**。先以计数证明收益，再授权实施；不得把 inputs、validate、preview、apply、replay 之间的重新核对删除。

## 已确认的重复路径

| 位置及实际调用链 | 静态可确认的重复 | 后续应测量的成本 |
|---|---|---|
| [followup._load](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/service.py:305) → 每个 Failure 调 `_result` → [fixed_failure_result](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/quality_result_bridge.py:117) | bridge 针对一条 Failure 仍取固定 Run 的全部 Measurement，复算完整 Projection，并逐条 verify_measurement。`captured_reports` 只在一次 bridge 内去重，同 Run 的另一 Failure 会再次读取相同报告、核全部原值。 | 每阶段不同 Run/原件数、实际原件 read 次数与字节量、JSONL 解析/核值次数、retained 次数。不能只计 Failure 数。 |
| 同 bridge → `inspect_retained_execution` 前后各一次；followup `_load` 末尾 [_refresh](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/service.py:432) 又调用 `recheck_fixed_failure_result` | 正常通过的一次 followup `_load`，每条 Failure 至少进入 **3 次完整 retained**：bridge 前/后 2 次 + `_refresh` 1 次；这只是本函数，尚不含共同 validate/review/apply。窄 refresh 无原件 read，但 retained 不是廉价标量比较。 | retained 内 source/历史专业/物理样件/actual method/占用查询总数与时间；分别标识初读和 after-all-IO 刷新。 |
| [inspect_retained_execution](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/test_resources/retained.py:21) → 原 Start v2 → physical `_basis` → front `_recheck` → resources `_load` → `_scope`/inspect_sample/actual method | 每次 retained 都重核原 Start、当前来源/issuer、资源事实、样件和使用证明；`resources._scope` 已按 sample ID 在**本次**加载去重多个 pair。收益应来自其上层的重复 retained，不应再次声称 pair 内无去重。 | 原 Start/fixed binding 对应的相同深核次数、当前资产/样件 epoch 查询，不能将当前消费者、原 signer、事实 maker 三个 Context 合并。 |
| [followup._exact_basis](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_followup/service.py:214) 与 `_load` | `_exact_basis` 对并集和旧 row 分别 `source_basis`；稍后 `_load` 又对总 reads 和旧 row 各核一次；末端 `_refresh` 再核总 reads。原失败 bytes 已交给 B 的 pure `basis_from_issue`，**这一处已避免 B 再读原失败**，不能建议重复加入已完成的优化。 | 每个唯一 Artifact 在一次 `_load` 的 source_for/require_original/require_safe 次数、集合之间重叠率。 |
| [Link._load](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_verification/commands.py:124) → `load_exact_followup_basis` → `resolve_followup_outputs` → `recheck_followup_basis` | initial exact basis 已真读原失败，resolve 的前/后 recheck 又各走 exact basis；`commands._refresh` 再完整 resolve。若 Current 不变，一次 Link `_load` 正常路径至少 **5 次 exact basis loader**、每个 output 至少 **4 次 `_reading`**。Current 已推进时另有 current basis 加载，次数还会增加。 | 每阶段 exact basis、全字节 bridge、owner `_reading` 次数；`_new_write` 与 apply 末端刷新另外计数，不能把 5 当整请求总数。 |
| [resolve_followup_outputs](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/capa_verification/service.py:421) → 逐 output `_reading` → owner API | 输出 initial 读取和 after-owner 读取是刻意独立重核。但后者当前再次走完整 owner API；例如 verification_run 又进 retained；build 又读固定工程制造配置。 | 单一不可变输出的纯快照解析与当前 proof 读取分别计时，确定窄刷新能否代替第二次完整重建，而不是删第二次检查。 |
| [公开 GET](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/quality_followup_views.py:367) → `_current` → internal list → `_read_row` → `_options`/`_links` → 再 `_read_row` | 有 option/link proofs 才会在全部 owner IO 后第二次完整 `_read_row`，重读原失败报告、两个 op authority/policy。选集为 exact 单 Issue/版本，没有默认全产品扫描。末端又分别核 policy、各 authority、source_basis、Current。 | options=0 与 options>0、links=0 与 links>0 四种分支分别测；不能用 options=0 测量宣称有回链页面已提速。 |

另外：[共同 preview](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:405) 先 `module.validate` 再 `reviewed_view`；[共同 execute](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:498) 先 validate，再去重，必要时 `replay_subject`，随后 [consume](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:453) 重算 review，最后 apply。后续测量必须给这些子阶段独立标签。本候选**不把跨子阶段缓存列为方案**，也不提前返回成功 Receipt 以绕过 current gates。

## 安全的最小实现切片

1. **精确 Run 级字节证明，再派生各 Failure。** 新窄 host reader 在一个 `_load` 内按 `(tenant/product/consumer Context, immutable RunVersion+hash, Projection+rules+basis, original Start intent, exact report/capture bindings)` 分组。每个 capture/原件读取一次，仍校验全部 Measurement 与 Projection，随后从完整 VerifiedRun 派生各 Measurement 的 FailureRef。输出是 typed `RunResultProofBundle`，不能由客户端提供；不省略未选中 Measurement。每条 Failure 的 exact identity、event 与完整读集仍核对，所有读完后独立刷新全部 Run 的 source/retained/runtime 证明。预计减少的只是同 Run 多 Failure 重复字节/整包计算；单 Failure 不应宣称有该项收益。

2. **Link 的 typed phase bundle，初读与末端刷新分开。** 一次 `commands._load` 内由服务器构造 exact Issue row/CAPA basis、原失败证明和精确 output readings。`resolve` 消费这些刚由 owner 核实的 typed 值，以 pure `basis_from_issue`/语义比较派生 resolution。Current 必须实际读，旧版与当前版的语义/来源相等仍检查；不存在完整已核依据时走真实 reader，不能返回空 success。末端采用逐 owner 的 narrow refresh（含 current pointer、来源、原始 retained、issuer 与固定快照摘要），而非立即再次全量重建同一 exact basis。窄 refresh 尚无完整协议的 output kind 保留原深核，不乐观跳过。

3. **来源 bundle 初读一次；最终 closure 重新读。** [source_basis](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/evidence.py:34) 已 merge/dedupe 单次输入，但多次调用之间没有去重。[check_source](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/domain/quality_execution/evidence.py:108) 先 source_for，再对同一 Artifact 调 source_basis→source_for。新 typed source bundle 可在本次加载把每个完整 source basis 与 immutable content/行数组一起返回，让多个 SourceRef 的精确行 SHA 从同一完整内容核对；集合子集比较从这份**已核初读**映射派生。新增 refs/reads 必须扩完整集合且≤20。initial→final 的独立 `source_basis` 刷新保留，禁止以这个 bundle 保留过期 positive gate。

   当前 [source_for](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/service.py:159) 每次锁 Product/Artifact，uploaded 分支再 require_original/require_safe；[require_safe](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/original_security.py:186) 又核访问、OriginalSecurity、扫描请求/结果与原扫描 requester 的 ACL/ABA。[Guard.bind_for_scan](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/pdos_next/original_security.py:120) 再核 Product/Principal/Grant。集合批读可以减少 SQL 往返，但要按既有 Product→身份/Grant→来源/祖先及 global asset 顺序设计，不宜先广泛重写公共 source_for。首切片优先单域 initial 调用去重；native registration Receipt 和 uploaded security 两类来源不可互替。

4. **GET 降低二次重建成本。** 当前 `_read_row` 返回 view 而没有用于窄刷新的完整 proof；未来可让内部 reader 返回 `(view, typed ReadProof)`，公开字段不授能力。options/link 全部 IO 后，从 proof 逐一真实重核固定失败、来源、当前专业/政策/owner，而不用重新 `_read_row` 的报告 bytes、资料行组装和不变 JSON 解析。首尾真实 Current、当前 source_status/caps、private owner 与期限均保留。真实 direct canonical Receipt EXISTS 选集已在 `quality_followup_integration.request_options`，不建议再换成宽 paired owner 或回退 planned 旧版。

单阶段指 **一次 domain `_load` 或一次 GET read 调用**；在 validate/preview/apply/inputs/replay 入口创建新的值。不得放 module/global/engine/`Session.info`，不得穿越 transaction/SAVEPOINT、不同 ctx/subject、网络等待、另一次请求或阶段。即使复用 immutable material，也不能复用“当前已授权/允许”布尔值；final runtime/issuer 标量、未来 valid_from/expiry 和当前 Principal/Grant/access epochs 仍需真实取得，取时钟在最后 IO 之后。

## 夹具：先减不相关 setup，不削弱业务证明

真实链为 `followup_work → quality_work → results_work → launch_work → accepted_work → ready_work → operational_work`。依赖均为 function 级；一个病例要先建立完整 Build→实际样件→方法/交接→真实 Plan/Promise/Start→报告扫描解析→definite fail→Issue/T1分诊/遏制/CAPA，再进入 followup 验收。某些很短的 test body 仍有这整条前置，不能只看 body 断言数。

- [results_work](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/tests/verification_results/fixtures.py:83) 完成真实 Start 后上传 `raw10.0000` 正报告；[quality_work](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/tests/quality_execution/fixtures.py:55) 又上传 `raw11.0000` 失败报告并 capture/import。品质夹具使用后者，前者没有在此链 capture/import。今后可新增明确的失败报告构造参数或专用 quality result fixture，在保存任何报告前选 raw11，保留真实上传/scan/parse/字节/元数据流程；减少一个不相关 upload+scan+parse 原件循环，不能改现 results 正例或覆盖已保存报告。
- [followup_work](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/tests/quality_followup_transactions/fixtures.py:212) 创建两项 action、两行 completion 与分类事实。单项根因/marker/Link 类例可用最小真实 CAPA 构造；partial→allComplete 例继续两项，字节/本人/9字段负例保留真实完成与分类原件。量化其额外 source/authority 读集负担，不为了速度砍对应证明。
- [advance_clock](/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/server/tests/verification_launch/fixtures.py:435) 等待真实窗口，直到实际时间点才 start；不是 clock mock。真实等待的量是调用时 `max(0, target-now)`，setup 已耗时会减少剩余等待，不能将固定+5分钟直接加到每例耗时解释。保留真实 UTC/SQL钟，记录实际 slept 时间。不能通过延长 TTL 或修改已保存时钟消除失败。
- 初始可共享的是**同一 worker/专用隔离租户内的不可变祖先**：配置、真实 native 资料、固定专业事实来源以及只读模板；每例的新 Build/样件/Run/占用/Issue、Current、proof、keys 和可撤回策略保持独立。不同租户之间不能复用实际行或权限，最多复用纯 bytes/template。ACL/issuer/profile/global asset/source withdrawal 的破坏性例使用独立祖先与 engine runtime，不能共享会被撤回的正例图。
- 先优化命令 helper 的纯选择/DTO读取：现 launch `command()` 已直接读真实 pointers 构造 input，不再为多个字段反复 GET，不能报告为新建议已实现。每阶段必要回读可取一份 listing 验全部字段；不能复用跨阶段旧 listing 断言新状态，也不能用直接 SQL 代替整链 API 验收。
- 多组并行只增加到实测有收益的程度。独立 Product 仍可能共享主机、连接池与磁盘；当前没有资源使用/等待数据，不建议立即再加并发，更不能用各实例不同 epoch/snapshot 掩盖共享占用检查。

## 下一候选量化和必须保留的反例

Root 后续可在独立候选加 bounded in-memory 计数/单调计时；不记录 token、原文、SQL参数、凭据。每个 node 分出 fixture祖先、真实clock等待、test body；每个命令分 inputs/validate/review/apply/replay/最终closure。记录 function 调用次数、SQL count/elapsed、不同固定 Run/capture/Artifact 数、store.read次数/bytes、retained/owner/authority/policy 次数、总elapsed。计数不能成为允许门栓，检查后移除或明确只读诊断配置。

最小对比：同一候选的一失败/两失败同Run、一个/两个 outputs、GET options0/1且 links0/1；按同样隔离数据规模与并发量做 before/after，保留原始结果。指标为每个**不同 exact Run/capture 在同阶段仅一次初始字节读取**、重复 pure构造/来源初读减少、末端刷新次数未减少、输出/Receipt与异常码语义一致；不预承诺分钟数或倍数。

受影响验收至少包括：最后一个报告/owner IO撤销最早的issuer；original安全epoch或ACL撤销后恢复的ABA；source私有跨主体；Future valid_from在最后IO期间激活、期限在最后Current读取期间到期；相同Run两Failure不同Measurement定位；第二output变化；SAVEPOINT回滚/外层事务分离；原同key/别key重放仍当前鉴权、无二次消费；late result只按原Start期间资格与当前来源核对；Outbox末端故障的新版本/Current/proof/Receipt/Audit/Outbox/Link全回滚。最终 after-all-owner fresh closure必须含完整原+新来源、current runtime registry以及所有 earlier proofs，不能“只不存缓存但仍成功”。

首个建议派工顺序：Root新增仅诊断计数 → A只做 quality/bridge 的 Run级分组初读与来源 typed bundle → B只做 capa_verification typed resolve/narrow owner refresh → C只做 GET proof投影/必要helper；共同源与DB验证Root统一。模型/迁移本身不是这次优化的前置，不改两个真实T2/同UOW消费或single Current真值。

## 所读源码摘要

以下为本次定向文件实际 SHA256，只证明这些读取字节，不是整 480 文件或 PG 候选新验收。

| 文件（均在 `pdos-next/server/`） | SHA256 |
|---|---|
| `tests/quality_followup_transactions/fixtures.py` | `cae4abd15db6dcfd164e14ca6f858648405521145f620c2a47c6f16d028dd3a9` |
| `tests/quality_execution/fixtures.py` | `1738572bc97e692d5cf8235377a184d1221d970e99b5594bf683794f95336ec9` |
| `tests/verification_results/fixtures.py` | `62d5d0e61839b49ac833d7bb8fcb5cc509bccaec4697c065e16087019f8a3df7` |
| `tests/verification_launch/fixtures.py` | `10e5c57889064fd47be6044f80197eecb6c07f46079153e6e6dcb63eef81ff5f` |
| `pdos_next/domain/quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| `pdos_next/domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `pdos_next/domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| `pdos_next/quality_followup_views.py` | `2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3` |
| `pdos_next/quality_result_bridge.py` | `28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077` |
| `pdos_next/domain/test_resources/retained.py` | `abf1c6d4599b3a5c13f113666b1971e85bfb173b5c27e1b34e1e17197517e0de` |
| `pdos_next/domain/quality_execution/evidence.py` | `f9b128b0cff62607415d16824bd6a8c1a7e9b30c397b1252991f1ec76bd98903` |
| `pdos_next/service.py` | `d4afc3197e77899c6211eba339fefe6ca9e317ee6b6d9ddec622128db4b7838a` |

本次交付只有此新文档。当前 PG20 候选与正在执行的病例保持不变；没有把静态重复调用当作已测性能修复。
