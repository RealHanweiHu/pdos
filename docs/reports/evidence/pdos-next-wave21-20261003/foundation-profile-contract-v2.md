# Wave21 三类多范围 profile 原子恢复 v2

此版仅变更隔离暂存的三 bootstrap 与三新纯测试；正式三源码/三个测试目标未由本段写入。函数、list 字段、有限 ledger、synthetic 与 single/plural 行为沿 [v1 合同](foundation-profile-contract.md)，API single/plural 互斥及最终应用由主线负责。

`configure_local_profiles(engine, profiles)` 先完整校验明确非空 list≤20 与所有材料，再核 test marker，最后发布有限名单。三类现有 registry/epoch/metadata 必须为真实 dict；epoch 值必须为非 bool 正整数。复用项必须是 exact `{canonical, issuer}` 可信 metadata、canonical 全材料相同、registry 原 issuer identity 相同、opaque issuer 的正整数 epoch 与实际 epoch map 相同、exact scope/key/version/nature 一致。epoch 单独残留也属于已有注册，不借缺失 metadata 静默复活。同名无关 scope、损坏、撤回、替换或材料变化一律发布前拒绝；不替换旧配置。

全部注册前保留该 family 的 registry、epoch、bootstrap metadata 三属性及其原缺失状态、原字典内容和 metadata row 内容。任何后续真实 factory 异常（包括已发布新 issuer 后异常）均恢复这三属性的原对象及内容；原本不存在的属性删除恢复为不存在。旧 opaque issuer、有限 decision callback、epoch 及 metadata row 的对象 identity 保持。捕获 BaseException 后恢复再原样抛出；不吞错、不留下早项注册，不执行 DB 事务、consume、commit 或 Session 缓存。此是受控启动配置过程的批次恢复，不提供并发运行时配置更新接口。既有 single 显式重配置保留原 epoch 推进语义。

实际实现属性：

| family | registry | epochs | bootstrap metadata |
|---|---|---|---|
| operational | `_pdos_operational_issuers` | `_pdos_operational_issuer_epochs` | `_pdos_operational_bootstrap_profiles` |
| test_resource | `_pdos_test_resource_issuers` | `_pdos_test_resource_issuer_epochs` | `_pdos_test_resource_bootstrap_profiles` |
| quality | `_pdos_quality_policy_issuers` | `_pdos_quality_policy_epochs` | `_pdos_quality_bootstrap_profiles` |

## 限定检查与证据

v2 最终 86 项 owned pure 通过（0.90s），三新测试明确用真实 domain factory/opaque issuer：第二项已经真实注册后注入抛错，验证旧 registry/epoch/metadata 字典及 row identity、旧 issuer/callback 可继续准确使用；另覆盖所有属性原不存在时无残留、reuse epoch 漂移/True、metadata/registry 形状与 epoch-only tombstone。marker/engine 为明确无连接替身，不能据此声称真实 test target、来源、专业资格或生产启用。

六文件 Ruff、format check、冷导入及 in-memory AST 退出 0；检查期间六文件 SHA 稳定。正式 owned 三源码逐项等于原 baseline，三个新测试正式目标仍不存在；暂存包只有三个 owned package 文件变化。完整 310 项 runtime 不再声称稳定：api、asgi、capa_rule_publisher、professional_authority/service、quality_followup_integration 五路径变化经 Root 确认为授权 B/C/Root 接线，见主线 applied-owned-source-v1.json。没有 DB/HTTP/browser、公共测试、应用启动或 build。

[v1 manifest](foundation-profiles-manifest-v1.json)、67 项原日志全部保留；六个 v1 exact 字节副本另存暂存 `v1-frozen/`，SHA 对照原 manifest 验证。v2 首 lint 仅长行失败原日志、83 项中间通过日志也保留；最终 86 仅绑定 v2 最终六文件，不将旧/中间结果累计。主线须按 [v2 manifest](foundation-profiles-manifest-v2.json) 核三个 target 基线后只应用准确六文件，不整包覆盖。
