# 供应与成本独立组件接入

日期：2026-10-02。组件是本包首版 UI；未注册公共页面、BFF、API、命令或持久模型。业务结果全部通过 typed props 和异步 callback 提供，合成资料只出现在本目录的检查脚本。

## 调用入口

从 `pdos-next/web/src/components/supply_cost/index.ts` 导入：

| 组件 | 输入 / 功能 |
| --- | --- |
| `SupplyEntry` | `binding / sources / materials / pools / port / onReceipt`。来源数量可未知；分别录入承诺、在途、实到、库存或限制。服务器生成实质预览后一次确认；持久回执前不显示保存成功。 |
| `SupplySnapshotHistory` | `snapshots`。按版本回查独立记录、当前池、全部占用、来源摘要及不可变前后差异；数量不在 UI 相加。 |
| `CoverageShortages` | `projections: ProjectionRecord<CoverageView>[]`。保留已占用齐套、关键件、库存候选、逐项未知/缺口及物理池使用依据，候选不产生预约或授权替代。 |
| `CostBreakdown` | `projections: ProjectionRecord<CostView>[]`。成本分项、原币与目标币、报价对象/阶梯/计价分母、固定工艺/损耗/直接汇率、所选费用口径及历史回查。 |

三个 viewer 支持共同 `ReadState`：`status: ready|loading|unconnected`、`error`、可选 `onRetry`。提供空集合时显示对应空态；未连接时显示待主线接入。输入集合顺序由服务器提供，第一项默认显示；用户可以回查旧版，旧版结果保留历史或重算提示。组件沿用当前 Button、Geist、橙色双主题、8px圆角与 Phosphor；仅写包内 Tailwind 类。

## 服务端字段与安全边界

`types.ts` 定义本包最小显示 DTO。`CoverageView / CostView` 直接消费引擎 `model_dump(mode="json")` 的结构子集；忽略未用字段，数量/金额不转成浮点。`ProjectionRecord` 的 `freshness` 与 `freshness_reasons` 必须由服务器核对实际来源、双配置、Build 与需求版本后填入，UI 不从时间或参数推导就绪。`SourceRef` 使用引擎状态 `current|stale|withdrawn|unknown`。

`BasisBindingView` 需要服务器固定 `basis_sha256 / demand_sha256 / basis / manufacturing_configuration`。`basis` 包含权威 Build（数量/成品单位/版本）、BOM 与工程配置来源。这里没有第二份需求对象，需求行只展示齐套投影内主线已核对的展开结果。

历史快照的 `basis` 与 Build 数量/单位必须来自与该版快照精确绑定的历史 `BoundDemand`，不能拿当前 BuildDemandPort 的绑定替换历史值。主线 read-model adapter 应先核对历史 Build/BOM/双配置/需求引用及摘要，再转换成 `BasisBindingView`；历史版本无可读取 `BoundDemand` 时显式报告待接入，不把当前数量嫁接到旧结果。

`SupplySnapshotView` 需要业务读模型映射 `binding / source_refs / records / pools / reservations / reconciliation`。记录类别与当前池阶段独立；每份记录保留原来源版本、时间、质量/可用性、备注。`reconciliation` 保留前后快照身份/版本/摘要及服务器输出的逐字段差异，UI 不制造差值。所有相关占用必须由服务器提供，包含其他 Build，`scope_complete=false` 时显示范围缺项。

`SupplyRecordView` 另外接收可选 `supplier_id / expected_at / commitment_id`。承诺行显示供方与承诺到达时间，日期缺失明确为未知；receipt 行 `recorded_at` 是该行的真实 `received_at`，显示“实际到达”，不使用来源 capture 时间替代实际到货。in_transit/receipt 保留承诺关联 ID，未关联时明确显示未提供。当前 backend `read_models.py` 与本包 `BasisBindingView / SupplySnapshotView / CoverageView / CostView` 已逐字段结构核对；引擎原 JSON 中未用的额外字段可保留，inventory 通过当前 pools 展示而非生成另一份可累加供给。

主线应将供给输入草稿映射到服务器 canonical 来源记录，不能把 `source_id / source_revision / material_id / pool_id / quality / availability` 当作授权或质量释放事实。当前草稿只表达用户要录入的来源字段；实际来源、范围、身份、当前资格和受众在服务端绑定。物理池选择会去掉相同固定键的重复视图，并禁用跨 `source_system` 的同名 `pool_id`，该冲突需服务器先明确绑定。供方正式承诺和放行保留具名流程。

`SupplyEntryPort`：

