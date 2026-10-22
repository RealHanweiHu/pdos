# S4 有限例外决定、附条件发布与具名撤回

本轮在固定发布包上接通独立例外/豁免：本人核对实际政策、双配置、原检查、用途、范围、限制和风险控制后作 T2 决定；新发布包显式引用该例外时，仅在可豁免且完整覆盖所选范围的条件下得到 `READY_WITH_CONDITIONS`。原检查的 unknown/blocked 保留，不改成 satisfied。另一位具备当前对应专业授权的本人可以撤回，原批准不可变，撤回追加独立记录，系列 Current 从 epoch 1 到 2。

两个辅助操作为 `release.exception.decide` 和 `release.exception.withdraw`，均由共同预览/确认/命令路径执行。主体与受众继承实际固定包，模型不提供政策或权限事实；AI 不取得 T2 执行权。无强制第二审批人、无新增 T2 TTL；未另设期限保存为 null。撤回不要求原批准仍在期限内，也不要求旧包仍是最新版本。实际消费重验固定政策事实版本、当前例外、用途/配置/完整范围、来源与原签署依据，不以同名政策版本替代同一事实。

## 候选和验证

- 实际隔离目标为 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`。0783 前备份 68,764,028 字节，SHA-256 `cd6d0078f50ff16157736d115f24c1456d3d7524a17e05d8c197ab2c9726b19e`；本轮未删除库或覆盖历史备份。
- `s0_0784` [升级](migration-up-01.json)、[回退](migration-down-01.json)、[再升级](migration-reup-01.json)通过；[metadata](metadata-01.log)确认两表与 ORM 无差异、普通属主/FORCE RLS、Agent 无直接权限、应用无 DELETE。已有历史后的[预期拒绝降级](closeout-and-downgrade-refusal.json)通过，6 条决定和 3 个 Current 的逐行摘要及 head 均不变。
- [216 项后端纯检查](backend-pure-01.log)通过，其中发布 136 项、例外 80 项。另在 HEAD `2b6162c` 加精确归属 43 文件的独立拼装上[同数复核](standalone-pure-01.json)通过；不累加重复检查。覆盖不可豁免/未知保留、完整范围、政策事实绑定、撤回/过期、真实 owner 及消费守卫。
- [第一条实际 HTTP/PG 全链](actual-chain-01.json)通过：实际政策续版→固定包未知→例外 T2 尾部失败完整回滚→同一原提交保存/重放→引用例外续包→两专业具名批准→另一名本人撤回→旧批准保留、包需复核。此后[同领域代码的浏览器候选](actual-chain-browser-02.json)完整链通过，再以独立 v5 包办理实际页面 T2。
- [114 项不同前端检查](frontend-checks.json)通过（49 项 lib、65 项组件/BFF）；归属 lint 和类型检查通过。HEAD 加精确 8 文件的[独立生产构建](production-build-02.json)通过，其 SHA 与最终前端归属一致。
- [最终合同/静态核对](final-contract-static-03.json)通过归属 Python AST、Ruff 和实际离线导出一致性：98 个 payload；精确归属增至 46 文件。最后 api.py 仅两处导入换行，已按原 SHA 重建旧文本并确认 AST 完全相同，复用前述行为验证；其余原 42 文件与独立检查逐字一致。冻结 SQL 保持原样，仅该文件的 E501 长行不参与 Ruff。生成合同同时补齐 HEAD 已实现的 external 和 change-execution 旧导出欠账，未加入其他作者未交付接口；三条 release 目录说明已改为实际 owner 接线状态。

## 实际页面与恢复

实际页面核对固定包 v5、政策事实 v3、原 unknown 检查、空批次/产线的明确范围、限制/控制措施、无额外期限及本人身份后确认。服务器实际保存成功时丢弃首次响应，页面保留未知结果；刷新命令 POST 为 0，只有显式“重放并核对同一原提交”才重发完全相同 body/key/token，并返回同一决定/回执，未增重复行。

证据：[本人预览](browser-human-preview.log)、[响应丢失](browser-human-lost-response.log)、[刷新](browser-human-refresh.log)、[显式原请求重放](browser-human-replay.log)、[批准 API](browser-approved-api.json)、[批准 DOM](browser-approved-dom.log)。

随后切换已有另一名本人会话，以新登记的撤回原件核对原批准并确认，得到独立撤回记录；原批准、两项范围/风险控制及原 unknown 均保留。实际 API 读回本病例恰好 4 条历史（原 API 系列 2 条、浏览器系列 2 条）；最终实库断言核对两个新 T2 的共同确认消费、Receipt/Audit/Outbox 与私有请求键，旧行逐列未变。

证据：[另一名本人预览](browser-peer-preview.log)、[保存](browser-peer-saved.log)、[撤回 API](browser-withdrawn-api.json)、[320px 暗色宽度](browser-mobile-layout.log)、[撤回长图](browser-withdrawn-mobile-dark.png)。宽度 client/scroll 均为 320；长图仅在截图时隐藏悬浮导航，避免遮挡固定记录。专属浏览器/cookie、API 和 Next 预览已关闭，私有种子凭据已移除，数据库与备份保留。

## 已知失败与剩余范围

首次[构建失败](production-build-01.log)为 BFF unknown payload 的回调类型收窄，改为局部已收窄变量后 build-02 通过。初始纯检查对旧未接线错误及可例外 unknown 的预期已随实际语义修正；原文件未据此冒充新资格。首轮[静态失败](final-contract-static-01-failed.json)是两条新增导入格式和冻结 SQL 长行，修正/按文件排除后通过。既有 SQLAlchemy 环状 metadata 和 flush 弃用警告未在本轮扩展重构。

[全局合同校验失败](final-contract-static-02-failed.json)保留：HEAD 设计文档 SHA 为 `010d2ee46ad025122a9a9c0b80f2ba1625f4116f2f38eb70526b7808d3bc723a`，HEAD 三份 canonical 目录 provenance 仍为 `2820b72159622c2131774b9b0a0b548d63b44fa948af882aa795c26e231246f4`。本轮精确交付不包含其他作者正在修改的设计/P18/provenance，未宣称全局目录校验通过。两例外 T2、实际 payload/OpenAPI 与辅助登记另作确定性一致性核对。

本轮为合成资料的本地功能验证，无真实模型/KMS/外部发送、客户接收或生产操作；不授予真实政策权威或人员资格。S4 正式验收仍未完成，S1 未验收、性能按 P13 暂缓、S3 一天观察与评效保留；七个既有生命周期表缺口继续拒绝全局清理。下一步按依赖接续 S5 的行动任务→明确分派→本人承接/承诺→提交成果→独立接收验收→具名周报引用，保持真实模型与出站边界。
