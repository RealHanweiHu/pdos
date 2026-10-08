# Coverage scope-only 减读审查：当前 seam 不足，未写补丁

结论：不能仅替换 `owner.fixed_seed` 并声称保留同等完整校验。当前冻结源码未改，PG/网络未访问，没有实际提速结论。`_change_scope_for_change` 适合作服务器范围定位，但两次 roots registry 并不覆盖全部 seed 引用。

## 具体反例与位置

`ChangeRequest` 与 `RequestCreate` 允许 roots=A、references=B，B可以是另一个同项目/同用途的 Issue 或带正确 key 的 CAPA，没有任何 validator 要求 B 在 A 的拓扑闭包内。`owner.binding` 的 seed 输入是 `(*request.roots,*request.references)`，原 `fixed_seed` 对每个 Issue version 调用真实 `get_issue_for_change`，要求 `source_status=current`。`registry._read_registry` 的初始队列却只有 `request.roots`；`OwnerReader.links` 从 Issue 走其固定失败引用，不会从 Change 的 references 增补 B。

因此 B 的原件权限撤回、Source安全/失败证明/当前风险政策失效，而 A 的完整闭包仍current时：原fullseed拒绝；scope-only locator只看header/Current且可返回相同scope/purpose；initial/terminal registry都只读A，无法补回B的完整guard。`inspect_basis`、trusted importer 也沿此结构调用binding，不额外完整遍历references；不能以当前公有consumer另外读refs来证明所有owner入口等价。

本目录8个纯反例检查使用实际 ChangeRequest/registry/fixed_seed，只替换owner IO：合法schema接受额外 Issue/CAPA；两次实际registry未尝试读该ref；原actual fixed_seed 对Source ACL403和source_not_current都拒绝。不是实际Source、资格或PG验证。

## Locator 保留的边界

实际quality helper逐次使用真实Session/root/nested UOW、具体Context/typedRef；禁run/AI代理；scalar ACL绑定tenant/product/当前具名人、active/kind、person/grant access_epoch、deadline并前后相等；其SELECT不autoflush。pending Product业务列、Principal、Grant、IssueVersion/Current先拒绝，不能refresh掉待保存撤回。

Issue snapshot摘要、tenant/product/project、private Issue owner/audience、purpose、具体Current元组/positive epoch和latest固定版也检查；typed CAPA必须对应该版的真实CAPA key，Issue不可带任意key。新实现不能继续仅用 `(id,revision)` skip第二种typedRef而跳过key语义；宜逐distinct `Ref.identity`定位。

这些只是范围定位。它不读取failure bridge、完整Source ACL/安全、risk policy或专业事实，也不直接核Project权限。Scope/purpose不得输出成当前证明或资格。现有owner/read/inspect/import入口的 `_caller` / `_project`、publisher权限、发行者和原件守卫仍必须执行；Project被停用/变private、跨project roots、调用者撤回等不能靠返回Scope绕过。Locator本身只返回已绑定Issue的Scope/purpose，不返回隐藏Source identity/content；不能据此宣称Source可读。反例风险是失去原引用事实guard，不是已经证明有hidden-byte泄漏。

## 可实施的最小前提

- 在实际调用 seam 明确区分 roots 和 supplementary references。确认所有会从fullseed去掉的 Issue/CAPA，都确实由当次initial及terminal完整owner遍历覆盖（exact typed identity/key）；不能接受client Boolean、以前图、缓存集合或跨阶段结果作此证明。
- 或保留references的完整当前Issue读，把它们放在完整owner phase的前后两遍guard中，而仅将binding的scope定位缩为locator。不能把这一步合并成只roots的registry就算完成，不能去掉Source/失败/政策/readset/TTL守卫。
- 现有 `fixed_seed(s,ctx,pid,refs)` 只收到合并refs，自己没有实际root/closed-owner覆盖证据。只改这个函数无法安全选取减读集合；追加受信内部参数或完整refs核验属于新的共享接线，需要Root另审候选，不在本次“只fixed_seed”补丁范围内。

Registry源码与old闭包材料、MAX250/20、两遍实际拓扑/Source/资格、最终Project/Grant/runtime/UOW/真实clock都不变。不要把references加入Graph.nodes/改变closure_sha256来伪造旧批准；如另改Material的coverage范围，必须取得新的合法原件/pin。

后续候选若Root扩展该私有seam，最少验证：补充引用不在roots且Source拒读/撤回/失效；typedCAPA key错或同行Issue/CAPA混合；Current回退/latestABA；pendingGrant/Project变化；Source IO后最后Scope/资格变动；两遍完整owner的exact材料/读集/最早期限保持，旧合法回执恢复无新增effects。实际提速只能由同一候选实测HTTP-worker读取/SQL/耗时确认。
