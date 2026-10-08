# 租户模型配置：主线接入合同

本包位于独占目录，未修改公共模型、命令、API、runtime、迁移、BFF、父页面、唯一清单或依赖。本合同描述必要接线，不代表已完成接线或批准真实调用。

## 可调用服务与 DTO

- `schemas/model_configuration/dto.py`：`ModelMetadata`、`SaveConfiguration`、`SavePreview`、`ConfigurationReading` 均 extra=forbid/frozen/strict。公共输入只有 expected_revision、metadata、enabled，默认 enabled=false。不接收 tenant/actor/run/grant/资格/出站/密钥/secret reference。
- `service.parse_save_payload(raw)`：共同命令入口使用的安全验证器；错误仅返回固定领域错误，禁止记录 raw 或 Pydantic errors() 的 input。不要将框架默认校验错误中带 input 的信息直接返回/记录。
- `ConfigurationService.plan(server_context, payload, now=server_now)`：核对当前 human admin、同租户 head、版本及服务端 secret slot；产生 immutable SavePlan。不写库或消费确认。`plan.preview()` 是允许进入共同预览 snapshot 的公共 DTO。
- `ConfigurationService.restore_reviewed_plan(context, payload, reviewed, now=server_now)`：**共同确认守卫通过后**，从其已持久化的公共 SavePreview 重建计划。版本 ID 按租户/前版摘要/请求/secret-binding摘要确定；到期取原预览；当前身份、配置和 secret 重新核对。客户端自行提供的 reviewed 不构成授权。该辅助方法不签发确认或回执。
- `apply_plan(context, plan, now=server_now)`：共同事务中再查管理员、租户/actor/前版摘要、过期与 secret 漂移，然后 CAS append；返回领域版本对象，不代表事务已提交。主线不得公开序列化 SavePlan/ConfigurationVersion/SecretBinding。
- `reading(context)`：管理员 masked 读模型，仅公共元数据、配置版本、密钥掩码状态；不解析密钥。不存在配置返回 None；secret 接口错误显示 unavailable。

初版每租户一个当前模型配置槽，显式选择 OpenAI-compatible 或 Anthropic-native；无 arbitrary fallback。model_version 是公共模型元数据；provider_version 是配置/secret 全绑定版本。每次保存（含启停）增加 revision，所有变更均需重新核对资格。

## 共同命令与事务

建议待注册操作名 `tenant.model_configuration.revise`，subject 为租户模型配置 head，expected_revision 映射 payload。**该动作尚未注册；本包没有给它分配 canonical T0/T1/T2，也未改变现有政策。** 主线须完成明确操作目录/权限/分级映射；初版仅当前具名 human admin 能走受控命令，一次预览与确认沿已有入口，AI 不能借管理员 port 取得操作权。

共同预览 snapshot 仅存 `SavePreview.model_dump(mode="json")`，包含摘要、元数据、下一版编号、掩码状态、expires_at；不存 secret reference/version 或 raw key。确认时从公共框架已经锁定的 Confirmation.snapshot 读取 reviewed，按既有 token/payload/read-set/subject/actor/expiry 守卫消费一次。既有幂等和稳定意图先行：重复提交须返回原真实 Receipt，不能再次 append；同 key 不同 payload 拒绝；跨 key 同意图复用共同框架。

同一 Session/事务完成：管理员与 head 当前性锁定 → 原 confirmation 守卫与持久 snapshot → restore_reviewed_plan → apply_plan → ActionReceipt/Audit/Outbox → 原 confirmation 消费 → commit。任何失败由调用者整体 rollback。领域返回 id/revision/provider_version 后，实际成功 UI 只依据共同框架提交后的真实 Receipt，并刷新 masked reading。不能把领域函数返回值当成功回执。

若预览与确认跨请求，不能重新用当前时间生成预览并冒充原摘要。restore_reviewed_plan 使用原公共预览到期时间重建确定版本，secret version 或 metadata/enabled 任一变化都会拒绝旧预览。两个并发计划的同版写入由 head FOR UPDATE/CAS 串行；落败者 rollback，不留下 Receipt/Outbox 或部分确认。

## 持久对象与公共迁移/RLS需求

`model_configuration/persistence.py` 仅声明映射（继承只读公共 Base/Row）和调用者 Session store，未注册、未连接数据库。

| 表 | 关键列/约束 | 主线责任 |
|---|---|---|
| model_configuration_heads | tenant_id PK、revision>=0 | 为每个租户预置 revision=0 行；首次保存也需真实锁行；不要临时 lazy insert 形成并发空洞 |
| model_configuration_versions | id、tenant_id、revision、public_metadata JSONB、enabled、created_by、created_at、secret_reference/version/available、binding_digest | tenant/revision 与 tenant/id 唯一；同租户 human principal FK；secret 三字段同时空或同时非空 |

主线按真实 migration head 新建迁移并导入本包映射做 schema 相容检查。两个表使用 tenant RLS；普通应用身份不能绕租户；`pdos_agent` 对两表零直接写。head 的更新和 version insert 仅受控领域服务；version 禁 UPDATE/DELETE（数据库权限/触发器），原版本保留。secret_reference/version 只允许服务端管理身份读取，不进入通用 ORM JSON 读模型/事件/审计 payload；审计写公开 digest/id/revision 与实际操作者，不写密钥材料。后端 restore/check 需要服务器从已锁定数据构建对象，禁止把客户端字典构造成 ConfigurationVersion。

SessionConfigurationStore 使用 caller Session、tenant-filtered 查询和 populate_existing，append 锁 head、检查 expected_revision、INSERT 新 version、推进 head、flush；不 create_all、commit、rollback。flush 不是提交。本包纯 fake Session 检查不能证明真实 PG 并发、RLS 或 DB 不可变性。

