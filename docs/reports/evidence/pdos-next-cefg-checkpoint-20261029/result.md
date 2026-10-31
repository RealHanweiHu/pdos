# C/E/F/G 本地检查点（2026-10-29）

本检查点已完成：C/E/F 原生浏览器、G/I14、B/D、CTA/taint、13 类功能恢复及正式性能均通过。当前 head 为 **s0_0850**。逐轮结果、候选边界与证据哈希见 [verification-manifest](verification-manifest.json)。

| 范围 | 结果与直接证据 |
|---|---|
| 前端候选 | [生产构建](frontend-cefg-candidate1-build-result.json)通过，48.61 秒；[747 项输入哈希](frontend-cefg-candidate1-inputs.json)在 build、浏览器与最终核对间保持一致。[前端 43 项、最终输入核对与离线合同导出](integrated-checks.json)通过。 |
| 最终静态/纯检查 | [145 项整合纯测](pure-integrated-final.xml)与后续 26 项无交集，分段共 **171 个唯一纯测通过**；[65 个 Python 文件 Ruff](ruff-integrated-final2.txt)与后续 [query.py 单文件 Ruff](../pdos-next-search-performance-20261029/ruff-query-state.txt)分段通过（66 文件），[最终 Python 输入哈希](final-python-inputs.json)已固定。正式编译范围 [ESLint 0 errors / 6 warnings](eslint-compiler-scope-run1.txt)。 |
| 查询性能修复回归 | [query.py 增量](../pdos-next-search-performance-20261029/query-state-delta.json)将普通 RLS 的 SearchSource 元数据在同一最终 SQL 语句中物化复用；[精确 patch](../pdos-next-search-performance-20261029/query-state-materialization.patch)。[26 项纯测](../pdos-next-search-performance-20261029/pure-state-metadata-run1.xml)与 [5 项实际权限/恢复回归](../pdos-next-search-performance-20261029/pg-state-metadata-run1.xml)分别通过，覆盖私有/租户过滤、撤回即时生效、损坏投影、扫描目标缓存回退及一跳关系。两轮分别保留，唯一用例计数见 [最终汇总](integrated-checks.json)。 |
| C/E/F 原生 UI | [实际步骤、截图与刷新读回](browser-native-ui/steps.md)、[fresh 本人核验](browser-native-ui/web-verified.json)、[fixture 公开结果](browser-native-ui/native-fixture-public-summary.json)：exit 0、native_ui_checks_passed=true。 |
| G 钉钉 | **17 个唯一实际用例按 5＋3＋1＋8 分段通过**。[独立报告](../pdos-next-dingtalk-20261029/result.md)保留各轮 XML/E3 日志、0845 持锁与 0847 局部变量消歧的修复及迁移往返。 |
| I14 完整动作来源 | [9 项实际 HTTP/Temporal](../pdos-next-action-footprint-20261029/pg-run2.xml)通过：完整来源 3＋原复验续接 6。[原失败与修复](../pdos-next-action-footprint-20261029/result.md)。 |
| E 设置与原入口 | [同轮 20 项](../pdos-next-summary-setup-20261029/pg-summary-run1.xml)通过：新设置/网关 16＋原个人摘要入口 3＋原 Temporal 1。[E3 日志](../pdos-next-assistant-combined-20261029/pg-summary-setup-run1.txt)。 |
| X2 当前候选与证据 | [合组 11 项](../pdos-next-x2-candidate-state-20261029/pg-evidence-x2-run1.xml)通过。[E3 日志](../pdos-next-assistant-combined-20261029/pg-evidence-x2-candidate-run1.txt)。 |
| D 三类原生来源 | 项目具名状态、制造草稿/正式文档、物理交接 **3 项按 1＋1＋1 分段通过**。[报告与各段 XML](../pdos-next-role-native-sources-20261029/result.md)保留修复及夹具失败。 |
| B 当前项目原生依据 | **7 项按 6＋1 分段通过**：[首轮 6 pass / 1 初始化失败](../pdos-next-project-current-context-20261029/pg-native-final-run1.xml)，真实 peer 上传来源夹具修正后的 [run3 唯一余项通过](../pdos-next-project-current-context-20261029/pg-native-revoke-run3.xml)。 |
| CTA 与动作 taint | **6 个唯一实际用例按 4＋2 分段通过**：[原生 CTA 4](../pdos-next-work-followup-20261029/pg-work-taint-final-run1.xml)；[最终 taint 1＋原复验 positive 1](../pdos-next-action-taint-20261029/pg-taint-verification-run3.xml)，[E3 日志](../pdos-next-assistant-combined-20261029/pg-taint-verification-run3.txt)179.82 秒。 |
| 13 类功能恢复 | [同轮 3 项](../pdos-next-role-native-sources-20261029/pg-thirteen-recovery-functional-run1.xml)通过：全派生表损坏后重建、Outbox 重放不重复、固定索引批次 worker 重启恢复。 |
| 13 类正式性能 | [run3 XML](../pdos-next-role-native-sources-20261029/pg-thirteen-performance-run3.xml)与 [E3 日志](../pdos-next-assistant-combined-20261029/pg-thirteen-family-performance-run3.txt)通过：**71 来源／13 类**，预热 5 轮、测量 40 轮；search p95 **0.9663491212s**，verify 13/59 项 **0.5147289586s / 0.6745712569s**，SQL **5/4/4**，均满足原 1s 门槛。 |
| 迁移与保留守卫 | [0850 真实备份及 up/down/up](../pdos-next-project-current-context-20261029/migration-0850.json)通过；[0843/0845/0849/0850 四条 exact 非空 guard](final-history-guards.json)均拒绝破坏性降级，rollback 后 head、计数、函数与 policies 保持。 |

