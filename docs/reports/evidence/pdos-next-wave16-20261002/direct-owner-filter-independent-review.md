# Wave16 直接 owner 回执首段过滤独立审阅

本文件仅为只读合同审阅：未修改运行源码/清单，未运行数据库、HTTP、pytest 或公共验证，未读取私有 seed。Root 新增过滤代码在本次阅读期间落盘，下文区分实际已读实现、建议和待主线实测。

## 失败事实与最小修复边界

Root 的 [http-current-read-initial.json](http-current-read-initial.json) 记录本机直连 GET 30.703 秒后返回 503 `INTEGRATION_REQUIRED`，消息是“固定输出缺少精确共同保存回执”。这次已有 API 业务响应，不能与先前环境代理 ReadTimeout 混为一条证据；本子任务未自行计时或请求服务。

[current-formal-owner-receipt-observation.json](current-formal-owner-receipt-observation.json) 记录一个当前 reported Formal v7 没有该版直接回执。源码解释相符：`verification_launch._record` 和 `verification_results._record` 可以在同一事务追加 Formal 版，但 Start/结果办理返回的共同 subject 是新 `test_run` 版行；Formal 的原子保存不等于它本身存在 `verification_request` 主回执。公共 `_option` 已先深读 owner，随后 `_receipt` 才发现没有直接主回执并抛 503。

**推荐且已看到 Root 实现的最小路径：**在 `quality_followup_integration.request_options` 的同范围 Current 行查询里加精确直接 Receipt `EXISTS`，先排除本宿主暂不能提供 owner 证明的行，再交既有 `_option` 深读和末端刷新。没有直接回执的当前行保持原状与可读历史；不退回旧 Formal v1，不伪造 Receipt，不以 paired Launch/Results fact 或 `test_run` 回执冒充直接 `verification_request` 回执。本轮不接 paired owner bridge。

## EXISTS 必须关联什么

当前已读实现关联以下字段，满足本次最小首筛要求：

| 关联 | 必要含义 |
| --- | --- |
| Formal → Current | tenant/product/logical request_id + 精确 `request_version_id=id`、`request_revision=revision`；继续同 Issue project、product/private owner 可读范围 |
| Receipt → Formal | tenant/product + `subject_type='verification_request'` + `subject_id=Formal.id` + `subject_revision=Formal.revision`；id 是不可变版行 UUID，不是 logical request_id |
| 操作 | `Receipt.operation == Formal.operation`；不能用别操作在同 subject 上的其他回执满足保存证明 |
| JSON result | `result.id` 是该版 UUID 文本，`result.revision` 是同值 JSON 整数；当前 `to_jsonb(Formal.revision)` 比较能排除字符串/错误版号 |

`append_receipt` 还固定保存 `result.status` 与 visibility。将 `result.status == Formal.status`、`Receipt.visibility == Formal.visibility` 纳入同一 EXISTS 是可选的低成本一致性加强；不能用 status 相等代替上表的身份/操作绑定。

首筛不拥有授权语义。既有 `_option/_receipt` 必须继续核实际保存人、writer/原运行归属和当前 source/ACL/private/professional/currentness。后续版本的 `authority_snapshot.subject_id` 是该次具名办理人，可能不同于系列 `owner_id`；不可新增 `Receipt.requester_id == Formal.owner_id` 的错误过滤。若先在 SQL 关联办理人，应与真实该版 authority 快照严格比较，且仍保留末端 owner 核验；本次小修不需要提前重做这个桥。

所谓直接 owner 回执不限于首次 `verification.request.create`：前段 `verification.method.prepare`、`verification.schedule.propose` 也实际返回 Formal 版，offer/accept/return 与 promise 中实际以 Formal 为共同 subject 的版本同理。过滤不应硬编码只选 create 操作或只选 draft 状态；应以 `receipt.operation == row.operation` 的实际保存语义为准。Start/Results 若只以 test_run 为主回执，则明确排除。

当前请求候选仍只返回有界最多 20 项；不能将空列表或这 20 项称作全部当前 Formal/全部已发生输出。被过滤的私人行身份、标题与数量不应通过 integration 描述泄露。

## 对新 Draft v1 T0 业务链的影响

既有 `verification.preparation.record` T1 保存真实准备，再以其固定 id/revision/sha256 调 `verification.request.create` T0。`verification_front._record/apply` 保存新的 Formal v1（draft、previous=null）、Current，并返回该 Formal ORM 行、subject_type=`verification_request`；共同 `append_receipt` 同事务保存对应 operation/id/revision/status。故新合法 Draft v1 自然满足首筛，不需要另建输出账或 paired owner bridge。

