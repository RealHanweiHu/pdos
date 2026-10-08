# Wave16 单 Issue GET 只读重复路径审阅

本文件是冻结候选运行期间的静态审阅，未实施优化，未运行数据库、HTTP、pytest、公共构建或性能计时，未读取私有演练凭据。只读取下表源码并新增此文件；当前后端、测试与清单保持不变。

## 结论与实测边界

代码中存在可确认的重复完整读取，尤其是有 CAPA 输出候选或已保存回链时，公共读取会在 owner I/O 后再次执行完整 Issue 阅读。可以考虑把第二次完整原报告读取改成已有的窄证明刷新，并继续独立核对当前来源、ACL、指针、风险政策、专业事实及 issuer/runtime 摘要。

**这不是本次接近 180 秒超时的根因结论。** Root 随后报告临时 HTTP Client 经过 `httpcore/_sync/http_proxy.py`，API 没有该 GET 日志、进程 CPU 为 0；该请求须以本机直连重新测量。此线索来自 Root，本审阅未独立取得网络或进程证据，不能把代理失败作为服务执行耗时，也不能据此修改冻结候选。

## 可证的重复路径

| 路径 | 当前实际调用 | 适用条件与边界 |
| --- | --- | --- |
| 公共单 Issue GET | [`quality_followup_views.py:359`](../../../../pdos-next/server/pdos_next/quality_followup_views.py) 先调用 A `list_quality_followup`；所有 owner I/O 后再次调用 A `_read_row`，再分别刷新 LINK 与根因/完成的专业事实及政策 | 第二次 `_read_row` 只在 `readings or link_proofs` 为真时执行。无 CAPA/无输出/无有效回链时不能按此推算重复量。历史版仍保持写能力 false。 |
| A 当前 Issue 阅读 | [`quality_followup/service.py:732`](../../../../pdos-next/server/pdos_next/domain/quality_followup/service.py) 对每个原 Failure 调 `_result`；政策/两项专业能力读取后，对每个结果调用 Root 窄 refresh；再独立刷新来源、政策和两项专业事实 | 首次完整原件验证与末端刷新具有不同安全作用，不应直接删除后者。A `_exact_basis` 使用已核结果与 B 纯 `basis_from_issue`，这里已经避免了第二次完整 Failure 读取。 |
| 原 Failure 完整桥 | [`quality_result_bridge.py:117`](../../../../pdos-next/server/pdos_next/quality_result_bridge.py) 每次验证精确 Run/Projection、重算该 Run 全部判定、遍历全部 Measurement、读取原报告，并在字节读取前后各核一次 retained execution | `captured_reports` 已在这一次桥调用内按 capture 去重；同一 Run 的另一 Failure 仍会重新走整个桥。不能以 Measurement ID 相近代替精确 Run/version/basis。 |
| 输出候选 | [`quality_followup_views.py:153`](../../../../pdos-next/server/pdos_next/quality_followup_views.py) `_option` 调 B `_reading` 与精确保存 Receipt；公共 GET 末端再次逐项 `_option` | 最多 20 项，第二遍当前 owner 证明是必要安全边界；可以优化 owner 的读取投影，但不能凭已有 Receipt 宣称当前来源或执行仍有效。 |
| 已保存回链 | [`capa_verification/service.py:608`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py) `_link` 先 `recheck_followup_basis`，其 `resolve_followup_outputs` 又在 owner I/O 前后各 recheck；公共 GET 对成功回链再调用一次 `_link` | 在相同当前 Issue basis 的成功路径，每个 Link 两轮合计至少 6 次 exact basis 加载；每次加载又逐 Failure 走完整结果桥。旧 basis 与新 Current 不同时还须验证当前语义，不能用新版本号替换旧依据。 |
| FormalRequest 输出读取 | B [`service.py:309`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py) `_reading` 经 `_owner` 调 [`verification_front/service.py:1098`](../../../../pdos-next/server/pdos_next/domain/verification_front/service.py) `get_request`；后者读取准备及 `_view` 的专业适用/窗口/三项前段 authority | B 固定输出 snapshot 丢弃 `capabilities`/`authority`，但之前已经执行其计算。其来源、方法现有效性、私有范围、父链仍是必要真实阅读，不可一并删除。 |
| 原文选项 | A [`service.py:705`](../../../../pdos-next/server/pdos_next/domain/quality_followup/service.py) `_source_options` 对每个精确引用重新 `source_for`/拆行；同一版原文的不同 position 会重复读取 | 当前函数是每引用一次 `source_for`，不是三次。它之外的完整 `source_basis` 初验与末端核验仍要保留。 |

仅按显式函数入口计数：一轮成功 A `_read_row` 对每个 Failure 包含完整桥内 2 次 retained 入口和 A 窄刷新内 1 次入口；公共条件性第二轮使这部分达到 6 次。此数字不是 SQL 数、实际 I/O 数或耗时。多个回链/输出还会增加独立 owner 路径，不能把这些路径简单视为同一证明缓存。

