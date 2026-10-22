# 第十三波：明确接收范围到实际开测

本轮闭环已完成本地合成实现与验证。沿用第十二波的样件、实际配置、品质部分接收及同一正式请求版本链，新增固定 Run 计划、具名承诺和同事务实际开测。真实测试资格、生产启用及人工 Exit 保持未完成。

## 可用闭环与复用

| 动作 | 保存结果 | 资源与样件效果 |
|---|---|---|
| `test.run.plan` | 固定完整已接收 sample/item 范围、实际配置/方法、执行者、设备/校准依据、环境条件及完整窗口；Run planned | 零占用、零消费 |
| `verification.schedule.promise` | 同 Run/计划摘要的具名承诺；正式请求 scheduled | 零占用，承诺与实际开始分别保存 |
| `test.run.start` | 当前权限、专业事实、来源事件、完整窗口、共享容量及样件使用通过后，请求 executing、Run running | 请求/Run、正式占用、样件使用与回执/审计/事件同事务保存 |

每项保持共同 T1 的一次具名确认、服务器读集和原命令恢复。实际事件的整行 JSON 绑定 request/Run/用途/操作/执行者/带时区发生时间；重复键、额外字段、无时区及未来事件拒绝。请求结果未知时复用原 key/载荷；刷新失败不重新消费。

首版一个请求只建立一个 Run，覆盖全部明确接收范围。本地实际请求 v7/executing、Run v2/running；样件 A 被接收，B 暂缓/方法未知及数量 1/3、模穴 B/C 缺项保持。保存人员/设备两条占用、一条非破坏性样件使用及预约；三动作各只有一份 Receipt/Audit/Outbox。结果、专业结论与处置仍未知。见[业务回读](actual-launch-check.json)、[计划/承诺零效果](zero-effects-before-start.json)及[页面记录](browser-final-check.json)。

复用 verification/resource_readiness 核、不可变请求/配置/样件链、专业事实、来源保护、共同确认及现有 UI 栈。指定 57 份旧轨、25 份验证核心和 7 份运行资产共 89 份哈希保持，见[复用核对](reuse-review.json)；这不代表整个旧工作区无变化。旧 server/web 未提交业务改动未操作。

资源与样件端口、Run/请求适配、办理界面三路独占并行；主线集中公共注册、共享占用、迁移与验证。Build/TestRun互查同一账本，锁定 Product、请求、Run、共享资产及样件门栓。完整自身提交证明仅排除本次自身增加的 epoch；其他变化继续使旧依据需重核。占用不自动释放，破坏性消费永久阻止另一 Run 复用。

## 最终验证

| 收口项 | 最终结果与证据 |
|---|---|
| 后端联合选集 | **1,598 项通过，0 失败，0 跳过**，57 组/64 文件/167 selector 无重叠遗漏；[最终去重结果](joint-final-result.json)与[覆盖审查](joint-coverage-review.md) |
| 开测/资源事务 | 精确范围、CAS、重放、来源撤回、职责/RLS、当前证明、破坏性一次消费与完整回滚通过；[三参数重放](recheck-launch-replay-result.json)、[消费复验](recheck-destructive-replay-result.json) |
| 存储与结构 | 3 项覆盖 8 种故障；六故障同计划复验通过，两个孤立负例原分组通过；最后 24 项生命周期检查单独通过，无 PG 并发 |
| 前端与静态 | [117 项辅助检查](ui-helpers-clock-final.log)零失败/跳过；[最终构建](web-build-saved-effects-final.log)通过；[后端 lint](backend-lint-after-sentinel-repair.log)通过，页面 lint 0 错误/2 条原 contracts.js 警告；原整模块收集另有 1 条 ORM 类收集警告 |
| 页面闭环 | 计划/承诺/一次确认实际开测、保存占用与历史只读；两尺寸亮暗检查及[最终页面证据](browser-final-check.json)通过 |
| 最终回读 | [结构检查后业务回读](business-after-joint.log)、12 表指定旧行、当前 v7/v2、三唯一回执和 Agent 零直写通过 |
| 合同与复用 | [合同检查](source-contract-check.json)：45 注册 payload = 25 canonical + 18 辅助 + 2 原扩展；受控事实导入走服务器 wrapper。66 操作/65 事件/48 AT 为完整定义，不能据此称全部业务已实现；89 份指定资产保持 |


运行代码在联合检查前冻结；后续改动为已登记的测试夹具/断言及单独复验过的页面显示。最终 [571 份候选](candidate.json)与[稳定性核对](candidate-stability.json)一致。原始失败与各增量覆盖保留，最终数量按用例身份去重；68 项修复包、早期最小检查和专项复验不重复相加。

