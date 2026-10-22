# Wave22 authority verifier v2 · actual digest 边界修复

本段仅修隔离暂存 verifier 和自有禁连接纯检查；没有执行 verifier、读取实际私有 checkpoint/profile、DB/HTTP、导入事实或更改现有业务源码。主线实际 v1 `IMPORTED_PROFESSIONAL_MATERIAL_MISMATCH` 与其 rawsafe 诊断保留；v2 实际运行仍由 Root。

## 已确定原因与精确修正

专业领域的 `trusted_import` / `_check_pointer` / `assess.facts_revision` 调用 `professional_authority.service.digest`，其真实来源为 `original_lifecycle.rules.digest`：完整 `_canonical` 将 aware datetime 固定为 UTC 六位微秒、JSON 默认 ensure_ascii=True。共同 `service.digest` 使用 ensure_ascii=False/default=str，不能用于重算专业 row 或 import_digest。v1 两处用错编码器；并非实际职责/资格失败，不需重新导入任何事实。

v2 `assert_publication_rows` 的 ProfessionalFact.fullhash 与 source_basis.import_digest 精确改为 **professional.digest**；QualityPolicyFact.fullhash 明确仍为 **policy.digest**。Receipt/request fingerprint 原真正 `professional_import` / `quality_policy_import` 都使用 common service.digest，本段保持其算法和完整字段。专业 assess.facts_revision 仅保留实际返回值作首末相等核对，未另用 common hash 重算。

比较入口使用实际严格 FactInput / PolicyInput.model_validate(...).model_dump(mode='json')，保留整份材料与实际默认 previous_id/expected_previous_revision、UTC Z 序列化，不按字段删摘要/删来源。frozen `authority.bound_payloads` 原已使用这些 DTO；此次边界规范化是增强，不冒充确定根因。

## 保持的真实门禁

13 个进口事实另加 native 来源的14个 exact Receipt/Audit/Outbox/original RequestKey、指针/fullscope/version/epoch、所有 source_refs/readset/原全文、当前三 caller ACL 与真实 opaque issuer、首末独立完整刷新、最早截止和实际 rollback-only driver/Session guard全部保持。仅 Outbox 合法投递字段沿原合同排除；没有截断材料或放宽安全判断。三个角色的55项实际专业评估及真实Policy仍 Root verifier执行，本段纯检查不是实际资格。

新39项自有 no-connect 纯检查包括原27项不变，以及实际 importer DTO+真实 transient ORM-shaped row 的 UTC/缺省字段、中文 ensure_ascii/aware datetime 编码差异、完整row/importdigest/source/approval/strict-bool错误拒绝。使用实际 digest函数；禁止 Engine.connect/raw_connection、psycopg.connect、httpx.Client.request。它们不证明实际保存组/ACL或 DB通过。

## 保留与交付

原v1源码/测试/合同/manifest字节另存 `readback-v1-snapshot/`，原readback-manifest-v1.json、全部原日志、Root实际失败报告和诊断均不覆写。新检查原始日志 `logs/readback-v2-*.log` 与result JSON、readback-manifest-v2.json单独存放。

Root只应用 verifier v2，复用原完整checkpoint、原Command/key/Receipt，不重导任何facts；实际读取报告用新 `--tag v2` exclusive创建。继续原 target62513 marker/source/profile/real Session UOW，不输出token/SQL/URL或私有正文。默认完整合同仍见 authority-readback-contract-v1.md；旧24表/6CAPA/private/core范围只可引用实际既有证据，不计为本段复验。
