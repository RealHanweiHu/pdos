# Wave16 后续读取性能实施建议

状态：仅下波实施建议，未施工。当前 19 项 PG 按 Root 的 v2 候选运行；本审阅未修改任何冻结后端/前端/测试、清单或运行时，未执行 DB、HTTP、pytest 或构建，也未读取私有凭据。

## 当前可用事实与优先级

Root 的 [http-current-read-recovery1.json](http-current-read-recovery1.json) 记录本机直连 **200 / 14.934 秒**，当前 Issue v4/source=current、1 个 Failure、`output_options=[]`、`links=[]`。这是服务实际响应；先前环境代理 timeout 不是 API 执行耗时。当前首段直接 owner Receipt 过滤已避免将只由 test_run 主回执推进的 Formal 当作直接输出。

本次空候选/空回链不会走公开 GET 的第二次 A `_read_row`，因此省略那一分支不能解释或承诺改善这次 14.934 秒。优先测量当前单 Failure 的完整 bridge/retained/source/专业路径；随后测量新 Draft 输出加入后的 GET，以及 Link 的 inputs/preview/execute。不要先扩大公共缓存。

## 可确认的重复及第一步改造

[`capa_verification/commands.py`](../../../../pdos-next/server/pdos_next/domain/capa_verification/commands.py) 成功同 Current basis 路径的静态入口数如下。数字不是 SQL 数/实际耗时；若旧 basis 与 Current 不同、多个 Failure 或多个 owner 输出，调用会更多。

| 同一模块入口 | 完整 basis 加载的构成 | 每 Failure 完整 bridge 次数 |
| --- | --- | --- |
| `_load` | 初始 `load_exact` 1；`resolve_followup_outputs` 前后 recheck 2；`_load._refresh` 再 resolve 前后 2 | 5 |
| `inputs` 或 `preview_view` | `_load` 5；`_new_write` 的 `load_followup_basis` 1 与 refresh resolve 2 | 8 |
| `apply` | 上项 8；真实 consumed-proof callback 后的最后 refresh resolve 2 | 10 |

这些调用中，B [`service.py:113`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py) 每次逐 Failure 调完整 Root `fixed_failure_result`；桥重读该精确 Run 的全部 Measurement/报告、重算 Projection，字节读取前后各核 retained。`resolve_followup_outputs` 还在前后重复 owner `_reading`。共同服务另外执行 validate、replay 判断、消费前 material review 与 apply；**那些阶段仍须彼此独立，不能用上一次阶段的肯定结果绕过**。

第一步建议只改 A/B 新宿主读取接口：每个 `inputs`、`preview_view`、`apply`、GET 或 replay 入口创建一个局部 typed read phase，首次完整核原报告及固定输出；本入口中的后续检查改为精确 Current CAS + 窄刷新。暂不改变 `inspect_retained_execution` 算法、不在共同 service 引入缓存、不缓存 DB/host 授权。新接口必须先有真实窄 owner refresh；不具备时继续完整读取，不能以 proof 字段存在替代刷新。

## 建议的精确 typed proof 合同

建议新增私有 `OwnerReadPhase` 和 `FixedOwnerProof`，只由服务器真实 owner reader 构造，客户端不能传入。持有：

- 同一 Session 对象、当前 root transaction 和 nested transaction 身份；ctx 的 tenant/product/actor/requester/run、operation 和本次入口 phase identity。
- Issue logical ID、固定版行 ID/revision/snapshot SHA；CAPA/action/root/requirement/failure/completion 的完整语义 hash，不能仅比较最新 revision。
- 原 Failure 的精确 RunVersion/Measurement/Projection/basis/rules、真实 byte-verified `FixedQualityResult`；报告 original id/revision/hash/size、security epoch、每字段位置及整行 hash、完整 source/readset/source basis。
- owner 输出的 kind/版行 ID/revision/key、snapshot/owner-basis SHA、scope/private、直接保存 Receipt 与原 actor/requester/run 归属。已发生 Run 另绑定原 Start v2 ID/SHA/intent、固定 plan/accepted coverage/actual start、实际 reservation/occupancy/sample_usage。
- 真实检查中获得的原签发人、source/access/issuer/profile/callback/runtime 摘要；deadline 必须含所读完整范围内下一有效期/激活边界，不只取旧 snapshot 的 valid_until。

