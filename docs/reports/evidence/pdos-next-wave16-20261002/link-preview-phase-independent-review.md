# 回链 common preview 窄阶段 · 独立只读审阅

记录时间：2026-10-03T10:15:37.736802+00:00。前置审阅完成；B暂存包尚待冻结，未提前审施工中源码。仅本报告写入，不修改业务/测试文件，不执行数据库、HTTP、pytest或公共检查。最终staged哈希与实现复核将在后文追加。

## 公共接线必须保留的规则

1. 只允许真实 `quality.capa.followup.link` 在同一次 common preview 调用栈中使用prepare/preview_prepared。不能全局删module.validate，不能在全局reviewed_view或consume_material_confirmation中沿用前一阶段Bound。
2. inputs、preview、execute是不同HTTP/Session/UOW；phase不能由HTTP、客户端payload、engine/global/Session.info缓存传递。当前实际消费marker与性能phase不同，既有consume/replay路径不改变。
3. phase必须绑定同Session、实际活动主/嵌套事务identity、ctx全部tenant/actor/requester/run/cancel_epoch、真实module/callback/runtime及锁定persistent Product identity/水位；不能只比较一个人为UUID或digest。
4. 绑定完整Command含command_id/idempotency_key/operation/product/revision/readset原数组及原payload，再绑定已验证完整payload/Bound。共同material_digest对readset排序，RequestKey request_digest保留原数组顺序；不能以semantic相等允许换key、改读集或丢显式默认字段。
5. preview_prepared仍须调用实际Link._new_write；它核Product/Issue Current CAS并独立完整_refresh。全部可能owner/source/专业/政策IO后再次取fresh clock核期限，不能从最初Bound回答自己。Bound来源、受众、resolver材料及实际callback都应不可篡改且一次使用。
6. Confirmation.snapshot仍由既有Link._review完整产生：after.id=None、received_at='server_on_save'、action_fulfilled=None，完整Resolution/authority/policy/readset不丢；没有新的实际事件钟，不把保存占位归一成now。prepared命令沿原exclude_unset返回，保留同command/key。
7. execute的validate→key/commonsemantic/domainreplay→consume重新实质review→apply实际consumed-proof→末端_refresh保持；不得借预览phase跳过去重前门禁，或重新消费/另发Receipt。历史重放不会获得新的当前资格。

## 前置源码快照

