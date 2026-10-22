# G4 试模 / 试产 / 可靠良率独立首版交付

2026-10-02。本包约定的独占实现与合成验证已完成；业务公共接线和真实工厂验收未完成。只写指定的四个源码/检查目录及本证据目录，没有修改唯一清单、公共父文件、注册/迁移/API/BFF/页面或他包。

## 已实现

- ToolTrial：固定Build/Tooling及trial_round、参数/单位/腔号、材料批次、原问题/整改/具名验收引用；复用完整verification.RequestCreate，输出唯一品质所有者的同事务意图，资料/样件/方法/资源未知分列。试次与AI写入T1明确分开。
- PilotRun：作为已有BuildLot的制造扩展，固定实际配置/工程配置/ProcessRevision及单位；制造基线、线体、人员、材料、设备/治具、SOP/control/risk、预约、实际参数和首件仅消费typed权威引用。ProcessRevision草稿不当成制造基线；未知条件下可记录候选/明确观察，但从不授权开工或声称批准试产。不建产出/库存/样件账。
- 不可变结果：逐件和严谨批次互斥；首遍通过与最终合格分开，累计返工次数不增加投入。12计数包含产出、返工合格、报废、返工中、未判定和未加工；已知矛盾拒绝，局部未知保留。来源原值、单位、发生/接收时间、现实/合成范围由服务器端口核对。修正仅追加续版并保持固定范围/窗口/判据/已知分母及逐件身份。
- 良率纯核：固定Decimal精度；零/未知分母不计算比率，未知首遍结果不显示可靠首遍率，未完成结果及不足样本明确提示。相容批次先加计数再计算；不同实际配置/工艺/单位/判据/窗口/nature拒绝混算，同一批次/修正版不能重复汇总。当前首版保守要求相同actual configuration，不提供跨实际配置的权威适用性汇总。结果永不宣布过程能力/工厂资格。
- 可调用三个canonical T1 handler、封闭不可变DTO、调用者Session事实/共同命令端口、准备度与历史读模型；资格/预约当前版本和来源进入预览固定读集。确认/资格撤回/过期/冲突/回滚由共同事务合同约束，未接端口明确失败。
- 独立typed ToolTrial/Pilot准备、结果续版和良率组件；既有Button/UI tokens，父区共同预览/一次确认/回执slot。`toDomainPayload`完整映射封闭DTO，未生成另一确认或命令权威。合成fixture不接业务页面。

## 固定候选与检查

整体候选 SHA-256：`a99bfaf02303f821c996121ba38caea8f2277b363d83c25740f77c40680dd206`。覆盖23份包内源码/纯测试/局部类型配置和1份合成跨端fixture；算法及每个文件hash见 [candidate.json](candidate.json)。证据文档和日志不参与源码hash，避免循环摘要。

后端子候选 `d2718901cf792f14e64c1755bbfdcb1e4e6445b72eb621f1a1e4dfcb407913a0`，前端子候选 `52502334697260dae4ee4c983131be8f850853ceb8087d921a7d5b681f8bf0f6`。前端hash采用路径NUL/文件内容NUL，与整体按每文件SHA串联的算法不同，定义已记录。

| 检查 | 结果 | 原始证据 |
|---|---|---|
| 独占pytest，禁自动插件/字节码，confcutdir本包，禁cache | 102 passed | [backend-checks.log](backend-checks.log) |
| 本包Ruff --no-cache | passed | [backend-checks.log](backend-checks.log) |
| 局部TypeScript nonincremental/noEmit | exit 0 | [ui-checks.log](ui-checks.log) |
| 本包ESLint --no-cache | exit 0 | [ui-checks.log](ui-checks.log) |
| Node纯合成渲染/边界/载荷映射 | 27 passed | [ui-checks.log](ui-checks.log) |
| 三canonical TypeScript adapter产物 → Python封闭DTO，结果计数纯核 | 3 CLOSED_DTO_PASS | [cross-contract-checks.log](cross-contract-checks.log) |
| 首读/交付消费接口复核 | 无漂移 | [initial](consumed-interfaces.initial.json) / [final](consumed-interfaces.final.json) |

纯检查覆盖多轮返工、重复命令/跨key回执、修正历史和分母、批次/实际配置/工艺/单位错配、来源原值/参数单位核对、现实合成错配、资格撤回及固定read-set漂移、T1过期/实质变化、草稿基线/准备不足、硬阻塞与未知并存、零/未知分母、样本不足、逐件重复、同lot重复汇总、数量矛盾、并发版本冲突和失败恢复协议。模拟persist在领域、verification owner意图、Outbox或回执阶段失败时，确认消费、领域/观察、品质意图、事件和回执全回滚，同意图可恢复一次。

三跨端payload真正由UI adapter输出，不是手工抄写server示例；合成观察验证得到首遍0.6、最终0.8，并同时保留INSUFFICIENT_SAMPLE/INCOMPLETE_FINAL_RESULTS，未当成成熟或放行。

AT-07/08/12/16/17仅覆盖本包固定实际配置、请求前置、数量/良率及准备阻塞规则子范围，不宣称这些完整验收或G4/G/N/P/Q出口已通过。模拟Session、角色和来源不是PG事务/锁/RLS、HTTP、浏览器或真实资格证据。

## 未接线 / 恢复条件

主线仍需共同registry/命令/T1、持久模型/迁移/RLS、事实端口、verification共同事务调用、resource_readiness现行资格/预约、供应实际可用/占用、API/BFF/父页面和真实读模型接线，然后对新的集成候选集中联验。Tooling、正式ManufacturingBaseline及SOP/control/risk等权威未齐时保持UNKNOWN/待接入，不能用字符串、模型字段或草稿绕过。实际参数/结果须有授权原始观测来源，资源资格/工装验收和制造放行仍归具名所有者。

未连接任何数据库/共享服务，没有读取.env/.local/真实密钥，没有启停服务、安装依赖、完整构建/写共享.next、真实模型/材料出站、设备/样件/原件操作、云/生产或git commit/push。唯一清单由协调会话更新。

主线逐项接线、锁顺序、幂等/确认/撤回/原子失败与恢复合同见 [integration.md](integration.md)；组件props/adapter与局部证据见 [ui-result.md](ui-result.md)。
