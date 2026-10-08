# Wave22 共享职责只读核验工具（待 Root 实跑）

新 `wave22_authority_readback.py` 只读 Root verifier；不改已冻结 authority 工具。当前仅暂存源码、禁连接纯字段检查和静态检查，未读取实际私有 checkpoint、未运行工具、未 DB/HTTP、未改 API/issuer/现有事实。Root 负责应用与实际执行，纯检查不是真实资格。

## Root 的明确调用

Root 原字节复制到 `pdos-next/tools/wave22_authority_readback.py`，要求同目录已有已冻结 `wave22_shared_authority.py`：

```text
PYTHONPATH=server:tools server/.venv/bin/python tools/wave22_authority_readback.py run --marker <actual-marker> --tag v1
```

可重复 `--reuse-evidence <public PASS JSON path>`：仅接受仓库 docs/reports/evidence 下 JSON，其状态 PASS、路径/全文 SHA明确记录。它们只作为旧24表/6CAPA/private/core等原证据引用，不在本工具重新验证、不提升成新运行覆盖或资格。本工具不读旧private文件、不抄凭据。未提供复用文件时，报告明确这些保留范围未重测，Root可在统一closeout链接既有证据。

报告为 `docs/reports/evidence/pdos-next-wave22-20261003/authority-actual-readback-v{n}.json`；exclusive创建，不覆写原失败。stdout仅status/report路径，异常仅安全code/type，无SQL/URL/环境/token/私有正文/traceback。

## 实际数据依赖与有限配置

复用原 authority 工具实际校验的 `verified(read_state())` exact62513/显式marker/tenant、owned0600完整 Foundation及新 authority checkpoint。只有 `synthetic_facts_saved_root_reload_required`，12专业+1政策+新native共14份完整Receipt JSON才开始读回；source和Definition引用保留真实revision，拒 bool整数和缺失/重复回执。

从新 `.local/wave22-professional-synthetic-profiles.json`、`.local/wave22-quality-synthetic-profiles.json`读取明确两scope列表，完整等于原checkpoint计划。新独立engine上真实factory配置synthetic opaque issuers；不会改变正在运行API的engine对象/epoch/名单。两旧、新对象及实际epoch map在本次读取首末绑定；只能本地合成范围，不授生产资格。当前API startup配置成功仍由Root另核，本工具不声称HTTP已加载。

## 真正读取与保存组核对

一个actual app Session/UOW，精确tenant上下文，当前Product/Project owner/purpose/product受众/active、三人active human、真实can_write Grant及其epoch/截止分别核，不借Maker Context给消费者。

逐12 ProfessionalFact及1 QualityPolicyFact：完整实际不可变row/hash/计划body/approval/来源/clock/reason、原series v1/NULL前版、精确Current scope/key/external/series/ref/revision/epoch。实际FactInput与PolicyInput由已冻结publication和真实新native Receipt revision派生；profession `_material`/import_digest及真实wrapper fingerprint、policy `_material`/data/issuer_epoch均核，不能用inspection摘要替代。

逐13 actual saved group另加新native：实际 scoped Receipt唯一、原Command UUID5、actor/requester/受众/无AI run、实际saved Receipt全文；唯一Audit/Outbox，精确operation/event/subject/revision/actor/correlation；原stable RequestKey/digest→同Receipt。不是从checkpoint生成模拟原子组。Outbox投递、lease、attempts等合法delivery变化不进入固定业务组。

全14行新native原文保持全字相等、真实服务contentHash和UTF-8 SHA、注册Receipt与当前生命周期/source_basis。原Foundation native也重核原两个hash/实际版本/注册出处。三位caller分别真实source_for + source_basis，不能private扩围或只检查SourceRef存在。

## 三人当前专业与Reviewer负向边界

实际professional.assess(write=False，fresh UTC)逐6组各operation：Maker工程9/制造4/品质2；Observer前段品质7/结果与Observation5；Reviewer仅品质Review1。每个结果完整scope、本人、用途、synthetic、角色、authorized=True/qualified=True、无阻断，并准确保留该actor全部当前出版fact_refs及唯一完整source读集。

Reviewer对所有Maker/Observer已出版operation逐一实际assess，要求仅明确缺职责/资格，authorized=False/qualified=None/roles=[]；source/ACL/issuer错误不能当作专业缺项的正确否定。其完整当前事实必须只有自己的Review duty+qualification，不准额外资格藏在不相关scope/未来series内。测试/报告/Observation办理权限均拒绝；这不证明业务参与者独立、也没有执行任何Review决定。

三人分别实际policy.assess，要求精确同policy id、high/independent=True/synthetic、无private来源，并保留其完整当前source/epoch。风险政策不会转独立性结论。

## 禁写与末端刷新

当前真实source_for有Product/Artifact SELECT FOR UPDATE；不能用PG READ ONLY事务令合法来源门禁失效。本工具采用真实app engine＋driver白名单仅SELECT/SET（CTE等也拒绝）、Session autoflush=False、任何flush/commit立即拒绝。保留真实来源锁与产品上下文，不改实际owner实现。Session实际transaction首末活动状态，全部事务最终rollback，成功必须s.new/dirty/deleted均空且driver DML/flush/commit=0。

首轮groups/Current/source/55次左右实际专业评估及policy后，再独立读取全部groups/Current/source/assessment/当前caller scalars；完整摘要首末相等。所有I/O后核真实runtime identity/epoch与synthetic flag，最后fresh UTC核最早三人Grant、Foundation、专业/政策有效期。没有跨phase/session缓存、旧DTO positive、假Clock/资格/持久消费证明。没有ActualStart/占用/样件/原值/Issue业务写。

## 检查与剩余范围

自有禁连接纯检查只验证checkpoint/ORM字段映射、完整common组错误拒绝、Reviewer操作集合、真实缺专业与源错误区分、实际epoch漂移和driver/flush/commit拒绝。Receipt/assessment/Current材料为明确替身，未证明PG数据或门禁真正通过。Root实际运行结果未产生，原表/旧CAPA/private/core保留证据仍只复用既有检查；完整新三人业务/NamedReview/独立采样/有效性关闭仍未完成。
