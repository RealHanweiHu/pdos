# M3 三入口 G0 → 项目承接检查点（2026-10-16）

客户需求、自主新品、派生迭代使用同一具名 G0 决定。页面现在可明确填写新型号/新变体名称、选择变体类别，确认时按提交固定副本显示实际目标；批准后读取实际决定、型号/变体、封存定义 v1、项目与带入任务/风险，并直接进入对应项目驾驶舱。退回、不立项不产生承接结果。

依据：v1.1 §03.14、§08.11、附录 A `proposal.g0.decide`、AT-06/AT-52；这是三入口的人工 G0 与项目承接闭环，未将其表述为三入口完整 AI 或 S1 验收。候选基于 `d06f202`，源码摘要和最终构建见 [source-manifest.json](source-manifest.json)。无迁移，实库 head 仍为 `s0_0760`。

## 实现与业务边界

- 新增提案内只读 `/handoff` 快照投影：按当前提案受众和实际对象权限读取，核对决定、来源提交、封存 v1、产品/变体及项目产品关联。具名历史签发后不因签发人后来失去 PM 权限而改写历史。
- 页面将服务器批准结果与当前决定、回执、具名身份、品类、提案、定义及项目逐一绑定；失败不沿用旧卡片，显式重新读取。BFF 只放行对应无查询参数的 GET，保持 no-store。
- 决定仍走既有 T2 人工预览与确认，未新增 AI 批准权。固定立项副本保留草稿与未知；项目中的规格冻结、专业签名、正式发布及承诺仍独立办理。

## 必要验证

| 范围 | 结果与证据 |
| --- | --- |
| 独立 PostgreSQL | [5 项通过](checks/g0-handoff-pg-first.log)：三入口实际创建/提交/批准/读取，原命令重放同回执，实际型号或变体/封存 v1/项目/任务与风险，重复读取业务计数不变，越租户拒绝，签发人事后权限变化，退回/不立项无项目 |
| 前端/BFF | [41 项通过](checks/web-first.log)：固定目标、具名变体身份与确认、实际结果绑定、错误范围/回执/定义/事项拒绝、BFF 方法/参数/无缓存；[类型](checks/typecheck-first.log)、[规范](checks/lint-first.log)、[Ruff](checks/ruff-final.log)通过 |
| 最终候选 | 浏览器发现原始 `assigned` 展示后，仅补中文状态；[最终规范](checks/lint-localized.log)与[最终生产构建](checks/build-localized.log)通过。5 项 PG/41 项前端覆盖变更逻辑，最终构建及后述浏览器覆盖最后的展示改动；未新增镜像文案测试 |
| 客户/新品页面 | [客户实际确认→承接→驾驶舱](browser/customer-flow.log)、[自主新品整链](browser/new-product-flow.log)通过；对应项目固定 v1、2 个实际任务/风险均可读 |
| 变体与保存不确定恢复 | [实际变体结果→刷新→驾驶舱](browser/variant-refresh-recovery.log)：保留同一父型号，创建具名客户变体，固定变体定义 v1，带入 8 项，刷新 POST=0。首次注入的保存响应回调未在等待窗口内完成；刷新后取得已保存结果。未取得浏览器内“二次原请求回执对照”，该项只由前述 PG 重放检查覆盖 |
| 读取失败/恢复及窄屏 | [最终页面](browser/handoff-read-recovery-final.log)：注入 handoff 读取失败时结果链接=0，人工重读恢复原对象，POST=0；1440px 亮色及 320px 暗色检查，暗色 scrollWidth=320 |
| 实际去重 | [浏览器后实库快照](checks/browser-db-snapshot.json)：独立合成租户有 3 个决定、3 个项目、3 条项目产品关联、12 项带入事项；产品 3（含原夹具型号）、变体 1、定义 4（含合成父版）。没有重复项目或变体 |

页面证据：[最终桌面亮色](browser/customer-handoff-final-desktop-light.png)、[最终手机暗色](browser/customer-handoff-final-mobile-dark.png)、[客户驾驶舱](browser/customer-cockpit-desktop-light.png)、[新品驾驶舱](browser/new-product-cockpit-desktop-light.png)、[变体确认](browser/variant-confirm-desktop-light.png)、[变体驾驶舱](browser/variant-cockpit-desktop-light.png)、[读取失败](browser/handoff-read-failure.png)。

## 环境、失败与剩余工作

只使用已核对 marker 的独立 `127.0.0.1:64245/pdos_test`，不回退 `.env`。浏览器专用 8036/3036、独有 Playwright 会话；合成客户原件走真实上传与隔离解析，但安全扫描器明确为测试夹具。首次预览未配置相同扫描运行时而按规则拒绝，修正临时预览配置后通过，未修改业务安全条件。初始定位器/短等待与注入回调中断日志保留于 browser/，不是额外通过病例。61 条既有 Session.flush 弃用警告保留于 PG 日志。公开终端输出仅规范换行与尾空白，原字节保留于本机私有 .local。

未做正式 p95 或完整性能/恢复验收；浏览器短等待曾超时，不据此宣称秒级 SLO 通过。未重复全量回归或攻防。工作流在本轮预览中关闭，真实模型调用 0，不授予扫描、T0、专业或生产资格。

下一步仍为三入口小Pai实际运行/演示及暴露的业务缺口，私有全文与跨对象出站绑定、正式性能/恢复和完整 M3/S1 出口。停用本轮自有临时服务/浏览器，保留合成数据及必要证据，共用数据库、Temporal、运行时状态库和搜索服务保持。
