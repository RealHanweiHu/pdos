# Wave16 回链预览调用链定向静态审阅

本报告只读观察当前源码，不执行 DB、HTTP、pytest 或公共构建；没有修改 server/web、冻结候选或唯一清单。主线报告的 inputs 已返回 200、preview 180 秒未返回仅作为调查背景。本报告没有采样运行中的线程、SQL 或对象存储，不能将下列调用次数等同于已证实的耗时瓶颈，也不声称任何速度提升。

## 1. 实际操作归属与事务边界

`quality.capa.followup.link` 的 handler 是 `domain/capa_verification/commands.py`，不是 `domain/quality_followup/service.py`。后者只负责根因 T2 与本人完成 T1：`command_handlers.py:56–64`。`reviewed_view` 最终调用 `module.preview_view`，没有另一层隐式 validation：`command_handlers.py:176–195`。

三次 HTTP 各自创建独立 Session/事务：

| 入口 | 实际调用 | 位置 |
| --- | --- | --- |
| `POST quality-followup/inputs` | `links.inputs` | `quality_followup_api.py:35–49` |
| `POST commands/preview` | `preview_command` | `api.py:329–332` |
| `POST commands` | `execute` | `api.py:312–315` |

`tenant_session` 以 `Session(engine), session.begin()` 创建 UOW：`database.py:19–26`。此前 inputs 成功不提供后来 preview/execute 的当前授权或原件核验结果。BFF 只有一次 `fetch`，180 秒是 `AbortSignal.timeout`；没有自动重试：`web/src/app/api/[...path]/route.ts:96–116`。浏览器超时也不能证明后端事务已取消或没有产生确认记录。

## 2. 单个回链 handler 方法的静态展开

下文 `_load`、`_refresh` 均指 `capa_verification/commands.py`；resolver 指 `capa_verification/service.py:421` 的 `resolve_followup_outputs`。

- `_load:124–196`：一次 `load_exact_followup_basis:132`、一次 resolver:144，建立完整 Bound 后调用一次 `_refresh:183`；随后查原语义回链并核保存内容。一次 `_refresh:199–224` 自身再调用一次 resolver:202，并在之后刷新专业、政策、完整 source_basis、当前 human 和有效期。因此一次 `_load` 是 **2 次 resolver**。
- `_new_write:231–237`：产品 revision CAS、一次当前 `load_followup_basis:234`，再独立 `_refresh:237`。不能只留下最初 Bound 而删掉这一当前检查。
- `validate:227–228`：一次 `_load`。
- `preview_view:264–268`、`inputs:271–286`：各为一次 `_load` 加一次 `_new_write`，各 **3 次 resolver**；`_review:240–261` 本身只格式化已有 Bound。
- `apply:289–333`：一次 `_load`、一次 `_new_write`、真实 consumed-proof callback:295、callback 后独立 `_refresh:302`，共 **4 次 resolver**。
- `replay_subject:340–350`：一次完整 `_load`；当前来源、专业、政策等不能因为重放跳过。

## 3. 公共入口实际累计次数

以下针对走完相应分支、没有提前失败、固定 Issue 版仍为 Current 的情况；不包含 owner 内部的递归调用。`N` 为选择的真实输出数量，`F` 为固定 Issue 内原失败数量。数字是控制流展开，不是 SQL 次数或测量耗时。

| 公共路径 | link `_load` | link `_refresh` | resolver | exact-basis 完整加载 | 输出 `_owner` 读取 |
| --- | ---: | ---: | ---: | ---: | ---: |
| inputs | 1 | 2 | 3 | 8 | `6N` |
| common preview | 2 | 3 | 5 | 13 | `10N` |
| 新 execute，无既有 key/Receipt/Link | 4 | 7 | 11 | 28 | `22N` |
| 已成功的相同 key，或 common semantic Receipt 重放 | 1 | 1 | 2 | 5 | `4N` |
| 无上述 Receipt 命中、由 `replay_subject` 返回旧 Link | 2 | 2 | 4 | 10 | `8N` |

公共 preview 在 `service.py:419` 先 `module.validate`，在 `:420` 再进入完整 `preview_view`，所以不能把它计成单独一次 preview_view。

新 execute 在 `service.py:521–522` validate；key/semantic Receipt 查找分别在 `:532–541`、`:582–598`。两者均未命中后，`:600–601` **即使没有旧 Link，也调用 replay_subject 并完成另一遍 `_load`**。接着 `consume_material_confirmation:483–486` 为实质快照比对再次运行 reviewed_view；最后 `:634` 调用 apply。因此是 validate + replay_subject + preview_view + apply 四遍 `_load`，不能只计三遍。

