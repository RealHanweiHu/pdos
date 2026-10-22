# N0-03 普通员工路径的 rollout 强制验证

2026-09-10。上轮费用真实性切片是有效进展；本轮继续已批准DC-06的实际接线，N0-03仍部分完成。[运行合同](../contracts/pdos-runtime-v1/freeze-record.md)与完整设计§21规定shadow仅供评测/管理查看，不进入员工正常待办或应用；disabled不阻断已经合法应用的业务历史。

## 本轮实际变更

原13能力登记中supplier/executive为shadow，但实际dispatcher按Agent路由，工具与Finding服务未检查rollout。本轮新增共用`rollout_guard.py`，在普通员工执行路径要求live。未知能力/登记缺失fail-close，不以zone标签或旧“确认区”文字授权模型业务写；没有更改现有能力的默认rollout，也未推广新能力。

| 边界 | 接线与结果 |
|---|---|
| 事件dispatcher | 仅为具有live事件能力的Agent进入普通订阅/排队；shadow不借普通worker发起模型调用。扫描游标仍正常前进，不反复重放受抑制事件 |
| 已排队run | 领取后、构建上下文前复检；停用/变shadow时以degraded与CAPABILITY_DISABLED/SHADOW结束，工具和模型零调用 |
| 工具/模型 | 每个现有AgentReadTools入口经scope检查同时复检rollout；模型出站前与返回后再查，保留原冻结前缀与租户/项目边界 |
| 候选preflight/受限writer | 根据具体Agent+Finding type检查，不因同Agent其他能力live而放过已停用输出；实际writer入口再次复检 |
| 两个请求式入口 | 风险建议API与测试计划建议在调用前和候选写入前复检；初始停用HTTP409；模型返回后停用则记录degraded、返回unavailable和明确错误码，无Finding写入 |
| 列表与待办 | Finding列表、详情、Review Inbox、My Work及run列表的待审数量使用当前策略；隐藏未应用的shadow/disabled候选 |
| review/restore/apply | 复检具体能力；不能接受、恢复或应用停用候选。权限及真值复核照旧，已合法应用记录仍可按原权限读取并幂等回放，不新增业务事实 |

普通运行路径没有“自行指定shadow评测”的绕过参数。本片未实现独立评测调度、管理查看评测正文或其存储；因此shadow当前不在普通worker执行，不将其表示为正常no_action/无风险。领域人工流程及真实业务历史保持可用。

## 验证证据

测试前重新确认本机127.0.0.1:57432数据库为pdos_test，迁移head0059；所有数据库测试显式覆盖TEST_DATABASE_URL，模型均使用测试替身。未触碰开发/生产库，未修改共享登录角色或其密码，没有新迁移。

- 初轮7个文件：48 passed、2 failed；两处失败都是新测试把未构建run_context错误写成NULL。核对现有schema默认与实际行值均为`{}`，修正断言后2项通过；控制行为原本已正确阻止上下文与模型。
- 后续聚焦与请求式API：25 passed（含上述2项复验、2项新增工具复检，以及风险/测试计划现有与新回归）。
- 能力合同：8 passed（含2项新增，旧6项与首轮重叠）。最终9个文件共75个不同测试，全部已通过；不将复验重复计数。
- 共同对象/产品计划/版本时间、运行政策/工具/采用、日历：160 passed。与上面合计235个不同测试。
- Ruff及格式：22个本片源码/测试文件；Mypy：14个实际实现文件通过。最终合同导出/获批摘要复核见[机器证据](evidence/2026-09-10-n0-03-rollout-boundary.json)。

数据库行为覆盖：已排队后停用；shadow不排队；列表/审阅收件箱/我的工作一致隐藏；review/apply拒绝且无Risk写入；已应用历史和幂等回放仍成立。HTTP覆盖风险/测试计划调用前零模型调用、返回后停用不生成候选且运行终止；纯合同覆盖同Agent多能力混合live/disabled及未知登记。原phase-three投影实现的隔离测试仅用明确的合成test adoption临时切到live验证投影，不是模型资格、用户批准或生产启用。

## 尚未完成

本轮策略来自当前代码注册表。租户级持久策略发布、跨进程撤权同步、在途bundle/pin与生成时rollout证据、shadow独立评测/管理查看、事件抑制原因的持久观察、真实pdos_agent数据库角色端策略强制，以及全部来源ACL复检仍待后续N0-03实现。旧shadow历史不能在后续推广时直接作为新live候选，须由采用/版本迁移合同处理。本片未声称数据库stored procedure本身新增rollout限制。

工具循环、原子tenant/lineage/attempt预算与未知响应对账、等待/checkpoint恢复仍未完成。DC-06/07/08批准持续有效，不重复询问；新增领域资格/真实样本依所属N项，N0-06/N2-01以及P/Q/Sprint出口状态不变。没有生产、真实外发、git push或golden写入。
