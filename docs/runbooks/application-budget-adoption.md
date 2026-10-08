# 应用模型预算的显式采用

2026-09-10，N0-03局部接线。`configured_application_gateway`默认仍为legacy。2026-10-06用户已明确确认MiniMax-M3真实计量包发布、本地预算采用与三个指定旧调用的保守占账；本机原3000/8000预览已切为budgeted，见[实际采用记录](../reports/evidence/preproject-research-runtime-20261006/enablement-application.json)。生产采用与其他模型资格仍独立办理。

## 本地预览的已批准恢复

0429新增独立、不可变的`legacy_usage_holds`，只允许当前租户三个固定的、已关闭的旧MiniMax-M3传输失败调用。合法Owner通过原登录与受控领域服务办理，每条按官方输入窗口1,000,000及输出硬上限524,288保守占账，归属原UTC日期2026-10-06。原调用的实际用量仍为unknown，零字段没有被解释成零消耗；取得真实回执后沿原追加核对服务纠正。此恢复不能接纳新的未知调用、改写原记录、给Agent业务表写权限或跳过draining。

本机私有配置固定发布包路径与SHA-256，启用`research_discussion`及`PDOS_RESEARCH_DNS_MODE=cloudflare_doh`。该DNS模式仅用于应用公开来源检查，固定通过TLS访问`https://1.1.1.1/dns-query`；无系统或代理修改，无私网回退，公开地址、每次重定向及实际连接的地址固定守卫保留。未配置时仍使用system，其他值拒绝。

已发布计量包到期时间为2026-10-14 02:12:31 UTC（洛杉矶10月13日19:12:31），不自动延长或退回legacy。为防共享源码热重载打断长调用，本次启动使用`PDOS_DEV_API_RELOAD=false ./scripts/dev.sh`；默认仍为true。关闭热重载不放宽源码bundle变化守卫，修改代码后须先排空活动调用再重启。

同一网站的公开研究复用匹配的active来源登记；停用、不同origin或用途不符的同名来源拒绝并保留未知，原文快照逐份保存。任何失败保留原请求与终态，不覆盖历史或重复派发。品类/提案仍须一次人工采用，立项与项目规格冻结仍沿具名批准。

## 应用 token 额度开关

2026-10-06用户明确要求“取消token预算限制”。0430为租户模型设置增加 `token_budget_enforced`，默认true。本机原预览经合法Owner在 `PATCH /api/ai/governance/model` 中指定false并回读核对，见[实际采用与真实验证](../reports/evidence/preproject-research-runtime-20261006/token-budget-disabled/result.md)。请求仍需包含当前已合格provider/model及daily_token_budget，false时后者仅保留配置值；省略开关保持原值。权限仍为Owner/Admin，事件原payload合同不变，开关保存在审计前后快照。

false只对服务器已绑定应用授权的run取消每日与累计token额度；独立Agent及未绑定调用保持原策略。实际计量、known/unknown记录和追加结算继续存在。真实预算绑定匹配、模型会话closed且整个运行终结的unknown尝试可不再占用新运行的执行名额；正在运行、会话未关闭、关联证据缺失及同lineage未知重放仍阻断。不删除未知账本或把未知费用记为零。

模型上下文/单次输出边界、实时资格、调用/工具次数、活动时间、在途并发、来源和授权守卫继续生效。额度开关不切换admission模式，不变更冻结profile，也不延长计量包资格。采用过false后迁移不得降级丢弃政策历史；生产默认true，生产采用仍须对应授权。

## 小Pai多轮公开研究

2026-10-07依用户要求扩大品类资料及热门产品覆盖，0431采用 `xiaopai-public-research-v2`：单次研究最多7次模型研究选择、6次不同查询，每次最多10条候选并自动读取3条未读网址，总读取尝试最多24次。模型依据已读来源、品牌/价格带/场景覆盖和缺项决定继续搜索、选页读取或整理结果；重复查询/网址不会再次派发。短问答仍可直接结束。搜索条数、候选线索和成功读取来源分别显示，采集失败及摘要截断明确保留。

每轮沿原运行授权、模型checkpoint、租约、真实工具账本及来源守卫追加回执；旧回执前缀不可改写，v1历史可回读。官方参数、独立评测和用户声音分开归因；搜索摘要只作线索，热门结论须有地区/时间及排名、评论量或重复评测依据。缺证据仅标代表样本或热门候选，不能把搜索顺序当成销量。提示词版本独立新增，冻结预算profile、额度关闭状态及真实计量不变，见[覆盖验证](../reports/evidence/research-coverage-20261007/result.md)。

长文研究为全部来源共用12,000字符正文窗口：保留来源开头及优先包含实测单位、价格、评论/评测的逐字原文片段，按原顺序展示并标注省略/截断。完整快照、来源身份、工具回执及线索总数不变；模型候选窗口最多12条/4,000字符，未展示候选不视为不存在。该投影减少摘要输入，不扩张单次输出的已批准及已合格边界。

