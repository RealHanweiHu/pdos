# 应用模型预算的显式采用

2026-09-10，N0-03局部接线。`configured_application_gateway`已经能装配真实预算控制器，但当前默认仍为legacy。本机或生产环境均未在本次施工中启用budgeted，真实计量资格仍待验证发布。

## 服务端配置

| 环境变量 | 内容 |
|---|---|
| `PDOS_APPLICATION_MODEL_BUDGET_MODE` | 未设置时为`legacy`；显式采用为`budgeted`；空值/其他值拒绝 |
| `PDOS_APPLICATION_MODEL_BUDGET_PROFILE` | `short`、`work_package`、`research_discussion`之一，来自已批准N0-02参数 |
| `PDOS_APPLICATION_MODEL_METER_PATH` | 真实计量发布包的绝对路径；配套资产按[计量手册](model-input-metering.md)准备 |
| `PDOS_APPLICATION_MODEL_METER_SHA256` | 独立可信部署配置中的64位小写SHA-256；不得在运行时从待加载文件自行计算后信任 |

legacy时后三项应为空；出现非空值但没有显式budgeted模式将报配置错误，避免以为预算已采用。budgeted时缺任一项、未知profile或发布包不通过资格/完整性校验，都拒绝构造Gateway，没有legacy回退。应用配置不影响独立Agent工厂，模型/HTTP请求不能传入这些政策参数。

三档参数随应用打包为`server/app/ai/policies/run-budget-v1.json`，SHA-256为`fd4b8f5c7a9d367480c48359137f539b7f6a60218617ec90d285d884e0b61974`；测试逐字段对照获批draft.3。保留原`candidate.v2`内部pin名称，不伪造新的政策批准。容器现有`COPY server/app`包含该文件，无需读取仓库docs。金额硬限仍未启用。

## 实际行为与切换前提

应用工厂使用只接受已有绑定的Owner服务账本；四个主动入口在运行创建事务内冻结预算，控制器在模型调用前核对并原子预留。详见[创建与续写手册](application-run-budget-creation.md)。已有lineage的profile不可热换；相同调用身份不能二次派发；结构化重试继续使用原调用身份和不同attempt。当前租户额度、旧未知用量、新旧在途互斥、发布包实时失效检查继续生效。

环境模式只决定该进程使用哪条调用链，不更改数据库中的租户admission状态。完整切换仍须满足[新旧准入验证中的条件](../reports/2026-09-10-n0-03-model-call-fence-validation.md)：可信采用、旧进程排空和租户状态转换。`ModelCallModeService`要求当前Owner/Admin、expected_revision与证据引用；先draining，全部已登记调用关闭、预留及未知用量有据处理后才能完成切换。禁止在在途调用不明时重置账本或降回legacy规避持有。

**目前不能用于全应用切换**：0068为Chat、0069为报告映射接入持久run/model_call_id与请求重放，真实API到显式预算工厂均有合成回执验证。现有五处StructuredModelGateway调用入口（事件执行、风险建议、测试计划、Chat、报告映射）均已提供持久运行和稳定调用身份；这不代表所有模型服务均已采用预算，嵌入服务不在本片范围内。0070已为新事件Agent运行接入创建时预算冻结和独立受限工厂，见[事件预算采用](event-budget-adoption.md)；旧未绑定运行不自动补额度。应用侧创建时冻结已接通，测试计划续写已继承父预算；这不证明其他领域关联run、等待/恢复和全部时钟均已接通。详见[Chat手册](chat-request-runs.md)和[报告映射手册](import-mapping-runs.md)。

生产Compose已把这组应用配置仅传入API服务，默认legacy；真实计量包及其配套资产仍须另按授权挂载到容器绝对路径。真实计量包需独立完成资格验证，不能用本次测试的合成发布包部署。开启模式不发布golden、不授权生产操作，也不启用新的业务能力。
