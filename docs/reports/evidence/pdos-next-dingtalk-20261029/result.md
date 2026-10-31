# 钉钉接入检查点（17 项实际用例分段通过）

本地隔离 PG/HTTP/Temporal 的 **17 个唯一实际用例已按 5＋3＋1＋8 分段通过**。它们沿原小Pai注册图、本人绑定、私发/明确群分享、持久投递回执、来源保留与并发持锁路径验证；下表同时列出每轮保留的失败。**不存在一次 17 项全量通跑的通过记录**，当前迁移 head 0849 也不等于在该 head 重新通跑了 17 项。

| 轮次 | XML / E3 原始日志 | 该轮实际结果与计入的通过段 |
|---|---|---|
| run2 | [XML](pg-run2.xml) / [原始日志](../pdos-next-assistant-combined-20261029/pg-dingtalk-run2.txt) | 5 通过、1 失败后停止；计入原生绑定、ack/未知回执恢复、本人/管理员撤回及维护角色边界 **5 项**。Temporal 主链在 provider.calls=0 与预期 5 的断言处失败。 |
| run4 | [XML](pg-run4.xml) / [原始日志](../pdos-next-assistant-combined-20261029/pg-dingtalk-run4.txt) | 3 通过、1 失败后停止；计入同小Pai Temporal 私发/群分享/丢回执主链和官方协议模拟的入站/持久查询、丢发送响应 **3 项**。官方协议模拟 Temporal completion 仍超时。 |
| run5 | [XML](pg-run5.xml) / [原始日志](../pdos-next-assistant-combined-20261029/pg-dingtalk-run5.txt) | 1 通过、1 失败后停止；计入官方协议模拟 Temporal 主链 **1 项**。双品类保留夹具传入不存在的 Context.product_id，在夹具构造处失败。 |
| run6 | [XML](pg-run6.xml) / [原始日志](../pdos-next-assistant-combined-20261029/pg-dingtalk-run6.txt) | **8 项全部通过**：4 项来源保留/原件 pending 或 quarantined/不可变 footprint，3 项撤回与配置变化持锁/固定 service scope，1 项 reserve 后 service 丢失及应用锁等待取消且不二次发送。 |

[首轮](pg-run1.xml)的绑定通过、ack 被误记 cancelled 的失败及[RLS 诊断](pg-run1-rls-diagnostic.json)保留。诊断显示 service 普通 SELECT 可见，而 Binding/App 的 FOR UPDATE 被 Human/admin 更新策略过滤；0845 合入固定实际 application→account 顺序的受控 metadata 持锁 helper，保留 runtime UPDATE RLS 关闭。[0845 实际备份及升级/降级/再升级](../pdos-next-source-compatibility-20261029/migration-0845.json)核对函数、ACL、历史计数不变；[原 0843 接入迁移往返](migration.json)也保留。

run2 的[主链诊断](pg-run2-main-diagnostic.json)记录 partial、预算不足且 0 次工具调用；合成 Temporal 夹具随后声明 200k 上下文窗口及独立合成运行记账额度，用于完整工具定义披露下的本地主链验证，生产路由和预算规则未因此放宽。[run3 XML](pg-run3.xml)及[原始日志](../pdos-next-assistant-combined-20261029/pg-dingtalk-run3.txt)仍保留 completion 超时：原始 Activity 错误明确是生命周期触发器中 categories 局部数组与 public.categories 表引用歧义。0847 仅把局部数组改名 source_categories；[函数预检](function-0847-preflight.json)及[0847 备份/往返](migration-0847.json)确认精确函数、原 owner/ACL 与历史计数不变，后续 run4 的原生 Temporal 主链通过。

run4 的官方协议模拟 completion 超时如实保留，日志本身没有给出足以断言真实钉钉故障的原因；该同一节点在 run5 通过。最终官方 MockTransport 具备个人/群消息查询终态回执；这些是协议适配器的本地模拟证据。run5 的 Context.product_id 错误则仅修正夹具，把产品范围留在实际 setup/命令中，Context 只替换合法 category 字段；run6 双品类保留及其余 7 项通过，未扩大正式权限或绕过原件状态。

原 89 项 root 纯测与暂存候选 298 项前端/类型检查属于此前证据；[service 丢失 14 项纯检查](pure-service-loss-run1.xml)独立记录，不用这些数量替代上面的 17 项实际用例。当前结果不宣称新增通用 taint 覆盖、全域性能或一次最终候选全套验收。**真实模型、真实钉钉发送及真实业务数据外发均未执行**；官方协议链使用 MockTransport，实际命名来源和扫描材料均为受控合成夹具。
