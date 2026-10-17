# S4 制造基线具名发布功能检查点

已接通实际项目与固定制造准备资料 → T2 具名发布 → 明确续接当前发布 → 历史固定内容回读。独立发布账本与 Current 保留原 T1 草稿，发布不授予资产资格、试产开工或制造放行。S1–S4 正式验收均未完成，性能按 P13 暂缓。

- [实际 API/独立 PostgreSQL 完整场景](actual-publication-04.json)：1 passed，131.06秒，源码未变。包含2版、跨人员回读、原键/异键重放、实际共同尾部失败全回滚、原件撤回后保留历史并拒绝新发布。属于合成原件及受控合成专业资格，不代表真实资格或生产启用。
- [页面完整记录](browser-final.json)：同一合成范围办理首版及具名续版，回读两版固定内容；升级前后原请求摘要相同，确认前零 execute，结果留完整实际回执。覆盖1440桌面亮色与390px窄屏暗色，无横向溢出；未声称全尺寸全浏览器矩阵或真实用户验收。
- [后端295项受影响纯检查](affected-pure-04.json)、[最终前端134项](web-checks-04.json)、[类型与lint](web-static-04.json)、[生产构建](production-build-04.json)通过。后端实际候选为 `/private/tmp/pdos-s4-publication-594m5l8p`；最终前端候选 `/private/tmp/pdos-s4-publication-gb4y6jtn` 的本闭环29个后端文件逐项一致，重用对应后台检查；其他变化属于独立M2/M3/UI上下文，未交付或冒充整仓回归。
- [静态范围](scoped-checks-04.json)：29个Python文件lint、26文件格式通过；3个共享文件保留已证明的原有格式差异，见[记录](preexisting-shared-format.json)。
- [迁移与metadata](migration-checks-reuse-04.json)：先私有备份0776，再0777升/降/升；实际metadata无新增upgrade ops。旧循环FK排序警告保留，3张新表的实际DDL/FK目标已独立核对。出现决定历史后不再降级或删除历史。旧全namespace目录完整性断言排除1项；只登记本次3表，其他未知没有被默认为已接线。

前序失败均留证：actual01为UUID嵌套字典未递归JSON投影；actual02/03为原命令省略默认字段而保存语义补齐导致约束不等。修复只规范持久化投影，原请求/key/token与共同请求摘要保持。首次浏览器inputs200但浅比较拒绝同一默认值，[失败及诊断](browser-attempt-01.json)保留；仅比较已知四个默认值，实际非null/来源/固定引用差异仍拒绝。初始lint分组错误及pnpm依赖bootstrap失败也保留，最终使用已安装Node CLI通过。

下一步仍是实际Pilot持久/API/UI、原始观察修正与固定分母/互斥终态统计、异常回链，以及实际资产验收、分别放行和外部接收/生效。S3一天观察期与有效性/关闭继续保留；真实模型、KMS、外发、push、部署及生产均未执行。

最终前端候选仅补成功态提示、去重说明及阻止重复提交，已对既有v1/v2只读回验；实际首次/续版写入分别由browser-final.json列明的前端候选执行，同一后台与命令策略未改。独立S1/M2的新agent-session读取对旧后台返回2次404，列入页面限制且不在本交付范围；不宣称全页零错误。
