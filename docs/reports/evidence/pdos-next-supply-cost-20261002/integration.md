# 供给/齐套与成本计算 DTO v1 接入说明

日期：2026-10-02。范围：G4.1 确定性计算首版，可提前用于 G1 定义约束。包不导入旧 `app`，不包含数据库、模型、业务对象注册或领域写入。调用方使用当前新工程 Python 环境，依赖仅为标准库和已有 Pydantic。

## 入口和回执

```python
from pdos_next.engines.supply_cost import (
    CoverageRequest, CostRequest, calculate_coverage, calculate_cost,
)

coverage = calculate_coverage(CoverageRequest.model_validate(server_bound_supply_payload))
estimate = calculate_cost(CostRequest.model_validate(server_bound_cost_payload))

# JSON 金额/数量序列化为字符串。不得在页面或数据库接线时转换为浮点真值。
coverage_json = coverage.model_dump(mode="json")
estimate_json = estimate.model_dump(mode="json")
```

公共父目录 `engines/__init__.py` 未修改，按 namespace 子包使用。完整 JSON Schema 见 [输入](input-schemas.json)、[输出](output-schemas.json)。[合成示例](synthetic-examples.json)包含未分配现货、承诺、已占用实到、质量未知、完整物料估算和缺汇率；仅用于接口理解，不是业务来源或资格。

每份结果保留完整 `input_snapshot`、`input_sha256`、算法/DTO 版本、分项和 `issues(code/path/message/kind)`。摘要规范化 Decimal 数值及 UTC 时间；输入数组顺序属于快照内容，调整数组顺序会调整摘要，计算优先级不依赖数组顺序。再次计算不取当前时钟，不查询外部状态，不修改输入。

## 主线需要提供的固定输入

| 输入 | 字段与职责 |
|---|---|
| Build/BOM/工程配置 | Build 身份、明确数量/成品单位；各来源 `source_id/version/sha256/captured_at/state/valid_until`；BOM 稳定 item、parent、material、相对父项数量、单位、损耗、供料层级和关键件。`None` 明确表示未知；损耗为 0 也需显式给出。 |
| 供给快照 | 物理池键 `(source_system,pool_id,material_id)`、当前余额/单位、`commitment/in_transit/on_hand/received`、`available/unavailable/unknown`、`released/frozen/unknown`，可另留 expected_at。一个物理池只选一个当前阶段/版本；不同阶段历史或不同版本不得作为新增供给相加。 |
| 占用快照 | 所有相关池的有效占用，包含其他 Build 的数量；稳定 reservation ID、来源版本、目标 Build/item、池键、数量/单位。输入 quantity 是当前池余额中的占用，不是已经从库存扣除的累计领料。未提供完整占用时 `supply_scope_complete=False`。 |
| 替代资格 | 从服务器已验证资格读取，包含资格 ID/来源、状态、目标/替代 material、两个单位及替代数量比率、精确 Build/BOM/configuration 摘要。不得采信模型或普通客户端自填 `externally_verified`。 |
| 工艺/成本 | 冻结 ProcessSnapshot/operations、每合格成品工时/用量和显式损耗；Price 的稳定 ID、subject_kind/subject_id、原币总额/计价数量/单位、税费与运费口径、报价区间/数量档位、来源及 scope_assumption。 |
| 汇率/口径 | 明确原币→目标币的单条直接汇率、来源时点、spot/budget 用途和年龄上限；目标币、税/运费口径、materials_only/materials_and_process、NRE 排除/单列/分摊及分摊量、显式假设。 |

这些 DTO 不含租户、项目授权、批准或具名责任。主线须由服务器从真实对象/Run/用户范围生成输入，核验来源摘要、权限、当前版本、质量事实、资格和快照完整性；`current` 是调用方提供的来源事实，不是本包授予的资格。有效期右端为排他边界，时间必须带时区。主线按本域 freshness SLA 设置 `state` 和有效期；本包不会自行把旧来源认定为新鲜。

## 齐套结果的使用规则

