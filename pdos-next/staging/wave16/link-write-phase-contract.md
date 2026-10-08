# Wave16 暂存回链新写实质阶段合同

状态：仅三个新增暂存文件，不注册公共 handler，不迁入 server，不改 SQL、TTL 或 Receipt。旧 preview 三文件保持冻结。用户的连续建设授权仍有效；主线负责公共候选修改和真实联验，本文件没有新增用户批准关卡。

## Python 接口与同调用栈边界

```python
prepare_write_review(s, ctx, command, product, payload) -> tuple[WritePhase, dict]
apply_prepared_write(s, ctx, command, product, payload, phase: WritePhase)
    -> tuple[RemediationLinkRecord, Literal["capa_remediation_link"], str]
```

参数是实际 SQLAlchemy Session、本人且无 Run 的 Context、完整 Command、本 Session 已持久保存的 Product、完整 FollowupLinkPayload；操作只接受 `quality.capa.followup.link`。WritePhase 与 PreviewPhase 是不同类型，不能构造、复制、pickle、序列化或通过 HTTP。同 Session、主事务、nested UOW、宿主连接和实际 Product 对象才可使用。调用尝试先标为已使用，后续失败也不能重用。

`prepare_write_review` 真实调用现有 `capa_verification.commands._load`、`_new_write`，保留所有来源、原件、owner、专业、政策、产品与 Issue Current CAS；然后返回现有 `_review` 的完整深副本以及不透明 WritePhase。已有 original Link 必须返回 `REPLAY_REQUIRED`，继续共同服务原 key/semantic/current-first 回执重放，不进入本新写阶段。缺原确认 token 也拒绝。

Phase 绑定完整 Context 五字段、Command 全字段（command_id、key、原 token、readset 原顺序、产品水位、完整载荷）、已验证 Payload、Product 全部实际映射字段。Bound 绑定完整 resolution/basis/outputs、authority、policy、sources/reads/source_basis、受众、真实旧对象与 callback identity。mutable nested dict 的改变同样不能复用。stamp 复用冻结 preview 的真实安全/存储/专业/测试资源/制造/政策 issuer epoch 与函数身份，并绑定真实 `quality_followup_host.require_consumed_proof` 身份。

## 公共接入所需最小 hook

主线须显式 opt-in 这一操作，并保留正常 Product 门栓、当前本人/权限/SourceRead 检查及所有已有 key/semantic/replay 分支。只有确定为新写的同一个共同实质阶段才调用 prepare，随后：

1. 将返回的**服务器内部 review**用于真实 Confirmation 的 snapshot/material 核对。不得接受客户端 snapshot、Bound、Phase 或 proof UUID。
2. 按原规则消费一次真实 Confirmation False→True，立即通过现有 `record_consumed_confirmation` 留同 Session/主事务/nested UOW 的实际 ORM 转换 marker。
3. 同一调用栈将局部 WritePhase 交 apply。不能放入 Session.info、全局或 HTTP 缓存；inputs、preview、下一次 execute 与回执重放不复用它。
4. 共同服务照常 s.add/flush 并原子保存 Receipt/Audit/Outbox。阶段不产生或消费任何证明、不 commit/rollback、不自行保存 Receipt 或移动 Issue Current。

现有 `consume_material_confirmation` 需要能接收该服务器实质 review；不能绕开其 actual snapshot/material 比较。公共 apply dispatch 需要仅为已准备的本次 Link 新写传递局部 phase。与 preview opt-in 是两个独立 hook；PreviewPhase 永不成为 WritePhase。

## 最后 owner I/O、证明和保存钟

apply 仍真实调用 `_refresh`，重新读取所有旧失败与输出 owner/bytes/来源/专业/政策；不在实际确认之后再丢弃 Bound 重跑 `_load + _new_write`。全部 owner I/O 之后重新核同 UOW、完整命令/Product/Bound、runtime/issuer stamp 与当前专业/政策 TTL。

随后捕获实际服务器 `saved_at`，不用 prepare、Confirmation 或较早领域时钟回填。再调用 Bound 的真实 consumed-proof callback；返回值必须是 UUID，且必须等于现有 `quality_followup_host.require_consumed_proof(..., tier="T1")` 从实际同事务 marker 和锁定 Confirmation 得到的 UUID。bool、任意 UUID 或历史 consumed=True 本身都不构成证明。

另对实际 Confirmation 做 exact tenant/product/subject/actor/operation/revision SELECT FOR UPDATE，核本 Session persistent、consumed=True、原 token hash、共同实际 material digest，以及 snapshot SHA 精确等于这次准备的 review。实际当前 Principal 仍由原 host guard 独立重核。缺 marker、没有真实 host callback、换 scope 或过期均拒绝，不做默认 positive。

proof 读取之后以及构造领域对象之后，再核同 UOW/材料/stamp/专业/政策/证明 expiry；最终 clock 不能早于已捕获保存钟。构造原 `RemediationLinkRecord` 时显式 `created_at=saved_at`，其 `input_snapshot.shared_proof={id:<真实UUID>,tier:'T1'}`；不保留原明文 token。返回 transient row，保存仍由共同事务负责。

没有修改证明有效期、SQL atom/deferred guard或签核规则。本协议在全部 owner/proof I/O 后重新核实际当前 TTL，并绑定 owner I/O 后捕获的真实保存钟。现有 `assert_quality_followup_proof` 将证明 expiry 与 `NEW.created_at`（saved_at）比较，不读取 COMMIT 时钟；最后当前 TTL 检查到 flush/COMMIT 之间的延迟，不保证数据库另按提交时刻拒绝。因此不能宣称本阶段保证消除 Root 已观察的 Link COMMIT 失败，也不新增 commit-clock 要求。未知候选、适用性、有效性和关闭都不由这一协议变为成功。

## 检查、历史与限制

本阶段只有无 DB 纯协议检查：实际 Session/transaction/ORM False→True 与真实 host marker 函数，明确 fake owner loader/refresh、Principal/Confirmation SQL 返回值。它证明调用与绑定边界，不能证明真实授权、原件 bytes、专业资格、数据库提交或速度改善。

首次测试替身导入遗漏导致 fixture `preview_work` 未注册；已在本新增 test 中恢复显式 fixture 注册，没有修改旧 preview 测试。修复后 50 项通过（0.85s），不与错误轮次相加。覆盖原 review、一次 load/new-write、末端 refresh/实际保存钟、真实 marker UUID 核对、未消费/伪 ID、proof/material 变动、读取期间到期与倒退、Current/source/runtime/Bound 漂移、完整 command/read 顺序、跨 Session/UOW、单尝试与旧 replay 拒绝。

仅运行本新增测试，不加载 repo conftest：

```text
cd pdos-next/server
.venv/bin/python -m pytest --noconftest ../staging/wave16/test_link_write_phase.py -q
```

Ruff、format、AST 也仅针对本新增两 Python 文件。Root 已停止旧 v3 公共验证并进入公共修复，不能把本检查当作旧 480/既往 11 文件当前仍未变的证明，也不能替代后续冻结候选的实际检查。