- 原始联合检查 1,589 项通过、9 项失败，见[joint-result.json](joint-result.json)。旧 pure 两项、两条尚未开测的合同预期、四个 Receipt 字段断言及一项过渡夹具时效问题分别由有效复验替换。完整 pure 960 项替换原 958+2；旧合同复验两项、三参数重放、破坏性消费复验和存储故障复验对应原节点。
- 长存储测试最终与默认夹具分开验证：严格显式 profile 的上游合成事实在导入/原两次 T2 签核之前设定适当时效，实际时钟、生产角色/资格矩阵及 token TTL 未变。六次故障取得各自的新 T1，并核对所有确认仍未消费。默认流程[真实 PG 复验](recheck-default-fixture-final-result.json)通过，只替换同一旧成功用例。
- 存储故障覆盖同 Build 错样件、少资源、错用量、错覆盖、错事件、错物理资产及两类孤立使用/预约，共 3 项、8 种故障。错样件所需的新门栓在同一失败 UOW 内先 flush；原完整集合错误预期保留，门栓与 Product/指针、资源/样件 epoch、凭证和回执/审计/事件一起回滚。见[最终六故障](recheck-storage-sentinel-order-result.json)及[测试修复记录](sentinel-order-test-repair.json)。
- [旧合同源码与 hash](legacy-contract-test-before-repair/before-repair.json)、[Receipt 修复](receipt-field-test-repair.json)、[长夹具来源与时序](long-storage-fixture-review.md)和[存储原源码](storage-test-before-sentinel-order-repair/source-hash.json)保留。过渡场景被 RESOURCE_NOT_READY 拒绝、错误插入顺序被即时 FK 拒绝的日志保留；未弱化生产守卫或放宽负例 regex。

页面实际完成计划→承诺→一次确认开测，原 pending 提交已取得成功回执。1440×1000 / 390×844 两尺寸亮暗无横向溢出、历史 v6 scheduled 与 Run v1 planned 只读且未开始，恢复到当前 v7/v2；控制台零警告/错误。running 展示保存效果，明确不代表当前空闲或资格。浏览器未注入运输故障，未知恢复由辅助检查覆盖，不能宣称真实断网演练通过。

## 迁移、历史与环境

真实 head `next_0018`，0016/0017/0018 单调迁移在业务写入前分别完成 up/down/up/schema；[最终 schema](schema-after-joint.log)通过。0016 的两次早期 schema 失败及加固前记录保留，不替代最终候选。[十二张旧业务表](actual-launch-check.json)指定旧行保持，[迁移前占用归属](pre-migration-occupancy-owner-check.json)额外回读通过。91 张业务表、9 张新增表强制 RLS，Agent 对业务表直接写权限为 0，业务预览模型调用为 0。

只使用已核对 `127.0.0.1:62513/pdos_test`，marker `916f950f-2d2b-405d-b809-c15db75dc20c`。原存续57432、57439/57441及旧业务未操作；9/27恢复边界保持。本地 API8898、预览3028、独立状态PG65109和 Temporal开发SQLite65425暂留。未调用真实模型、真实业务外发、生产或 git push。

[闭环后私有备份](backup.json)为本次真实页面开测后的 next_0018 快照，权限600、目录检查通过；[备份范围](backup-scope.json)说明它早于独立检查租户的收尾，不冒充全实例最后时刻快照或恢复覆盖演练。迁移前备份保留，没有覆盖恢复已有数据。

## 下一步

按[方案 §13](../../../design/2026-10-02-pdos-next-execution-plan.md#13-开测后的原值返回与专业复核衔接)、[结果合同草稿](../../../design/2026-10-02-pdos-next-wave14-results-contract-draft.md)及[衔接审查](../../../design/2026-10-02-pdos-next-wave14-results-integration-review.md)接同一 Run 的原值候选、部分/最终返回、固定规则、分别 T2 复核和处置；尚未施工。原值核验、结果领域、界面可独占并行，公共版本链与历史执行证明先冻结，不再占用一次资源。性能排程与未实施的优化见[执行速度记录](performance-review.md)。

G0/G2整体、真实资格、OCR/S3/生产扫描、生产 Temporal PG、自动释放、分段/纠正、Issue/CAPA、正式放行/外发及 N/P/Q 人工出口保持未完成。局部 Run 数值或专业处置不能代表请求完整覆盖、工程/制造放行、客户承认或交付。

