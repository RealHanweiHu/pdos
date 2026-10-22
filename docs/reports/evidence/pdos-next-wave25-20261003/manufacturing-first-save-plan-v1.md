# 制造准备三种草稿首次保存方案 v1

范围：只读方案；未授资格、登记原文、生成真实对象/Current/Reference或执行任何DB/HTTP/验证。未读取私有配置。Wave25 actual-http-final-v6 已记录制造inputs403 QUALIFICATION_REQUIRED、当前共享范围制造/变更保存0、资格导入0；该证据属于“合法拒绝”，不是正向保存通过。下列办理需要Root统一准备并实际确认。

## 共同前置依赖

```text
当前具名人 + 有效Product写权限
    + 服务器可信制造 duty/qualification（真实tenant/product/project、Project.purpose、各npi operation）
    + 完整当前来源/issuer/期限与local-synthetic允许范围
                          ↓
真实Project→固定Definition + 当前可读ProcessRevision→Engineering→BOM/Part→Definition
                          ↓
真实固定工序key全集 + 合法受众 + typed原文材料
                          ↓
WI草稿(K) ───────┐
                 ├─→ Baseline草稿(全部真实工序；K引用已保存WI/CP固定id/revision)
CP草稿(K) ───────┘
```

Product写权限与可读Process不授制造专业职责；旧Build工程/制造批准不自动覆盖三个新操作。服务器矩阵要求 `manufacturing`，且每次必须 authorized=true、qualified=true、精确operation/purpose/scope匹配；缺事实null或明确false都禁止继续。可信专业配置/来源只能由已有受控宿主路径提供，不能从表单勾选、标题、原文存在或本方案产生。当前专业端口还核完整未来负事实生效/失效deadline，所有source IO之后再采时钟；不能为了测试延长旧期或忽略撤回。

选真实现有Project与Process，固定revision，Process必须当前且固定工程的Definition恰与Project link一致。scope/purpose从服务器绑定，payload没有自填用途或资格。共享对象需要Project、Definition、Process/Engineering、所选来源和child都允许product；任何private材料不能扩成共享，默认private不能被测试脚本悄悄换product。首次 previous_id/expected_previous_revision 均null。

## 三个最小材料包

| 对象与T1操作 | 最少实际资料 | 可如实未知的部分 |
|---|---|---|
| WorkInstruction；npi.work_instruction.record | 固定Process的真实operation_key K，title/reason，至少1个有稳定key/text的步骤，顶层sources及每步骤sources均精确原文行 | conditions、安全提示及参数可缺；未知参数不用0。若任何nominal/lower/upper已知，必须真实单位及参数自身出处，有限Decimal且上下界有序 |
| ControlPlan；npi.control_plan.record | 同Process同K，title/reason，至少1个稳定key/feature控制项，顶层及每项sources精确原文行 | method/criterion/frequency/sampling_method/reaction_plan/responsible_role可null，服务明确CONTROL_CHECK_INCOMPLETE；不存在方法/数值时不可称已检验或已校准 |
| ManufacturingBaseline；npi.manufacturing_baseline.record | 固定Process每一个真实工序恰一次，title/reason/顶层sources；K选已保存WI/CP的真实kind/id/revision | 其他工序文档、risk_notes、packaging_label_basis可以null并显示缺项，不能省略整条工序或虚构引用 |

引用是实际不可变owner行，不是逻辑series id、标题或未保存UUID。Child须同Project/Process revision/operation_key、status=draft、is_current=true、source_status=current，受众不能扩私有。WorkInstruction/ControlPlan可并行整理材料；两次同Product实际preview/确认/提交由Root协调锁、当前水位和原命令，不能把“可并行准备”当同时批准或缓存旧资格。

**三个对象首次联验最小切片**：取现Process真实K保存WI/CP；随后Baseline仍列全体真实工序，K回链这两真实Current，其余缺文档保持null/明确gaps。若Process有N个工序，三次保存不等于全部工序资料齐备；要求每工序两类真实资料则至少2N+1个对象，不能默认Process只有一个工序。

