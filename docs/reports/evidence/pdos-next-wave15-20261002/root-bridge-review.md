# Wave15 结果桥与政策导入只读核对

记录时间：2026-10-03T04:59:22.899528+00:00。本次仅定向阅读宿主桥、政策回执适配与 A 的固定证明/重核合同；未编辑业务文件，未运行 DB、HTTP、pytest、公共构建或浏览器。UI 三文件保持冻结。

**未发现需额外修复的集成阻塞。**

- 结果事件经 Outbox → 同租户/产品 Receipt → 精确 RunVersion 或 Projection.run_version_id 装配，核对操作、事件类型、subject/revision、actor、correlation 与 schema；不以客户端事件 UUID 或当前 Run 替代所选归属。Projection 的固定 basis、Run/plan、规则版本/摘要及逐测量重算与保存判定相互比对；原件逐字段核验来自不可变 MeasurementRecord 与原 capture，而非 UI 原值。
- 每个桥调用在字节读取前后核对原件 ACL/安全、固定执行/自身占用及来源 basis，并绑定运行时签发注册表、epoch、存储和安全端口。A 在全部读取之后逐失败调用 `recheck_fixed_failure_result`；该重核再次检查运行时 stamp 与保留证明，随后重新核当前政策及本操作专业资格。未发现后续读取可直接复用早期正面证明的旁路。历史执行窗口自然结束只排除两个显示时钟，不因此重新占用或获得新执行许可。
- 政策导入先核当前具名本人、产品写范围和精确可信 issuer；即使已存在 RequestKey，也先调用 `trusted_import` 核发布原文、来源 basis、issuer 与固定 payload，之后才返回原 Receipt。同 key 不同事实冲突；exact historical import 不倒退 Current。

`quality.policy.import → quality.policy_imported` 的共同 EVENTS 登记当前尚未加入。此前已向主线指出首次导入会在 Outbox 构造时遇到缺键；主线明确这是 Wave14 结束后统一公共接线的已知待办，**不列为漏掉的最终接线或新增桥缺陷**。该项完成前不能宣称 policy fixture/公共联验已通过。

本结论针对下面源码快照，不代替 Wave15 的真实 PG 回滚、跨字节故障注入、HTTP 或页面结果：

- `pdos-next/server/pdos_next/quality_result_bridge.py`：`28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077`
- `pdos-next/server/pdos_next/quality_policy_import.py`：`b38004b73ace8a67938c4ab1ff3fbf9b4e346b8cd4e2937c8b4e680c42d862ba`
- `pdos-next/server/pdos_next/domain/quality_execution/ports.py`：`3ecb83ea278cf36b15dc1c1103a499a5af94a103a6e506721c2f312c90fcc095`
- `pdos-next/server/pdos_next/domain/quality_execution/service.py`：`284f5749ca953ec24127b6595f263f0165faa5d1992095cb4b7639deff845427`
- `pdos-next/server/pdos_next/domain/quality_execution/policy.py`：`18987da3dcc09406abb09dabc5af99c1c21e627b857136b418a9fa490551755b`
