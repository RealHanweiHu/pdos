# Wave16 合成调查分类宿主接口

仅实施新 `quality_followup_bootstrap.py` 与独立纯检查。未运行数据库、HTTP、公共验证；未接公共入口、未授真实专业资格，未证明实际完成、有效性或关闭。

## 显式配置

`configure_local_profile(engine, profile) -> assess_callback` 自行调用 `verify_test_target(engine)` 后，保存当前范围的有限不可变 entries 与单调宿主 epoch；只返回回调，由 Root 显式注入既有 Runtime。它不安装 Runtime、不改变专业资格或风险政策。默认 CompletionAssessment 仍为 None，缺接线按既有服务返回 INTEGRATION_REQUIRED。

profile 的唯一范围为 `tenant_id / product_id / project_id`，entries 为 1..100 项，每项精确绑定 `issue_id / capa_id / action_id / executor_id / purpose / action_sha256 / classification / nature / source / valid_until`。仅允许 `classification=investigation`、`nature=synthetic`；禁止同措施范围出现歧义 entry，禁止客户端额外授权字段。替换、撤回须旧闭包失效。`disable_local_profile(engine, *, tenant_id, product_id, project_id)` 撤回该范围并推进 epoch。

## 两份独立来源

分类出处必须是新受控事实，整行 JSON 恰有以下十二字段；额外字段、重复 JSON key、非有限常量、无时区/数字时间均拒绝：

```text
tenant_id, product_id, project_id,
issue_id, capa_id, action_id, executor_id,
purpose, action_sha256, classification, nature, valid_until
```

source 是核 DTO `ExactSource`，固定 `kind=artifact`、真实版本、`position=line:N;quote_sha256:<整行 UTF-8 SHA256>`。回调沿既有 `quality_execution.evidence.check_source` 核对当前 ACL、不可变内容摘要、状态及实际 `evidence.artifact.register` 回执的 actor/requester/run provenance。source 行须精确等于 profile 的全部绑定，valid_until 固定、不随调用续期；同一 UTC instant 的合法 offset 可比较，未观察到的时间不补值。

此切片支持已登记 native immutable text 分类出版来源。有 UploadedOriginal 的分类源先经过现有 source_for/current security/生命周期门禁，随后因缺专用真实字节核对入口明确 INTEGRATION_REQUIRED；不把派生文本当原件已核。分类源不能作为仪器原始测量报告。

实际完成另由冻结 A 包核 `CompletionFact` 九字段事件及真实来源。分类 publication 不包含发生时钟或完成文字，也不替代该事件。回调核对传入 observation 与固定 Issue/CAPA/措施/本人/用途/原完成文字/真实 occurred_at/IANA 时区；模型文本、普通完成行或产品 Grant 不能自行给出调查分类。formal_change 不开放，owner_proofs 为 []。

## Callback 与完整证明

```python
assess(s, ctx, product_id, basis, action, completion,
       *, policy_snapshot, observation, write=False)
    -> SyntheticCompletionAssessment
```

同一 Session/Engine、tenant/product/project、具名本人 actor=requester/run=None、synthetic basis 均须匹配。action_sha256 按固定措施（排除 completion）核对。来源读取前后独立核对，宿主 profile 身份、登记 source basis 与读集漂移均拒绝；固定期限取分类和当前合成政策期限的最早值，过去期限或未来完成事件拒绝。

返回 `SyntheticCompletionAssessment` 是宿主-only `CompletionAssessment` 子类，新增完整 `classification_source_basis`、`profile_epoch`、`profile_sha256`。`proof_sha256` 覆盖完整子类 JSON（仅排自身 proof 字段）。冻结 A 的 isinstance 路径保留子类，末端 `_refresh` 比较整个 assessment；禁止转换回 base DTO 丢失附加证明。各 validate/preview/apply/replay/final-refresh 阶段均独立调用，不跨阶段复用肯定结论，不创建 Receipt/Confirmation 或 commit。

## 当前证据与余项

32 项独立纯检查通过，含 target 自核、闭包范围、全字段证明、A 保留子类、source hash/ACL/登记、重复/额外 JSON key、原件缺接线、真实事件独立、固定期限、source/profile/登记 IO 期间漂移；Ruff、三文件 AST/compile 通过。原 A 九文件与 host 三文件冻结哈希保持。

Root 尚需显式配置真实已核对测试目标、创建受控 native 分类出版事实并注入回调；公共 consume/append、同事务 Receipt/Audit/Outbox、RLS/CAS/回滚、HTTP/浏览器由主线集中验证。纯测试中登记证明与 source reader 为明示 fake，不等于真实 PG 已通过或生产启用。
