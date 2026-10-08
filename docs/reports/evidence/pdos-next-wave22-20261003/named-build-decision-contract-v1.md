# Wave22 两次具名 T2 的合成专业材料合同 v1

状态：仅新材料方案与纯组装器；未注册原文、未替 Root 办理工程/制造批准。原 Build 工具 v1 不改。现有 Foundation 五行说明合成边界、mm 判据与 23°C 干燥工况，不能代替本 Build 的四项具名专业适用结论。

## 真实服务器门槛

工程操作 `build.engineering.authorize` 必须恰好包含 `product_definition_applicability`、`verification_objective_applicability`；制造操作 `build.manufacturing.authorize` 必须恰好包含 `process_configuration_applicability`、`output_disposition_applicability`。每项须明确 `status='applicable'`、非空精确原文 sources、原因和有效期；unknown/blocked 不能批准。服务器按 operation 绑定 role，原文中的角色文字不授职责或资格。

每次批准均須明确接受以下完整闭集，不增删、不重复：

| 精确值 | 具名接受的含义 |
| --- | --- |
| `no_test_run_or_sample_qualification` | 本制造批准不启动 TestRun，不确认样件测试资格；后续测试须独立核对品质资格、交接与开测。 |
| `no_external_delivery` | 不批准客户接收、真实外部交付或正式外发。 |
| `retain_traceable_outputs` | 产出及样件仅内部保留，固定本轮/批次/实际配置/单件身份与证据可追溯。 |
| `stop_on_configuration_deviation` | 配置偏离、来源或资格失效时停止并重新核对，不借本批准继续。 |

来源必须在 Maker 当前真实 tenant/product/project 范围内，`visibility='product'`，不得将 private 来源放入共享 Build。Maker 仍需当前真实受控导入的 engineering/manufacturing 职责、用途精确一致且 qualified=true 的专业事实。合成 publication 不是职责/资格 import，不接受客户端 flags 自授。

原评估须为真实 Current、assessment SHA/版精确，并仍满足 `candidate_ready=true`、`operational_state='READY'`。只支持 prototype/tool_trial 的限定内部制造；原文不能豁免未知物料/释放、资源/校准、完整保留/占用等硬条件，pilot 不借此通过。

每项专业结论有效期须覆盖完整 window_end 和批准 valid_until；批准 valid_until 必须仍在未来、覆盖 window_end，且不超过当前专业 authority 与 operational bundle 的 valid_until。冻结工具采用 window_end 作为批准期限，故材料各 rule.valid_until 建议也精确采用该真实 window_end。提交时服务器再次采钟核对，旧资料不能续期。

## 一份共享原文、六条完整 JSON 行

新文件使用 native Artifact 登记，标题可为“共享内部合成制造 · 具名专业评估与控制接受”。所有值来自这次新 Foundation、已保存 Build、当前 assessment 与实际 execution_scope；不用旧 Demo、旧 private、客户端 profileID 或另一个产品的身份。`reviewed_at` 是 Root 明确提供的本次声明时点，不能预写 Start/Actual 发生。

每行共同包含以下绑定。它是专业材料的明确限定，不是服务器资格的替代证明：

```text
schema_version = wave22-synthetic-named-build-publication-v1
nature = synthetic
visibility = product
binding = {
  tenant_id, product_id, project_id, maker_id,
  build: {id,revision}, assessment: {id,revision,sha256},
  definition: {id,revision}, bom: {id,revision},
  engineering: {id,revision}, manufacturing: {id,revision},
  build_type: prototype,
  execution_scope: {
    purpose,quantity:"2",unit:"ea",site,
    window_start,window_end,window_timezone
  }
}
reviewed_at = 本次明确声明的 aware ISO（不使用计划钟冒充实际 Start）
valid_until = 实际固定 execution_scope.window_end
production_qualification = false
test_run_or_sample_qualification = false
external_delivery_authorized = false
```

下表给出六行的额外字段。`assessment`/`reason` 是 Root 当前具名判断的全文，不是从旧第一行自动推出；必须检查实际对象后才采用下面的限定表述。

| 行 | 字段及材料正文建议 |
| --- | --- |
| 1 | `kind='scope'`；statement 明示仅本地合成内部制造调查，不授真实生产、测试、外发资格。 |
| 2 | `kind='professional_assessment',role='engineering',rule_id='product_definition_applicability',status='applicable'`；确认所列真实 Definition 草稿、BOM 和工程配置仅适用于这次两件 ea 的合成 prototype 内部调查；定义 mm/23°C 干燥范围未扩大。不声称定义已正式发布或产品已合格。 |
| 3 | 同上 engineering，`verification_objective_applicability`；确认 Build 已保存目标“两件独立 A 身份供原失败与整改后复验；开工不授测试资格”与固定用途一致。后续原失败/整改后复验各自独立质量办理，未取得 TestRun/样件资格。 |
| 4 | manufacturing，`process_configuration_applicability`；确认该制造配置固定所列工程配置、BOM 及 assembly 工序，在明确 site/window 下用于两件 ea 的本地合成内部调查；仍须服务器当前物料/专用资源、校准/接受和原子保留核对。不豁免未知/偏离。 |
| 5 | manufacturing，`output_disposition_applicability`；确认本 Build 已保存 disposition 为“本地合成、内部保留可追溯样件；不外发、不正式放行”，与批次、实际配置、两单件身份追溯相符；不冒充品质处置、客户接受或正式放行。 |
| 6 | `kind='accepted_controls',accepted_controls=[四个精确枚举]`；statement 由当前 Maker 明确接受四项约束，只针对上述固定 scope/有效期。 |

