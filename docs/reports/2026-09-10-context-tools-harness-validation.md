# 上下文、工具与 Harness 设计检查记录

日期：2026-09-10。对应[运行设计合同](../design/2026-09-10-ai-context-tools-harness-contract.md)、[统一架构](../design/2026-09-10-ai-native-architecture-consistency-contract.md)与[整合清单v1.3](../../tasks/ai-native-integrated-todo.md)。

**本轮完成详细设计与静态检查，未实现新的运行能力或通过功能验收。** 设计补充回填原N项，65项编号、依赖与状态不变；N0-01仍部分完成，其余64项未完成。

## 1. 方法与代码取证

按用户要求继续使用 `ai-agent-engineering`，完整读取信息生命周期、ACI工具设计、Harness五功能三个reference；另分派只读审查上下文、工具执行链与员工运行场景。根据统一架构收口后的边界设计增量合同，没有重新引入模型业务直写或只读输出的人为审批。

| 核对位置 | 本轮确认的事实 | 设计中区分的差距 |
|---|---|---|
| [runtime_contract.py](../../server/app/ai/runtime_contract.py)、[context_builder.py](../../server/app/ai/context_builder.py)、[S4-4合同](../design/2026-08-12-s4-4-context-builder-layers-contract.md) | 已有v2四层、固定persona、project范围、文档片段上限及确定性预聚合 | 不是新授权主体、typed scope、逐次manifest/Observation或完整工作记忆；原数据出口/分类约束仍生效 |
| [context_projection.py](../../server/app/ai/context_projection.py)、[gateway.py](../../server/app/ai/gateway.py) | 已有出口字段投影、模型资格、结构化尝试及用量/缓存token记录 | 出口字段白名单不能代替来源ACL；缓存计量不等于已实现带撤权治理的应用缓存 |
| [tools.py](../../server/app/ai/tools.py) | ToolDefinition只有名称、描述、输入示例；部分只读handler已有分页/范围校验 | 不是统一schema/handler/副作用/恢复注册合同；reach工具名称出现不能证明主执行器会调用 |
| [executor.py](../../server/app/ai/executor.py)、[capability_contract.py](../../server/app/ai/capability_contract.py) | 主图固定取项目/事件/记忆/领域证据后单次调用；13个capability登记 | 尚非模型选择工具、执行、追加观察和续读循环；专业建议不能继续全部等同Risk载荷 |
| [application_gateway.py](../../server/app/ai/application_gateway.py)、[debate_runtime.py](../../server/app/ai/debate_runtime.py) | 前者构建模型Gateway；后者接注入的SeatSpeaker协议 | 不能将模型Gateway称作人工应用入口；协议/stub不代表真实多席位模型接线 |
| [run_store.py](../../server/app/ai/run_store.py)、[agent-runtime.sql](../../infra/postgres/security/agent-runtime.sql)、[test_plan_suggestions.py](../../server/app/ai/test_plan_suggestions.py) | 合法运行下context可整体更新，测试计划续聊写旧context的superseded_by | Python冻结类型不等于数据库正文不可改；目标合同分开manifest/观察与可变lease/替代关系，需兼容改造 |

本轮对持久化相关位置作静态复核，没有连接数据库或构造运行故障，因此不声称发现已经复现的线上漏洞。

## 2. 详细设计已明确的内容

- **上下文**：授权envelope与模型包分开；每次调用的manifest_revision与实际观察集合绑定；按目标选资料、保留来源/版本/缺项、分类与出站限制。
- **长期任务**：运行记忆、历史记录、verified知识分开；压缩/handoff保留精确条件和来源ACL；缓存命中/摘要重发均重新鉴权，不能靠撤权后的旧上下文继续披露。
- **工具**：Capability/Tool/Engine/Human Action四类注册合同；14类目标工具列明输入、输出、副作用、验证、失败和所属N项；正式批准/apply不挂入模型列表。
- **编排**：确定性workflow与局部工具探索分开，真实handler/观察/检查点/控制状态接线；席位讨论共享身份/证据/预算合同，可信Skill不增加权限。
- **预算与恢复**：租户/lineage原子预留、attempt计费、deadline/取消传播；超时未知费用保留待对账预留；worker异常零LLM，未知回执先核对，已审载荷只幂等重放。
- **状态与反馈**：Run完成、Finding接受/应用、业务执行/验证分开；等待人释放worker，补充输入留修订；知识派生失败不阻塞合法业务关闭。
- **质量**：真实模型/真实工具结果轨迹、故障注入、来源权限、压缩保真和相同预算消融；员工审核纠错/接收结果与调用成本共同衡量。

新稿回审后补齐了四处易遗漏的细节：调用绑定不可变manifest修订；压缩/缓存的传递ACL；正常0搜索结果与provider不可用的区分；超时费用未知时的保留预留。另将模型`reports.preview_import`限定为已有解析产物的只读预览，专用上传/映射/草稿写沿既有授权工作流，不藏在只读工具里执行。

## 3. 文档验证与保留事项

自动检查覆盖：14个唯一目标工具及每行所属工作项；8份新增/修改Markdown的本地链接、围栏、冲突标记和行尾；活动清单65项、52N/6P/7Q、单项部分完成状态、依赖ID/无环/全N抵达Q6；旧84个ID/历史状态、107原条款及27能力语义保留。Q1未重新依赖P3或N7全量，Q0–Q5分阶段证据语义保留。

最终结果：上述断言全部通过；11节设计、14类目标工具和12个既有工作项补充有落点，8份Markdown的89个本地链接有效，`git diff --check`退出码0。未新增完成状态或功能通过记录。

检查属于文档结构与静态合同验证，不是模型评测、应用集成或性能测试。Mermaid是设计流程图，不是运行trace。

待完成仍包括：N0完整字段/状态/错误码/物理映射与具体政策值冻结；真实capability和工具handler/循环、manifest持久化、来源ACL及恢复实现；新增领域adapter、真实模型/员工场景验收。不能用本设计中的工具名、建议错误码或状态充当已存在接口。

本轮没有业务代码修改、模型调用、数据库/迁移操作、生产访问或外发；没有关闭任何N/P/Q条目。后续按原工作项验收，N0公共运行基础不等待14类目标工具全部实现，Q6仍保留完整集成和员工价值总验。