- `secured_ready` 只核对本 Build/item 的明确占用，且来源当前、实到/现货、可用及质量已释放。仅有未分配现货时仍不是已占用齐套；结果也不批准 Build 开始。
- `potential_ready`、`known_potential_quantity`、`potential_gap` 描述一份不重复消费物理池的候选。候选先关键件、再 item ID；同项先原物料、再外部验证替代；池按固定键排序。它不实际预约库存。
- `potential_is_feasibility_proof=False` 必须保留。涉及多个物料争用替代池时，贪心候选失败不证明不存在其他可行分配；不得据此宣称不可解或自动授予替代资格。最优替代分配/全局搜索未实现，交主线后续按业务需要扩展。
- `True/False/None` 分别为当前所核对范围满足、已知不满足、未确定。未知数量、单位、占用、来源或可用状态不补零；已知充足的独立供给可覆盖其他未知池。整体已知不满足优先于其他行未知，空 BOM/需求不报齐套。
- 完全相同的池/占用视图只计一次；同身份不同内容排除并报冲突。有效占用超余额、未知/不可比/过期占用使池可用量未知。其他 Build 占用先扣除；本 Build 过量占用不释放为候选余量。
- 每个 BOM 末级路径必须明确选择一个供料层级；遗漏路径保持未知，父组件及子件同时需求报冲突。固定 BOM 任意未选中分支的环/缺父项仍影响完整性。
- commitment/in_transit 不进入当前实到齐套，即使 expected_at 已经过期；质量冻结/明确不可用库存排除。预计到料、长周期排程和日期齐套尚未实现，保留 expected_at 供主线后续使用。

## 成本结果的使用规则

- `complete_in_selected_scope` 只代表选定费用范围内的计算完整；`materials_only` 不声称已覆盖工艺、NRE、物流或其他未选费用。估算/报价都返回候选，不支持把实际成本、冻结批准或真实降本状态写入本包。
- 一条 Price 必须绑定选中 material/operation；材料按 BOM 展开而非调用方另传数量。父组件整包报价可覆盖后代，父/子同时选择或同 BOM item 重复选择会排除相应金额。整项 NRE 同一 subject 的不同报价不能叠加。
- 物料损耗口径为每个路径节点乘 `(1 + loss_rate)`；工艺为明确“每合格成品用量/工时”乘 `(1 + loss_rate)`。这不是 `1/(1-yield_loss)`，不接受未知损耗等同 0。BOM 父项必须为计数单位，层级最多 64；输入最多 2000 BOM 项。
- 支持计数 `ea/pcs/个/件/台`、质量 `kg/g/mg`、长度 `m/cm/mm`、容量 `L/mL`、时间 `h/min/s` 的同维换算。不猜盒/盘/套装系数、密度、跨维单位或工艺产能关系；数量不做采购包装/整数取整。主线需另行核对实物计数和包装约束。
- 金额/数量输入不接收二进制 float，数值有限且有界（数量/金额最多 24 位、8 位小数；损耗最多 8 位小数且 0～1）。BOM 在独立 4096 位上下文中精确乘法；成本在固定 38 位、ROUND_HALF_EVEN 上下文中计算，不依赖宿主精度/rounding/traps，不做币种展示舍入。
- 报价数量档位按换到计价单位后的 Build 需求核对，价格 denominator 保留。税口径转换必须有税率；运费口径不符/未知不按零。只使用指定直接汇率，不自动反转、串联或选择“最新”汇率。
- 缺报价/金额/单位/币种/汇率、来源失效、数量档位或税/运费不符时，总计为 `None`，已知小计与逐项原因仍返回。NRE 单列不自动分摊；分摊须明确费用与 volume，保存损耗、报价档位、汇率和分摊敏感项。

## 接线与验收边界

本包没有新增 MaterialDemand/AvailabilitySnapshot/CostEstimate 权威表，也没有更改 Build、BOM 或供给。主线统一增加所需强类型字段、序列化持久快照和计算结果，并经共同命令服务完成权限、expected_revision、source_read_set、资格、幂等、取消以及同事务回执/审计/Outbox；提交前重新核对固定来源，禁止用本包输出旁路写业务表。正式供方承诺、替代资格、放行与成本批准仍由对应专业流程办理。

本包检查只覆盖纯计算与 DTO，无数据库、迁移、API、页面、模型、真实 ERP/供方资料或真实业务效果验证。依赖项恢复条件：主线完成真实新对象/快照投影与受控 handler 后做联合数据库/API/页面验证；真实来源、外部授权、逐能力资格及人工出口按原合同补齐。本包没有外部条件阻塞纯计算首版交付。

独立复核命令（工作目录 `pdos-next/server`，禁止去掉 cutoff 后误加载数据库 fixture）：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest \
  -p no:cacheprovider --confcutdir=tests/supply_cost_engine tests/supply_cost_engine -q
.venv/bin/ruff check --no-cache pdos_next/engines/supply_cost tests/supply_cost_engine
.venv/bin/ruff format --check --no-cache pdos_next/engines/supply_cost tests/supply_cost_engine
```

来源函数、旧新差异及哈希见 [源摘要](source-summary.json)；只参考规则和反例，不复制旧 SQL 锁、分配事务、供方批准、资格或业务实例。冻结代码/测试候选及检查见 [结果](result.md)。
