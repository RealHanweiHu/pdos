# N0-03 持久工具观察与模型上下文关联验证

2026-09-10，本地候选0076。实际读取节点生成已批准Observation DTO，Gateway验证出站上下文记录，模型trace与观察链通过租户/run复合外键关联。[操作及边界](../runbooks/agent-tool-observations.md)。N0-03保持部分完成。

## 结果

123项不同测试通过，含18项新增、105项回归。实际Worker/Agent账号验证在独立临时pdos_test完成；HTTP模型、资格及故障注入全部是合成手段，没有真实模型请求。

- 实际配置工厂生成顺序连续的项目/事件/知识观察；未配嵌入时明确unavailable及未知总量，真实25条增量事件触发分页partial及续读提示。数据库实际正文摘要、DTO、SourceRef及模型可见摘要一致。
- HTTP捕获的实际PDOS_CONTEXT_JSON与冻结出站上下文相同。允许出站字段在冻结后改变会在Gateway准入前拒绝，内部字段被过滤，不会为了“保持一致”而泄露。
- 相同内容幂等；乱序/缺失观察、冲突正文、跨scope参数、错工具及外租户来源拒绝。两个并发追加使用同一个观察/sequence和原时间；调用冻结后新增但未选择的观察不会被伪装成模型已消费。
- 三张新表对Agent/Worker不可直接读写，Owner直接删除历史也拒绝。trace缺run或指向另一run的上下文记录被数据库拒绝；schema/metadata与迁移一致。
- 工具异常产生固定失败观察，错误路径零模型；模型无可用选择且没有trace时保留MODEL_NOT_AVAILABLE/degraded。没有伪造invocation或checkpoint。
- 新执行器恢复原模型结果时复用原观察/上下文记录，模型/嵌入不增加。原租约、触发期限、受限数据库、网关及工具回归通过；空历史迁移往返及持久证据拒绝降级通过。

计数去重：实际角色批次68项（17新增+25 checkpoint+9权限+17触发），共享网关/工具/schema54项（初轮51通过、3项旧断言修复后通过），后补分页1项，共68+54+1=123。最终18项观察用例和17项网关schema分别完整复验，不重复累加。

## 发现与修复

全新临时PG首轮25个checkpoint用例均在fixture初始化失败：0075新增的列权限撤销没有检查角色存在。补齐角色/列存在检查后恢复；未以预建假角色掩盖撤销脚本缺陷。

第二轮37项通过，1项仅匹配旧checkpoint降级错误的断言失败。现在0076观察历史保护先拒绝降级，断言明确接受两种持久历史保护，不关闭保护。后续68项实际账号批次全部通过。

共享回归的三个失败分别是精确列集合缺context_receipt_id，以及两条费用迁移测试写死0067为head。补列并使用Alembic当前单head核对事务回滚版本，保留精确集合和费用证据拒绝降级断言；17项schema复验通过。

类型检查修正工具SourceRef的UUID/事件整数联合类型和LangGraph节点回调包装；未改变旧工具权限或业务应用出口。实际观察时间与幂等重放时间分开，重复写不刷新旧证据。

## 检查与环境

Ruff/format10文件、Mypy5实现文件、三个DBA窄函数与不可变迁移快照一致性、共同合同4产物和运行合同5产物漂移检查通过；获批draft.3两份manifest哈希不变。无前端变更。

独立真实角色测试仅`pdos-observation-test`（127.0.0.1:57433/pdos_test）；共享回归仅57432/pdos_test，两个环境变量显式绑定测试库，不修改共享角色。schema测试包含空历史downgrade/upgrade及有证据降级拒绝，最终两库head为0076。专用容器验证后删除。

机器证据见[记录](evidence/2026-09-10-n0-03-tool-observation-receipts.json)。未git push、未真实模型/嵌入请求、未golden写入、未生产操作；生产release、delivery=false、P/Q/Sprint出口保持。

## 未完成

当前ContextReceipt记录准备调用的投影和观察选择，不是完整ContextManifest或完整请求字节记录；无trace或零派发不能算模型已消费。完整授权envelope、运行/模型资格版本束、Context修订/压缩及遗漏原因、全部衍生来源ACL、工具调用前预留、模型—工具循环、持久等待和分步checkpoint、Owner租约及生产保留策略继续。此片完成不关闭N0-03。
