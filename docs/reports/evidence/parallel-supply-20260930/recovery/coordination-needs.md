# 供应恢复 → 原 Issue 具名关闭：统筹接缝

供应域实现与文件由本线完成，共同 Issue/API/工作卡及排程桥归统筹。未操作任何数据库。

供应异常详情 `GET /api/projects/{project}/npi/material-exceptions/{exception}` 及原 preview 返回新增：

```json
{
  "closure": {
    "ready": true,
    "review_current": true,
    "supply_ready": true,
    "disposition": "supply_ready",
    "source_digest": "<当前供给核心摘要，排除预测/日期刷新>",
    "reasons": [],
    "reference": {
      "exception_id": "<原异常 UUID>",
      "review_id": "<最新不可变具名复核 UUID>",
      "source_digest": "<同上>"
    }
  }
}
```

未恢复、仍需跟进、来源/分配/实际领料变化或范围变化未复核时 `ready=false`、`reference=null`，原因保留。原事项和历史核对仍可阅读。页面的恢复办理入口只在当前 reference 有效时暴露，供应记录不自动关闭 Issue。最新供给复核接口保留 `ExceptionReview` 输入与不可变 review 返回形状。

**共同关闭入口所需最小变更**：原 `IssueTransitionBody` / 工作卡增加可选 `material_closures`，类型是本线 `MaterialClosureReference` 数组（仅 exception_id、review_id、source_digest）。在 `IssueService.transition(to_status='closed')` 原项目锁事务内、Issue/事件/审计写入之前调用：

```python
material_context = validate_material_issue_closure(
    connection,
    tenant_id=tenant_id,
    project_id=project_id,
    issue_id=issue_id,
    actor_user_id=actor_user_id,
    expected_sources=material_closures,
)
```

两个类型/函数均位于 `server/app/domain/material_exceptions.py`。无关联物料异常且无引用时返回空 sources，普通 Issue 不变；有关联则必须精确覆盖该原 Issue 的异常引用。守卫保留真实当前查看权限、获取池锁后重新读取，要求引用的 latest review ID 与当前 source_digest 精确匹配，并且最新具名结论在当前来源下为 supply_ready，或正式需求已移除且结论为 scope_changed。旧快照冻结、过期、原件摘要漂移、归还/报废、共享失效等会阻断旧引用；不接受仅自由文字 closure_evidence_ref 代替此引用。

供应页面的“到原问题进行具名验证”保持原 `entity_id`，附带三个 URL 参数：`material_exception_id`、`material_review_id`、`material_source_digest`。共同工作卡需将这三项转换成 `material_closures` 数组并保留原 Issue 的 `expected_updated_at`；刷新/重新选择后才替换引用，不静默改成最新来源。服务参数名也使用 `material_closures`，新联合 PostgreSQL 用例明确检查这个接缝。

返回的 policy/sources 应加入原 Issue transition 的审计 context，保持具名验证人、四眼政策、原 Issue 版本、关闭证据与原事件事务。失配抛 `MaterialAllocationError`；共同 API 应映射成明确当前来源冲突（409），不作为未知 500。本线不直接改 `issues.py`、`issue_risks.py` 或共用工作卡。

最小整合场景：不足与未复核状态拒绝关闭；齐备预览后新的冻结快照/归还或共享撤销使旧 typed reference 拒绝、Issue/事件/审计数不变；新具名核对后由指定验证人按原四眼规则关闭同一 Issue；审计故障撤销整个关闭；普通 Issue 路径兼容。

余额对账另新增 `POST /api/projects/{project}/npi/material-movements/{movement}/reconcile/preview`。输入 `ReconciliationSelection`（supply_snapshot_id、outcome、evidence_id、reason），输出 digest 绑定 tenant/project/reviewer、来源/交易行/前次版本、选定证据元数据及结论。原保存需沿该预览填写 expected_version / expected_digest / request_id；GET 列表摘要不能再直接作为保存批准摘要。API 与供应页面由本线同步修改，无 schema/迁移。

该预览有独立具体 Next BFF 路由，未改共用 `npi-bff.ts`。最新源文件摘要漂移会令池 `state=source_changed`，不能分配或计为合格现货。已保存余额核对的证据摘要漂移也会撤销其当前采用效果，原领料重新进入待对账扣量，旧核对历史保留；重新预览/确认及异常复核后再采用。

排程桥接缝已获悉但未修改：正式 baseline 替换/节点移除的旧 binding 影响残留由统筹处理。本线保留 exception_id、review_id、当前 source_core 摘要与原 binding 的办理入口，解除/rebind 必须重新核对当前异常及来源；不将供应恢复自动写成正式承诺或删除旧影响。