不要把它保存到 Engine/global/Session.info，也不持久化成新的“资格”。Rollback/SAVEPOINT 回滚、事务替换、ctx/target/operation/phase 不同均拒绝复用。ORM identity map 的旧对象、Receipt 的存在、普通 bool 或此前 `allowed=true` 都不是此 proof。

### 单阶段执行顺序

1. 首段按服务器 scope/当前 ACL/Current/精确 Receipt 缩小真实 owner；原报告至少完整 byte 验证一次。对本阶段反复使用的不可变 snapshot、typed DTO、原文材料只做纯解析/投影复用；沿用真实来源性质，不把 native 文本当 measurement 仪器原件。
2. 从这些已核材料生成固定 basis/输出 resolution，保持现有 scope、private、完整来源并集（超过 20 拒绝）、exact failure/config/method/result/rules 断言。后继 Issue 只有版号推进时仍须检查 CAPA/action/root/requirement/failure 语义，不能跳过 `recheck_followup_basis` 的含义。
3. **全部 owner I/O 完成后**逐原 Failure 调现有 Root `recheck_fixed_failure_result`。它保留当前源/issuer/runtime/消费证明核验而不再读 object-store bytes。当前真实 owner 输出也须独立 fresh reader/refresh：重核直接 Receipt、Current/受众、完整来源及相关原签发资格；没有窄端口时保留完整 owner reader。
4. 最后独立核当前具名人/Grant（fresh 标量、active/kind/access_epoch/can_write/expiry）、政策、当前新操作 professional facts、全部来源/安全 epoch、runtime/profile/callback 身份与期限。后一个 I/O 撤销前一个证明必须阻断；检查结束后跨 deadline 或 stamp 变化须 SOURCE_STALE，不只是取消 memo 后继续成功。
5. 新写另做 fresh Product/Issue CAS；apply 在同事务真实 consumed-proof callback 后保留最后刷新。callback 的实际 UUID/同 Session 消费 provenance 不复用、不预造，preview 仍不能消费。一次共同 Receipt/Audit/Outbox、无额外 commit、不推进 Link 的 Issue Current、不重复 reserve/consume。

自然经过旧执行窗口只改变 `checked_at/execution_window_elapsed` 展示，不能使已发生执行变成“不曾执行”。retained 稳定对比可继续排除这两个字段，但实际 Start/原期限/身份、所有来源/issuer/资源和样件消费 epoch 不可排除。当前办理资格与原期间证明仍分别核。

## 分批归属与测量点

建议先分两个小候选，不与当前 v2 验收合并：

| 候选 | 独占实施建议 | 验证重点 |
| --- | --- | --- |
| P1 原失败 basis 单阶段复用 | B `capa_verification/service.py, commands.py` 与其 owned tests；A/Root 提供只读 typed 初验结果+窄刷新接口，不改共同命令消费 | Link 的 8/10 次完整 bridge 减到本阶段首次完整核 + 各必要末端窄核；Current/语义/来源并集及回执/proof 原子性不变 |
| P2 owner 输出阅读瘦身 | Root `quality_followup_views.py`、B owner adapter；必要时 front 新只读投影，单独候选 | GET 有输出/Link 后只减掉确实不用的能力投影与重复原件；历史/当前专业适用如实显示，直接/paired missing 合同不变 |

retained 深层 proof 复用应最后考虑：没有覆盖可信 callback 内部状态的可重核 epoch 合同，就继续真实 evaluator；不能只凭 DB Product 锁推定宿主 issuer/profile 未变化。不同 Run、不同 Start 或不同 fixed basis 不共享肯定 proof。

Root 最小计时可覆盖：请求到达 API/UOW、Product/Grant 锁等待、完整 bridge、原件 gated IO、Projection 复算、retained `_load`、source_basis、professional/policy、owner `_reading`、最后 refresh。记录输入的 Failure/Measurement/capture/owner/Link 数、函数次数、DB 往返与总 wall time，日志不含凭据/原文。对同一固定候选比较 options0 GET、一个新 Draft option GET、Link inputs、preview、execute、同 key/跨 key replay；按实际路径报告，无默认“已提升若干倍”。

