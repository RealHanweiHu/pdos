# 供给与成本快照业务首版交付

2026-10-02。独立首版已实施并完成包内检查；主线事务、持久注册与业务整链接入未完成，不据此勾选 G/N/P/Q 或宣称真实资格/生产/人工Exit通过。

## 已交付

强类型服务器port与DTO、独立T1候选handler、不可变快照/前后版对账、共享池去重/冲突守卫、质量分区/来源时效、权威Build需求与同版输入比对、齐套与Decimal成本适配、来源变更/历史回查状态及界面映射已落在独占目录。复用原 `engines/supply_cost`，没有新增BOM/需求/Build事实所有者或旁路写表。

四个独立组件提供供给录入与一次确认回执、前后版差异、已占用/候选齐套缺项、成本分项/报价阶梯/范围与历史；供方承诺日期、实际部分到货时间、质量限制和全部占用分别显示。待接入/加载/缺项/失败/不确定回执均保留真实状态，无业务成功fixture。

## 固定候选与检查

候选 `8876b5bc371bd86fdf2ca9b3afd0311907463b2937aadc2657bf6c7e26274763`，24份本包代码/测试/组件文件，逐文件见 [candidate.json](candidate.json)。证据脚本独立于运行候选。最终一致性与导入审计见 [final-consistency.json](final-consistency.json)、[import-audit.json](import-audit.json)。

| 检查 | 结果与证据 |
|---|---|
| 隔离纯领域/port/查看映射 | **106项通过**；[原始输出](pytest-final.txt)、[JUnit](junit-final.xml)。禁用根数据库fixture、第三方pytest插件自动加载及公共缓存，未连接数据库。 |
| 包内Ruff与格式 | **通过**，16份Python候选与1份证据脚本；[Ruff](ruff-final.txt)、[格式](format-final.txt)。 |
| 独立组件 | **15项合成SSR/预览callback负例通过，局部TypeScript/ESLint通过**；[组件结果](frontend/result.md)、[检查](frontend/checks.json)。该组件候选与总候选逐文件一致，未重复未变的检查。 |
| 只读独立复核 | [Build/引擎合同](review/build-engine-contract-review.md)、[领域正确性](review/backend-correctness-review.md)。复核发现的来源、时点和质量分区问题已在最终候选中修复并覆盖。 |

检查覆盖同版摘要/全字段权威需求、缺接口与原件读集、scope/port拒绝、重复/过期/冲突/乱序快照、承诺/在途不作实到、部分到货/质量分区/共享池其他Build占用、替代服务器范围与重核、工艺全量keys、缺报价/费用保留未知、Decimal精度、报价/汇率/质量在预览后过期、实质预览漂移、原回执优先回放、历史basis与查看映射不覆盖旧值。

初期98项检查属于独立预冻结候选，见 [tests/result.md](tests/result.md)，其后新增快照时效、映射和同维单位精确分区反例并统一完成106项。一次末轮命令的未引用目录参数被 `&`截断，检查未执行，已修正；证据脚本的局部格式错误随后修复。早期调用错误见 [invocation-errors.json](invocation-errors.json)，不当作测试结果或候选验收。

## 接入状态与剩余工作

本包的 `supply.snapshot.record/supply.coverage.calculate/supply.cost.estimate` 是未注册的人工T1快照/候选参与动作，未改变canonical合同的T0资格/低干扰计算或T2替代批准。本包没有授予任何真实T0/T2权限。

主线施工中的Build service/readiness发生元数据哈希和当前性变化，已在交付前定向复读，摘要与差异见 [consumed-summary.json](consumed-summary.json)。7份复用引擎源码保持首次读取摘要。本包没有直接导入Build实现，缺BuildDemandPort或未冻结固定bundle仍显式待接入。

剩余：主线提供Build固定需求/制造工序/完整原件读集、真实供给物理分区与全部占用、报价/工艺/汇率来源和资格ports；注册对象与迁移、共同命令/一次确认/两级去重/取消/撤回/Receipt/Audit/Outbox原子接线，以及API/BFF/父页面和集中真实DB/HTTP/浏览器联验。字段、步骤和病例见 [integration.md](integration.md)。port协议和fake-host测试不能替代真实SQL权限、锁/并发或回滚证据。

本轮未读`.env/.local`凭据、连接/迁移数据库、启停共享服务、修改共享.next、安装依赖、全量构建、真实模型调用、云/生产/业务外发、资产删除、git提交或push。只修改分配的5个独占目录；共享模型、原件/API/runtime、父__init__、配置/锁/BFF/workspace/CSS、唯一清单/方案及其他领域和引擎保持本包只读。
