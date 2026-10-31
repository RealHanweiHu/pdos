# Embedding canonical provider / P26 修复候选

这是独立 delta，依赖上级凭据 UI 包；未改 live、未访问 DB/真实 KMS/Keychain/网络，未构建，无 SQL/迁移。

实际证据：聊天 Gateway 经 Bootstrap.provider_for → TenantRuntime.provider_for，精确读取已登记连接的 canonical provider；connections.add 对已知端点保留该身份（例如 minimax）。P26 的 ProviderDataAgreement.provider 精确匹配该身份。Embedding 旧代码却直接使用 EmbeddingMetadata.provider 的 endpoint hostname，导致同端点独立连接价格核对失败；单独把 RateCard 标签改成 hostname 会绕过已登记别名协议。本候选不重标价格卡、不采用 hostname fallback。

按 manifest 复制 2 个新文件并审阅应用 13 个小 patch：

- 新 embedding_identity.canonical_provider 只能调用服务器可信 port.provider_for；启用、计划和执行缺失身份时 fail-close。停用 profile 仍可在 host/KMS 故障时完成。
- HostEmbeddingSecrets.provider_for 经与聊天相同的 TenantRuntime.provider_for，按当前 tenant × 显式 connection_id × protocol × endpoint × model × version 查 canonical identity；用户/模型不能传 provider 事实。
- Profile 启用价格核对与预览绑定 canonical provider，confirmation/binding digest 同时绑定身份；前端启用预览必须有合法 provider 并显示给管理员。
- 后台 plan 的 P26 分类过滤、batch 的当前 P26 与价格核对，以及 query 的两次 P26/价格核对均使用该身份。Query 发出前复核身份未变。
- 两个已有合成 port 夹具补确定性 provider_for；缺端口不静默转用聊天或 hostname。ModelMetadata 的 endpoint hostname property 只保留为明确的端点派生信息/合成夹具输入，不用于原生 P26。

验证：新 4 项 + 原 query/hybrid 63 项 = 67/67 纯后端通过；新凭据/原 profile 前端 23/23、隔离 TypeScript、精确 3 文件 ESLint、Ruff 和 13 patch apply-check 通过。日志均在本目录。Ruff 使用仓库显式 config，并仅为 staging 路径补 `lint.isort.known-first-party=["pdos_next","tests"]` 以维持原 import 分类；未借此删除规则或重排无关 import。

新负例使用内存 fakeKMS、真实 TenantRuntime/HostEmbeddingSecrets/RateCard/native policy.egress 和原 QueryEmbedding：已登记别名且协议只准 public 时，internal query 在 claim/embedding 前拒绝；同端点价格 card 保持原 canonical 标签；发送前身份变化拒绝且零 embedding；缺身份 fail-close，停用允许。

主代理仍须统一实际 PG/API：已登记 canonical 别名 + 限制数据类别下，分别核对 profile preview、后台 plan 不建受限批次、batch 执行拒绝及 query 零调用/正确回执；可沿已核隔离库和 fake provider，不启用真实服务。完整构建/浏览器确认摘要/明暗窄屏由主代理集中完成。历史 pending T1 预览的签名内容变化后须重预览，不把旧确认视为对新身份的授权。
