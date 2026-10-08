# 候选薄父组件与权限撤回接线 v2

新增 `capa-effectiveness/candidate-panel.tsx`、`candidate-panel-contract.ts`，只窄改已公共迁入的 `candidate-workflow.tsx`。原 v1 八文件清单与检查完整保留，另七份公共文件及全部 stage 来源未变。

## Root 实际挂载

```tsx
import { CandidatePanel } from "@/components/capa-effectiveness/candidate-panel";

<CandidatePanel product={product} principalId={principalId}
  issueId={selectedLogicalIssueId} api={api} onSaved={refreshCurrentFacts}
  onPendingChange={lockIssueAndBuildSelection}
  onAccessRejected={clearPrivateParentContext}
  blocked={parentBusyOrReadFailed}/>
```

`product` 是 `{id, revision}`，`issueId` 为当前显式选定 logical Issue 或 null，`onSaved` 必须返回实际只读刷新的 Promise。上例命名为接线位置，不新增业务 DTO/权限。新 GET 只用 `v1/products/{pid}/capa-candidates?issue_id=...`，不加 revision。空选择不请求；全部写仍经实际 `quality-followup/inputs`、共同 preview 与 commands，唯一候选 operation 不变。

GET schema 全字段运行时核对，Host.scope 的 product/principal/Issue 与 props 逐项匹配，其他范围、Current、origin、CAPA、整项 mapping 与精确引用严格解析，不补默认肯定。服务器实际产品 revision 可以比父入口新，使用该真实返回值办理；若落后父当前版则阻新办。不能把 origin revision 用作 Current CAS。

## 业务阅读

真实 13 项 review 的 stable_anchor.origin 与完整 failures 是固定依据。每原 FailureRef 精确按 measurement_id 选同固定 `result.verified.run.measurements` 唯一原值，按 coverage.item_id 选同固定 Run.items 判据；不查当前 Request 或猜 Run。原值、单位、工况、环境、原设备名、模穴、观测时钟/原时区逐字只读，null 保持未知。展示具名根因及该固定 origin 的全部实际措施完成说明、原发生钟和原时区；新选 Link、mapping、精确原文单列，当前没有可完整核对的新测试配对时允许缺项候选，不补样件/Run/measurement。

当前政策风险/独立性要求/期限、专业准入/期限及实际 synthetic 标签单列。inspection 的所有 missing.detail、三项 NULL、indeterminate、观察边界 NULL、有效性/关闭 false 继续保留。完整结构或固定关系无法读到时 complete=false，一次确认禁用。普通界面中文业务文案，UUID/对账定位仅折叠显示，不渲染原 command/token/body/hash 列表。

SourceReading 仅在原固定 SourceRef 的精确 line 定位与实际返回 option 一致时展示该原文；不拿同 Artifact 任意一行替代。未单独提供原文的固定依据明确保留出处且尚未单独公开。浏览器不重建 SHA 或证明字节，原件/专业/同 UOW/全部 owner 的实际核验仍归服务器。

## 异常与恢复

parent `blocked` 独立于实际能力，只禁新开始与确认，已存在 UNKNOWN 仍可按原完整 command/key 恢复。读取 sequence 隔离：旧响应不能清新 loading；操作接管读序列时结束旧 loading。当前 READ_CANCELLED 会明确只读重试，旧 READ_SUPERSEDED 不覆盖新状态。不自动重读或重发业务。

401/403 或实际 Host.scope 不匹配时，workflow 先接 `hostAccessRejected` 走 clearPrivate，再通知 panel/Root 清私有选项、预览、pending 和对应 scope 的 localStorage；不把单纯卸载误当授权撤回。原请求若此时实际返回保存 Receipt，只保留最低已保存提示，不能重发。在途 inputs/preview 收到拒绝后不重新写回旧材料。新 scope 的其他用户存储不被清除。

generic network/DTO 读取失败只锁新办，不删原 UNKNOWN。保存回执先于后续 Root/panel 刷新；刷新失败显示“已保存、只读重试”，不重发。`hostAccessEpoch` 只在同 scope 的新 GET 实际完整验证成功后推进，可恢复已清敏感的只读视图；实际写资格仍按服务器 host/caps 独立核对，不从该 epoch 授权。新候选 op 未有明确过期未保存恢复码，普通 409 等仍不能解锁。

## 本段证据

最终 10 文件独立严格类型检查 exit 0；3 个受影响文件 ESLint 0 error / 0 warning。原 v1 17 项 helper/test 源码不变，未重跑、未冒充新组件运行验证。原早期 narrowing/两个 lint 告警的实际记录摘要保留于 v2 check；不新增镜像组件测试。源码清单与命令日志见 `public-candidate-ui-source-manifest-v2.json`、`public-candidate-ui-check-result-v2.json`。

未运行公共构建、HTTP、PostgreSQL、真实保存/恢复或浏览器尺寸/主题验收；这些由 Root 统一办理。新 GET 接线与实际旧 link/原失败/专业回执能力均不在本段被宣称实际成功。
