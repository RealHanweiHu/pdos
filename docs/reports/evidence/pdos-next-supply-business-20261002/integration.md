# 供给与成本业务包接入

日期：2026-10-02。这是独立可调用领域、port、快照和界面组件候选。公共对象注册、迁移、API/BFF/页面入口及共同事务由主线完成。本包没有创建第二个 MaterialDemand、BOM、Build、SampleUnit 或 ActualConfiguration 所有者。

## 入口与对象

- `pdos_next.schemas.supply_cost.dto`：固定 Build 消费 DTO、供给承诺/在途/实际到货/质量限制/当前池与全部占用快照、成本输入、前后版对账、计算投影、T1 候选载荷和回执。
- `pdos_next.domain.supply_cost`：`coverage_candidate`、`cost_candidate`、`canonical_supply`、`reconcile`、`projection_freshness`、`snapshot_freshness`；`SupplyCostHandler.preview/apply` 参加调用者传入的共同工作单元。
- `read_models.py`：`binding_view`、`snapshot_view`、`projection_view`、`reconciliation_view` 映射到 `components/supply_cost/types.ts` 的查看 DTO。映射前由服务器授权每条记录，历史查看须传入当时完整 FixedBasis。
- `components/supply_cost`：`SupplyEntry`、`SupplySnapshotHistory`、`CoverageShortages`、`CostBreakdown`。通过 typed props/async callbacks 接入；无 API 依赖或成功 fixture。入口不可用时显示待接入。

## 四个服务器 port

| Port | 主线需要提供的内容与守卫 |
|---|---|
| `BuildDemandPort.load` | 服务器绑定 tenant/product/project/audience；同一 Build 版本、数量/成品单位、工程/BOM/制造版本、**同一次权威 FixedBasis 与完整 DemandLine 展开**；完整原件读集及 `source_read_set_complete=True`，所有原件版本/摘要/ACL/撤回/有效期；固定制造工序 keys。默认不完整标志会显式阻断。 |
| `SupplySnapshotPort` | 授权来源草稿 `capture_id`、当前快照指针、按 ID/版读取和历史读取；真实池键 `(source_system,pool_id,material_id)`、当前余额、现货/实到与承诺/在途阶段、质量/可用事实、所有有效占用（含其他 Build）；仅服务器核验并返回的外部替代资格。`current` 不接通或版本不同阻断新的计算，已完成回执可经授权原样回放。 |
| `CostInputPort.get` | 固定报价对象/数量阶梯/物料或工序、税/运费范围、原币与计价数量/单位、时点/直接汇率/预算或即期用途/年龄上限、工艺每合格产品用量与明确损耗/NRE范围；绑定同版制造配置与全量工序 keys。缺项可保留未知，但不能由节拍猜工艺成本。 |
| `CommandPort` | 真实会话/Run与当前权限/资格/受众/取消；服务器固定预览时点与真实当前时间；实质预览、一次确认、相同 key 不同 payload 拒绝、跨 key 相同意图去重、过期与源读集重核；调用者同一事务内写事实/回执/Audit/Outbox，失败全部回滚。无自行 commit/另开事务。 |

Ports 缺失只阻断依赖部分，不返回空需求或成功记录。ports 是主线需实现的契约，不是已有真实授权、ERP连接或数据库原子性的证明。

## 当前 Build 消费边界与漂移

当前 `compute_readiness` 返回 `demands`，其同次引擎 basis 位于 `coverage.input_snapshot.basis`；没有稳定公开的 `BoundDemand` 接口。主线应暴露该固定 bundle，而不是让供应包从不同工程视图重新哈希/展开。`coverage.input_snapshot.as_of` 与需求计算须同次固定；工程源键是 `configuration:{id}`，显示 source_refs 的 engineering_configuration 名称不能替换哈希键。制造 ref 单独提供，不能遗漏。

主线施工期间 `builds/service.py` 与 `builds/readiness.py` 发生了变更，首次和交付前摘要见 [consumed-summary.json](consumed-summary.json)。已定向复读：新增 Versioned.metadata、Build目的/双配置/原件读集等上下文纳入哈希，以及读取准备结果的 is_current；需求与嵌套 basis 路径仍保留。**不得继续使用首次旧摘要自行重建来源**。本包没有直接导入 Build 模块；未接通服务器 port 时保持待接入，不声称接口冻结。

规则先验证 `digest(FixedBasis)`、制造摘要、所有源有效性和完整权威展开字段（数量、单位、未知、ancestry、critical、issues），重复/缺行/不一致显式阻断；后调用既有 `calculate_coverage` 内部展开并核对选中需求。成本也按同版 basis 计算。供给或成本来源变更要新快照/重算，旧结果原样回查。

## 快照、物理池和质量

当前快照使用新不可变 ID、单调 revision、前版 ID/revision/内容摘要；同 ID 不同内容拒绝，相同视图只计一次，同物理池不同阶段/版本拒绝相加。新 capture 时点必须严格晚于前版。前版、后版与逐实体字段差异一并保留，第一版明确无前版。

