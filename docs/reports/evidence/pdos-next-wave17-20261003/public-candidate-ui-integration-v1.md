# Wave17 公共候选界面接线说明 v1

本段只新增 `web/src/components/capa-effectiveness/` 内 8 个文件。五份已冻暂存表单/状态/视图逐字迁入；新薄 `CandidateWorkflow` 只办理实际候选 T1，不为后续观察、复核、有效性或关闭制造接口和能力。暂存源、公共父页面、BFF、后端及依赖未修改。

## 当前可用接口

`CandidateWorkflow` 的 `host` 消费实际范围、当前 Issue CAS、固定 origin、CAPA、真实 Link/完整 FailurePairMapping/精确原文选项、服务器能力及专业资格。`required_source_read_set` 只能是实际读取依据；空映射允许保存待核对候选，不能合成测量或通过结果。`current_evaluation`、`source_status`、`allowed`、`authority` 必须由宿主实际读/评估取得；不能从 ProductGrant、选项存在或 UI checkbox 推导。

Root 可按下列边界接线，函数参数路径与既有 api helper 一致：

```tsx
<CandidateWorkflow
  host={actualCandidateHost}
  api={api}
  inputs={command => api(`v1/products/${product.id}/quality-followup/inputs`, command)}
  renderReview={readActualCandidateReview}
  onSaved={async receipt => { await readCurrentFollowup(receipt); }}
  onRefresh={readCurrentFollowup}
  onPendingChange={lockScopeSelectors}
  onAccessRejected={clearPrivateHostChoices}
/>
```

上例 callback 名是接线位置，不是新增公共 API。inputs 只读后使用服务器完整读集，继续共同 `v1/commands/preview`，用户核对一次再原封提交返回 command 至 `v1/commands`。Receipt 仅接受 `capa_verification_candidate`、该 operation 与第 1 版。Root 自行挂载，无新导航。

`renderReview(review, command)` 必须返回 `{content, complete:true}`，完整业务阅读未接通或内容为空时确认禁用。该候选的真实 review 为 13 项：operation、payload_semantic、stable_anchor、binding、inspection、raw_source_basis、required_source_read_set、sources、authority_snapshot、policy_snapshot、owner_id、visibility、current_issue_revision。不能套旧 before/after/effect 的预览校验；不能显示 raw body/token。阅读应体现原失败固定范围、Current CAS 与 origin 的区别、选择的真实整改回链和复验对应、精确原文、实际受众及三项未知；宿主实际名称缺失明确未知，可核验标识仅置于折叠对账。

helper 核对完整返回命令与原命令去 token 后深相等，固定 Issue/CAPA/Link/mapping 和完整读集一致、三个 NULL 与 indeterminate 保留。它不重建 Python 摘要、不证明原件字节/专业事实/七 owner；这些继续由服务器核验。

## 范围与恢复

scope 使用实际 tenant/product/project/principal/Issue/CAPA；当前 Issue 引用是实际版本行及 revision，origin 另列固定历史引用。`accessEpoch` 只表示宿主一次已确认的新读取/访问版本，不授资格。选项、CAS、材料、能力或来源状态变化清 editable draft 和未提交预览，旧选择不会迁为 Current。payload 受众须等于实际 origin 受众；产品受众需明确允许且所选材料全部可共享，表单仍默认 private，不能静默改为 product。

原提交结果未知时持久化完整返回 command/payload/readset/key，锁新候选，只提供同请求恢复。scope 控件由 `onPendingChange` 锁定；父页面不能主动清除原 prepared command。新 op 尚无明确“未保存、已过期”恢复协议，所以普通 409、500、timeout、旧三操作的恢复码均不能解锁、重造 key 或自动重新确认。

保存回执先持久化，再调用实际刷新；后续刷新失败保留成功提示并锁新办，只读刷新不能重发。401/403 立即清私有选项/预览/原请求及本机数据，成功后只保留最低“不应重发”的结果提示。访问恢复需宿主确认新 accessEpoch 和完整真实 capability，界面不自行重新授权。保存回执恢复后也先读当前事实，不直接开放新办。

精确 pending 恢复在表单挂载前完成。未提交 editable 表单的全部选择/原因刷新后自动回填不在本段保证内；这里不冒称已实现完整本机草稿重建。固定事件时钟/原值逐字来自提供项，不用 JS Date 重写微秒或原时区。

## 检查与边界

本候选 17 项 meaningful helper checks 全过；8 文件严格 TS 与公共规则下局部 ESLint 0 error / 0 warning。原输出、配置、源码 SHA 见 `public-candidate-ui-check-result-v1.json` 与 `public-candidate-ui-source-manifest-v1.json`。初始 lint/setter 错误及临时 TS node 类型配置失败保留，未混算历次检查。

未运行公共构建、真实 HTTP/DB 保存、浏览器/亮暗/320–1440 布局验收。本包不声称实际候选已保存、G3 资格已具备、措施有效、关闭或生产启用。父页面完整业务 review 与当前 host choices/访问 epoch 的接线仍由 Root 完成并集中验证。
