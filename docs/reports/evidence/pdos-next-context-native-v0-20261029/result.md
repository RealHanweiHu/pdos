# 上下文题原生回放与本地修复

2026-10-29 UTC。按用户委托已制作40道岗位题、12道上下文题及24份合成资料；本轮补完12题×两档F的24格本地原生控制回放。真实模型、embedding和外部渠道调用均为0。题集仍为合成候选，未写入golden-case。

## 本轮真实修复

1. `DomainReads`的parameters/knowledge/competitors列表每次生成顶层as_of，导致同一结果句柄的第二页误报SOURCE_STALE。恢复时重新执行普通READ及权限检查，仅保留原顶层观测时刻，其余字段仍比较完整摘要；自定义read_tools不继承该适配。实际正文/版本/嵌套字段变化及撤权仍拒绝。见[失败复现](ctx09-clock-reproduction2/native.xml)及[最终原生回归](native-regression-frozen-final/native.xml)。
2. 工作状态已经保留待确认候选的kind/operation/state/receipt_id，技能资料schema却未登记，新候选续轮因此被context_schema_mismatch拒绝。仅登记现有白名单四字段，保留实际枚举、null与additionalProperties=false；未知及私有payload字段仍拒绝。27项新增纯回归覆盖该合同。真实失败见[修复前F64](ctx11-candidate-run3/native.xml)。

另外修正了夹具的原文引用行号、provider记录器误收emit，以及只数主循环而漏记隔离子图预算的观测器；完整账本和所有脚本派发均保留。

## 冻结候选验证

| 范围 | 最终结果 | 证据 |
| --- | --- | --- |
| 受影响纯检查 | 174通过，12项原生用例按显式环境守卫跳过 | [pure.xml](pure-frozen-final2/pure.xml) |
| 完整24格回放＋10项相关纯检查 | 34通过；24/24观察记录 | [原生XML](native-candidate2/native.xml)、[逐格结果](native-candidate2/result.md) |
| 原六项失败＋服务详情＋三类入口＋分页恢复/变更/撤权 | 17通过；原六项再次6/6 | [最终原生回归](native-regression-frozen-final/native.xml) |
| 去重统计 | 174项纯检查＋41项原生控制/回归 | [最终检查点](final-checkpoint.json) |
| 静态检查 | 11个Python文件Ruff通过，schema可解析 | [Ruff](ruff-frozen-final.txt) |
| 候选一致性 | 856项生产/框架/技能schema与正文/夹具/原题输入，回放及补验前后哈希一致 | [完整摘要](native-candidate2/baseline.json)、[补验核对](native-regression-frozen-final/source-verification.json) |

独立目标为127.0.0.1:53502/pdos_test，marker f117bb5b-b3d7-4286-aaec-c54d9255e96b，head s0_0853；无迁移。此前前端与生产构建证据保留原检查点，本轮仅有后端/schema/评测工具改动，未重跑未变化的UI或构建。

## 24格的实际含义

18格原生绑定完整，5格部分绑定，1格预算不足未执行候选链。34项控制检查通过不等于24格回答质量通过：

- CTX-01：两档均真实建立30轮会话并回读早期轮次；32次脚本派发/档，最高准入43608。原题原话及物化SHA保持。
- CTX-02/03/05/06/07/08：干扰、精确编号、焦点切换、解除排除、版本更新和撤权均取真实来源、引用或工作状态；两档控制通过。
- CTX-04两档部分绑定：项目与任务、负责人实际登记；建议日期来自所选不可变资料，未把它伪造成WorkTask日期或已接受承诺。
- CTX-09两档部分绑定：同句柄第二页成功、第三页实际失败并保留缺页；生产分页单位为JSON片段，不能声称已读6/9个业务条目。
- CTX-10两档绑定完整：24条必要约束真实保存且超过STATE1500，原生prepare阶段明确partial、缺项可见、模型账本和派发为0。这是必要状态超限控制通过。
- CTX-11：F48000实际需要50185，在生成候选前停止；F64000最高51849，旧候选pending及原事件摘要不变，新标题生成新的pending，创建/指派回执增量为0。
- CTX-12：普通品类读取变体中，8份各4695字符原文通过实际passage READ区间并集合并核对；F48000最终需要48298而停止，F64000完成读取。每档54/55次脚本派发。主循环不平铺原文。

CTX-12显式变体为category_scoped_read_without_fixed_pins，符合原题未要求固定选择八份资料的范围；原fixed_pins_eight_sources变体可重放，旧STATE1436→1681、固定选择元数据898及STATE1500超限诊断保留，未改F、STATE上限、原题或标签。见[原固定选择诊断](ctx12-state-diagnostic.json)及[新变体逐格结果](native-candidate2/baseline.json)。

完整回放共325次脚本provider派发；usage0仅为脚本占位，不是实际输入、费用、速度或缓存测量。答案正确率、引用语义忠实度和真实计量均未评分。本回放使用实际原生API/注册图/普通权限与账本，工作流启动由测试端记录，未把它冒充本轮Temporal或真实模型整链验收。

## 保留记录与剩余边界

原始失败、夹具修正、首次完整候选中止及普通取消记录均保留，见[过程与归属](task_plan.md)、[中止清理](native-candidate1/interruption-cleanup.json)。首次pure收集工具路径错误、混入三个PG入口而缺显式环境的记录也保留；最终已拆分并在正确环境通过，没有改写失败原件。

[52题与离线召回](../../../evaluations/xiaopai-v0/README.md)的macro recall@5/@10均97.92%，QUA-04漏召回仍保留。本轮不以脚本控制回放代替题集人工审阅、真实岗位题/真人试点、两档模型正确率或混合检索收益。部分绑定的项目日期/业务条目语义需后续审阅对齐。按用户要求暂不启用真实模型或embedding；没有真实发送、生产操作、提交或推送，未新起持久服务，既有测试库和Temporal保留。
