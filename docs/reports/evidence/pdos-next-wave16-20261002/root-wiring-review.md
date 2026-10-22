# Wave16 公共接线定向审阅

日期：2026-10-03。性质：实施前、只读源码审阅；未应用公共补丁，未连接数据库、调用 HTTP、运行公共测试或构建，未读取私有配置与凭据。仅本文件由审阅者新增。原 A/B/host/bootstrap 与事务验收候选保持冻结。

**结论：所审两份新接线文件与十路径公共补丁未发现需要先修复的实质源码接线缺陷。** 当前可接受的是接口和静态时序；尚不能据此声称迁移、真实事务、API 或业务闭环已经通过。Root 仍须在应用后的同一候选验证实际 False→True 消费、末端回滚、RLS/不可变约束及历史重放。

## 核对结果

| 检查点 | 实际依据与结果 |
|---|---|
| 同一事务的实际消费 | 公共补丁在 `consume_material_confirmation` 完成固定载荷、读集、实质预览复核后，紧接 `confirmation.consumed = True` 调用 `record_consumed_confirmation`，中间只有模块导入，没有查询、flush、add 或 commit。该 host 已由 `configure_integration` 在应用创建期导入。host 方法本身只核已加载 Confirmation、SQLAlchemy history、Session/transaction 对象、载荷/令牌/实质/读集摘要并记录私有 marker，不执行 SQL。第一次后续 SQL/autoflush 可在 marker 已建立后发生。历史 consumed=True、脱离会话对象或另一事务不能构成本次证明。见 [host:170](../../../../pdos-next/server/pdos_next/quality_followup_host.py#L170)。 |
| 实际 proof 的使用 | `require_consumed_proof` 再核当前具名 human、同 Session/transaction/command/material/readset、实际锁定 Confirmation 与期限；返回实际 Confirmation UUID。A `apply` 把 T2 UUID 绑定 kernel Invocation.decision_id，并在末端追加前再取同一 proof。B link 通过专用包装只索取 T1 proof。共同服务去重/旧 Receipt 分支位于消费之前；重放不建立新 marker、不再消费。见 [host:246](../../../../pdos-next/server/pdos_next/quality_followup_host.py#L246)、[A apply:617](../../../../pdos-next/server/pdos_next/domain/quality_followup/service.py#L617)、[B apply:289](../../../../pdos-next/server/pdos_next/domain/capa_verification/commands.py#L289)。 |
| 分级、载荷、事件 | 补丁同时将 root cause 注册为 T2，complete/link 注册为 T1；PAYLOADS 分别为 `RootCausePayload`、`ActionsCompletePayload`、`FollowupLinkPayload`。根因仅 quality 职责；完成与 link 仍需独立当前专业 assessment，完成另核本人 executor 与实际事件。事件分别为 `issue.root_cause_decided`、`capa.actions_completed`、`capa.followup_linked`。根因使用 approval_token，完成/link 使用 confirmation_token。Issue 新版本仍由共同 writer/Receipt 保存；link 返回 `capa_remediation_link`，不推进 Issue Current。没有开放有效性/关闭或给 AI T2。 |
| 默认失能 | `configure_integration(..., synthetic_completion_profile=None)` 仅安装共同追加/实际消费断言及只读选项，CompletionAssessment 保持 None。A `_assessment` 对缺 callback 返回 `INTEGRATION_REQUIRED`/503；GET 的完成准备能力同时要求 callback 存在，且尚无候选时 `can_complete=false`、`completion_verified=null`。根因或 link 的其它真实权限、政策、来源守卫仍独立生效。见 [integration:55](../../../../pdos-next/server/pdos_next/quality_followup_integration.py#L55)、[A assessment:229](../../../../pdos-next/server/pdos_next/domain/quality_followup/service.py#L229)。 |
| 合成分类入口 | 只有显式 host profile 才调用 `configure_local_profile`。bootstrap 自核 test target，封闭 tenant/product/project/Issue/CAPA/action/executor/purpose/action SHA、synthetic/investigation、固定期限及 profile epoch；每 phase 核真实分类登记 Source 与整行 JSON/摘要/current ACL，保留独立 classification source basis。分类来源是另一份受控发布事实，不能替代 A 核的实际完成九字段事件；不能把普通完成文字、产品 Grant 或关键词提升为分类/正式变更实施证明。见 [bootstrap:309](../../../../pdos-next/server/pdos_next/quality_followup_bootstrap.py#L309)。未配置、未核对原件分类 transport 或 formal_change 仍明确失能。 |
| 单 Issue API/UOW | GET 必须提供一个 logical issue_id，revision 有界，未知/重复 query key 拒绝；POST 收完整 Command，只允许三项操作且路径 product 必须匹配。两个入口均沿当前认证依赖和 `tenant_session`，返回 jsonable_encoder；没有新提交端点、commit 或第二份确认/Receipt。现有 api.py:194 的 auth_dependency 确为 Depends(authenticated)，传入新 register_routes 的用法相容。见 [API:14](../../../../pdos-next/server/pdos_next/quality_followup_api.py#L14)。 |
| 当前与历史读取 | 公共 views 先核具名 consumer/current Issue 指针及其来源可读，再按精确指定版读取，前后复核指针/专业/政策/Runtime/完整 source basis。历史 basis 不被作为当前写入依据；history 写 caps 全 false，不枚举新候选来授予旧版能力。当前 action 只可开始候选事实核对，GET 不声称完成已核。未接候选持久化、独立验证、有效性与关闭均显式 false/缺项。见 [views:359](../../../../pdos-next/server/pdos_next/quality_followup_views.py#L359)。 |
| Request 选项范围和真实保存 | `request_options` 只选当前 Formal 指针准确指向的不可变版本行，同 tenant/product/project，并限定 product 可读或本人 private，确定排序、最多20个固定 OutputRef。此枚举不是权威证明；views `_option` 再经 B 的 owner 当前来源/范围读取，核真实共同保存 Receipt 的 subject/version、实际本次保存人、visibility、result、actor/requester/run provenance。Formal 系列 owner 与本版保存人不同时使用本版 authority_snapshot.subject_id；不是误用初始 owner。所有 option/link 来源合并仍须 MAX20，全部 owner IO 后再次复核。见 [integration:16](../../../../pdos-next/server/pdos_next/quality_followup_integration.py#L16)、[views:106](../../../../pdos-next/server/pdos_next/quality_followup_views.py#L106)、[views:153](../../../../pdos-next/server/pdos_next/quality_followup_views.py#L153)。 |
| 输出语义没有假阳性 | B `_reading` 保留固定版本、project、private、真实 ancestry/来源门禁与缺项。计划 Request 仅标 planned；仅链接它不创造 Run、实际实施、pass 或独立验证资格。候选输出可以是同项目的真实保存对象，适用性/目的/pair/观察条件仍交由后续明确 verifier 判断，不能把20条列表当作全范围已覆盖。见 [B reading:309](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py#L309)。 |
| 模型/导入/生命周期声明 | 公共 models 的新 import 在 Base/Row 及旧模型声明之后；B models 只引用已经声明的 Base/Row、SQLAlchemy，不导入 service/api/contracts。公共 contracts 的新增依赖仅 schema DTO，未形成新的 contracts→service 回环；API 在 create_app 执行时才安装 integration，shared service 已定义。十路径内存重建 AST 均可解析。catalog 仅新增 `capa_remediation_links`/`capa_verification_evidence` 的列集合及 GUARDED 分类，旧表列集合无改动/删除。实际迁移的触发器/RLS/权限仍待 Root 验证，静态 catalog 不替代数据库门栓。 |

## 检查方法与限制

逐段读取两份接线文件、公共补丁、既有共同预览/消费/execute 去重路径，以及冻结的 A、host、bootstrap、views、B owner/link 实现。用离线 Python 对统一补丁在内存重建：所有十路径上下文精确匹配当前文件，全部 `ast.parse` 通过；另用 AST literal 逐键比较 lifecycle catalog。没有执行 export、应用补丁或 import asgi/create_app，没有测试或 collection，也没有初始化 Engine/会话。

静态导入关系未见新增循环，但未执行应用启动；sameTxn 及并发/末端回滚正确性仍须 Root 在真实接线后运行已交事务候选。当前新增两表只是公共声明方案，未在本次审阅中验证迁移号、实际 head、触发器、Receipt FK 或应用数据库权限。上述待验范围不是已经通过的结论。

## 精确来源摘要

| 来源 | SHA-256 |
|---|---|
| `root-public-integration-proposal.patch`，十路径，未应用 | `e9047fb546da4bb029c8a5ff42e3e35fb2913bc7840c53b85b4f37ed7bddec1f` |
| `quality_followup_api.py` | `7beecc6c44b19dafbf1a3f29887af2eb9d9f835acfb68f69ea2fe7ecdbf2a502` |
| `quality_followup_integration.py` | `7aafcdd287143f43ba22fe46a85d6ab9163210ff2af9f153e940f3f2997cea35` |
| 冻结 `quality_followup_host.py` | `6b67f2d9d20bfbd48d869aa2028ba92d84e85660e7a27d3e4fc8c049035470de` |
| 冻结 `quality_followup_bootstrap.py` | `02cbc5c4f21000c597e3d4207f60744278ad2c0454d8e0148d5e6aee31ee403c` |
| 冻结 `quality_followup_views.py` | `c3f4fdcae8639fed3a4fe53d954df563f004c4802bf160d8695bbb2798e8196c` |
| 冻结 A `quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| 冻结 B `capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| 冻结 B `capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |

公共补丁十路径为 `command_handlers.py`、`contracts.py`、`service.py`、`domain/professional_authority/service.py`、`api.py`、`asgi.py`、`models.py`、`domain/quality_execution/models.py`、`lifecycle_catalog.py`、`tools/local_environment.py`。本审阅未改其中任何文件或已冻测试/资产。