## SecretPort 与授权事实

`ManagementContext` 和 `RuntimeQuery` 只由服务器会话/Run 构建。AdministratorPort 必须从当前会话、human principal、租户管理员政策取事实，不能信任 canEdit 或 request actor。管理员权限不等于业务材料出站许可。

SecretPort.current(tenant_id, protocol) 查同租户明确 protocol 的服务端受控槽；引用和版本均为不透明 UUID。SecretPort.resolve(binding) 只返回该 reference/version 的 SecretMaterial，禁止 env 自动回退、跨协议、跨租户或备用模型。真实 key 仅在 SecretStr 字段中由服务端注入现有 ProviderRoute，所有 repr、公共读模型、摘要和日志排除原 key。轮换/替换/撤销后重新启用须发新 immutable secret version；旧版本不能悄悄映射新 key。端口异常统一脱敏。

保存配置与 Runtime 选择均不调用模型或签发出站授权。真实 secret manager 尚未接入；无 port 不可升级。配置与 secret 当前性、管理员撤销必须由主线在提交处保持：建议 secret-binding 元数据和 admin 政策 epoch 落同库锁/版本检查，或 port 提供等价线性化守卫；跨外部 secret manager 的读检查不能自行宣称原子。网络密钥读取不可放在等待中的长领域事务，应缓存受控版本材料并在事务核对可线性化绑定元数据。

RuntimePolicyPort.current_facts(query, binding_digest) 必须依据当前服务器事实返回：同租户/Run/writer 的使用权限、**真实**独立 golden-case 资格、当前材料出站授权、持久预算可用性、取消真值及短到期。qualified 必须绑定 operation/purpose/skill_version/tool_version/model_version/provider_version 与具体场景；现有 Qualification 表仅含 skill/provider/operation/purpose，tool/scenario 的注册/关联守卫由主线补齐，不得凭单个旧 Qualification 行绕过本合同。当前 cancel_epoch 与 Run 不一致必须拒绝，不能只信任捕获的 query.cancel_epoch。

所有 facts 的 query 和 binding_digest 必须精确相同；None/非 bool、过期、错误、接口缺失均拒绝。无事实不能用 false=默认通过；预算读取不替代实际预算 reserve。

## 现有网关接线

```python
# 所有 context/query/ports/authorize 都来自服务器，禁止客户端构造。
selection = runtime_configuration.select(query, now=server_now)
if selection.state != "authorizer_check":
    # 只公开 state/code。Selection 是服务端对象，含 route/credential，不能 asdict/json。
    show_unavailable(selection.code)
else:
    gateway = ClaimGateway(
        writer_id=query.writer_id,
        route=selection.route,
        authorize=existing_authorizer,  # 唯一真实 CallPermit 签发器
        require_current=runtime_configuration.currentness(
            selection, query, now=server_clock,
            require_permit_current=existing_current_permit_guard,
        ),
        budget=existing_durable_budget,
    )
```

currentness 复合主线原许可守卫，并核对 writer/route/provider/purpose/egress/protocol/expiry、当前租户 config/secret、权限/资格/预算/取消。若主线当前许可守卫未接入则拒绝；检查后再次取服务器时间，防止慢守卫后继续使用过期许可。现有 ClaimGateway 保持请求摘要、持久 reserve/settle/unknown、网络前后 currentness 和领域写资格守卫；不得因为本包 selection 状态是 authorizer_check 就签发 Permit 或授予 T0。现有 CallPermit 无 tenant/run 字段，主线原 current_permit_guard 必须持久核对 call_id 的真实 Run/tenant/material 意图；本包闭包捕获 query 不替代那项关联。

Runtime 未配置/停用/secret 缺失与变化/缺权限或资格或出站或预算/取消/过期/接口缺失各有稳定错误码；只有全部基础事实齐全返回 MODEL_AUTHORIZER_CHECK_REQUIRED。公开读模型仅 `{"state": selection.state, "code": selection.code}`，不返回 route、configuration 或 SecretMaterial。

## 设置组件

`web/src/components/model_configuration/ModelConfigurationSettings`：读取 ConfigurationReading、canEdit、readiness、pending 和 onPreview(request)。onPreview 由父层对接原共同预览框架；该组件没有 confirm/save/Receipt 消费。服务器再次验证 canEdit/tenant 真值；无回调或非管理员禁用表单；异常只显示固定安全文字；props revision/version_id 变化重置编辑器。双协议、输出参数/限额、启停可编辑；无密钥输入框、无 fixture 注入、无默认有效端点。

主线父层负责一次确认、回查未知提交结果、原命令幂等 key 与真实 Receipt、刷新 masked reading；不要在 callback 中增加第二次确认消费。组件渲染检查并不覆盖浏览器交互/响应式/主题验收。

## 主线集中验证的异常病例

1. PG 并发初次保存与同版不同计划，失败方不留下新版本/Receipt/Audit/Outbox/消费的确认。
2. RLS 跨租户 current/history、非 human admin、会话过期/管理员撤销、AI 直接 SQL 拒绝。
3. 确认后配置/secret/meta/启停漂移；原 preview 到期、payload 注入、重复回查/幂等与敏感错误输出。
4. 无 secret manager、缺字段/政策端口、真实资格或用途/工具版本不符、当前材料无出站许可、预算耗尽、取消 epoch 变化，零 provider 请求。
5. 真实 manager 轮换与配置版本变化，在 reserve 前/后及网络后失效；拒绝 old binding，不自动 fallback；结果未知沿原 call_id 对账。
6. DB 权限/迁移往返、真实页面预览与一次确认/失败刷新、主题/尺寸及键盘检查；符合授权后才运行真实 golden-case。没有真实材料许可与当前 CallPermit 时不得调用真实模型。
