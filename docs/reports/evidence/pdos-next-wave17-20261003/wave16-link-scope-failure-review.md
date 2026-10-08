# Wave16 repair-v4-16：Build 输出错版拒绝分类只读复核

结论：本次失败是交易用例最后一个错误分类断言与现行输出守卫不一致；未发现此次请求绕过版本、租户、产品、私人 ACL 或项目边界。建议仅修该用例的精确断言，不修改冻结业务代码或降低输出核验。

## 实际复现路径

`repair-v4-16.log:3–11` 记录同一函数在 `test_transactions.py:425` 失败：预期 `409/VERSION_CONFLICT`，实际 `403/FORBIDDEN_SCOPE`，消息为“输出版本、租户或产品不能精确核对。”本次日志为 1 failed、2279.94 秒；本复核没有运行该测试。

1. `fixtures.py:159–172` 的回链输出是实际 Build 固定行，第 1 版；不是逻辑 Request/Run 指针，也不是当前版自动选择。
2. `test_transactions.py:386–420` 已办理合法 T1 回链，并检查 Link 的精确 Issue/CAPA/输出绑定、真实共同 proof、private/owner、`action_fulfilled=null`，Issue 指针/版体未推进，Link/Receipt/Audit/Outbox 各追加一条。此次执行到 425，说明这些先前断言没有触发失败；不能据此声称整函数通过。
3. `421–424` 为新的 command/key，保留原 prepared 请求其他内容，仅把同一个 Build OutputRef 的 revision 从 1 改成 2。它是新错误请求，不是原请求重放；旧 token 也不能作为新语义批准。
4. `capa_verification/service.py:235–258` 的 Build owner 分支按固定行 id 读取真实 Build，再读项目/双配置/来源；并不以客户端 revision 改写或改取另一行。`builds/service.py:22–42` 已核租户、产品、private owner、项目与双配置。
5. `_reading` 的 `service.py:308–317` 比较 `(row.tenant_id,row.product_id,row.id,row.revision)` 与当前服务器 scope/精确 OutputRef。此例 row 为 1、ref 为 2，故命中整体绑定不一致的明确 `403/FORBIDDEN_SCOPE`。因此失败是正确的拒绝结果，非错误版本被接受。

`commands.py` 的 `validate → _load → resolve_followup_outputs` 以及末端 `_refresh` 均保留真实 owner 核；此处在输出材料校验阶段已经拒绝，不应改成忽略 revision 后依赖后面的 proof/token 守卫兜底。

## 为什么应修断言

冻结 Wave16 施工合同要求 closed OutputRef kind、immutable owner 行 id/revision/key、实际 owner/来源/范围核对，但未规定这个 Build 错版场景必须返回 409。

已有 `tests/capa_verification/test_pure.py:133–158` 的 `test_owner_exact_scope_and_acl_survive_fixed_ref` 将 product/project/private/**revision** 四种不一致都要求 403，和此实际 Build 路径一致。另 `service.py:205–217` 的 `_fixed_row` 在已取得可读行后对 revision 单独返回 `VERSION_CONFLICT`，目前用于 verification_run；不能把该局部分支误当所有 OutputRef kind 的公共统一分类。

建议 Root 下一测试候选只将 425 改为严格：

```python
assert refused.status_code == 403 and refused.json()["code"] == "FORBIDDEN_SCOPE", refused.text
```

保留全部合法回链断言、原错误 revision、后面的完整 `truth_counts` 比较与 RequestKey 既有例外；不接受宽泛 403/409 两者任一，不改 scope/ACL/版号，不在测试中放宽 proof 或创建虚构第 2 版。

此日志在错误分类断言停止，所以紧随其后的 `truth_counts` 断言尚未执行；修正后仍需主线对该受影响函数作真实 PostgreSQL 验证。无需因这个断言调整运行整个前端或变更迁移。原失败日志应保留，不覆盖为通过。

如果主线另决定统一“已可读行错版”返回 409，那是另一个公共错误协议调整：需在确认可读/同 scope 后单独核 revision，更新既有纯用例及客户端 403 清敏感语义覆盖，不能为满足当前一个断言悄悄替换组合守卫。本次不建议扩大该范围。

## 证据绑定与范围

本报告不含凭据、实际租户/产品/人员 UUID。仅阅读本次日志、精确用例、owner 与回链适配、相关合同；未改任何 public/staging 源码，未运行 DB、HTTP、pytest、构建或公共检查。其他仍在执行的 PG 结果不在本报告判断范围。

| 已读路径 | SHA256 |
|---|---|
| Wave16 `repair-v4-16.log` | `c047b783ccc5e6b61df237a039d465b14c3b53bf2b2590dbc446735d1f310f4a` |
| `server/tests/quality_followup_transactions/test_transactions.py` | `7e0a9bf64b4fb6a702bb7658598211e18e1194669c1a6aa0ac5563c29e1d4dfc` |
| `server/tests/quality_followup_transactions/fixtures.py` | `cae4abd15db6dcfd164e14ca6f858648405521145f620c2a47c6f16d028dd3a9` |
| `server/pdos_next/domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `server/pdos_next/domain/capa_verification/commands.py` | `7b05a392c1897632d2e41b4812500401dd0a326bf6fdbcdd51cc165855741e84` |
| `server/tests/capa_verification/test_pure.py` | `4f253f80c454220535cb67e7f97a3cdba86ed6501efd626f4d41a1cb0622b2ba` |
| `server/pdos_next/domain/builds/service.py` | `bd898f7deee5bb3372e108d88cf17f656514cc95f4eb0d5ca8793de649ca0b4b` |
| Wave16 implementation contract | `dcca68b9190353c19d71e94e94fa4e7505af1a2e0c7b63b8ed36c4eb18f0520d` |
| Wave16 `typed-binding-contract.md` | `bd382777a7b0ef86bedcbf2be5c2ceb479f25d45c83049ba70c8226e0083f141` |

表中 server 路径以 `pdos-next/` 为前缀，Wave16 证据位于 `docs/reports/evidence/pdos-next-wave16-20261002/`。哈希绑定本次已读取材料，不代替主线完整候选清单。
