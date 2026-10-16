# 指定项目的首版计划接续 · 2026-10-16

从项目列表或驾驶舱进入工作台时，原来只携带型号，计划页需要再次选择项目。这批将指定项目直接接到既有首版计划办理，完成“驾驶舱 → 计划候选 → 一次确认应用 → 回看原项目”。依据冻结 v1.1 §05 页面契约、§08.11 读取一致性及附录 A 的 `work.plan.propose/apply`，完善 S1 建项目后的接续；没有恢复 S2–S4 施工或增加阶段批准流程。

## 可用能力

- 项目入口带品类、型号和具体项目，直接打开“工作与计划”，项目已选定；可返回同一项目驾驶舱。内部页签保留项目上下文，主动切换型号时清除旧项目。
- 新增指定项目的普通授权 GET，复用现有计划读模型，在只读 RR 快照中读取目标。查询先限定项目，不受原列表最近 100 项截断；不存在、范围不符或失去权限时明确失败，不回退为其他项目或空集合。没有新增迁移或业务权限。
- 本机计划输入及待确认请求按“用户 × 型号 × 项目”保存；旧型号缓存只在项目匹配时复制进入当前项目，原缓存保留。其他项目输入/请求不会被载入或执行。重载只读，原请求须由用户明确重试；确认预览仍核对实际项目。
- 继续使用现有人工起草、预测、一次确认、原请求与领域回执。读取失败保留输入并可刷新，不再显示假空。批准基线、个人承诺和实绩仍分别显示未记录；未知估时和完成日期不补造。

## 验证与实际结果

基线 `17b6621`；源码和检查范围见 [source-manifest.json](source-manifest.json)。只使用核对过的独立 `127.0.0.1:64245/pdos_test`，标记 `f9048729-3f2a-4494-af75-56e1db7d743d`，head 保持 `s0_0762`。

| 覆盖 | 证据 |
| --- | --- |
| 指定项目实际 G0/候选/应用/原回执重放/驾驶舱读回，错误项目与授权到期无回退/零写入，既有首版计划及个人投影回归 | 集中 28 项通过＝27 项不同 PG + 1 项后端纯检查：[pg-final.log](checks/pg-final.log)。首轮新增 2 项重叠，不重复计数。 |
| 全局项目直达和实际 BFF | 48 项通过：[web-first.log](checks/web-first.log)。 |
| 真实组件的项目选择、缓存隔离、匹配旧输入、未知请求恢复/显式原样重试及失败刷新 | 最终 16 项通过：[component-final.log](checks/component-final.log)，与前项合计 64 项不同前端检查。 |
| 受影响规范、类型与生产构建 | [Ruff](checks/ruff-final.log)、[ESLint](checks/lint-final.log)、[最后新增测试 lint](checks/lint-incremental.log)、[TypeScript](checks/types-final.log)、[生产构建](checks/build-final.log)通过。最终仅增加一项组件恢复测试，随后组件/lint 增量复核；业务源码未改变，不重复构建。 |

实际浏览器使用普通合成人会话和生产构建。在原有第二个 G0 项目中输入两项任务：工程 60–120 分钟，NPI 依赖工程、估时未知。实际保存候选、取得确认预览并应用后，刷新仍是原项目的首版计划 v1；返回驾驶舱读到同一计划和 2 项任务。独立库只读核对为 **1 份候选、1 份计划、2 个工作包、2 项任务和 1 条依赖**，回执和计划 ID 见 [browser-write-audit.json](browser-write-audit.json)。

页面证据：[候选及未知传播](browser/candidate-open.md)、[实际一次确认范围](browser/apply-preview.md)、[应用后刷新](browser/plan-applied-reload.md)、[返回驾驶舱](browser/cockpit-after-plan.md)、[桌面亮色](browser/plan-applied-desktop.png)、[320px 暗色](browser/plan-mobile-dark.png)。移动文档宽度 320px，与视口一致；截图已查看。只在浏览器模拟项目 GET 503，页面有明确错误且没有假空，撤销模拟后刷新恢复实际计划，见[失败页面](browser/read-failure-mobile.png)、[恢复快照](browser/read-recovered-mobile.md)及[请求状态](browser/requests-final.log)。

保存响应丢失的浏览器模拟未取得证据：首次脚本调用格式错误；修正后 `route.fetch/fulfill` 出现“Route is already handled”，页面实际收到正常成功并应用计划，没有进入未知回执态。保留[原始记录](browser/apply-response-loss.log)与[初次调用记录](browser/apply-response-loss-runner-first.log)，不宣称该项浏览器通过。原回执重放由 PG 覆盖，未知保存请求重载及明确重试由真实组件检查覆盖。控制台其余记录为未登录 401、缺省 favicon 404 及合成读取 503，未冒充业务故障。

## 剩余

完整 M3/S1 未完成；实际模型/服务商协议/Temporal Worker、正式性能与恢复和实际浏览器保存丢失态仍需对应证据。首版计划后续修订、批准基线、承诺、实绩与资源/供应冲突继续按冻结阶段推进。

本批真实模型调用 0；无新增迁移、golden-case 写入、真实外发、push 或生产操作。仅关闭本轮自有预览与浏览器，保留共用独立测试库和运行时；原 UI 设计稿及其他聊天备注保持未提交。