每个 resolver 对同一 basis 前后两次 `recheck_followup_basis`：`capa_verification/service.py:425,434`。当该固定版仍 Current，每次重核都调用一次 `load_exact_followup_basis:177–179`。每个输出读取前后两次 `_reading:430,435`，每次 `_reading:310` 进入真实 owner。`_new_write` 的 current loader 又在 `:161` 加载一次 exact basis。因此 exact-basis 数为 **`_load次数 + 2×resolver次数 + _new_write次数`**。若 Current 已是另一合法后继，`recheck_followup_basis:197–201` 还会读取后继并比较完整语义；表格不对该分支承诺固定次数。

`load_exact_followup_basis:123–134` 每次对每个失败调用真实 `quality._result`，所以一次 common preview 是 **`13F` 次实际失败桥调用**。`quality_result_bridge.fixed_failure_result:190–204` 读取该固定 Run 的实际报告、逐 Measurement 核原值；`:143,220–228` 前后核 retained/current/runtime。因此这些不是只重复 Pydantic 校验或 digest。桥内 `captured_reports` 仅限单次桥调用，同一 Run 的不同失败、不同 resolver 调用不会共享该字节核验。

## 4. 共同证明不是另一遍预览

`quality_followup_host.record_consumed_confirmation:231–278` 验证同 Session、实际活动 transaction/nested transaction、ORM consumed 的真实 False→True history、命令/material/read-set/token 绑定，保存 consumed marker；它没有调用 reviewed_view 或领域 `_load`。

`require_consumed_proof:307–325` 重新检查当前 Principal scalar、精确锁定 Confirmation、消费状态、到期与 marker/material 绑定；它也没有重新运行预览。`quality_followup_integration._link_proof:62–65` 只包装这个真实 T1 assertion。当前 `Session.info` 中的是共同实际消费证明，不是可复用的原件/资格加载缓存；本建议不新增或复用 `Session.info` 作为验证缓存，也不删除现有真实消费 provenance。

## 5. A 包两个操作的区别

`quality_followup/service.py` 的 `_load:306–429` 固定原失败字节、措施完成原文/可信分类、完整来源与专业/政策后，已执行一次 `_refresh:428`。`_new_write:506–523` 只核产品/Issue Current CAS，不像 link 的 `_new_write` 再完整刷新。

对根因/完成的正常无旧记录新 execute，同一 common 控制流仍是 4 次 `_load`；模块直接 `_refresh` 共 5 次（四遍 `_load` 的末端加 apply 的 record 末端一次）。inputs 是 1/1、common preview 是 2/2。这里未把 kernel `_review` 中精确额外来源检查计成无 I/O；也未将这两个操作的次数混入实际回链表格。A 的末端失败证明刷新在 `:466–474`、专业与时效在 `:475–503`，应继续保留。

## 6. 最小下一候选：先合并同一次 common preview 的重复完整加载

建议第一步只给显式允许的回链操作增加 **prepare → preview_prepared** opt-in 协议，保留其他 handler 原合同。让 `preview_command` 在同一调用栈中接受由该真实 module 完整 `_load` 建立的 typed phase bundle，然后传给 preview_prepared；后者继续执行当前 `_new_write` 的产品/Issue CAS 与独立 `_refresh`，最后才格式化 review。这样避免 common preview 的 validate 丢弃 Bound 后又为 preview_view 从头 `_load`。按当前控制流，该方案会从 2 次 `_load`/5 次 resolver变为1次 `_load`/3次 resolver；这只是拟议调用数量，不是速度承诺。

最低绑定必须由服务器对象检查而非客户端 digest 自授：

1. 实际 Session identity、当前活动 transaction 和 nested transaction identity；专用 phase=`common_preview`，单次消费后销毁，不存 engine/global/Session.info，不跨 inputs、preview、execute、请求或 UOW。
2. server Context 的 tenant/actor/requester/run/cancel_epoch、operation、真实 module 与 callback/runtime identity；保持本人 human 与当前授权条件。
3. command_id、idempotency_key、product_id/锁定 Product identity及水位、完整已验证 payload（不丢显式默认值或私有范围）、semantic/material 和完整 read-set 摘要；精确 Issue version/CAPA/action/output refs 及受众绑定。摘要只检查同一载荷，不能替代真实 owner/bytes/proof。
4. bundle 必须只能由完整 prepare 创建，不能公开接收用户构造的 `Bound`、`authorized=True` 或 `accepted=True`。preview_prepared 应显式拒绝跨模块、跨人、跨事务、跨 phase、payload/read-set 改换、缺真实 prepare 的使用。
5. 末端 `_refresh` 必须独立、真实地再核所有 owner/原失败/当前来源/安全 epoch/专业/政策，不能从 bundle 的 positive 值回答自己；在全部可能 I/O 后重新取 now 检查期限、issuer/runtime 与真实 Current。Confirmation 仍由 common 在最终 review 后创建，snapshot/material 相同且只消费一次。