## 服务端配置

| 环境变量 | 内容 |
|---|---|
| `PDOS_APPLICATION_MODEL_BUDGET_MODE` | 未设置时为`legacy`；显式采用为`budgeted`；空值/其他值拒绝 |
| `PDOS_APPLICATION_MODEL_BUDGET_PROFILE` | `short`、`work_package`、`research_discussion`之一，来自已批准N0-02参数 |
| `PDOS_APPLICATION_MODEL_METER_PATH` | 真实计量发布包的绝对路径；配套资产按[计量手册](model-input-metering.md)准备 |
| `PDOS_APPLICATION_MODEL_METER_SHA256` | 独立可信部署配置中的64位小写SHA-256；不得在运行时从待加载文件自行计算后信任 |

legacy时后三项应为空；出现非空值但没有显式budgeted模式将报配置错误，避免以为预算已采用。budgeted时缺任一项、未知profile或发布包不通过资格/完整性校验，都拒绝构造Gateway，没有legacy回退。应用配置不影响独立Agent工厂，模型/HTTP请求不能传入这些政策参数。

### 小Pai能回复、搜索却被拦住

普通模型回复在legacy模式下仍可能成功；小Pai的公开搜索和原文读取需要创建时冻结的应用运行预算、本人授权、活动租约及模型选择checkpoint。只有API Key或每日token总额不满足这些条件。

2026-10-06修正：未绑定应用运行授权的搜索返回已保存的终态 `APPLICATION_RESEARCH_BUDGET_REQUIRED`，页面明确提示本地计量/预算配置未完成，输入框可继续讨论。通过准入、记下实际派发之后才显示“正在搜索”，不会把被拒绝的工具选择显示成已经执行。原消息及失败记录保留；修复配置后从原对话继续提出研究目标，不覆盖旧失败运行或盲重试旧派发。

启用所需材料是当前模型与端点匹配的真实输入计量发布包、配套资产、独立可信摘要和租户模式切换证据；沿下方既有切换流程处理。已有模型golden资格与输入计量资格分别核对，测试中的合成发布件仅用于隔离验证。本轮诊断、校准预检与尚未启用的条件见[运行问题记录](../reports/evidence/preproject-research-runtime-20261006/result.md)。

三档参数随应用打包为`server/app/ai/policies/run-budget-v1.json`，SHA-256为`fd4b8f5c7a9d367480c48359137f539b7f6a60218617ec90d285d884e0b61974`；测试逐字段对照获批draft.3。保留原`candidate.v2`内部pin名称，不伪造新的政策批准。容器现有`COPY server/app`包含该文件，无需读取仓库docs。金额硬限仍未启用。

## 实际行为与切换前提

应用工厂使用只接受已有绑定的Owner服务账本；四个主动入口在运行创建事务内冻结预算，控制器在模型调用前核对并原子预留。详见[创建与续写手册](application-run-budget-creation.md)。已有lineage的profile不可热换；相同调用身份不能二次派发；结构化重试继续使用原调用身份和不同attempt。当前租户token额度按上述开关执行；旧未知用量保留、新旧在途互斥及发布包实时失效检查继续生效。

环境模式只决定该进程使用哪条调用链，不更改数据库中的租户admission状态。完整切换仍须满足[新旧准入验证中的条件](../reports/2026-09-10-n0-03-model-call-fence-validation.md)：可信采用、旧进程排空和租户状态转换。`ModelCallModeService`要求当前Owner/Admin、expected_revision与证据引用；先draining，全部已登记调用关闭、预留及未知用量有据处理后才能完成切换。禁止在在途调用不明时重置账本或降回legacy规避持有。

**目前不能用于全应用切换**：0068为Chat、0069为报告映射接入持久run/model_call_id与请求重放，真实API到显式预算工厂均有合成回执验证。现有五处StructuredModelGateway调用入口（事件执行、风险建议、测试计划、Chat、报告映射）均已提供持久运行和稳定调用身份；这不代表所有模型服务均已采用预算，嵌入服务不在本片范围内。0070已为新事件Agent运行接入创建时预算冻结和独立受限工厂，见[事件预算采用](event-budget-adoption.md)；旧未绑定运行不自动补额度。应用侧创建时冻结已接通，测试计划续写已继承父预算；这不证明其他领域关联run、等待/恢复和全部时钟均已接通。详见[Chat手册](chat-request-runs.md)和[报告映射手册](import-mapping-runs.md)。

生产Compose已把这组应用配置仅传入API服务，默认legacy；真实计量包及其配套资产仍须另按授权挂载到容器绝对路径。真实计量包需独立完成资格验证，不能用本次测试的合成发布包部署。开启模式不发布golden、不授权生产操作，也不启用新的业务能力。
