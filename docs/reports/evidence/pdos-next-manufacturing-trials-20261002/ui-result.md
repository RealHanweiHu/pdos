# Manufacturing trials · isolated UI package

本包前端候选已完成。独占文件为 `pdos-next/web/src/components/manufacturing_trials/`；未修改公共页面、BFF、配置、依赖、共享组件或其他业务包。

UI candidate SHA-256: `52502334697260dae4ee4c983131be8f850853ceb8087d921a7d5b681f8bf0f6`。按排序后的包内路径、NUL、文件内容、NUL组成哈希；包含包内测试与局部类型配置。逐文件及消费接口摘要在 [ui-checks.log](ui-checks.log)。

## 可调用组件与合同

- `ToolTrialWorkbench`：固定 Tooling / 物料 / 参数 / 模穴，编辑目的与非负 `trialRound`；试模轮次和“一次确认”分别展示。保留原问题、整改和已有具名验收来源；品质方法、资料、预期样件/模穴、时间、返回形式及缺项明确。只输出 `npi.tooltrial.create` 意图及由 verification 唯一落账的品质准备共同事务意图。
- `PilotRunWorkbench`：固定既有 Build、实际 BuildLot、实际产品配置与工程配置、ProcessRevision、可空 ManufacturingBaseline、线体/具名人员/物料/治具/设备/参数/首件及作业指引/控制计划/过程风险/资源预约引用。draft ProcessRevision 不替代正式制造基线；缺基线允许准备候选，明确不能宣称开工或已批准试产。不存在新产出、库存或样件账。
- `PilotResultsWorkbench`：固定统计范围、分母、单位、判据、窗口、现实/合成口径；互斥批次终态和逐件终态两种模式。未知保持 null，不等于 0。累计返工次数不增加投入。真实发生时间及 IANA 时区、服务器提供的精确来源、带来源的异常/缺项事实、已有问题及具名处置来源和修正原因进入完整 typed 意图。修正引用前版，原观察不覆盖；系统接收时间只由服务器绑定。
- `YieldReading` / `ObservationScopeReading`：展示服务器的首次通过率、最终合格率、原始计数、前版、范围/窗口/判据、来源、两个时间和样本充分性。零/未知分母、冲突、无结果或无效比率不显示成功百分比；不声明过程能力、工厂资格或放行。

入口统一从 `index.ts` 导出。`contracts.ts` 包含 typed projection 和 intent；UI 不调用 API，也不把 label/字符串当业务权威。

## 共同 T1 接线要求

`callbacks.onPreview(intent, contextKey): Promise<void>` 仅把意图交父办理区。`SharedAction` 的 `busy` / `unresolved` 锁定编辑与重复提交，`previewSlot` / `receiptSlot` 显示父区的共同预览、一次确认与回执。本包没有 onConfirm、执行命令或自建确认。

父区须在生成预览时固定 payload、读集、operation 和 context watermark；输入/来源/权限/资格/版本变化、预览过期或撤回后不可继续确认。同一事务复核全部端口及 expected revision，失败不得留下部分品质意图/试产/观察，重复 key / 重复意图返回原回执，不同 payload 冲突。未知结果先对账同一回执，不能重新写入。现有共同办理框架拥有这些能力，本 UI 只消费其状态和插槽。

## 主线具体适配

1. 把服务端闭合 DTO 映射为 `FixedRef(kind,id,revision,label,source,current)`、`SourceRef` 和 `ServerContext`。tenant、project、actor、现行资格和资源当前性只从服务器确定；context capability 是展示投影，不能替代服务器判定。source、ref、scope 与 resource readiness 引用必须由服务器重新解析，拒绝伪造、来源撤回和跨批次/配置/单位口径。
2. 把使用本包 `toDomainPayload(intent, newUUID)` 将前端 camelCase intent 映射为后端 schema 的 snake_case exact DTO；忽略展示 label / current / capabilities 的任何授权含义。`operation` 仅为附录的三个 canonical T1 动作；正式工装验收/制造放行不在本包执行入口。
3. `ToolTrialPackage.quality` 交 verification 的唯一持久适配，以共同事务创建/关联 VerificationRequest。预期样件不是实际 Sample，暂定时点不是正式预约、交接或品质承诺。
4. `PilotPackage` 和 `ObservationScope` 从 build_execution、configurations 与制造权威端口投影。资源准备引用来自 resource_readiness；本包不创建 qualification 或 reservation。权威对象未齐时按 missing、null 或 unknown 提供，不能伪造 ManufacturingBaseline。
5. 服务端处理批次/逐件互斥账、固定分母、累积返工与修正前版并发控制；计算数值与相容汇总仍归后端。`YieldProjection` 比率为 Decimal fraction 字符串（`rateUnit: fraction`），服务端返回口径状态与样本充分性。UI 的安全格式化不重新决定品质结论。
6. 将组件接进已授权父工作区，提供共同 T1 插槽及真实读模型；禁止导入 `__tests__/fixtures.ts` 到业务页面。`fixedContextKey` 包含完整 context/fixed snapshot，变化会重挂载候选；父区须同步撤销旧预览及回执动作。

