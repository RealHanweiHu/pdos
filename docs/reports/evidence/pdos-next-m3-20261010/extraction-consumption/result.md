# M3 抽取 Claim 消费证明

从 `c21c387` 续建，head 保持 `s0_0758`，无迁移。AI 登记的 `extracted` Claim 引用**客户原件**时，`evidence.claim.record` 现在必须在准入时消费一条实际已核对的抽取行：`extraction_ref={call_id, row_index}` 指向本 Run 内已结算的 `evidence.extract` 调用，经 `_historical_read` 复核运行/调用/绑定/模型链与提示前缀钉住后，Claim 的引文（artifact、版本、定位、逐字 quote）必须与该行完全一致，内容必须等于服务器从行字段投影的唯一形态（`text=行 statement`；spec 行仅带 ClaimContent 重叠键，非空才保留），可用性必须等于行的派生可用性（spec 行取 spec.availability，其他行恒 known），行内 `read_call_ids` 逐条复核为本 Run 已完成的 `evidence.artifact.read` 调用。引用注册知识文档（无原件根）与快照的 Claim 保持既有钉住读集/快照证明路径，不受影响；人工（无 Run）路径不变。`page:`/`cell:` 定位经 locator_map 解析派生行后仍走 `load_source` 的逐字核对。真实模型调用 0 次，未授予资格。

- [最终 4 项纯检查](pure-1.xml)：内容投影键白名单、可用性派生、非法行拒绝。
- [最终 8 项实库检查](pg-1.xml)：真实抽取派发后 canonical 与 legacy 两种 Claim 形态消费实际行并落库（`extraction_ref` 持久化）；无证明、无效引用、越界行、非行引文、篡改内容全部按 `extraction_*` 拒绝；既有 95 项 Claim/快照/适配器回归确认注册文档与快照路径零影响。
- [受影响 161 项定向回归](affected-1.xml)（抽取派发/库存/候选/适配器/快照/计算证明/载荷）与[全量 1542 项 agent_kernel + 证据套件](full-regression-1.txt)通过；[规范检查](python-lint-1.txt)通过。
- [源码清单](source-manifest.json)固定本段 1805 份源码（前置 `c21c387`）。仅使用核对标记的 `127.0.0.1:64245/pdos_test`（marker `f9048729`），无迁移、无前端/构建产物变化。

开发期缺陷（均未出库）：`load_source` 需派生行号（page/cell 经 locator_map 解析，首轮占位错误已纠正）；夹具资格缺 `reviewed_by/reviewed_at/review_case_refs`（按 v1.1 §06.12 补齐 10 条合成案例）；Claim 模型调用未带已加载技能绑定；DomainCommands 路由未指向合成路由；首轮受影响 XML 环境变量不全（25 个收集错误，已重跑）。

本段完成抽取 Claim 消费证明。标准品匹配尚未启用；继续标准品、平台、AT/演示/性能；无 push、生产、真实外发，M3/S1 未完成。