## 必须保留的回归断言

- 原件读取 hook 期间撤回其他 Failure 的 issuer；最后刷新阻断，0 新版/Link/Receipt，原 token 未消费或事务回滚。
- Principal/Grant ABA、专业或政策 issuer/runtime/profile 变化、OriginalSecurity/source epoch 变化、未来 valid_from 激活和核验中跨 expiry；不能命中旧肯定结论。
- 不同 ctx/tenant/project/private owner、Session、事务、SAVEPOINT 或 phase proof 拒绝；缺 callback 明确 503/能力 false。
- 旧精确意图重放先当前 gates，只返原 Receipt，无第二次 proof 消费/Receipt/Audit/Outbox；新不同意图仍完整 CAS/确认。
- Link 固定 basis/source/hash/owner 输出与 preview 确认一致；末端 Outbox 故障完整回滚，旧原件/Issue/Run 历史保留；正式占用/样件消费不会由读取重建。
- 新 Draft 只为真实计划输出，action_fulfilled/独立验证/有效性/关闭不因加速被提升；所有未知仍显式未知。

## 测试 setup 可共享什么

现有 `quality_followup_transactions.followup_work` 继承 `quality_work → results_work → launch_work → accepted_work`，每个函数 setup 有独立随机 tenant/product；不能为了速度直接改 module/session scope 共享 live Issue/Current、Grant、issuer registry、资源 occupancy 或 destructive sample usage。

可优先共享**纯不可变模板**：原文 bytes、schema 通过的 DTO 模板、BOM/方法/JSONL 生成算法；每个隔离租户仍用真实服务器入口绑定新身份并产生真实 Receipt/来源证明。跨租户不能复用业务行、source UUID、proof 或原作者授权。

在一个已经独立 setup 的测试函数内，可以共享实际保存的 Definition/BOM/双配置及已经真实 Plan/Promise/Start 的不可变祖先，随后用多个明确子场景/事务故障验证；子场景必须保持独立 command/key/确认，基线计数逐次重新取得，故障后完整回滚。需要撤回/ABA/消费/并发的用例仍独立祖先，不通过“恢复”不可变来源来重用已污染 setup。一个 Failure 的 stable Issue 去重不能通过换 title/event 造多份可互不干扰的 Issue。

夹具读取可在每个阶段取得一次 listing/current/plain deep-copy，供本阶段多个断言使用；不在每个 assertion 重新深读整链，也不把旧阶段读集当下一命令当前读集。必要列在活跃 Session 内复制，避免 detached ORM。真实 future Plan/Promise 与实际 Start 等待保留，不能 monkeypatch DB clock；长场景的合成期限必须在签核前明确配置，不后改已保存事实。避免上游每次额外加入无关新专业 series 拖慢 Start；results-only/followup-only 新事实的时间与 retained 规则须仍按真实合同核，不能任意移动。

## 只读底稿 SHA256

| 文件 | SHA256 |
| --- | --- |
| `quality_followup_views.py` | `2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3` |
| `domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| `domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `quality_result_bridge.py` | `28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077` |
| `domain/test_resources/retained.py` | `abf1c6d4599b3a5c13f113666b1971e85bfb173b5c27e1b34e1e17197517e0de` |
| `tests/quality_followup_transactions/fixtures.py` | `cae4abd15db6dcfd164e14ca6f858648405521145f620c2a47c6f16d028dd3a9` |
| `tests/verification_results/fixtures.py` | `62d5d0e61839b49ac833d7bb8fcb5cc509bccaec4697c065e16087019f8a3df7` |
| `tests/verification_launch/fixtures.py` | `10e5c57889064fd47be6044f80197eecb6c07f46079153e6e6dcb63eef81ff5f` |
| `http-current-read-recovery1.json` | `86db6b8b0f519a00dbb72bfbfd6132c563c6e2379bec353ef33aad44d5bfd110` |

底稿路径的代码/测试均位于 `pdos-next/server/`。上述是读取时的具体范围，不是 477 源码或当前 19PG 的独立验收。本报告不代表候选优化已经通过或生产真实资格已经获得。
