# G 六表完整目录与逐列分类

精确 PG 类型、nullable 与每列分类见 `lifecycle-columns.json`。下表完整列名由同一份 inventory 生成。

| 表 | 分类 | 全部列 |
|---|---|---|
| dingtalk_applications | CONTROL_CONFIGURATION | administrator_id, service_principal_id, revision, corp_id, client_id, robot_code, secret_arn, secret_version, active, id, tenant_id, created_at |
| dingtalk_binding_nonces | CONTROL_IDENTITY_NONCE | application_id, owner_id, app_revision, state_sha256, expires_at, consumed_at, id, tenant_id, created_at |
| dingtalk_account_bindings | CONTROL_ACCOUNT_AUDIT | application_id, owner_id, external_user_id, verified_nonce_id, active, epoch, verified_at, revoked_by, revoke_key, revoke_reason, id, tenant_id, created_at |
| dingtalk_messages | CONTROL_RUN_REFERENCE | application_id, binding_id, binding_epoch, owner_id, external_message_id, envelope_sha256, conversation_kind, conversation_id, run_id, state, error_code, lease_id, lease_until, workflow_id, id, tenant_id, created_at |
| dingtalk_share_consents | NAMED_EXTERNAL_DECISION_METADATA | message_id, owner_id, request_key, payload_sha256, include_citations, state, error_code, id, tenant_id, created_at |
| dingtalk_deliveries | CONSUMING_OUTBOUND_SNAPSHOT | message_id, owner_id, consent_id, request_key, phase, payload, payload_sha256, content_kind, source_dependencies, state, p26, provider_receipt, error_code, attempts, attempt_id, send_started_at, id, tenant_id, created_at |

五个控制表在 Delivery lifecycle 接线前后均为 NON_CONSUMING：不保存 question、answer、quote 或 source_proof 正文。Message 是原 Run/绑定的引用，不是聊天内容副本。ShareConsent 只存本人决定、固定 payload hash 等元数据；Delivery 才存实际发送正文。

**Delivery 前后始终是 CONSUMING_OUTBOUND_SNAPSHOT**。接线前缺保留闭包；接线后其真实固定 source_dependencies 按各 category 分组，通过唯一 F resolver 连向 source→Artifact→原件，并进入实际 m3 nodes/roots/clock/gate。其没有 category_id，不套通用 NEW.category_id trigger。

Delivery.source_dependencies 每项是服务器固定的 source_type/source_id/source_revision/content_hash/category_id，含真实 uncited 依据；不能由浏览器或模型建立授权。answer 必须有完整依赖，control/local_link 的空依赖不含业务事实。不能用 current 新版本补旧答案。

最终六表 owner 都是 trusted ordinary pdos_next_owner；FORCE RLS 保留。表 owner 自身有固有表权限，四列显式 GRANT 不是 owner 正文隔离证明。metadata-only 保证来自专用 nodes/gate/clock SQL 只取 id/tenant_id/content_kind/source_dependencies，不读取 payload 或 to_jsonb(row)。NOLOGIN maintenance 不拥有六表，只有限定 metadata 列/写状态权限，没有 Delivery.payload/业务正文 READ；runtime 无 role membership/SET ROLE。