C 独立连接与停用 profile v1 已保存，刷新后预算/费用/批次/调用可读；客户原件未选。F 原个人回答保存知识后，普通页刷新读到 v1；fixture 核对知识 1 / Human review 1 / gap 1。gap 的持久归属由 fixture 核验，普通 UI 刷新重读证据止于知识页。E 摘要 draft→active 共 2 版本、服务授权 1，刷新可读；本次 UI 验证涵盖创建与启用。最终还核对 managed connection 1 / MemoryKMS write 1 / profile 1、原个人 Run/回答保持、Artifact 仍 1，新增通用 Run、钱包、技能启用和 EmbeddingCall 均为 0。[公开结果](browser-native-ui/native-fixture-public-summary.json)附原文件哈希；浏览器、fixture 与专用 Web 已统一清理。

关键失败记录继续保留：CTA 合组原有 known_configuration 缺失的 setup error；[taint run2](../pdos-next-action-taint-20261029/pg-taint-verification-run2.xml)的夹具曾错误假定 parent private=false，修正为原生项目实际 private scope 后，最终 run3 核实 customer_original 初始未登记、child 重新分类与真实出站路径拒绝。B/D/G 的原失败与后续通过分别链接于上表。

性能原失败保留：[run2 XML](../pdos-next-role-native-sources-20261029/pg-thirteen-performance-run2.xml)与 [E3 日志](../pdos-next-assistant-combined-20261029/pg-thirteen-family-performance-run2.txt)记录同为 71 来源／13 类、5 轮预热／40 轮测量，search p95 **1.0259137981s** 超过 1s；verify 13/59 项 **0.5053929361s / 0.5013382480s**、SQL **5/4/4**。[run1](../pdos-next-role-native-sources-20261029/pg-thirteen-performance-run1.xml)计时前的夹具 QUALIFICATION_REQUIRED 失败也保留。

边界：[无过滤全目录 ESLint](eslint-full-run1.txt)保留既有排除副本 `use-work-products 2.ts:12` 的解析错误（1 error / 8 warnings）；真实模型、真实 Embedding、真实钉钉发送与真实材料质量验收暂缓。上述验证采用本地隔离环境、合成材料与受控 provider/协议端口。唯一活动任务清单由 root 更新。

后续增量已完成：Change详情/标题提示、项目本人讨论回看和摘要同时私发钉钉另有[最终本地验收](../pdos-next-two-designs-20261028/local-acceptance-20261029.md)。本报告仍只对应上述747输入的CEFG候选；后续757输入、0851/0852及浏览器证据独立保留，完整质量验收状态以唯一清单为准。