| 路径 | SHA256 |
|---|---|
| `pdos-next/server/pdos_next/service.py` | `d4afc3197e77899c6211eba339fefe6ca9e317ee6b6d9ddec622128db4b7838a` |
| `pdos-next/server/pdos_next/command_handlers.py` | `b669d0b9cf0a58a38892b5c385ba800a717899aaea1c0a76e000f442120b280c` |
| `pdos-next/server/pdos_next/domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| `docs/reports/evidence/pdos-next-wave16-20261002/link-preview-static-review.md` | `071b41bb3e4a291953550ba8b971b4b7f0519a29d7ce59c2b6d593195cff5476` |

## 暂存冻结后复核

待B冻结后再读取 `pdos-next/staging/wave16/link_preview_phase.py` 与 `test_link_preview_phase.py`，绑定最终SHA，记录实际same-UOW/一次使用/末端fresh/CAS控制流和所属用例覆盖。此节未完成不能视为实现通过或速度提升；本报告不把fake结构正例称为实际专业或原件资格。

## 追加：冻结暂存协议的定向复核

本次读取B明确冻结后的全部3文件。以下SHA与B提供值相符；只读源码和纯用例，未运行pytest、数据库、HTTP或公共检查。当前server共同入口尚未引用此phase，因此结论仅适用于暂存协议，不是480运行候选的新公开能力。

| 暂存文件 | SHA256 |
|---|---|
| `pdos-next/staging/wave16/link_preview_phase.py` | `9177cef30ef7bac656bd9632d04e0711fc80016ffc93f8bc95e36d347c1bc1ca` |
| `pdos-next/staging/wave16/test_link_preview_phase.py` | `73a242e4f4e3b35518bf9a48158368df46770f22aeb58c3e2833ed97bea83405` |
| `pdos-next/staging/wave16/link-preview-phase-contract.md` | `fb98e5bc2c0cbb284d95fd6220ef67ee6e86210505f0e82a344adba45002895e` |

在指定范围内，未发现该暂存协议新增的明确阻塞项：

- `phase.py:65–102`限定实际Session、活动主/嵌套事务、本人Context及精确Command/FollowupLinkPayload；Product必须为同Session的persistent对象。摘要保留5个Context字段、Command完整readset数组和payload、全部Product映射值及完整typed payload。没有压缩为只比较semantic/key或客户可传的范围标识。
- `:105–166`绑定结果/安全/存储/专业/制造/测试资源与政策issuer epochs、loader/new_write/refresh等实际函数、共同proof callback，以及完整Bound的resolution、authority、policy、source_basis、来源、读集、受众及旧Link映射材料。nested dict改动也会改变材料摘要；真实loader负责完整来源并集、20条上限及private收窄，phase没有替代它或截断来源。
- `:190–213`只调用一次实际Link._load，然后在owner读取后独立核UOW、命令/身份/Product和runtime，并用宿主fresh clock再次执行原专业/政策期限守卫。缺真实host/loader配置仍直接失败，不把结构值变为资格。
- `:216–255`进入消费先核原Session/Product及主/嵌套事务identity，发生rollback后不先访问过期ORM材料。phase先标已使用，任一失败都不允许旧phase再试；随后仍调用真实Link._new_write，保留Product/Issue Current CAS和完整独立_refresh。new_write及原_review之后均重新核Bound/UOW/runtime和期限。没有调用proof消费、保存Confirmation、Receipt、占用或commit，没有新增global/engine/Session.info缓存。
- `:25–58`阻止通常构造、赋值、copy/deepcopy/pickle；不向客户端提供phase。它是可信Python调用栈内的对象约束，不是防止具有宿主任意代码执行权的人使用object.__new__/object.__setattr__的安全沙箱。公开接线仍须在已有门栓之后以该唯一operation显式调用，不能把phase作为通用HTTP输入或跨调用缓存。

B报告41项owned pure通过0.90秒和局部静态通过；本审阅没有重跑。用例明确fake loader/new_write，仅验证阶段顺序、同UOW、完整材料、期限/issuer变化、错误传播与一次使用。它们不证明真实DB权限、原件字节、同事务Proof/Receipt组、专业资格或速度。后续主线需要验证真实公共opt-in入口与剩余execute/consume/replay完全独立。

## 追加：pg-v3-08共同证明提交失败的只读诊断

原结果 `pg-v3-08-result.json`记录2636.78秒、source_stable=true、首次Link保存失败；日志 `pg-v3-08.log` SHA为 `8d093ab1c0e401f708a56d3a2e265b5e19910645cfa36ddf39591f3c557d3b97`。它定位在首次accepted调用，而非成功后的相同/跨key重放：`test_transactions.py:213`。异常是COMMIT时 `require_capa_link_atom`调用 `assert_quality_followup_proof` 的合并条件第17行拒绝。日志没有Proof字段和各时间值，不能据2636秒总时长断言此次唯一原因是TTL。

已确认源码存在可触发的末端证明时效间隙：

1. `capa_verification/commands.py:295`的实际callback进入host.require_consumed_proof；`quality_followup_host.py:307–325`锁定本事务真实已消费Confirmation，核marker/命令/material/token与当前期限。
2. callback成功之后，Link在 `commands.py:302`又做完整_refresh，包含resolver、owner/原失败字节、专业/政策和完整来源读取。其 `:199–224`末端只再次核专业及政策期限，没有再次核共同T1证明期限。
3. 新Link未显式提供created_at；`models.py:31`的Python default=now在 `service.py:726`最终flush时赋值。因此若T1 proof在步骤2中到期，domain.apply仍返回新行，最终0024守卫用NEW.created_at检查 `c.expires_at<=saved_at` 而拒绝。这条guard也检查其他字段，本次异常尚不能排除其他绑定失配。

建议后续Root在保持真实consume及deferred原子守卫的前提下，在全部owner IO之后再次核实际已消费proof，并使最终保存钟与该末端核对有一致的明确边界；不要用先前callback成功、延长TTL或preview phase当作修复。原SQL拒绝仍是正确保守回滚，不能视为已经成功写入。精确本次原因须由主线对真实失败Proof/Product/保存钟作限定诊断；本审阅不读取数据库。

| 诊断源码 | SHA256 |
|---|---|
| `pdos-next/server/migrations/versions/0024_quality_followup.py` | `a957c6dbc22647f2f5dbb39fc014bb4b7ef269b014d9497642110cc4664df252` |
| `pdos-next/server/pdos_next/quality_followup_host.py` | `9400df47e01a8c7b4e9dc7f65bd56279da167e4de1f772509c864d0d079a7cb2` |
| `pdos-next/server/pdos_next/models.py` | `6397c986d170c5ea7d3b31ad3030990c18d4b31811393334dea209e0d6c570d3` |

该末端间隙属于既有execute路径；暂存包严格保持preview-only，未修改它。不能将本节或41纯检查称为pg-v3-08已经修复、真实Link已提交或公开性能验收通过。
