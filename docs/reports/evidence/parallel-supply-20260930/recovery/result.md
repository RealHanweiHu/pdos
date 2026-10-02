# 供应短缺 → 部分到货 → 对账 → 原异常恢复 · 本线候选

本轮补齐供应恢复的当前采用边界，并交付原 Issue 具名关闭的供应守卫、类型化引用及联合用例。已有分配/对账/异常对象继续复用，无新实体、schema、迁移或 ERP 反写。**本线候选代码和针对性检查已交付，完整闭环尚待统筹接入共同 Issue 路径并执行数据库与浏览器联验**。

## 可用链路与修复

- 原固定需求、合格分配及领用时合格净领料继续决定实际齐套；未分配库存和预计到货不能抵作齐套。部分到货沿同一 material_key、原异常及原 Issue 追加具名 follow_up/recovery 核对，原承诺、历史和 Issue 生命周期独立保存。
- 最新供给原文件 SHA 与 captured document_digest 不符时，池标为 `source_changed`，旧分配不能新增采用或计为合格现货；不会回退旧库存版本、补出未知数量或改写 ERP。
- 新增余额确认专用预览，绑定当前租户/项目/确认人、余额及交易行/前次版本、所选证据元数据、确认/撤回结论和理由。GET 列表摘要不能充当批准摘要；保存锁后重新预览，身份、权限、来源或所选证据漂移拒绝。相同请求重试保持原回执，页面保留原输入与请求号。
- 已确认余额的凭据 SHA 后续改变时，不删除旧记录，而是停止当前采用，原领料重新进入待对账扣量；新对账/分配和原异常具名复核后再采用。供给新版本、归还/冲正、共享撤销等现有变化也继续使原来源待核。
- 原异常详情新增 `closure` 当前来源投影：只有当前最新具名 supply_ready 或正式 scope_changed 才提供 `exception_id/review_id/source_digest` 引用。供应页面仅在有效引用下显示到原 Issue 的具名验证入口；不足、变更或未复核不显示。共享证据沿既有原行/双方确认入口回查，不拼出跨项目整份文件链接。
- `validate_material_issue_closure` 供共同 Issue 状态机在原锁事务内调用：精确绑定原 Issue/异常/最新 review，获取池锁再核对当前来源，不执行关闭动作，不绕过指定验证人、四眼规则、Issue 版本或关闭证据。具体输入、URL 字段、409 和审计接缝见 [统筹接口](coordination-needs.md)。正式 baseline 替换/节点移除的排程桥缺口保持统筹归属，本线不自动 release/rebind 或修改正式日期。

## 已执行检查

| 检查 | 本轮结果及覆盖 |
|---|---|
| 纯投影/受影响回归 | **18 passed**：[最终输出](../../../../../output/parallel-supply-20260930/recovery/backend-tests-final.txt)。包含 8 项新恢复投影及物料覆盖/池算术；SQL 查询替身用例仅为纯算术，不能算作 PostgreSQL 证据。最后凭据采用守卫改变后重跑受影响范围；此前输出保留，不重复累计。 |
| 页面确认与恢复入口 | **7 passed**：[输出](../../../../../output/parallel-supply-20260930/recovery/frontend-tests-r1.txt)。专用预览绑定、换证据阻断、网络不明保留输入/请求、失效预览拒绝保存、类型化原 Issue 链接与失效入口抑制。 |
| 新具体 BFF | **3 passed**：[最终输出](../../../../../output/parallel-supply-20260930/recovery/bff-tests-final.txt)。会话、路径/体积、no-store、指定后端路径及 409 透传。首轮断言误将实际 URL 对象当字符串比较，已修正测试并保留 [失败输出](../../../../../output/parallel-supply-20260930/recovery/bff-tests.txt)。未执行实际 HTTP。 |
| 后端静态 | [Ruff](../../../../../output/parallel-supply-20260930/recovery/backend-lint.txt)、[Mypy 6 个目标](../../../../../output/parallel-supply-20260930/recovery/backend-types-final.txt)通过。Mypy 使用 follow-imports=silent，范围内文件实际检查，不将并行共同文件的导入诊断冒充已修复；最初共有 schedule_resource_feedback 类型诊断及本线修复前输出保留。 |
| 前端静态 | 组件/原供应视图 [lint](../../../../../output/parallel-supply-20260930/recovery/frontend-lint-r1.txt)、新 [BFF lint](../../../../../output/parallel-supply-20260930/recovery/bff-lint.txt)、证据链接增量 [lint](../../../../../output/parallel-supply-20260930/recovery/source-link-lint.txt)、最终全项目 `tsc --noEmit --incremental false` [无诊断](../../../../../output/parallel-supply-20260930/recovery/frontend-types-final.txt)。未执行 Next 类型生成、完整构建或浏览器。 |
| PostgreSQL 新用例 | **15 项仅完成代码和静态检查，全部未执行**。真实服务/权限/锁/审计及失败恢复设计见 [联验计划](postgres-test-plan.md)。原数据库测试不重复运行。 |

## 候选与剩余条件

开工前的 21 份相关文件摘要见 [baseline](baseline.json)，原脏树内容保留在本线日志的 baseline-sources。最终精确源文件、修改前后摘要及依赖摘要见 [candidate](candidate.json)；只记录本线 15 份改动，不把上轮或并行会话改动计入本轮。原始日志在 `output/parallel-supply-20260930/recovery/`。唯一清单仍由统筹原位维护，本报告不替代活动清单。

本轮未连接 57432/57433/57434/57439 或上轮 57440，未读取 `.env` 获取测试地址、探测/迁移/清理数据库、启动共享服务、调用模型或发送真实数据。恢复条件是统筹核对并分配一个新独占临时 `pdos_test`，完成共有关闭接缝后执行新 15 项及集中 HTTP/浏览器；无授权地址不尝试旧环境。

未完成：共同 Issue/work-card 的 typed 输入和锁内守卫/审计/409 接入；数据库写入/约束/并发/回滚的实际证明；供应恢复到原 Issue 具名验证关闭的实际页面链；基线替换/节点移除的旧 waiting 影响接续。成本降本不在本轮实施。真实 ERP/供给/质量和业务效果、逐能力 AI 资格、生产/外发及原 N/P/Q 人工出口没有据本候选通过。
