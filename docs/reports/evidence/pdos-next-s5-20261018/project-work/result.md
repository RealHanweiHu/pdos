# S5 项目任务、分接收者承诺与成果验收

已接通人工项目工作闭环：从实际来源创建任务，明确受派人与成果接收人，受派人接受责任后分别向不同接收者承诺，记录实际开始，提交逐项成果，由指定接收者退回或验收，最后追加引用固定任务版本的具名项目状态更新。接受责任不产生日期承诺；未知承诺时间保持 null；部分、缺失和未知成果不能冒充完成。退回后保留原提交、逐项意见和全部办理历史。

实现遵循 [S5 接续合同](../../../../design/2026-10-18-pdos-next-s5-project-work-contract.md)。八项操作通过共同命令、T1 预览/一次确认、Receipt/Audit/Outbox 与原请求幂等办理；`work.task.create` 仍受既有 T0 规则约束，本轮实际页面使用人工身份，未接通小Pai任务技能或授予资格。任务与承诺采用不可变版本和 Current，具名状态更新只追加摘要、下一步和明确选择的任务版本，不修改计划、基线、预测、承诺或实际时间。

## 候选与验证

- 隔离目标为 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`。升级前 head `s0_0784` 的备份 `pre-s5-work-20261018-s0_0784.dump` 为 69,284,280 字节，SHA-256 `156e956de18e017e61ff3a15566c194085859727b5bb1e13d1dcda963fb4fd17`；数据库、原备份和历史保留。
- `s0_0785` 的 [升级](migration-up-01.json)、[回退](migration-down-01.json)、[再升级](migration-reup-01.json)均通过，共 133 条升级、38 条回退语句。[metadata/权限](metadata-01.log)核对五表与 ORM、普通属主/FORCE RLS、Agent 零直接权限、应用无 DELETE。出现业务历史后的[预期拒绝降级](closeout-and-downgrade-refusal.json)保留 head 与五表逐行摘要，无数据变化。
- 基线为 `03904d7`。[初始 candidate](candidate.json)是含共享工作区上下文的 34 项快照，不能作为最终交付范围。[独立精确候选](standalone-pure-01.json)从 HEAD 仅叠加本闭环 39 项归属，去除其他施工上下文；最终另加入两份实际生成合同，共 41 项。[最终清单与静态证据](final-contract-static-01.json)列出逐文件 SHA。
- 最终[后端纯检查 36 项](standalone-pure-01.log)通过；首轮 [35 项](backend-pure-01.log)是较早候选，不累加。覆盖状态转换、分接收者承诺、完整结果验收、来源/成员/实际 owner、确认消费和原子共同尾部。最后两处 Python 修改仅换行，AST 与已验候选一致；27 份 Python AST/Ruff 通过，冻结 SQL 文件仅排除 E501，不重写已安装 SQL。
- [前端 50 项不同检查](frontend-checks.json)通过：19 项 lib、31 项组件/BFF（8+23）；归属 lint 零警告。HEAD 加 8 项精确前端文件的[独立生产构建](production-build-02.json)含类型检查通过，源码 SHA 与最终交付一致。[首次构建失败](production-build-01.log)为受限网络无法取得 Google Fonts；相同源码恢复公共字体下载后通过，没有发送业务数据。
- 两条实际合成 HTTP/PG 全链通过：[首轮](actual-chain-01.json)及[精确交付候选与浏览器轮](actual-chain-browser-02.json)。后者继续实际页面操作并核对数据库，最终来源文件无变化。覆盖同一原提交恢复、旧版本拒绝、来源撤回/失权后旧预览拒绝与尾部失败回滚；不宣称整仓完整回归。
- [离线合同导出](contract-export-01.json)和[最终逐字核对](final-contract-static-01.json)通过，实际 payload 为 106 个，OpenAPI 与精确交付一致，数据库连接为 0。HEAD 设计/目录 provenance 既有失配仍保留，其他作者正在修改的设计及 provenance 未混入；未宣称全局 `validate_contracts` 通过。

## 实际页面、恢复与数据库结果

两名合成具名用户办理新任务 `869b8ac3-4fc8-4c22-b97e-98f2a8fd8220`：创建 v1→分派 v2→受派人承接 v3→实际开始 v4→部分成果提交 v5→指定接收人退回 v6→受派人完整重提 v7→接收人验收 v8。承接后页面明确没有承诺，随后对项目负责人和受派人自己分别创建两项独立承诺；第一项时间未知，第二项保存原始 `Asia/Shanghai` 时区和明确时点，不合并两位接收者。

分派首次保存实际成功后丢弃回传，页面保留未知结果；刷新命令 POST 为 0。显式恢复时重发同一 body/key/token，返回原回执且不增加任务版本。网络过程由实际浏览器操作记录证明，最终 API 快照只证明最终状态。

证据：[分派预览](browser-assignment-preview.log)、[回传丢失](browser-response-lost.log)、[刷新](browser-refresh.log)、[原请求重放](browser-original-replay.log)、[承接未承诺](browser-accepted-without-promise.log)、[两位接收者](browser-two-recipients.log)、[部分成果](browser-partial-preview.log)、[退回](browser-return-preview.log)、[完整重提](browser-complete-submission-preview.log)、[验收](browser-acceptance-preview.log)。

最后由项目负责人追加状态更新 `58d1efc9-8b91-40a4-9d4e-c3c3025983f2`，固定引用新任务 v8，未改任务、四时间或计划。[最终 API](browser-final-api.json)、[具名更新预览](browser-status-preview.log)及[数据库对账](browser-database-result.json)一致：新增 8 个任务事实、1 个 Current、2 个承诺事实及各自 Current、1 条具名更新。11 个新事实的实际办理人、共同回执、T1 消费和私有原请求键关联完整；原五表旧行及来源 Artifact 逐列不变。

[桌面完成图](browser-completed-desktop.png)、[退回图](browser-returned-desktop.png)及 [320px 暗色图](browser-completed-mobile-dark.png)已检查；[窄屏测量](browser-mobile-layout.log) client/scroll 均为 320。长图仅截图时隐藏悬浮导航及焦点跳转链接。专属浏览器/cookie、API、Next 预览已关闭，私有种子文件已移除，其他预览与历史资产未清理。

## 剩余范围

S5 正式验收未完成。下一步接跨品类个人工作分诊、本人未结承诺与项目三个摘要入口的具名更新读取，并为项目工作读取增加分页与批量共同证明；当前 workspace 返回完整历史，尚无分页。承诺接收者当前要求写成员，后续需按实际只读受众细化，不以本轮证明通用接收者政策已齐。非空日历引用在缺少实际 calendar owner 时明确拒绝；小Pai任务工具/技能、AutomationRule、知识沉淀、爬坡反馈等仍待建设。

本轮为合成资料的本地功能验证，无真实模型/KMS、客户资料外发、部署或 push。S1 保持未验收，P13 性能验收暂缓，S3 一天观察/有效性与各阶段正式出口保持未完成；七个既有生命周期表库存缺口仍阻止全局清理。
