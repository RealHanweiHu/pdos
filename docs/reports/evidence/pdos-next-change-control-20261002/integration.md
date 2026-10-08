# G3 双线变更首版接入合同

本包仅写 change_control 领域、schema、纯测试、独立组件和本证据目录。共同 ORM/迁移/注册/命令/API/BFF/父页面及现有对象均未修改。新工程独立，不继承旧数据、批准或资格。下列实现可调用，但尚未接入实际页面与持久事务。

## 入口与固定合同

- ChangeControlHandler(Ports).preview(uow, operation, subject_id, expected_revision, payload) 返回实质结果范围、固定载荷/读集/预览摘要、拟到达状态、未知原因。只读检查，不开始事务、不消费证明、不写业务。uow 必须是主线调用者的同一 Session。
- execute(uow, Invocation, payload) 解析封闭DTO并核对 semantic_digest，调用共同 begin/当前授权/原意图 replay，再重读领域来源/状态，T1/T2共同 confirm，最后 record。没有模型、网络、事务提交或第二个命令入口。Invocation 是领域适配参数，不是新的HTTP信封。
- ChangeControlReader(Ports).get(uow, request_id) 返回全部受控历史与当前适用性、分专业批准、实施/生效范围缺口及独立复核。来源/配置/政策/期限变化使 current=false，不重写历史批准/关闭。返回之前核验全部历史嵌套引用的ACL；无权来源直接拒绝，不泄露历史。
- compute_impact(GraphSnapshot, request_revision, hypotheses) 是确定性纯核。GraphSnapshot 由服务器 FactPort.graph 固定读取，客户端只提交 graph_snapshot Ref，不可提交图、覆盖完整/性质标志或跨租户节点。固定输入包含完整来源、scope/audience、节点/边/覆盖版本、捕获/失效时间和服务器nature。AI hypotheses 分栏，不产生边或已批准范围。

subject_id 是实际 ChangeRequest ID；create 的领域 expected_revision=0，其他为当前正版本。公共 Command.expected_revision 仍由主线检查 Product 等共同对象版本，wrapper 单独绑定领域版本。新请求ID由主线合法意图分配且 insert-only；不得用新UUID绕过共同业务意图去重。

## 对象、影响与状态

ChangeRequest聚合保存不可变版本、精确roots/references、来源、requester、assessment与order历史。Issue/CAPA/TestRun引用只读，CAPA无独立版本时使用所在Issue聚合版本并以key定位CAPA，不编造独立revision。Spec/BOM行/Operation必须有精确key。

双线遍历仅沿有来源的边：Spec→Part/BOM→EngineeringConfiguration→Build/Sample/Test；Part/Interface→Operation→Tooling/Fixture→SOP/ControlPlan→PilotRun→ManufacturingRelease。已知结果包含节点及证明路径；库存/WIP、供应承诺、客户样件、在制Build、证据适用性、生产切换和培训分别有coverage切片。每个可达节点缺任一来源范围manifest，或关键后继边缺失，均保留UNKNOWN，不把无边当无影响。完整声明必须有来源；模型推测不补边。

状态 draft→analysis→review→approved→implementing→verifying→closed。order.prepare 只准备固定计划/意图，工程与制造及当前政策要求的客户/法规批准分别记录，全部决定到齐才 approved；批准者不得是requester，AI不得办理T2。任何UNKNOWN影响/处置不允许批准。

EffectivityPlan包含明确对象、object:/batch:/serial:单位、条件、来源、有效期和ControlledIntent。全部已知影响必须有Disposition：实施计划项关联或有出处的 reviewed_no_change；unknown不批准。计划不靠到期日期生效，也不能凭任意字符串扩范围，FactPort.selection必须解析和核验实际对象归属/条件/适用性。

ControlledIntent仅描述新工程/制造配置、新Build、新Run或ERP/MES生效意图。真实对象由现有所有者创建、真实外发仍需原授权/DeliveryIntent/worker路径；本包只记录其固定输出。成功实施必须有该所有者核验的新对象固定引用，不可复用旧配置/Run ID覆盖冻结内容或原测量。ERP/MES外部范围须使用真实权威记录，不能把本地意图当外部生效。

