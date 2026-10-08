# Wave17 暂存 UI DTO 与交互状态协议 v1

本包仅包含四个新暂存文件：`ui-contract.ts`、`ui-state.ts`、`ui-state.test.ts` 与本文。没有 React、HTTP、路由、浏览器、本地持久化、业务写入、证明消费、Clock/UUID 生成或公共文件接线。宿主必须先把真实读取结果映射为明确 `capa-effectiveness-ui.v1` DTO；本文不是公共 GET/POST 载荷合同，不授予任何专业资格或实际业务能力。

## 输入材料与能力

Root 已冻结五个操作名与分级：

| 操作 | 分级 |
|---|---|
| `quality.capa.verification.candidate.record` | T1 |
| `quality.capa.observation.record` | T1 |
| `quality.capa.verification.review` | T2 |
| `quality.capa.effectiveness.decide` | T2 |
| `quality.issue.close` | T2 |

Rule publication 只有 `host_only` 只读投影，不在人工操作集合。候选的 applicable/independently_verified/observation_complete 必須为明确 null、result 必须为 indeterminate；拒绝缺字段、布尔替代或 pass。未知、not_applicable、缺观察与 ineffective 分别保留，状态包没有从 checkbox、数值通过或候选存在生成专业结论的函数。

Model 必填 schema version、真实 scope/caller/Product 水位、一个明确选择的 Issue 固定版、真实 Current 指针（可明确 null）、稳定 anchor（可明确 null）、late Link/候选/规则/观察/Review 的固定 refs、逐五操作 capability 与 missing/current_evaluation。没有默认 true、默认 Current、按日期取最新版或把缺能力当可办理的路径。每操作 binding 固定 scope/caller/logical Issue/不可变 Issue 版/CAPA/purpose/anchor，与 host command 再比较；kind/family 不能由按钮猜测。

late Link 保留 planned/performed，原 Draft/planned 不因出现新 Current 自动升级。Current 与历史独立，历史固定版始终可读；Current 改变时不静默迁移选择，必须显式选择新版本。Rule/Observation/Review 保存的时钟、nature、issuer、结论和缺项来自宿主投影，纯结构 proof 不产生 allowed。完整字节/当前 ACL/issuer/职责/参与者独立性/采样核验/同 UOW 等真正条件仍由实际宿主核。

`canPrepare` 仅是保守显示门闩：必须真 Current/evaluated_current/source current、完整 anchor、服务器 allowed/authorized/qualified=true、精确 scope 和目标绑定；private 的普通办理只能原 owner。三个 T2 另要求 product 可读原锚与宿主 independence=verified，故 Product peer grant 或正面结构 capability 不能使旧 private 调查成为独立正例。这不是客户端评估专业资格；服务器仍须在 inputs/preview/execute/replay 每次实际核验。

部分候选/观察允许保存与业务证据齐备不同：不把 missing 数组非空一概变成拒绝，实际允许与否由 selected operation 的宿主 allowed 返回。缺来源/当前身份等硬门槛仍阻断。有效性和关闭的 subject family 严格 quality_issue；三个 companion 的 family 必须由宿主实际 registry 传入，未冻结不得假定旧 family。

## 原命令与交互阶段

宿主提供 `HostCommand` 的 opaque JSON payload 和完整 Artifact source_read_set，状态包不生成或补业务字段。完整命令含 command_id/idempotency_key/product/expected_revision/operation/payload/reads；克隆并递归冻结，数组顺序、decimal 字符串、原事件值完全保持。读集最多20且身份不重复，冲突/超限明确拒绝，不排序、截断或自动替换。

`begin → acceptInputs → acceptPreview → confirm` 分别对应准备、只读核对、取得完整预览、用户显式确认。开始 requires 当前 selected capability；inputs 与已有完整原命令/绑定/读集精确相同。若公共宿主未来需要 inputs 才补齐读集，必须在真实 adapter 独立冻结规则，不能依此包任意改原命令。

Preview 只允许增加本分级真实 token；T1=confirmation_token，T2=approval_token 且 write_tier=T2/named_decision=true；去 token 后整外层/语义 JSON/读集与原命令相等，必须有 before/after/effect/实际期限。公共服务若 Pydantic 归一时间或补默认字段，不能在当前包偷偷归一以放行；Root 应明确其 canonical host DTO 映射后再接线。JSONB 对象键顺序不影响比较，数组或原时间值变化会影响。

`confirm` 是单独用户动作，不在取得 preview 时自动执行。它再次核当前客户端读取/资格门闩、Product 水位/读集及预览期限，之后 pending.mode=execute，保存服务器 prepared 原命令。任何字段或当前读取变化废弃预览，保留原请求。确认之前未 execute 的准备可显式 cancel；execute 未知不能 cancel/换选择或另造命令。