更小的等效第一步可以是只对明确 opt-in 操作的“已完整 validation 的 preview”入口合并两次调用，但必须证明 preview_view 覆盖原 validate 全部门禁；不能全局删除 common validate 或把 `hasattr(preview_view)` 当充分条件。

## 7. 第二步可复用现有 byte-verified 证明，但另需窄协议

仍慢时才考虑 resolver 内每次 basis 重核的字节重复：现有 `quality_result_bridge.recheck_fixed_failure_result:262–314` 是已存在的真实“全部字节读取后无再次对象存储 I/O”重核端口。它核固定 Run/投影、来源闭包、retained/current/实际占用消费、runtime stamp。可由同一显式 phase bundle 保存每个精确 failure 的 `FixedQualityResult`，将后续 fresh basis 构建与该端口连接；每个 failure仍要完整核 exact FailureRef，且所有 output/bytes I/O 结束后，对 **全部** 原失败独立刷新。

这不能直接用 pure `basis_from_issue` 或 immutable hash 替代原失败门禁；也不能共用早先 Current、某个调用者资格或 cached positive 作为 refresh。输出 owner 若无等价窄 fresh 端口，仍须真实读取；不能为了速度去掉 resolver 的前后输出比较。跨 key/semantic replay 仍须当前 guard 在返回原 Receipt之前，且不再消费证明；新写 CAS不能抢先阻断合法旧意图重放。

新 execute 的 validate/replay_subject/material-review/apply 可以随后分别设计显式准备接口，但第一步不建议在四个阶段之间分享一个隐藏缓存。至少 phase标识、已消费 proof 边界、Current变化及末端刷新要先形成测试合同；保持共同 Receipt/Audit/Outbox 和 DB deferred atom原样。

## 8. 验证范围与剩余风险

下一候选必要检查：同一次 preview仅准备一次但末端真实刷新仍发生；跨 Session/事务/nested rollback/人/operation/command/payload/read-set拒绝；多个失败/多个输出读取时最后一个 I/O撤回前面 issuer/source/原件 epoch仍拒绝；读取期间期限到达拒绝；Current CAS变动拒绝；原成功 key/semantic回放仍先当前门禁、不重复消费；Confirmation snapshot/material/tier真实UUID及同事务 atom保持。

应先按主线冻结候选进行受影响真实检查，再在无并发污染的条件下量取 inputs/preview/execute 单独阶段、SQL/对象存储/锁等待/末端刷新，不把总 HTTP时间推断为CPU或某个函数耗时。本报告不能区分当前180秒中的 DB往返、锁排队、对象存储或环境中断，也不建议扩大超时/TTL、删安全门禁或放宽20读集。

## 定向源码观察摘要

以下仅为11个定向源码的读取摘要，不是480候选或全工作区冻结结论。路径均相对仓库根；行号为本次观察值。

| 文件 | SHA256 |
| --- | --- |
| `pdos-next/server/pdos_next/service.py` | `d4afc3197e77899c6211eba339fefe6ca9e317ee6b6d9ddec622128db4b7838a` |
| `pdos-next/server/pdos_next/command_handlers.py` | `b669d0b9cf0a58a38892b5c385ba800a717899aaea1c0a76e000f442120b280c` |
| `pdos-next/server/pdos_next/quality_followup_api.py` | `b4ddb2e0f576637206dc8864e93793387b1180dfa30d328c99cf36253cea4bc5` |
| `pdos-next/server/pdos_next/quality_followup_host.py` | `9400df47e01a8c7b4e9dc7f65bd56279da167e4de1f772509c864d0d079a7cb2` |
| `pdos-next/server/pdos_next/domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| `pdos-next/server/pdos_next/domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `pdos-next/server/pdos_next/domain/quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| `pdos-next/server/pdos_next/quality_result_bridge.py` | `28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077` |
| `pdos-next/server/pdos_next/domain/quality_execution/evidence.py` | `f9b128b0cff62607415d16824bd6a8c1a7e9b30c397b1252991f1ec76bd98903` |
| `pdos-next/server/pdos_next/quality_followup_integration.py` | `2c722d0fa94e02fd5d0e1d7ebeec1e52a782015457cb58e4ed5efbf3fce32e5f` |
| `pdos-next/web/src/app/api/[...path]/route.ts` | `1c94099e657f564a2030dd8a9ec738f46f5daf6e49dc2fca93a1d55156461888` |
