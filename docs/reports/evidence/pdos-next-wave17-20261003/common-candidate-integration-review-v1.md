# Common candidate integration — directed static review

范围仅新操作 `quality.capa.verification.candidate.record` 的共同 preview / prepare-write / bind / False→True / capture / writer、回放与 startup；未运行 DB、HTTP、pytest、公共构建或攻防，未修改源码。结论为**所读接线未发现新增阻塞**，不代替实际数据库原子组、过期、回放和页面联验。

## Observed source binding

审阅开始时固定读取：

| 文件（`pdos-next/server/pdos_next/`） | SHA256 |
| --- | --- |
| service.py | d1ba6e06be3a7369c60bbe163560bf59057b82091cee4540817fda8840732ce5 |
| command_handlers.py | 616a1f900182380b65f3385687797588a29da7180b1f8b8cf90c0e2ed97992d3 |
| contracts.py | 0b187bb4e319b451e4768b108d612d21524a9107bf3828b4b883c25c35ec67c9 |
| api.py | 454ef93eb45d6bc4494b2fc0d4cd47a18b7f0e8824fd0467d4502c5dfc2052f6 |
| quality_followup_api.py | cb48aa9f742c7ea45bba64d9d8ae916d7a39a97e56a9f25f6ffd978496f05748 |

专用依赖：候选薄 service `33b7343e50e551d681a289d8d61f073a3b0ef1dce05d5f61aa16997dbca55223`；A 专用 prepare `66b4169d848f3b348eaf8bf1c65d515eacd0f0fd58314b6f7e7f0743ff81712c`。本文不扩大为全 namespace 或工作区冻结结论。Root 随后新增 candidate GET 文件及 api 注册属于另外接线；不以本次 api 起始 SHA 代替那个后续候选。

结束时再次计算，common service / handlers / contracts / quality_followup_api 四 SHA 仍相同。api 已成为 `46432ddf76aa903cc1a407bc766a60847d38e74b4b36218e37da6bf6cd3f2b55`；定向再读确认 startup 128–139 行保持，216–218 行新增 `capa_candidate_api.register_routes`。新 GET reader 本身不在本次审阅范围。

## Exact consumption sequence

`service.py:406–457` 仍由 Common 持 Product 门栓、当前 access/human/source 检查。候选与既有 Link 选择 `prepare_preview` → `preview_prepared`，避免先 validate 再独立完整 view 的重复准备；候选 renderer 单次绑定完整 UOW、ctx、command/key/token/有序读集、Product、真实 prepared 材料与 runtime，末端实际 clock。共同 Confirmation 保存服务端 13 键 snapshot、实际 material digest 和一次 T1 token。

新写入口 `service.py:663–689` 的 `prepare_write_review` 实际取得 persistent 未消费 Confirmation，进入 A `CandidateAnchorRestoreHost` 与 `prepare_candidate_write`；phase 保留该 ORM 对象。consume 在 `service.py:474–505` 重新选择该证明，核 revision/material/snapshot；同 Session 的 identity map 保持对象身份，adapter `bind_consumption` 另显式要求 `phase.proof is confirmation`，不只依赖 UUID 或 DTO。A 对原证明 raw SQL immutable 列、原 full anchor / 13 键材料、Current/Project/caller/完整来源与专业政策的实际重核保持。

`service.py:510–518` 的精确次序为：实际 bind → `confirmation.consumed=True` → 直接调用 `record_consumption` → 返回原 `(binding,marker)`。**赋值与 capture 调用之间没有 SQL、flush、autoflush、owner IO 或额外回执调用。** adapter 在捕获前仅做 weak identity registry 查找和纯 require；实际 `ConsumptionHost.capture_after_transition` 首先采真实钟，再核 persistent loaded proof、ORM deleted False / added True 与实际 expiry。它自己的同 UOW 内部消费登记不是客户端 DTO 或跨 HTTP 阶段缓存。

`apply_prepared_write` 仍调用原 `candidate_write`：原 marker 的 require_live → A 完整独立 owner/bytes/source/policy/professional 刷新 → 原 phase 原锚/材料比较 → 全部 owner IO 后 require_live 和实际 saved_at/期限 → 仅 `s.add`。没有阶段 DTO 或客户端 anchor 替代证明，原完整锚不重封。当前态检查和 proof expiry 均以真实末端钟核验；现有 SQL 绑定真实保存钟，本文**不声明另有 COMMIT clock 保证**。

共同 `append_receipt` 使用原 subject 和真实 flattened `action_result` 两个 hash；主线保存一次 Receipt/Audit/Outbox/RequestKey。候选 owner/visibility 继承原完成系列，writer 为实际 actor；候选 `indeterminate` 与三个资格字段 `None` 不变，不推进 Issue Current。

## Replay and existing operations

`service.py:542–553` 当前 access/AI 检查/完整来源和 module.validate 在 RequestKey / semantic Receipt 查询之前。候选 validate 执行实际当前人、专业、来源、Issue/Project/原失败门禁，但没有把旧 Product expected_revision 当新写 CAS。`service.py:569–629` 两种成功回放均在新 write phase / consume 之前返回，保留旧 Receipt，不重新消费、追加候选或移动 Current。新的 Source/authority/readset 漂移仍可阻断回放，不能借旧成功回执恢复资格。

候选是 `T1_OPERATIONS` 单独成员，handler 和 PAYLOADS 指向实际公共 service / 原 CandidateRecordPayload；semantic 是 actual commands 函数 alias。既有 Link 仍使用原 preview/write phase，consume 返回 None 后按原无 consumption 参数写入。RootCause/Complete 仍走原 `record_consumed_confirmation`，过期恢复也仍仅原三操作；T2 注册没有因为候选扩大。候选 tuple 分支只在精确候选 operation 上执行。

## Startup and public boundary

`api.py:104–116` 的 synthetic professional profile 仍需显式参数、精确 tenant/product 和 verify_test_target；默认 None 不开启 synthetic。`api.py:137–139` 的候选 configure 仅建立 actual module 的 restore/consumption host，没有写 duty、qualification、Grant、issuer 或七 gate。专业 operation role mapping 是可用职责矩阵，不是事实授予；实际 prepare 仍要求当前专业 assess `authorized=True/qualified=True`、政策、原件/结果桥和源安全。缺相应实际宿主/事实明确拒绝。候选仅具名本人、run=None，不能借通用 AI Qualification 或 ProductGrant 自授办理资格。

`quality_followup_api.py:41–54` inputs 有路径 product exact match、封闭四操作分派和同 tenant_session。Common commands/preview 继续在同 tenant_session UOW 中执行；失败回滚 pending candidate 与 consume，证明和回执不拆事务。未配置有效性、关闭或七 owner 门禁 positive 的事实不能由此 inputs/host 配置产生。

## Remaining validation ownership

实际持久 SQL False→True / reciprocal atom、真实 TTL 到期、Source/issuer/专业 ABA、Current CAS、同/跨 key replay、末端回滚及 UI 属主线真实联验。没有发现需要修改本次五文件的具体接线阻塞；本报告不是这些联验的通过证据，也没有重复运行 owned 26 / A 17 pure。
