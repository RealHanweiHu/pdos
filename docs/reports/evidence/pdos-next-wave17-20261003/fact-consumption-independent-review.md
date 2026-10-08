# Wave17 fact consumption 暂存协议独立只读复核

结论：在本次三文件读取范围内，未发现需要窄修的明确实现缺陷。common/domain semantic 分离、真实未刷新 False→True 捕获、完整命令与事务绑定、首钟不续期均与当前共同服务边界相容。该模块未挂载，不是新的公共 consumer、实际 SQL 原子证明或 G3 资格正例。

## 与真实共同路径的对照

`service.execute` 在当前产品锁/授权/来源/领域 validate 后，依次办理 RequestKey、共同 semantic Receipt 和领域原回执路径；只有真正新写才进入 consume/apply/append_receipt。新 hook 不能插到任一已保存 replay 路径，也不能因恢复取得旧 Receipt 再制造一次消费钟。

`fact_consumption._material` 使用领域 `module.semantic(payload)` 作为**共同公式内的 payload**，另计算 operation/product/named_actor/source_revision/private_owner 的完整 common intent。该公式和实际 `execute:573–592` 的领域 module 分支一致；领域 semantic 的单独 digest 不等于 Receipt.intent_digest。新五操作属于独立领域载荷，source_revision 保持 None；不得借旧 Claim/Work 载荷或别的 module 绕过这项前提。原完整 command digest 独立绑定 command_id、key、Product 水位、原 payload 和读集顺序，material_digest 与 canonical read-set digest 则沿实际约定核来源材料，二者不能互相替代。

`append_receipt` 仍持有唯一真实 subject/family/revision，保存 actual request_digest/intent，并追加 Audit/Outbox。LiveConsumption 不预建 Receipt、target 或事件 UUID，只提供本次真实消费列。领域保存及反向 SQL 必须使用同一 actual common intent，不能改用域内 `_intent`。

当前 `consume_material_confirmation:457–508` 先取真实 FOR UPDATE Confirmation、核 Product 水位、payload_digest 与完整 reviewed snapshot，再赋值 consumed=True；旧 Wave16 record hook 紧跟赋值。新模块的正确未来接线位置只能是：完成真实 common review 后、赋值前调用 bind；赋值后立即 capture，且 capture 前不允许 SQL/autoflush。public prepared_review 目前仅 exact Link 分支开放；不能以本次只读审阅把该旁路拓展为新操作的自定义预览。

## 具体门槛

| 核对点 | 当前实现与实际保证 |
|---|---|
| persistent、已加载与历史 bool | `_proof_state` 要求 actual Confirmation、同 Session、persistent、未 deleted，所有被读属性含 consumed 必须已加载；因此不为 expired/unloaded 字段触发 lazy SQL。bind 要求 consumed **is False** 且无既存消费变化。capture 要求 **is True** 且 history deleted=(False,)、added=(True,)；历史 True 或已经 flush 丢失该 history 不能首次产生 marker。 |
| 原请求与 proof 不可换 | bind 固定模块对象、ctx 全材料、command 全材料、proof 对象/固定字段、原 token hash、review digest、material 与读集；`_bound` 每次重新比较。command/key/operation/readset/revision/snapshot/token/module 改变被拒。相同 command 不能改绑第二 proof，复制的 marker/binding 不符合宿主实际身份。 |
| 首消费钟与期限 | capture 第一动作采 UTC，无 owner I/O；要求 created_at ≤ consumed_at < expires_at。重复 hook 返回原 marker，不写新的 consumed_at。真实 writer 完成全部 owner I/O 后 require_live 再采当前钟，核原首钟和原 expiry；本地规则、客户端时钟或重复调用不能续期。 |
| actual Session/UOW | 沿 `fact_atom_storage._uow/_same_uow` 核 actual Session、活动状态、完整 actual SessionTransaction 父链、nested 对象、engine bind 与 caller 摘要。同一有效 SAVEPOINT 可用；捕获所在事务/子事务结束、回滚或换新链不能重用。根事务中原已成立的消费，不等同于后续任意子事务回滚必须撤销它；判定仍依原实际消费所在链与当前 loaded proof。 |
| 首捕获与后续 flush | 首 marker 必须在 flush 前；之后实际消费可随同 UOW 刷新，require_live 使用原 marker，不从新的 consumed bool 或 Receipt.created_at 重推首钟。后续任何 unloaded proof 都先拒绝，不能以读取历史行冒充首消费。 |
| exact tier 与 Rule | trusted startup map 只收两个 T1、三个 T2 固定 operation，exact module identity 再核。host-only Rule import 及旧 Wave16 三操作不在此 registry；模块不根据规则内容、自定义客户端 map 或 checkbox 授予 T2。 |

