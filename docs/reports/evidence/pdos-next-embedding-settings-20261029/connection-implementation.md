# 独立 Embedding 凭据入口 · 待主代理集成

base HEAD：`28bacbb7d8be01b50296004a66891ab9892d30f4`。本包只写 staging；未改 live 源码、未访问 DB、真实 KMS/Keychain、提供器或网络，未构建。

## 实际能力结论

已有安全注册能力，不需要新建凭据数据库、迁移、COMMON 操作或 Host 核心：

- `model_configuration/connections.py:add` 以独立 request_id 创建 immutable ManagedConnection，API Key 只传给现有 KMS create，元数据原子写入既有 host 文件；不调用 `model.configuration.save`，不写活动聊天配置。
- `connections.py:readings` 只读公开连接元数据，不解密 Key；当前本人管理员通过原 `/v1/categories/{category_id}/model-connections` GET/POST 使用。
- `host.py:current_for` 精确检查 tenant × connection_id × protocol × endpoint × model × version，再返回 SecretBinding；`HostEmbeddingSecrets.current_embedding` 已走此入口，从不取 `current(tenant, protocol)` 聊天默认槽。
- 独立价格取同一显式连接的 rate card；缺失时拒绝，不回退聊天计量。

原 UI 的“添加服务商”可在不点“切换使用”时注册，但 Embedding 页缺少明确操作入口和公开连接选择。本包补齐这部分，不要求先切换聊天模型。

## 集成

按 `manifest.json` 复制 4 个新文件，审阅应用 `patches/embedding-settings-connection-hook.patch`。hook 仅向已集成的 EmbeddingProfileEditor 传 api、添加选择器，并在连接编辑时锁住 profile 表单，两个 form 为同级而非嵌套。

可操作路径：设置 → 小Pai与模型 → 模型配置 → 企业资料 Embedding → 新增独立连接 / 换 Key。

- 添加端点、模型/版本、独立 API Key，按需填写已核对的输入价格、每次请求费用及文本计费上界。原安全接口保存连接，不启用索引或切换聊天模型。
- 成功后只把公开 connection_id、base_url、model、model_version 带入 profile 表单，启用重置为关；用户填写维度、类别、预算后继续原 COMMON T1 预览和一次确认。
- 旧连接可明确选择，不自动选择聊天默认或无公开 ID 的 Host 默认项；选择前提示核对 /embeddings 支持，已有计量不冒充质量资格。
- 换 Key 使用新 immutable 连接，再由原 profile T1 追加版本；停止后台索引继续使用原 profile 停用流程。本包不删除/覆盖旧 Key，不新增破坏性 KMS 吊销操作。
- Key 仅存在密码框与同一组件内存请求。未知保存保留同一内存请求供本人核对；不放 URL、history、receipt、profile 预览或 localStorage。关闭后清空，刷新后可先只读查已保存列表。

## 验证

- 前端新 8 项 + 原 profile 15 项回归：23/23，通过 `frontend-tests.log`。
- 后端 3 项纯 Host/fakeKMS：通过 `backend-pure-tests.log`。真实使用 existing add/current_for/resolve/readings/pricing，证明独立 Key、第二份连接轮换、原请求幂等、租户/端点边界、活动聊天槽/models 不变、公开读取不解密、缺计量不回退。
- 精确隔离 TypeScript、4 文件 ESLint、Ruff（显式 `pdos-next/ruff.toml`）、hook `git apply --check` 通过。
- `check/` 只含候选与直接依赖拷贝、已有 node_modules 链接；不运行 Next typegen/build。新增测试自包含，不依赖 /tmp helper；后端使用 `python -B`、禁用 pytest cache，不开 DB。

主代理统一 PG/API 和浏览器实际操作/焦点/窄屏/亮暗、构建；本包不把纯测冒充真实服务启用。

## 单独发现的 provider canonical 缺陷（不混入本包）

现 Host 已登记聊天端点可能使用别名 provider（例如 minimax），connections.add 会保留该 canonical provider；当前 EmbeddingMetadata.provider 只取端点 hostname。这样同端点独立 Embedding 连接的 RateCard 与现有 embedding 校验不一致；直接换 RateCard 标签还会使 P26 对已登记 provider 的协议类别限制失配。因此 provider 修复单独产 delta 与 P26 负例，本包未改价格标签或出站守卫。该问题不影响独立连接注册与 UI 选择，但相关端点的真实启用须等 canonical 修复验证。