专业职责/资格、精确用途、当前 product writer、准备/Build/配置/来源及完整读集仍由现服务核对；首筛不会授予创建权。准备和正式请求各自的新逻辑 ID 保持明确。创建成功后刷新当前 Issue 页面可选择该**新 Formal 版行**，再由 `quality.capa.followup.link` 的 inputs/T1 保存固定 action→真实输出；不能用原失败请求代替独立新分支。

新请求仍为 planned 意义：空样件/acceptances，未 offer/accept/promise/start、未新增资源/样件消耗。回链存在也不证明措施已满足；`ACTION_FULFILLMENT_PORT_MISSING`、未完成措施与独立验证缺项仍保留，有效性/关闭 false。若新请求后来 Current 推进到一个仅有 test_run 主回执的 Formal 版，首筛不会把旧 draft v1 重新冒充当前候选；该输出需要未来明确的 paired owner 端口。

## integration.missing 与界面必须如实显示

Root 已读 delta 在 `ViewRuntime.missing` 配置 `PAIRED_FORMAL_OWNER_PROOF_NOT_CONFIGURED`，公开 `integration.missing` 返回该缺口：由开测/结果推进、主回执归属 test_run 的 Formal 版本当前不能选择；可以选择直接保存回执的当前新请求，不回退旧版本。这一固定宿主能力说明是恰当的，不应改成 `SOURCE_STALE` 或谎称没有任何历史请求。

候选为空时 LINK 既有 `NO_VERIFIED_OUTPUT_OPTIONS` 保持，LINK allowed=false；根因/本人完成按各自真实 capability 独立，不应因 paired 输出缺口一律失能。候选存在时也继续显示 paired bridge 缺口与 `CANDIDATE_PERSISTENCE_NOT_ENABLED`，不把本次过滤说成该端口已实现。默认无 callback、缺固定 CAPA basis、历史版只读分别保留原明确原因，不应由 `[]` 推断能力已完备。

**不要吞掉所有 owner 503/403 来加速。**只用这个可证的“没有精确直接主回执”条件提前排除。一个通过 EXISTS 的行若随后真实来源/ACL/issuer/current owner 不可核，既有深读取与末端刷新仍按其准确错误处理；不能用首筛结果缓存肯定资格或跨 phase 复用。

## 主线受影响核验建议（本审阅未运行）

最小首筛检查：同 scope Current 无主回执/只有 test_run 主回执应不进入；错 operation、错 result.id、字符串或错 revision 不进入；新 create Draft v1 正确主回执进入。Current 更新后不回退旧版，private/跨 project 不扩大，exact Receipt 存在但来源撤回或专业失效仍被后续真实核对阻断。实际新 Draft 创建及 T1 回链需读回共同 Receipt/Audit/Outbox、Current/原旧历史、零新测试消费，并保留可见 missing。

## 所读字节

| 文件 | SHA256 |
| --- | --- |
| `pdos-next/server/pdos_next/quality_followup_integration.py`（Root 首筛 delta） | `2c722d0fa94e02fd5d0e1d7ebeec1e52a782015457cb58e4ed5efbf3fce32e5f` |
| `pdos-next/server/pdos_next/quality_followup_views.py`（Root missing delta） | `2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3` |
| `pdos-next/server/pdos_next/domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `pdos-next/server/pdos_next/domain/verification_front/service.py` | `0ccc98a4f9b3127d47a45be11f949d0e23b776da7865856933c741bf90e4d2d0` |
| `pdos-next/server/pdos_next/domain/verification_launch/service.py` | `f2c4484ee8f55a1a64e73bf9a5ab1ae1f57655a67f54c685f9b59a1bbbde64bd` |
| `pdos-next/server/pdos_next/domain/verification_results/service.py` | `c0f4e4dc465868264167c77362ed831224856b923d073e06aae7c3979b27b8d0` |
| `pdos-next/server/pdos_next/service.py` | `8df806e61ad64cc6f87aa2cfea92114c9877e2ba3af7cfba347d729ccf663d84` |
| `http-current-read-initial.json` | `81d126491744bcfcc41e6946b3b3f3da83cc6e4bebfbbf637c942be558874ab9` |
| `current-formal-owner-receipt-observation.json` | `e9531f36769baa32e6cecbefb4723c08eadb0168f8563ea27611a9606af93bfe` |

源码静态关联足以支持首筛方案；不能把此审阅或 Root 原始失败记录当作新 delta 的真实通过证据。