ImplementationFact由FactPort读取 owner 已持久化的事实，不接受模型 outcome/actor/nature。人类实施记录沿共同T1一次确认，必须本人且发生时间不早于所需批准；失败/未知仍implementing。成功记录不自动生效。

EffectivityFact区分 sent、accepted、effective；仅effective+succeeded且覆盖全部精确units/conditions并绑定实施输出才进入verifying。部分范围单列，未知/失败保留；日期/HTTP状态码不变成生效。相同固定fact ID不增版本/历史/业务事件；同ID不同载荷拒绝，同原始system/external_id/stage/occurred_at不可换新ID重复导入。

未知执行/回执禁止新attempt盲重发。服务器认证的新fact可携 reconciles_id 解析同一unknown原执行/回执；执行须同item/intent/executor/occurred_at，回执须同item/intent/system/external_id/stage/occurred_at并覆盖原未知units（无units时全部批准范围）。新结果不得仍unknown，一份unknown只允许一次解析，原记录保留。真正新一轮失败恢复由所有者提供独立已核验事实，不在本包发网络请求。

独立VerificationFact由品质权威端口读取，须匹配order.content_digest、全部item_ids、真实新输出、观察起止、适用性、current与服务器nature；不得用原Run自证。提出、批准、实施及新测试测量执行者均不能担当独立复核；具名品质验证结果pass/fail可记录，unknown不构成决定。观察须晚于全部实际生效。通过后仍verifying，close再次具名决定并重读依据，不能以任务done或根因假设关闭。

来源撤回/更正、配置变化、政策或计划/批准过期阻止新执行。change.recheck仅记录服务器确认的失效原因，旧决定/执行/关闭保留；若根/来源需要新版本，change.request.revise固定新引用和原因，重进draft→analysis→review并作新专业决定，不能沿用旧批准。

## 操作与主线注册

| 操作 | DTO | 等级 / 事件 |
|---|---|---|
| change.request.create | RequestCreate(title,reason,roots,references,sources) | canonical T0 / change.requested |
| change.impact.compute | ImpactCompute(snapshot: graph_snapshot Ref,hypotheses) | canonical T0 / change.impact_created |
| change.order.approve | OrderApprove(discipline,text,expires_at) | canonical T2 / change.approved |
| change.implementation.record | ImplementationRecord(item_id,fact_id) | canonical T1 / change.implementation_recorded |
| change.request.revise | RequestCreate | **候选待注册** T1 / change.request_revised |
| change.order.prepare | OrderPrepare(assessment_id,plan,reason) | **候选待注册** T1 / change.order_prepared |
| change.effectivity.record | EffectivityRecord(item_id,fact_id) | **候选待注册** T1 / change.effectivity_recorded |
| change.verification.record | VerificationRecord(fact_id,text) | **候选待注册** T2 / change.verification_recorded |
| change.close | Close(text) | **候选待注册** T2 / change.closed |
| change.recheck | Recheck(reason) | **候选待注册** T1 / change.recheck_required |

OPERATIONS只是可调用registry候选，CANONICAL_OPERATIONS只标原附录4个动作，不改共同注册。T0仍要求当前服务器授权、run未取消与真实能力资格；测试fake qualified=true不授生产资格。AI只能准备T2内容候选，无approve/verification/close执行权。本包T1采用具名人已发生事实，不扩大AI执行权限。

## 实际接线 ports 与事务

