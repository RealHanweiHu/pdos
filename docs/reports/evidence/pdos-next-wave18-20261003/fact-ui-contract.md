# Wave18 观察与独立具名复核界面合同

状态：四个独占前端文件已冻结；主线负责宿主、公共接线和实际办理验证。本包没有运行数据库、HTTP、浏览器或公共构建。

`FactWorkflow` 接收当前 `FactHost` 与 `inputs(command)`、`preview(command)`、`execute(command)`、`onSaved(receipt)`、`onRefresh()` 回调；可选 `onPendingChange`、`onAccessRejected(saved,late)`、`blocked`、`hostAccessRejected`。组件不自行决定路径或专业权限。`readReview` 可以传入主线只读渲染器，默认使用本包实际材料渲染器。

Host 范围固定 tenant/product/project/caller/logical Issue/CAPA，当前 Issue 的 immutable 行 ID 与 CAS revision 独立于原锚点版本。每个操作单独提供 allowed、当前资格、独立性、来源状态、当前评估状态、缺项和完整读集；不存在默认授权。规则仅来自可信宿主发布，页面没有自授或发布入口。独立复核缺少真正独立资格时保持禁办。

观察只选择宿主提供的整条原记录、真实规则与完整精确 SourceRef。`records` 可附已核对的 `observed_from`、`observed_until`、`at`：三项必须齐备，时钟带偏移、保留微秒、区间有效且事件来源属于该记录。选首条时复制这些原值供本人核对，不从当前时间或说明文字生成事实。来源完整原文上限 20,000 字符，按需展开，绝不截断或重算定位。

独立具名复核只选择实际 Candidate/Rule/Observation 与宿主完整配对、方法/判据和措施选项，逐项填写本人结论、原因及精确来源。客户端不编辑 issuer、参与者、独立性、完整观察布尔、原值或完整 FactBody。结论 unknown 保持未知；Rule/Observation/Review 历史与来源失效分别展示。

inputs 的真实返回是 `{command,review}`。除服务器核对后的完整读集外，返回的无 token 命令必须与原完整命令一致；实际 13 键 review 的操作、语义、CAS、范围和读集必须闭合。T1 预览允许共同接口省略展示 tier，限此已登记观察操作；T2 必须明确返回 `write_tier:T2`、`named_decision:true` 和批准 token。完整返回命令原封提交。

确认阅读固定原失败的原值/单位/工况/设备/原观察钟、原根因及所有措施完成钟、固定规则与抽样要求、本次原记录或具名判断、实际缺项与未知、专业/政策事实及合成标识。服务器接收时间只说明“保存时由服务器记录”。具名复核与实际观察分别一次确认；保存不等于措施有效、问题关闭或产品放行。

执行前持久化完整命令、原 key、payload、读集、token。UNKNOWN 只允许按原请求恢复，普通 409、超时或其他操作的过期码不能解锁。明确回执 `capa_observation` / `capa_named_verification_review` 先保存，再调用父刷新；刷新失败只能读取，不重发。401/403 删除私有选项、命令、预览和回执标识，只保留最低“已取得保存结果，不能重发”提示；晚到结果通过已存在的 `(saved,late)` 回调由父作用域守卫处理。新 scope/材料变化废弃未提交预览，但不能静默替换 UNKNOWN 原请求。

检查和四份源码 SHA 见 `fact-ui-source-manifest-v1.json`；原始结果 `fact-ui-helper-final.log` 为 22 项通过，定向类型与四文件 ESLint 均退出 0。保留早期检查日志，不累计为联合通过。主要覆盖真实 inputs/预览合同、微秒及偏移、原来源/材料与受众、UNKNOWN/保存优先/拒绝、完整业务阅读和原记录时间选择。页面/真实专业资格/源字节/事务/响应超时恢复仍由主线验证。