## 验证与消费接口

局部 nonincremental/noEmit TypeScript、ESLint --no-cache 均退出 0；27 项独立合成渲染、闭合载荷与边界检查通过。覆盖多次返工、互斥/矛盾终态、局部未知、未知/零分母、来源口径与撤回、时区/窗口、固定批次/配置变化、逐件重复与批次混算、缺基线/draft工艺、端口未接入和父流程未知回执锁。

首轮有一项测试断言把按钮 class 中 `disabled:` 当作 disabled 属性；已修正断言为准确属性 `disabled=""`，最终检查通过。原检查输出和最终候选在 ui-checks.log。

消费接口摘要：运行时只导入现有 `Button`（`ComponentProps<button>`、variant/size、asChild）与 Phosphor；transitive utils 继续提供 cn。参考 verification 的 fixed refs/SourcePosition/前后读集语义和 build 的固定配置/缺项展示，未导入这些包的业务实现。Next.js 本地 server/client guide要求交互组件 `use client`；本包父区是 client workspace，callback 与 ReactNode slots 不从裸 server props 跨边界传递。交付前复核消费文件摘要；原值见日志。

未进行 DB、HTTP、真实浏览器、多尺寸/双主题视觉、生产构建、迁移或 G/N/P/Q 正式验收；未连接服务、真实来源、设备、样件或模型。主线还需公共注册/持久/API/页面接线和适用联合验证。


## 闭合 DTO 对齐补充（最终候选）

已定向读取 `schemas/manufacturing_trials/contracts.py`、`schemas/verification/contracts.py` 和制造计数纯核；后端合同与运行时消费接口检查前后 hash 未漂移。上方当前 UI hash 替代历史候选；日志保留各次检查范围。

- `Counts` 的 12 项全部一一映射：input→input_count、output→output_count、firstPassGood→first_pass、firstFailed→first_failed、firstUnknown→first_unknown、finalGood→final_good、reworkedGood→reworked_good、scrap、reworkPending→rework_pending、undetermined→undecided、unprocessed、reworkAttempts→rework_cycles。编辑界面具备全部相应字段；input 保持服务器固定分母，未知数量序列化为 null。firstUnknown 非零或未知时不显示可靠首次通过率。
- `UnitInput` 固定每件 sample 与独立 source，first/final 支持 unprocessed；未加工在两种口径一致且无返工，首次失败后合格须带返工。batch/unit 互斥保持。
- `ToolTrialPackage` 包含 build/source，`quality.requestCreate` 由父办理区提供完整、typed `VerificationRequestCreate`（全部 TestItem 方法/判据/工况/材料/模穴及 DocumentRequirement 精确适用范围）。缺此对象或 Build 固定版本不匹配时不允许预览；adapter 不猜测方法或来源位置。
- `PilotPackage` 增加 engineeringConfiguration、unit/source、work_instruction instructions、controlPlan、risk、reservation 固定引用；`ObservationScope` 增加 build/engineeringConfiguration/line 与 `criterion` 类型固定 Ref。判据的 source 仅作只读展示；minimumSample 必须是服务器固定正整数。窗口 start==end 的合法单时点观察已与后端对齐。
- `ResultIntent.exceptions` 是 typed ExceptionFact 列表：key/description/source/issue/dispositionSource。异常现象或缺项说明带共同观察 source；问题只能选择服务器当前可见固定 Issue；处置只能引用父区提供的已有具名处置 source，不提供自由文本决定或代签动作。
- `toDomainPayload` 返回 exact ToolTrialCreate / PilotCreate / ResultRecord body；不包含 operation、label、current、权限、状态或 synthetic 投影字段。DomainSource 只含 id/revision/kind/position，kind 明确支持 artifact/domain/command。observed 使用同一 source，含 occurred_at/original_timezone/effective_at:null。父办理区预先提供稳定新 UUID（trial/pilot/observation），adapter 不生成 ID；operation/subject/expected revision 仍在共同命令外层。
- 无法在闭合 DTO 落账的普通 note 与自由处置文本入口已移除，不静默丢弃已输入内容。未知参数显示“未知 / 单位未知 / 来源未知”。

新增检查覆盖三操作 exact top-level / nested shapes、12计数null、完整 RequestCreate 固定方法资料、来源与引用去除投影字段、必需 minimum_sample、Unit source/unprocessed、未知首遍率、作业/控制/风险/预约展示以及单时点/未知参数。

已输出 [domain-payload-fixtures.json](domain-payload-fixtures.json)：以三个 canonical operation 为键，值为 adapter 实际生成的 valid-UUID exact payload。只用于主会话直接 Pydantic 跨端合成校验，不导入业务页面、不连接数据库或外部服务。本会话 27 项属于前端独立候选，后端跨端验证与公共联验由主会话记录。