| 端口 | 必须实施的主线适配 |
|---|---|
| CommandPort.context/begin | 从认证/Run绑定scope/actor/requester/audience/职责/授权/资格/取消/aware当前时间；锁请求、命令key与稳定语义意图。服务器业务指纹须区分合法新轮次，不能永久合并相同payload，也不能由模型新key制造重复效果。 |
| CommandPort.replay | 校验同key不同载荷冲突，持久跨key精确原意图回执；重验原读集/来源ACL/受众/取消/当前权限。可返回已完成历史效果，但不能新消费proof/写业务；current状态由Reader另报。 |
| CommandPort.request/record | scoped读取/行锁，聚合版本CAS/insert-only；固定assessment/order/实施/回执/验证及完整原revision历史。失败必须回滚业务、proof消费、 imported fact映射、ActionReceipt、Audit、Outbox。所有表/RLS/注册/迁移由主线统一，record不能commit/start transaction。 |
| CommandPort.confirm | **复用共同T1一次确认/T2具名证明**，匹配scope/audience/actor/run/cancel、operation/目标版本、payload/read/preview digest、政策和期限，一次消费与record同Session。不能把invocation.decision_id或token字符串自行视为已批准事实。 |
| FactPort.ref/currentness/source/audience | 核验精确版本/item、所在租户/项目、当前ACL与来源原文/撤回/用途。audience专门核验来源到目标受众的使用许可；能读两个客户来源不意味着可以输出给共同受众。内容hash不证明真实性；未知权限须拒绝。 |
| FactPort.graph | 新工程配置/BOM/制造/品质/供应所有者提供固定图和有出处覆盖manifest。当前配置包含工序/SOP/资源要求但Tooling/Fixture/ControlPlan/PilotRun等完整对象未接入时返回unknown，不能fabricate complete。所有节点/边来源在同一Session重验。 |
| FactPort.selection | 解析真实object/batch/serial、条件、产品/项目/受众和controlled intent适用性，核对在制Build/客户样件/库存WIP切换与培训真实范围。不存在或无权对象拒绝。 |
| FactPort.implementation/effectivity | 读取实际对象所有者/受控人工导入的具名事实和认证原始回执；固定来源、当前输出、服务器nature与时间，不做网络调用。sameID更正使旧决定待重核；未知对账必须认证reconciles_id关系而非新发送。 |
| FactPort.verification | 品质独立具名新Run及适用性依据，含全部执行人、全部输出/范围、观察条件窗口、服务器nature、current；客户端bool/模型文本不能充当专业事实。 |
| PolicyPort.assess | 当前policy source、必需专业决定（至少工程+制造）、职责和独立复核政策，当前权限/资格不能从payload解码。 |

最低持久约束：租户/产品/项目scoped FK；正revision；请求CAS与新ID insert-only；immutable revision/history；order.content_digest对应固定评估+计划+政策；每专业每order只一个具名决定；scoped owner fact identity唯一和未知reconciliation单次关系；独立验证/关闭身份与依据保留；回执自然身份防换ID；公共proof/receipt/audit/outbox同事务。不要将远端发送、接收或实际生效装进本地事务，也不要称分布式恰好一次。

## 消费接口与漂移复核

consumption-initial/final.json固定只读消费文件SHA-256。本包运行时只导入新工程 errors.DomainError 和 verification.contracts 的封闭DTO/Scope/SourceRef/Key/Text/Revision；未导入现有业务写service。定向读取 quality_issues 的Issue/CAPA/固定Run来源及integration规则、configurations 的固定Spec/BOM/双配置合同、build_execution 的ActualConfiguration/BuildLot/Sample身份接口、supply_cost 的调用者uow/固定来源端口，以及共同Command：只记录摘要，不修改它们。

具体主线映射：配置所有者的固定来源并不自动包含完整制造依赖；需建立owner提供有出处边的graph adapter。Build仍区分计划与actual配置；客户样件与库存/WIP必须按实际服务器来源绑定。品质TestRun/Measurement原值不复制到本包，只保存Ref与独立验证投影。主线同时消费其他包时应在接线前再次核对接口变动。

## 前端与联合验证

详见ui-integration.md。组件仅接 typed reading/candidates/context与callback，复用Button、双主题tokens和父传共同sharedReview，不生成token/确认权威，不接合成fixture到业务页面。缺port/未注册/当前资格或来源不完整须明确待接入；外部unknown仅核对原意图。

主线待做：上述实际Session/owner/政策ports；ORM/RLS/迁移与公共命令注册；共同T1/T2预览一次确认/真实ActionReceipt；API/BFF/父页面读取与组件映射；新配置/Build/Run所有者办理；实际失效传播与受控ERP/MES对账/外发授权。接线后至少集中验证真实DB并发与全回滚、双线来源完整/缺边/跨受众、配置与政策漂移、token过期/取消、部分与重复/unknown回执恢复、审批独立性、复核/关闭不足、HTTP/浏览器亮暗窄宽/键盘和恢复结果。包内纯检查不是DB/HTTP/浏览器或G/N/P/Q验收。
