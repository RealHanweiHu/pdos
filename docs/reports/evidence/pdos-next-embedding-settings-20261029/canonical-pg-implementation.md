# Canonical provider 三项实际 PG 负例候选

只新增一份测试文件；base HEAD `28bacbb7d8be01b50296004a66891ab9892d30f4`。本包依赖已冻结的 canonical provider delta。未修改 live、访问 DB/KMS/Keychain/网络、运行 PG 或构建；主代理统一执行。

复制 `manifest.json` 中唯一新文件到仓库同路径，再在已核对的独立 TEST_DATABASE_URL / checkpoint 环境运行该文件。测试沿用仓库 setup fixture 与原普通角色服务，不新建隔离环境。

三个场景：

1. 原 artifact register/index → 原 profile COMMON T1 preview/confirm/replay，核对返回 canonical provider 与实际 consumed Confirmation.snapshot、profile binding_digest；通过原 ProviderDataAgreement 管理 owner 具名登记“canonical别名仅准public”。真实 profile_saved Receipt/Outbox → Activities.plan 不创建 internal 批次，覆盖缺口计数保留、调用和索引占账均为零。
2. 原管理入口先登记准 public/internal 的 v1，真实确认 profile 并排出 queued batch，再具名追加只准 public 的 v2。连续执行同一真实批次两次均须报 P26 类别拒绝；synthetic provider 零调用、独立 Key 不得 resolve，原 queued/attempts 与预算完全不变、无新增调用行。这里拒绝发生在预留之前；不虚构“先占用再释放”，应无占用/费用泄漏。
3. 复用 `test_embedding_query_pg.actual_query`：真实模型行、完整 ReadBinding、ordinary-role KernelStore、原 wallet。通过原 native.ledger 的创建注入点，在任何 Run/模型行落库之前把 scope 与 run.data_categories 设为 internal；不修改已有业务或模型历史、不修改冻结 read 参数。实存 ReadBinding 经完整 DTO 解析，核对主图/工具/真实 model_call_id/response_index/身份/类别。对 canonical 别名登记只准 public，再执行原 AssistantReadAdapter.search 两次：query provider/Key resolve 均为零，无 query child 费用行、钱包无增量；返回来源与相同范围的原 keyword search 一致，semantic 明确 unavailable/query_egress_not_permitted，不冒充 RRF。

可信端口：仅复用原 SyntheticEmbedding 与 rate 卡，测试宿主明确返回和 endpoint hostname 不同的 canonical 别名；不改业务表上的 provider 或任何真实凭据。协议写入均经原 AgreementInput/register_agreement，来源/批次/绑定均用现有原生 owner/fixture。

本轮验证仅：`pytest --collect-only` 成功收集 3 项；源码导入成功；Ruff（显式仓库 pdos-next/ruff.toml，并为 staging 路径标注原 first-party imports）通过。日志见 collect.log、ruff.log。没有实际 PG 通过声明；任何实库夹具或语义失败应由主代理按真实结果修复，不把 collect 等同执行。
