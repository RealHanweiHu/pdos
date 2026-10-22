# 第十六波回链修复 · 同一次办理的固定材料与末端证明

**2026-10-08：本施工合同已被[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)整体取代，仅作只读历史对照。下方旧“当前/下一步/冻结”不再作为施工指令。** 范围根、一致性、期限与数量限制按 v1.1 和已批准的 [S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md)执行；[旧条款对照与 B0 基线](../reports/evidence/pdos-next-s0-20261008/baseline/baseline.md)保留取代依据。原证据、失败与当时范围不改写。

本合同在既有建设与加速授权内处理两个实际问题：BFF预览180秒未返回，以及事务用例`pg-v3-08`首次保存被提交证明守卫拒绝。原日志、数据库拒绝及480候选保留；当前尚未证实提交拒绝的唯一条件，不能把静态重复次数直接称作运行瓶颈。实际Link仍未保存，问题Current为v6，不再无条件重复原预览。

## 已冻结预览模块与公共接线约束

B独占 `staging/wave16/link_preview_phase.py`、`test_link_preview_phase.py`、`link-preview-phase-contract.md`；41项纯检查及静态检查通过，C只读复核与主线准确摘要见[主线范围核对](../reports/evidence/pdos-next-wave16-20261002/link-preview-phase-root-observation.json)。暂存41项纯检查不证明实际速度提升或业务通过；主线已迁入正式模块，公共运行时及事务验证待下方新候选。

旧20项已按下方检查点停止，Root在新候选接入：common preview完成原Product/本人/来源门禁后，显式只对Link调用`prepare_preview → preview_prepared`。保留真实`_load`、`_new_write` Current CAS及末端`_refresh`，准确旧`_review`、完整Command/key/读集顺序/显式payload与actual Confirmation snapshot/material不改。其他操作及common `reviewed_view`、consume和replay不因此复用preview对象；不存Session.info或跨请求缓存。不同Session、主/子事务、作用域、命令、Product或Bound变化及失败后再次使用均拒绝。

## 另一个独立阶段：新写实质核对到原子保存

B独占新增 `staging/wave16/link_write_phase.py`、`test_link_write_phase.py`、`link-write-phase-contract.md`，不得编辑此前预览三文件、server、web、迁移或依赖锁。只做该段纯/静态检查，C只读审阅，Root统一接线与公共验证。

`prepare_write_review`须真实完整加载、Current CAS与末端重核后给出原格式review及仅本次common new-write调用栈可用的opaque阶段材料。Root后续在所有现有key/semantic/replay门禁之后，才允许新写使用此阶段的服务器review；真实Confirmation身份/期限、snapshot/material比较、False→True消费及同事务marker全部保留。客户端不能传入可信review、Bound、已消费ID或accepted旗标。

真实消费之后，`apply_prepared_write`核同Session/UOW/完整原命令与材料，仍独立读取全部owner并核Current、来源、安全、issuer、runtime与资格/政策。全部owner I/O结束后才捕获服务器保存钟，真实callback再核本次已消费UUID，最后核UOW、绑定及真实时效，再构造原Link记录；保存钟不得回填到较早phase。Callback缺失、返回布尔/空值、已到期或变更均拒绝并回滚。共同Receipt/Audit/Outbox及SQL deferred配对原样保持，预览阶段不能办理此写入。

这段旨在避免实质review之后再次丢弃完整材料重建，并补齐最后owner I/O之后的共同证明核对。它不延长TTL、不放宽数据库守卫，不承诺一定解决本次提交失败。旧成功重放仍按当前来源/权限/真实owner核验后返回原回执，不消费第二个证明；旧阶段对象不能跨key、HTTP或事务复用。

## 收口范围

10:23UTC因新增实际Link提交失败，主线停止旧v3运行，保留13项完成结果（11通过、2失败）、6项在途及1项未启动原日志；480文件在停止前保持。见[停止检查点](../reports/evidence/pdos-next-wave16-20261002/pg-v3-interruption.json)。此前等待全部20项再施工的安排在此检查点因已知实际错误更新，未完成项不记通过。

Root随后区分实际错误与等价时间文本断言，单调冻结新候选；精确记录保留范围与新增改动，不把旧整树结果冒充新整树通过。公共影响验证涵盖新准备/核对/消费/保存、真实末端撤回与期限、不同UOW/命令拒绝、同/跨key单回执、末端回滚和实际页面原请求恢复。最后以实际T1保存、只读closeout及清晰页面证据交付本闭环。独立有效性、Issue关闭、真实资格、生产及人工Exit不因这些修复开放。

## 新候选实际接线

Root已接入两个exact-Link阶段，137项公开阶段/owner/选项纯检查通过，局部静态与格式通过。共同服务只使用本调用内服务器生成的review，所有key/semantic/domain replay门槛保持；无已保存domain intent的module replay在已有current-first validate/Product锁之后直接返回None，新写仍完整核对。旧apply入口也将真实callback置于owner refresh后，保存钟取该末端实际时间。当前SQL核expiry与领域created_at/saved_at，不按COMMIT时钟重新判断，阶段末端到提交之间的延迟不宣称另有提交时点TTL保证。具体源码与原版本差异见[绑定](../reports/evidence/pdos-next-wave16-20261002/public-phase-repair-binding-v4.json)。