Preview 到期且未 execute 时，转 expired_preview，只允许用户主动 requestRepreview，保持原 command/key/payload/readset。已 execute 的 timeout/500/普通409，包括旧 FOLLOWUP_CONFIRMATION_EXPIRED，都转/保留 UNKNOWN 的 exact execute；本地时钟过期不能解锁。resumeOriginal 只恢复同一模式/原命令，不生成 key/time/payload。

## 明确过期恢复与真实 BFF 边界

`ExpiredUnsaved` 是待真实 transport adapter 实现的**内部宿主类型**，不是新 HTTP code/route，也不能由浏览器根据 expiry/409 自行构造。它只表达宿主已锁内核定的 not_saved_expired_proof 与原命令去 token 精确回显。ExpiryTransport 默认 null：即使传入外观完全正确的结果也保持 UNKNOWN。只有 Root 冻结实际协议并配置真实 inspect 回调后，acceptExpiredUnsaved 才可在原 execute 的显式恢复尝试中、尚无 saved Receipt、完整回显相等且不含 token 时接受，进入 expired_preview；仍不自动预览或具名批准。回调缺失、返回 null 或异常都保持原状态；纯测试的 synthetic decoder 不接公共 transport。

当前公共 FOLLOWUP_CONFIRMATION_EXPIRED 仅支持 Wave16 三操作，不能映射给新五操作。Root 必须先扩充/冻结真实服务端限定分支：原完整请求去重无 Receipt、Current/material 精确、原 proof 未消费且已过期、原 command 去 token 逐值回显。未接此 adapter 时不得向状态包发 ExpiredUnsaved，新操作 UNKNOWN 保持原请求恢复。若新的真实 transport schema 与本内部类型不相容，先反馈并冻结单点映射，不能新增另一恢复 route。

## 回执、读取和敏感清理

acceptReceipt 仅对 execute 接受匹配 operation、实际 immutable subject/ref revision 与宿主 family 的确定回执；不匹配仍 UNKNOWN。saved Receipt 优先于任何随后读取错误，pending/preview 清除，提示只刷新事实、不能重发。新的下一动作需要 fresh read 和明确选择，不因上条成功自动进入 close。

401/403 立即清 scope、选择、Model、私有 draft、pending、preview、Receipt 细节及已用命令标识；仅保留 last_outcome=saved/unknown 等非敏感状态与最小错误提示。已保存后撤权仍是 saved_scope_rejected，不能变成 unknown 后重发；未确认保存而撤权不保留可执行命令或私有草稿。

read_epoch 绑定同次读：过时响应/READ_SUPERSEDED 不清新 loading；当前读取消则结束自己的 loading，保留 read_failed 与禁写/只读重试。同一客户端生命周期内的401/403优先清敏感，即使原读epoch过时。跨 scope/caller 的客户端必须销毁旧生命周期，旧异步回调不得投递给新 initialState；此包不提供跨用户缓存或全局状态。begin/confirm 接管序列时结束旧 reading；保存后的 fresh read 若返回另一个 Issue 版，明确要求选择而不静默升级。相同 scope/caller 的宿主 Product 水位可更新，但旧 pending.expected_revision 和内容保持，旧批准不能继续确认。

两次 canonical T2 必须单独 begin/inputs/preview/confirm/Receipt；effective 后 close 还要求宿主返回同 Current 的 effective 与原决定者当前资格。ineffective/unknown/indeterminate 不开启关闭。状态包拒绝第二动作复用已确认命令或 key；真正不同消费 UUID、Invocation.decision_id、Current CAS、同事务反向原子与精确材料仍是宿主/SQL 职责，不能从不同 token 字符串证明。

## 时间与检查范围

eventTime/eventTimezone 只校格式/可解析 aware/IANA，返回原字符串；不 Date.toISOString、不补 now、不抹微秒或 offset，也不把原 IANA 替成显示时区。时序、未来、窗口覆盖及真正原文事件内容由对应真实服务器 schema/owner 守卫核。服务器保存钟在 preview 可为 null/server_on_save，但实际事件字段不得置 null。

所属纯测试只验证 DTO/交互转换，受控正面 capability 与 fake token 明确不代表真实资格、字节、安全、Session、同事务消费或持久化。TypeScript 编译输出仅放临时目录，未在 src/staging 产生 JS。检查记录/四文件哈希放 Wave17 evidence 的 ui-state-* 文件；Root 统一实际接口/事务/页面验证，当前不声明性能改善、业务有效性或关闭已完成。
