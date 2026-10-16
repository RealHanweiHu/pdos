# 租户模型默认宿主接线 · 2026-10-16

已补齐默认 API/Worker 的租户密钥、服务商与费率端口，并打通“实际受理 → Temporal → 默认 Worker 主入口 → LangGraph → 提案候选 → 本人一次确认 → 实际保存”闭环。本批按冻结 v1.1 §06/§07.5 建设，没有新增迁移或前端。基线 `c6e7f5e`，源码摘要见 [source-manifest.json](source-manifest.json)。

## 交付

- 阿里云 KMS 通用凭据适配使用官方 SDK 与官方身份链。状态读取只取版本元数据；解密时同时指定当前版本和 `ACSCurrent`，核对返回名称/版本/阶段/文本类型。对外错误不包含云 SDK 原始错误或凭据。支持地域对应的共享公网/VPC HTTPS 网关；专属网关未实现。
- 服务器元数据文件按租户/协议绑定完整 KMS ARN 与稳定引用，按精确模型地址/名称/版本绑定服务商身份和当前十进制 USD 价格卡。API 与 Worker 共用绝对路径，默认 Bootstrap 实际加载；显式注入保留。文件不存密钥、不授予资格，KMS 版本/目标轮换使旧绑定失效。
- Run 钉住实际服务商身份，后续调用不能静默换服务商；现行签约/范围/资格/来源/预算仍执行。修复了默认 Run 固定 100,000 token 导致完整注册工具请求在充足钱包下提前结束的问题：由服务器所选活动钱包的输入/输出上限确定 Run 上限，共用钱包原子限制保持。
- 提供 [配置示例](../../../../../pdos-next/config/tenant-runtime.example.json)、[运行手册](../../../../runbooks/pdos-next-tenant-model-runtime.md)和环境变量入口。示例价格已过期且费用覆盖标志为 false，不能作为真实价格或资格。

## 集中验证

| 检查 | 结果 | 证据 |
|---|---:|---|
| 模型配置纯检查，含 13 个新宿主病例 | 89 通过 | [pure-final.log](checks/pure-final.log) |
| 网关、费用、实际配置保存与 Worker 恢复 | 30 通过（29 实库、1 纯检查） | [pg-regression-candidate.log](checks/pg-regression-candidate.log) |
| 完全默认 API/Worker 的实际提案保存及费用结算 | 1 实库/进程病例通过 | [pg-host-final.log](checks/pg-host-final.log) |
| 受影响 Ruff | 通过 | [ruff-final.log](checks/ruff-final.log) |

合计 **120 个不同病例：30 实库、90 纯检查**，不累加重复运行。正向模型配置覆盖 OpenAI 兼容和 Anthropic 原生两种协议；新 KMS 检查覆盖元数据分页、唯一当前版本、轮换、租户/协议隔离、精确模型与价格失效。原 Worker 两项验证仍实际停止/重启进程，继续证明同 Temporal 工作和同 PostgreSQL 检查点恢复、离线取消不写回。

默认宿主进程病例的 API、Worker 均不注入 `RuntimePorts` 或完整适配器，仅替换 KMS SDK 和模型网络传输。其余采用默认预加载、实际签约/技能/模型配置路径和严格费用检查。两次合成模型调用生成一个可确认候选，人工预览/确认后实际落一份草稿提案及绑定原 Run 的回执。按合成用量/费率在实际账本结算 240 微美元，调用数 2、占用归零，凭据轮换后管理页显示“需重新绑定”；见 [业务回读](business-result.json)与 [Worker 阶段日志](checks/host-worker-final.log)。`cost_state=actual` 仅表示这两次合成已知用量的账本状态，不是外部模型真实费用。

业务库始终是已核对标记的独立 `127.0.0.1:64245/pdos_test`，head `s0_0762`，检查点使用同标记容器的 `pdos_checkpoints`。本地 Temporal 使用专用、核对标记的 namespace；本批自有实际工作全部终结，共用服务和历史保留，见 [runtime-status.json](runtime-status.json)。无 `.env` 回退，无删库、push 或生产操作。未改前端，不重跑浏览器或构建；这是实际 ASGI/进程/数据库闭环，并非浏览器或真实模型验收。

## 失败与修复记录

1. [首次运行](checks/pg-host-first.log)在固定 Run token 上限下提前 `partial`，模型传输次数为 0；已修复服务器预算绑定，最终用例核对 Run 上限为 1,322,880 且钱包限制仍有效。
2. [后续运行](checks/pg-host-fixed.log)完成模型调用，但合成用例把新建提案错误绑定到了已有型号；服务器正确拒绝 `proposal_run_mismatch`。修正为品类范围，并在合成模型第二轮明确断言工具候选成功，再完成实际采用，[品类运行](checks/pg-host-category.log)通过。
3. 最终把 Worker 用例收紧为完全默认 `main()`，只替换两种网络传输；[最终运行](checks/pg-host-final.log)再次通过。中间 [回归调用](checks/pg-regression.log)因测试路径笔误未收集病例，不计通过数；修正路径后上述 30 项集中通过。

框架保留既有 `Session.flush(objects)` 弃用提示；没有新增运行失败。测试后只收回 Bootstrap 无关格式变化，行为不变，未进行无必要重跑。

## 仍需实际材料的部分

真实 KMS 云权限/网络/凭据、实际服务商协议、当前已核对费率和计费边界尚未配置或验证；真实模型质量、适用资格审阅及三入口真实模型联验、正式性能/恢复、完整 M3/S1 出口仍未完成。该文件与合成检查不替代这些证据。后续按[运行手册](../../../../runbooks/pdos-next-tenant-model-runtime.md)接入获得授权的真实配置；外部条件等待期间继续已授权的独立建设。

本批真实模型调用 **0**、真实 KMS 请求 **0**、golden-case 写入 **0**。官方接口依据：[版本元数据](https://www.alibabacloud.com/help/en/kms/key-management-service/developer-reference/api-kms-2016-01-20-listsecretversionids)、[精确版本取值](https://www.alibabacloud.com/help/en/kms/key-management-service/developer-reference/api-kms-2016-01-20-getsecretvalue)、[官方凭据链](https://help.aliyun.com/en/sdk/developer-reference/v2-manage-python-access-credentials)。
