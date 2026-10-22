# Wave16 窄宿主实现检查点

这是上述只读接线审查后的新实现检查点，仅新增 `pdos_next/quality_followup_host.py` 与 `tests/quality_followup_host/`。Wave15 303 与此前 A frozen 9 个 Python文件未修改。Root 公共注册/迁移/UOW hook与真实数据库验证仍未由本agent执行。

公开导出：`configure_host(engine)`、`append_issue(...)`（既定 AppendIssue Protocol）、`record_consumed_confirmation(s,ctx,command,payload,module,confirmation)->UUID`、`require_consumed_proof(s,ctx,command,payload,*,tier)->UUID`、`OP_TIERS`。

Root 在共同 `consume_material_confirmation` 已检查 material/snapshot 且设 `confirmation.consumed=True` **后立即、任何 flush/SQL 之前**调用 record。record要求真实persistent ORM行同Session、实际未flush `False→True` history；拒绝历史已消费/伪造transient/detached记录。只将 token digest、完整 command/material/readset/context、真实 ConfirmationID/hash 放入private Session marker，不存rawtoken。marker绑定 Session对象、`get_transaction()`对象及当前nested transaction对象，回滚/结束/新transaction/不同Session不能使用。

require只锁真实行核完整绑定/expiry与当前Principal，重复assert原UUID，不消费、不重算preview、不生成UUID；wrongtier/不同commandID/key/actor/payload/readset/行内容均拒。B link已在OP_TIERS中；其现proofcallback有 `(s,ctx,command,product,payload)` 位置参数，Root可显式wrapper转调 require(...tier='T1')，不修改B frozen commands。

append只接受同Session实际旧Issue、一个连续mutation与本事务实质共同preview，核scope/audience/input/intent/snapshot/authority/policy/sourcebasis/readset，完整重建sources，Current按tenant/product/project/Issue锁与CAS后+1。保持旧owner/purpose/visibility，服务器新版本UUID，保留全部sharedproof/observations。只有IssueVersion insert和Current update/flush，无commit/Receipt/Audit/Outbox、FailureMap/Delivery或新aggregate；末端共同服务负责一次Receipt原子组。

`configure_host`安装窄append/proof但 completion assessment=None。合成分类ledger尚未创建；任何真实调查/正式Change实施缺出处接口继续503，GET仅可prepare不等实际完成已核。生产角色/资格/现表约束与agent权限不受此文件改变。

33项owned pure通过（0.85秒），Ruff/AST/compile通过。其中一项使用无bind、无连接的真实SQLAlchemy identity map检查真实ORM false→true history，其余明确为synthetic Session/rows；都不证明PG锁、RLS、deferred atom或公共消费接线。

Root下一步：公共consume immediate hook、A/B callback配置、Root公共模型/单调迁移和agent/RLS/deferred proof+Receipt门栓、精确synthetic assessment输入及集中PG。不能将本纯检查宣称真实资格、HTTP闭环或正式Exit。
