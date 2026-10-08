# Change 影响图过期：最小未应用补丁审阅

状态：只读诊断与提案，尚未应用。主线 pg12 v3 的 `GRAPH_CAPTURE_EXPIRED` 是真实10分钟期限在2232秒办理链中失效，原失败保留；此处没有运行测试、数据库、HTTP，也未改变 v3 三个源码文件。页面 views 施工暂缓。

提案见 [change-owner-lean-proposal.patch](change-owner-lean-proposal.patch)；基线与拟议哈希见 [change-owner-lean-proposal.json](change-owner-lean-proposal.json)。只在内存构造 unified diff 并 `ast.parse` 拟议内容，语法可解析不代表测试通过或实测提速。补丁 SHA256 `6b8c72d805a5638f1d470a5f916c9132185bcb339a9c9a5973c5f5c70e616e56`。

## 已读到的热点

`quality_execution.service.get_issue` 当前调用 `_view`。每个 current Issue 先 `source_basis`，逐 failure 调真实 `_result`（原报告/原值与 retained 执行/消费证明），再 `policy.assess`；最后为与 Change 无关的四项品质写动作调用 `professional.assess` 并合并其读集。PAYLOADS有五项，其中create跳过，实际额外评估 merge/triage/containment/CAPA 四项。

Change 的 `_seed`、`OwnerReader.resolve(Issue/CAPA)`、`_capture_valid` 的新 Reader/capture_graph、`_refresh` 的新 Reader 都重复调用上述完整 getter。`OwnerReader.objects`按包含kind/key的 `Ref.identity` 缓存，所以同一 Issue logicalID/revision 的 Issue和CAPA节点仍分别构建同一 wrapper。`_seed`也独立逐引用读取重复logical/revision。共同validate/preview/apply仍必须独立执行，不能在各阶段之间复用历史成功许可。

这些是代码层确定重复；没有本轮分函数耗时/SQL计数，不能把2232秒全部归因于四项professionals或宣称补丁将消除TTL失败。

## 未应用补丁只做三处

1. `quality_execution.service._view(...,assess_capabilities=True)`保留原默认行为。仅四项非本操作品质写caps loop受该flag控制；source_basis、真实failure bridge、risk policy及policy读集仍照原路径。新增独立 `get_issue_for_change`：当前 human+product access、真实fixed Issue `_row/_snapshot`、真正Current指针全部照原getter，然后 `_view(...,assess_capabilities=False)`；返回同类型IssueView，所有写caps仍false、authority空，不伪造专业批准。品质原GET/其他owner默认不改。
2. `change_execution.service._issue_loader` 默认选择lean getter，显式host loader仍按原配置优先。`_seed`仅本函数局部memo `(logicalIssueID,revision)`，不跨调用/Session/actor/product保存，仍逐引用核逻辑ID/rev/tenant/product和跨project/purpose。
3. `graph.OwnerReader` 每实例增加Issue wrapper memo `(logicalIssueID,revision)`，Issue/CAPA共用同版wrapper；**每个CAPA仍逐key核真实 `capa.id`，Issue仍禁止任何key**。缓存wrapper不缓存按Ref派生的合法性判断、不修改pure Issue/CAPA原值。另一Reader没有旧memo。

`_refresh`、`_capture_valid`仍分别构造新的Reader，新读取真实failed result/Current/来源/risk policy；没有跨这两fresh阶段共享wrapper。`_runtime_stamp`、Change本操作专业authority完整negative fact/epoch、`_evidence`完整读集/真实Original bytes/hash/security epoch、受众检查、精确图重建摘要、TTL exact-key不延长、最终 `_valid_at`均不删除或放宽。withdraw/restore ABA、Current推进和政策issuer变更继续通过新Reader或末端权威/来源比较拒绝。

提案不删原固定Failure/显式roots，Build/Sample邻接仍保持v3精确RunCurrent；当前planned未接owner仍阻断；八facet仍UNKNOWN。没有延長capture期限、伪造retained证明、另开账/Receipt、加全局cache或忽略UNKNOWN。

## 必要纯检查计划（尚未执行）

- `_view`默认True仍调用原品质caps专业评估；lean False不调用这些评估，但实际failure bridge与policy各被调用，并保留完整源/风险policy读集与failure真实性。
- lean错quote/withdrawn原件/source security变化/原failure retained不current不可变成current；policy变化/expiry仍拒或标needs_recheck，private不扩大。
- 同一Reader Issue+正确CAPA同logical/rev只调用loader一次；第二Reader必须再次实际loader；同一_reader中不同Issue revision不能共用wrapper。
- 缓存命中后wrong CAPA key仍拒，Issue non-null key仍拒，project/private audience/needs_recheck仍按每次resolve约束，不因memo放行。
- `_seed`同Issue/CAPA复用一次loader，跨project或purpose仍拒；没有root Issue/CAPA仍拒。
- `_refresh`必须fresh：前一Reader成功后政策/current/source变化，新Reader重新读且拒，Change authority/runtime epoch/原件安全依据漂移原负例继续通过；不要用“调用次数少了”替代守卫断言。
- 保留GRAPH_CAPTURE_EXPIRED真实边界：期限内合法；到期（含末端I/O推进时钟）拒；同capture_key重放不延长expires_at。

主线若授权应用，仅指定三源码与两个现有pure测试文件施工；随后保留v3原失败、新candidate delta，复验原pg11与pg12以及受影响纯范围。实际办理耗时若仍超过期限，继续按精确热点优化或显式重新捕获，不把过期归为fixture断言错误或放宽TTL。