Sources都是已真实出版、当前可读的 `{artifact_id,expected_revision,line,quote}`，正revision/line、精确完整单行UTF-8 quote≤4000。可合法引用同一已形成原件的不同完整行，同时减少distinct Artifact版本数；不能为预算裁剪父闭包、改行、拼原文或提前生成未来验收。Process/Engineering/Definition、所有child、nested材料与当前专业来源的完整union必须≤20；Definition使用真实view.sources全体，不能用空闭包跳过。规划来源预算可先做，实际计数只有服务器inputs返回后才成立。

## Root办理顺序与受影响验证

1. 无写入并行准备：核现Process工序全体与真实父链；分别整理WI步骤/CP控制项；制作Baseline的全工序资料需求表；根据已存在真来源逐条核locator/受众和预计完整读集。现有三表/共同流程已实现，无需为首个正例改schema、增加发布操作或把缺项改known。
2. 必须先满足：具名人真实对应三operation制造职责及有限资格，真实材料/Source版本，当前登录/Grant、专业issuer和期限。Root按现有授权及受控合同办理，方案不代审批或自动导入。只具有读权限或当前403资格不足时，可继续资料准备，不能提交。
3. 各WI/CP：完整无token Command→制造inputs，采用服务器返回原command/完整readset→共同commands/preview→完整业务before/after/gaps/authority/读集核对→人工T1一次确认→原returned command执行。Root可以先后保存，不手拼proof、snapshot、scope或Current；每份取得真实Receipt后读回固定version与Current。
4. Baseline：只有WI/CP保存并精确回读后才选真child id/revision；再以全工序列表同一流程保存。服务器created_at/time_policy为保存钟，不伪造制造发生、发布或设备验收时间。
5. Root实际PG/HTTP验证：三个新对象各一Receipt/Audit/Outbox/RequestKey、原Confirmation实际False→True、精确Current/固定父闭包/child；Agent0/RLS/crossscope和末端来源/期限失败整组回滚；原Process/BOM/Definition/Build及历史不改。可复用Wave25 PG包，但其pure结果不代实际commit/RLS。实际页面在亮暗/窄宽展示gaps、三种对象Current/历史、一次确认和原请求恢复，不能把草稿保存看作发布/Pilot。

UNKNOWN/timeout仍保留原Command/key/payload/readset与原办理人，只按原请求恢复；不自动新key、换资格身份、重预览或改变受众。实际Receipt先持久化，之后GET失败只重读，不重发已保存动作；401/403清私有状态并保最低成功提示。明确409/403拒绝与实际未保存证据可供Root按已冻结恢复合同处理，普通错误不是解锁依据。

## 当前后续可施工与仍待真实材料

可继续独立实现/准备：完整工序资料表单及缺项解释；root指定合格场景的纯typed材料校验；Baseline exact child/历史展示；受影响PG/页面步骤及Source预算检查。无需调整canonical66或重新审批本方案。

不能由现草稿替代：Tooling验收、Fixture校准/资格、制造基线具名发布、完整制造范围negative enumeration、Pilot准入、正式变更实施/生效、真实生产或外发。现规则对全部草稿固定保留四类缺口，manufacturing_release=null、qualification=unknown、negative_enumeration_complete=false。对应真实owner/资格/发生证据及原批准必须分别接入后才能办理；不得把草稿或新的Source当正式放行。

## 本次读取绑定

以下只是只读时的实际源SHA及Wave25已存在证据；不证明其余全树冻结或新正例已运行。

- service: `822db2a718f02958e9bc06fb02073355606f9d565c22c0da4bd8cbabb81952bc`
- schemas: `948f32fbf5f8b6ccc2c8c9b56a271e2e3c58da61cb1864255e6be09a2ff2d763`
- rules: `789aaa7fe1f307a5ccd1cc9c02590e65bfc280755104b7027ba3a78aa4444401`
- authority: `5212366b6276eff7a3e0fdb1f0fd241209f51b44d342cfa36ec421e692254c9f`
- http_evidence: `a4d26da3e165fffe83de000b06752d71aa90f3d4fe9cdc11867d7447c344bbe2`