各行均为完整紧凑 JSON：`json.dumps(...,ensure_ascii=False,separators=(',',':'),sort_keys=True)`。每条完整行 ≤4000 字符（DefinitionReference.quote 上限），只缩短说明文字，不能截断引用、hash 或绑定字段。Root 保存后按真实 Artifact 内容 `splitlines()` 取得原行；**quote 使用对应完整原行**。更改任何 scope/reason/有效期都形成新材料及新原文版本，不能改旧已发送请求的语义。

## 纯组装器与两份材料

同目录 `named_build_decision_material.py` 无文件/网络/数据库操作、无默认 now、无默认 applicable。入口：

```python
lines = publication_lines(
    actual_binding,
    explicit_reviews,       # 四 rule_id -> {status,reason,assessment}，真实具名结论
    explicitly_accepted_controls, # 必须显式传完整四值 list
    explicit_control_statement,
    reviewed_at=explicit_aware_time,
    valid_until=actual_window_end,
)
# 由 Root 真正登记共享 native source、核对返回版本与六条原行以后：
engineering_material = authorization_material(
    'engineering', actual_artifact_id, actual_artifact_revision, actual_saved_lines,
    reason=explicit_engineering_reason, authority_sources=actual_engineering_source_refs,
)
manufacturing_material = authorization_material(
    'manufacturing', actual_artifact_id, actual_artifact_revision, actual_saved_lines,
    reason=explicit_manufacturing_reason, authority_sources=actual_manufacturing_source_refs,
)
```

组装器输出恰好冻结工具接受的四字段：`professional_assessments,accepted_controls,sources,reason`。工程两项按服务规定顺序引用行 2/3，制造两项引用行 4/5；top-level sources 为行 1/6，加必要的当前本角色 authority 精确来源。每次共同 command 的 assessment ID/rev/SHA、前版 CAS、当前 Product 版本由实际冻结工具与服务器处理，组装器不生成 command/key/token 或确认。

来源闭包不能漏：service 合并固定 assessment、当前该 operation 的 authority、当前 bundle、top-level sources 与每项专业 sources。冻结工具 authorize 目前只组装 assessment reads + 输入 refs；若当前 T2 的 authority 来源不在 assessment 中，必须把其可核对的真实整行 DefinitionReference 加到该份材料 `sources`。由 GET capabilities.authority 的实际对应 role/operation 取 required_source_read_set，再用当前可读真实源还原精确行/quote；没有来源就停，不猜 UUID 或只改读集。

一次新 publication 只增加一个 Artifact/version 读项，六条 quote 不计为六个 SourceRead。完整 union 仍≤20；保留实际 authority/config/operational 全部闭包与版本冲突守卫，不删来源凑预算。该新增原文不引用新设备校准的文字替代真实 operational fact。

## Root 实际办理顺序与不能声明的部分

1. 确定已保存固定 Build/配置/评估范围、当前两角色 qualification、共享 ACL、有效期及剩余窗口。若窗口/事实已失效，重新形成合法 scope/评估；材料文字不能解锁。
2. 用 Maker 当前真实 Context 注册这一份 product-shared native 原文，核对保存的六行/真实版本。它不是上传测试报告或 scanner 资格声明。
3. 分别用工程和制造原文材料形成两次 T2 真实服务器预览。核对 role、固定 assessment、有效期、两项结论、四项控制、专业 authority synthetic 标识及完整 source reads，然后各自具名确认一次，原封提交 prepared command。
4. UNKNOWN 按同一原 key/body 恢复，Receipt 优先；不重造预览/token/钟，不代 Root 确认。不把尚未保存的原文/批准当事实。
5. 工程批准和制造批准分别有独立历史/Current CAS；两者都保存仍不等于实际 Start。Start 必须另有已发生的精确 JSON 原文、真实事件时间、当前制造资格、两份精确批准及完整原子保留。

实际代码依据：`build_start/schemas.py` ProfessionalApplicability/BuildAuthorizationPayload；`build_start/rules.py` CONTROLS/PROFESSIONAL_RULES/validate_professional_review/require_candidate；`build_start/service.py` `_authorization_inputs`/`_exact_reads`/`_decision_cas`；`supply_execution/service.py` `_sources`。当前 `_sources` 核实际 ACL/security/hash/revision 与指定行包含 quote，并不解析这份新 JSON 的专业业务字段；采用完整自包含行是本材料合同，不能宣称现服务已新增专业出版 JSON 的字段解析/资格授权。

纯验证只说明组装结果匹配现 payload/规则、无默认自授及原文界限；实际 source 登记、当前专业资格、两次 T2 和随后 Start 均由 Root 执行与保存证据。本文件不是实际批准结果。

本次定向检查：9 项无连接纯检查通过（0.004 秒），直接调用实际 BuildAuthorizationPayload 与 validate_professional_review，覆盖两角色精确规则/四控制/完整原文、缺项/unknown/混合 scope 拒绝、来源闭包追加、有效期、4000 字符界限及微秒保留；原始输出 `/tmp/wave22-named-material-pure-check-v1.log`。helper Ruff 通过。纯夹具没有原始业务数据；未访问数据库/HTTP或执行 Root 确认。该 9 项不与 Build v1/v2 的 33/38 项累计为同一候选覆盖。