- `prepare(draft) -> SupplyEntryPreview`：返回服务器固定的 `review_id / confirmation_token / binding_sha256 / expires_at / allowed_to_confirm / basis_binding / source / record / changes / warnings`。`changes` 是实质字段的原值与录入值；不得返回空差异或仅写“保存成功”。预览展示真实最终记录及固定双配置/Build。客户端拒绝过期、来源漂移、配置/需求漂移和缺凭据预览；这些检查不能替代服务器提交复核。
- `confirm({review_id, confirmation_token, binding_sha256}) -> SupplyEntryReceipt`：提交不重传未经服务器绑定的草稿。主线 port adapter 必须在共同命令事务里验证预览、当前权限、来源读集、版本、幂等及一次消费，并返回 `{receipt_id, review_id, status:"persisted", snapshot_id, snapshot_revision}`。组件用同步锁防止重复点击，一次确认后的不确定异常保留凭据并锁住编辑。
- 可选 `resolve(confirmation) -> SupplyEntryReceipt|null`：回查原确认对应的持久回执；`null` 保持未确定。此回调只查既有结果，不创建新命令或重发写入。未提供回查接口时，由主线按原凭据回查。主线若取得明确“未写入”的拒绝回执，可在它的办理入口明确恢复编辑；组件不能从普通异常猜测拒绝。
- 可选 `onReceipt(receipt)`：更新主线快照和结果集合。只有已确认持久回执后才出现“录入下一条来源记录”；它清空下一条草稿，下一次需新服务器预览。来源/配置 props 漂移不会清掉一次确认后待回查的凭据。跨用户/项目入口必须由主线按授权身份隔离或卸载组件；刷新恢复与回执历史由主线处理。

上述 UI port 与领域命令 DTO 分离。当前领域 `RecordSupplyPayload` 只接受服务器验证的 `capture_id`，不直接接受本 UI 草稿：主线 `prepare` adapter 必须先在授权来源入口创建或取得服务器 canonical 导入/人工依据 capture，然后构造 `supply.snapshot.record` Intent（服务器绑定 Build/expected_revision/前版引用/command_id/idempotency_key），再调用共同 T1 预览。capture 的创建只形成未应用依据，不提交正式供给快照、不另设一次业务确认；UI 中的“确认保存此来源记录”是最终唯一共同 T1 确认。主线需保留原 Intent 并绑定预览，`binding_sha256` 映射领域 `Preview.plan_sha256`，确认映射 `{review_id, token:confirmation_token, plan_sha256:binding_sha256}`，不能映射为 `basis_sha256`。领域 `CommandReceipt` 需由 adapter 校验 subject_type/subject_id/revision/plan_sha256 后转换 UI 持久回执；`resolve` 使用既有 Intent/回执身份读回相同结果。capture 创建/API/模型与这段 adapter 尚未由本独立组件实现。

## 主线接线顺序

1. 在已授权主线入口提供固定 BuildDemandPort 绑定和可见来源/物料/物理池 choices；没有实际材料事实时传 `null` binding 或空数据及 `unconnected` 状态，不能补库存或就绪事实。
2. 持久供给与成本快照、对账及计算投影后，映射本包显示 DTO；历史绑定从精确历史 `BoundDemand` 读取。成本输入中的 BOM/工艺损耗、报价及汇率按引擎原版保存，UI 不取当前价格或把缺项补零。
3. 由公共命令/API adapter 实现 prepare、confirm、resolve；回执提交、审计、Outbox、幂等和来源再核对参加同一事务。
4. 从已有 workspace/Build 入口挂四个组件，按服务器可见范围输入回查列表。公共页面/API/BFF/认证、真实数据库事务及浏览器联合验证由主线执行。

消费源码摘要见 `consumed.json`：共享 Button、utils、CSS、package、引擎 DTO/common，以及本包主 agent 的 backend read-model mapper/schema。未导入旧工程或改动上述共享文件。Build 漂移与领域 schema 最终对接由本包主 agent/主线核对。

## 本包验证

局部 TypeScript 检查通过（专属配置 `incremental:false`，不读取或生成 `.next`）；包内 ESLint 通过；15项合成 SSR/展示/预览-回执负例检查通过。具体检查见 `checks.json` 与原始 `check.log`，源码冻结摘要见 `candidate.json`。

检查脚本使用当前已安装 React/ReactDOM/TypeScript 和真实 Phosphor ESM 入口，无图标 stub；初次 CommonJS 加载遇到 Node25 对该包 `index.cjs.js` 的 ESM 判定，改为加载包实际 ESM 导出后通过。该调整仅在检查脚本，不改变组件或依赖。

覆盖：当前/漂移/过期预览、无实质字段、具名决定禁止确认、不匹配/不完整回执、物理池去重及跨系统同名、Decimal原字符串/零/未知、未连接/读取中/空/失败状态、已占用未知与库存候选分开、历史重算标识、部分实到与承诺/冻结/其他Build占用/前后差异、承诺供方/预计到达与实际到达/关联、仅物料口径及未知总价。未覆盖：真实浏览器点击与布局矩阵、持久事务/并发/服务端幂等、API/BFF、真实材料/来源/资格、外发、模型及正式财务/质量/Build批准。未运行服务、构建、原引擎测试、数据库或迁移，未安装依赖、读取凭据、提交或 push。

复核命令（仓库根目录；不得替换为共享构建或 typegen）：

```sh
pdos-next/web/node_modules/.bin/tsc --project docs/reports/evidence/pdos-next-supply-business-20261002/frontend/tsconfig.json
node docs/reports/evidence/pdos-next-supply-business-20261002/frontend/check.cjs
```

包内 lint 在 `pdos-next/web` 使用现有 `node_modules/.bin/eslint src/components/supply_cost`，不写缓存。