承诺、在途、增量实际到货是分开的证据记录，**不累加到当前池余额**。当前池余额和占用由服务器事实投影提供；全部有效占用中其他 Build 先扣除，本 Build明确占用和未分配库存候选分开显示。冻结/待检/未知质量不当已释放实物，scope不完整不补零。

`restrictions` 表示本快照有效的质量分区事实：状态须与当前物理池一致；已知数量按标准单位精确匹配整个分区，部分或未知放行不能覆盖整个已知可用池。服务器需要把部分受限/部分释放投影为有权威固定 ID 的独立分区，本包不创造池 ID或裁切实际库存。质量证据有效性也进入计算、预览后源重验与历史时效判断。无限制行不自动授予资格：池的质量状态仍须由服务器来源验证。

替代资格认证、范围、当前有效性和真实受众来自服务器；请求 payload 不含 `externally_verified`。结果仍保留 `potential_is_feasibility_proof=False`；贪心候选不是最优可行性证明，也不预约库存或批准 Build 开工。Build其他资源、品质方法、工程/制造放行缺项继续由主线保持未知。

## 命令命名与写入分级

包内 `supply.snapshot.record`、`supply.coverage.calculate`、`supply.cost.estimate` 是**未注册的人工 T1 来源快照/候选参与动作**。它们不是当前66个合同操作的直接实现或改级。本包未修改共同 operation/PAYLOADS/write-tier 注册。

原合同 `supply.commitment.record` 是需真实资格与当前授权的 T0；`supply.kit.compute`、`cost.estimate.compute` 是确定性 T0；`supply.alternate.approve` 是具名 T2。主线将来接 canonical T0 时须沿真实资格、当前授权与既定低干扰回执路径，不把本包人工 T1确认新增为已合格T0审批，也不得由本包授予T0或执行T2。人工快照录入只是记录已验证来源中的供给事实，不伪装正式供方决定。

当前 handler 的准备 plan包含 scope/固定时点/semantic intent/source read set/完整结果/业务影响；共同 preview port 保存 plan hash。apply先复核权限并查询原回执，然后按原预览时点重建 plan，变更则拒绝。除 SnapshotRef 到期外，报价有效区间和汇率年龄在真实当前时点再次核对。stage_once须锁当前对象/快照指针/源和两级去重，并原子消费一次确认。任何回执不匹配或后续异常必须由共同服务回滚整组，不单独提交领域对象。

## 主线具体接线步骤

1. 将上述 typed snapshots/projections注册为同 scope 的不可变持久对象；保存完整JSON、内容摘要、前版关系、固定双方配置、需求和原件读集。供给当前指针独立锁定；历史结果不能被新计算覆盖。MaterialDemand继续由Build拥有。
2. Build公开同次固定 demand bundle与制造工序keys；将原有20份来源上限/ACL/当前版本/撤回守卫复用到port，不能只信计算结果内 source_state字符串。
3. 人工供给 draft或导入先保存**未应用的来源capture**并核对证据；其ID进入`RecordSupplyPayload`，再走共同实质T1预览/一次确认。UI `prepare`只建立capture+预览，不更新库存/当前快照。UI `binding_sha256`映射真实domain `plan_sha256`，保留原Intent、review与token供confirm和未知结果回查；`resolve`仅查询原持久回执，不能再建副作用。
4. 供给/成本port返回同版输入；CommandPort把原件读集和本包的全部固定源锁定重验，原子消费token/写快照或投影/Receipt/Audit/Outbox。接取消、幂等、撤回及下游消费保护。补 schema/迁移时依据实际head统一分配，本包未占迁移编号。
5. 授权读取后使用read_models映射；父页面注入当前绑定/来源/物料/池choices和callbacks。历史snapshot需要按原basis取回数量与版本，不允许传当前basis。SupplyEntry回执只在服务器确认 persisted后显示；不确定结果保留原凭据回查。查看组件保留未知、已知小计和费用范围，成本不是实际降本/财务批准。
6. 在主线已核对隔离测试库集中验证：当前指针锁竞争、共享池跨项目占用完整范围与受众、两级重复/不同载荷冲突、预览后源/报价/汇率/质量/资格漂移、取消/撤回/跨租户拒绝、事实+token+Receipt+Audit+Outbox整体回滚；再做HTTP/BFF/页面办理、亮暗/多尺寸/键盘/未知回执恢复。所有真实供方/ERP材料、资格、外发/生产与人工Exit依原授权条件。

## 本包复核命令

工作目录 `pdos-next/server`，不去掉数据库fixture隔离条件：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  -p no:cacheprovider --confcutdir=tests/supply_cost_domain tests/supply_cost_domain -q
.venv/bin/ruff check --no-cache pdos_next/domain/supply_cost pdos_next/schemas/supply_cost tests/supply_cost_domain
.venv/bin/ruff format --check --no-cache pdos_next/domain/supply_cost pdos_next/schemas/supply_cost tests/supply_cost_domain
```

组件局部类型/ESLint/15项合成SSR及callback负例材料见 [frontend/integration.md](frontend/integration.md)。无完整构建、浏览器、数据库事务、真实模型或业务材料检查；原引擎75项没有重跑或计入本包成绩。