`Session.info` 只持本 host 的同 UOW 内存绑定，桶按原 transaction/bind 区分，使用前再核完整链；不是跨 HTTP/用户缓存，也不是持久反向证明。保存它或外观相同的 dataclass 不能自行建立真实资格。

## 宿主仍须承担的边界

1. startup 必须传实际公共 handler 所用 module；payload/model/semantic 验证必须为可信纯函数。hook 不替代产品锁、Principal/Grant、policy、Current、issuer、原件字节和专业职责核验；common 已核这些基础访问也不等于新五操作完整资格。
2. 真实 writer 必须在**全部** owner/source/bytes/issuer/professional I/O 后再 require_live，并维持 exact Current、真实 delta 与同事务 target。不能把一个提前成功的 marker 回调当末端重新核对。
3. 尚未登记新 consumer、SQL reciprocal targets、proof 一次使用/反向原子和运行存储权限。本报告不把内存 marker 转换成“七 owner 当前证据已授权”或“同事务 T2 已持久成立”。后续提交守卫和 source 撤回/rollback/重放需主线真实接线后验证。
4. require_live 仅保证该调用时点尚未过期，不保证后续任意延迟到 COMMIT 的时钟。历史存储还须以 actual proof_consumed_at 和目标保存钟核原 expiry；不能声称现 SQL 使用 COMMIT-clock，也不能延长生产 TTL。

## 测试材料与只读限制

阅读的测试使用实际无数据库 Session/SessionTransaction 和 detached-loaded Confirmation 替代行，明确以测试赋值模拟 common 消费；禁止 hook SQL/flush/commit。覆盖首次时钟/common semantic、历史/已flush拒绝、材料替换、对象伪造、实际事务/子事务变更、过期/naive/future 创建钟、owner I/O 后期限、卸载属性和 Rule/旧操作排除。它们不是数据库返回的真实 Confirmation，不证明安装了消费 hook、反向 SQL 或专业资格。本复核没有运行这些用例或引用它们为实际 G3 完成。

仅新增本报告；无源码编辑，无 DB、HTTP、pytest、构建或公共检查。下列为最终读取绑定，不替代主线候选清单；不含原 token 或私有业务资料。

| 文件 | SHA256 |
|---|---|
| `pdos-next/staging/wave17/fact_consumption.py` | `4bbc52ff7423fa4cf389ff12b21f7c64201a0566b6296580399561bfade50458` |
| `pdos-next/staging/wave17/test_fact_consumption.py` | `cac4835928a7a21f32d675eac9be1832a1cb6be99f8d5f7b2e042fb47bab9ea2` |
| `pdos-next/staging/wave17/fact-consumption-contract.md` | `762e37ecbfce9387bd216fe65eda3483fe482de30e9abb46f13c2c2e19705dce` |
| `pdos-next/staging/wave17/fact_atom_storage.py` | `b3794750da19f6394dc12cce062489e1aad7022619f4aac7dccb7e7246b9e604` |
| `pdos-next/server/pdos_next/service.py` | `a710834b172d33de60f713333fd63a5d2d6bab3c39d5a7002b03c7d3d2982686` |
| `pdos-next/server/pdos_next/quality_followup_host.py` | `9400df47e01a8c7b4e9dc7f65bd56279da167e4de1f772509c864d0d079a7cb2` |
| `pdos-next/staging/wave17/fact-storage-contract.md` | `eb020013ea6f10c7ca8ee6959bc361ef878679317fe1ea485d9a5a6c6e9f9f85` |