## 最小安全优化建议（待授权及实测，不改本候选）

1. **先替换公共第二轮完整 Issue 阅读，而非缓存授权。** 增加仅本次 GET 内可用的私有 `ReadRowProof`：绑定同一 Session 与 transaction、tenant/product/actor/requester、Issue 版行 ID/revision/snapshot SHA、首次真实 byte-verified `FixedQualityResult`、完整读集/source basis、政策/专业 snapshot、runtime 身份。首次读取同时返回 view 与此 proof。所有输出/回链 I/O 后，逐结果调用已经存在的 [`recheck_fixed_failure_result:262`](../../../../pdos-next/server/pdos_next/quality_result_bridge.py)，重新核 Issue 当前指针、scope/private、完整来源、政策、专业事实、具名人/Grant 到期与 runtime/issuer 摘要；再比较实质 DTO。窄 callback 缺失须明确阻断，不能退为旧布尔。首次 A 的内部末端刷新暂保留，这样只移除公共第二遍原报告/Projection 重算，避免同时重构多层安全时序。

2. **原文展示可复用一次已核材料，末端仍新读。** 在同一 fresh read pass 内按 `(artifact_id, revision)` 取得完整原文，逐 position 保留真实行号/全文行 hash 核对；标题与片段从这份材料生成。不要把 ORM identity map 当当前 ACL/security/provenance 证明，也不要删掉最后完整来源刷新。这属于局部展示重复减少，不足以证明主要耗时改善。

3. **B owner/link 读取单独作为后续优化。** 可以新增窄 owner 读取 DTO，省去输出 snapshot 从未使用的前段操作能力计算；仍须核真实保存 Receipt、精确版本、父链、原件/来源、安全 epoch、当前专业适用及执行消费证明。已有 Link 绑定完整固定 snapshot，不能静默改摘要语义。B 当前前后 basis recheck 的重复完整桥，可在同一个未发布 read phase 以真实初验值加最后窄 refresh 替代，仍要覆盖后一个 owner I/O 撤销前一个证明。此项跨 A/B 接口，范围大于建议 1，应在 profile 明确收益后独立处理。

4. **同 Run 多 Failure 的批读取不是本轮小补丁。** Root 可将完整桥扩为 exact Run/version/event + measurement IDs 的批接口，一次验证全部原件/判定后返回逐 Failure typed proof，末端仍逐一刷新。不能跨 Run、事件、basis 合并，更不能跨请求或命令 phase 缓存肯定证明。

以上均禁止 Engine/global/Session.info 肯定缓存，禁止跨 GET、事务、validate→preview→apply 或 replay 复用。临界期限、Principal/Grant 停用、来源撤回/ABA、专业或策略 issuer/profile 变化仍须最终重新核。GET 的 `can_prepare_completion` 仍只表示可开始提交候选核对；`can_complete=false`、`completion_verified=null` 不变。

## Root 后续直连测量建议

先确认请求确实到达 API，再区分 Product 锁等待、DB 往返、原件 I/O、判定复算。可定向记录 A `_read_row`、完整桥与窄 refresh、候选 `_option`、Link 的 basis/owner 阅读、来源/专业刷新各调用次数与耗时。只报告实际所选 Issue/CAPA/候选/回链数量；不要由 20 项上限推测实际负载。未经测量不能声称上述优化已解决延迟。

## 读取范围与 SHA256

| 文件 | SHA256 |
| --- | --- |
| `pdos-next/server/pdos_next/quality_followup_views.py` | `c3f4fdcae8639fed3a4fe53d954df563f004c4802bf160d8695bbb2798e8196c` |
| `pdos-next/server/pdos_next/domain/quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| `pdos-next/server/pdos_next/domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `pdos-next/server/pdos_next/quality_result_bridge.py` | `28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077` |
| `pdos-next/server/pdos_next/domain/quality_execution/evidence.py` | `f9b128b0cff62607415d16824bd6a8c1a7e9b30c397b1252991f1ec76bd98903` |
| `pdos-next/server/pdos_next/domain/verification_front/service.py` | `0ccc98a4f9b3127d47a45be11f949d0e23b776da7865856933c741bf90e4d2d0` |

仅通过文本阅读与标准库文件 SHA 核对；没有执行业务模块。实际 `0024_quality_followup.py` 中 Root 的 CASE 语法恢复亦只读确认：`event_effect IS DISTINCT FROM (CASE … END)` 已括号化，没有再次发现 `IS DISTINCT FROM CASE` 模式；本审阅未编译 PL/pgSQL，原提案与前次独立审阅未修改。当前迁移源码 SHA 为 `a957c6dbc22647f2f5dbb39fc014bb4b7ef269b014d9497642110cc4664df252`。
