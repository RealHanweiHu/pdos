# 第二十波 · 共享回链签发人核对与真实配对业务 owner

已统一高级 Formal 的业务读取、回链预览/保存与历史重核：配对输出使用实际共同保存组的回执，当前调用者、门栓、宿主配置及有效期留在同阶段局部证明，不写入不可变输出。实际 HTTP、修复后的页面和末端存储回读通过；原直接 Draft 输出与私人范围保持。未宣称新的共享三人复验、独立 Review、有效性或关闭通过。

## 已完成

- 启动时将同一个 `LivePairedOwner` 注入配对业务 owner 和具名复核 owner。高级 Formal 的五类保存操作走真实 `read/refresh`，核对唯一 Current Run/身份、原子事实、原件、原专业依据及完整来源。多 Run、缺实际证明或配置变化拒绝，不猜最新记录，也不退用旧 Draft 回执。
- 共享 Link 先精确绑定原签发人、操作、用途和固定 Scope；仅专业历史重核使用原签发人，原问题、输出、来源、项目、政策与当前权限仍按真实读取人核对。当前 Principal/Grant、原政策/issuer epoch、完整来源及末端时钟共同约束读取。保存行保持不变。
- 输出枚举核对全部 Current 键、实际项目和可见范围，分别保留直接保存组和配对操作族；Formal 与 Run 合计超过 20 项拒绝，不截去第 21 项。页面只取得固定引用和真实回执，不取得门栓或跨阶段资格。
- 四类已有索引内的历史选择改为本地切换，清未发送填写/预览；Build/Run/Issue 改变仍重新读取，原 pending/UNKNOWN 恢复锁、私人清理及服务器 inputs/preview/execute 重核保留。尚未实测耗时，不报秒数提升。

## 验证证据与范围

[17 文件冻结影响选集 v2](affected-backend-v2.log) **511 项通过**。v1 仅因检查启动未加入既有测试 helper 路径而收集失败；修正执行环境后 v2 使用同一份运行和检查源码，未改业务来适配检查。配对包 28 项、签发/分派 52 项已包含于该选集，不再相加。[原 Draft 固定材料回归](root-fixed-output-pure-v1.log)将旧无签发人替身补成明确的完整边界替身，未放松真实守卫。纯检查包括显式替身，不冒充实际权限、配对或共享正例。

[44 项网页辅助检查](ui-speed-result-v1.json)、[159 份网页源码](web-candidate-source-v1.json)及[类型/lint/生产构建](web-build-result-v1.json)通过。全文 lint 保留原两条未使用变量警告，没有错误。临时定向类型配置、Root 静态及工具检查的原失败日志均保留；最终静态和冷 API 导入通过。

冻结源见 [v1](candidate-source-v1.json)及[v2](candidate-source-v2.json)：355 份服务器运行源/配置/迁移、17 份后端检查源、159 份网页源/配置、两个实际检查工具。v2 仅修正实际读取工具的回执查找：由真实配对 action/Current Run 的保存组核对，移除对不存在的 next-request 回执结果键的假设；v1 在实际 HTTP 前失败，原日志保留。运行、后端检查和网页逐文件与 v1 保持，不重复已通过的同源验证。

实际 [HTTP v2](paired-actual-http-v2.json) 返回 200，耗时 230.037 秒：同范围 Formal v7/`test.results.import` 与 Run v3 使用同一真实配对回执 `2bf40754-969f-4455-9d62-090f12e9541f`；直接 Draft v1 保留自己原回执。输出不含 HostGate、runtime 或有效期。

首轮真实页面失败，见[原失败](browser-timeout-v1.json)及[截图](actual-read-timeout-v1.jpg)：页面深读仍为 180 秒，低于这个实际节点耗时，源锁等待还占用请求预算。仅将质量/变更/整改/结果 GET 的传输上限与现有独立 600 秒 dispatcher 对齐；写入原上限、请求原体及 UNKNOWN 恢复保持，不自动重发。修复后[31 项 BFF](deep-read-bff-v2.log)、[30 项整改转发](deep-read-followup-v2.log)及[4 项实际短合成传输检查](deep-read-transport-v1.log)分别通过。第一次 Node 多路径调用只实际选到这 4 项，原日志保留，两个 BFF 文件随后逐一直接运行，不冒充已覆盖。[最终网页 v2](web-build-result-v2.json) 的 159 文件类型/lint/构建通过。后台 355 运行源/17 检查源与 v2 完全相同，511 项不因网页窄修重复执行；[最终源 v3](candidate-source-v3.json)明确记录增量。

修复后真实页面完成冷读取并显示三个真实输出。[实际历史切换](browser-history-selection-v1.json)核对问题 v4→v5→v6、变更 v2→v1→v2、已有变更空选/恢复及固定失败空选/恢复；历史保持只读，四类入口完成 GET 计数在操作区间保持，未重读整条链。此处没有秒数 benchmark，不把 600 秒容忍当作后台提速。[独立 Review](browser-review-v1.json)默认候选空选、Rule/部分 Observation 历史保留，实际缺职责/资格与完整候选依据时具名预览禁用；未发 inputs、preview 或业务命令。

[末端回读](browser-storage-readback-v1.json)确认同 marker 62513、head `next_0026`、所列 24 张旧表摘要和候选2/Rule1/Observation1/Review0保持，原 HTTP 回读与浏览器后回读一致；533 个列明源哈希保持。本波业务命令和模型调用均0，无新迁移。所列表一致不等于整库一致；检查不冒充 PG、真实资格、物理复测或全树联合验收。下一段宿主配置暂存在隔离副本，未混入本候选。

## 继续衔接

复用当前 owner、共同保存组和完整来源读集，在全新合法共享资料及三位具名人员的案例里，先完成新 Run 的原值、复核/处置，再固定当前输出与候选、完整观察和独立 T2 Review。旧 private 不扩围，原失败原值/Rule/部分 Observation 不改写。真实资格、物理整改、有效性/分别关闭、G0～G5全量建设和原人工出口仍未完成。
