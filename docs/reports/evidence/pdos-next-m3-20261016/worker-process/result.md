# 小Pai Worker 进程等待、恢复与取消 · 2026-10-16

本批验证了冻结 v1.1 §06.2/06.10/06.11 的实际持久运行链：鉴权 API 的真实 lifespan → 本地 Temporal → 正式 Worker 主入口进程 → Activity → LangGraph → 独立 PostgreSQL 检查点 → T1 领域命令及回执。新增两个可复跑的进程集成检查；不改业务规则，不新增模型资格、迁移或前端。

## 已取得的证据

1. API 受理一个真实合成 Run。Worker 提问并进入等待后，结束该 Worker 进程；在 Worker 离线期间，通过 API 提交实际回答，再启动另一个 Worker 进程。同一 Temporal 工作继续，同一 PG 检查点 thread 的步骤向前推进，合成模型没有重复提问。后续产生实际 Claim 候选，经本人一次确认，得到一个署 AI 作者、归属本人负责的 Claim 和一份领域回执；原命令重放返回同一回执，Run 预算占用释放。
2. 另一 Run 等待期间结束 Worker，API 离线取消后预算占用立即为 0。重启 Worker 后，原 Temporal 工作变为 `CANCELED`，业务 Run 保持 `cancelled`、`cancel_epoch=1`，没有 Claim 写入。
3. 实际 Temporal 历史检查：启动只含 tenant/category/actor/requester/Run 五个引用字段，Activity 仅增加回答引用，signal 只含已提交回答的 UUID。正文、问题答案、凭据和模型工具载荷不进入这些历史输入。

集中 [pg-candidate.log](checks/pg-candidate.log) 两项通过；随后只为第一项新增 PG 检查点 thread/版本前后对照并定向复核，[pg-checkpoint-final.log](checks/pg-checkpoint-final.log) 一项通过。**合计两个不同实际进程/实库病例**，不累加首轮和重叠复验。受影响 [Ruff](checks/ruff-final.log) 通过。业务、前端和迁移源码未改，不重跑构建或完整回归。

首轮正向原始记录见 [pg-first.log](checks/pg-first.log)。进程的合成模型阶段日志见 [worker-phases.json](worker-phases.json) 及 [worker-logs/](worker-logs/)：第一次进程只有 `question`，恢复进程为 `claim_candidate → final`；取消后的新进程不再进行模型步骤。新测试须显式选中已核对的本地进程 profile，常规离线测试不会自动连接或创建运行环境。

## 环境和边界

- 基线 `c01f5c4`，实现及被验证运行框架摘要见 [source-manifest.json](source-manifest.json)。业务操作只使用已核对的独立 `127.0.0.1:64245/pdos_test`，真实 head `s0_0762`；检查点使用同一标记容器中的 `pdos_checkpoints`、普通检查点账号。没有 `.env` 回退。
- 共用本地 Temporal 起初已停止，经既有 `server/scripts/agent_runtime_environment.py` 恢复。采用带 M3 标记的专用测试 namespace，未消费其他 namespace 的任务。每个 Worker 都是独立操作系统进程，经过实际停止和重新启动；全部为本批自有进程。
- Temporal 使用既有本地开发 SQLite 历史，不冒充生产 PostgreSQL Temporal 的恢复证明。业务库和 LangGraph 检查点均为真实 PostgreSQL。全部自有任务已终结，见 [runtime-status.json](runtime-status.json)；共用服务和历史保留，没有删库或清理其他任务。
- 模型为本地合成适配器。通过正式 `workflows.worker.main(agent_kernel_adapters=...)` 注入合成 provider、预加载、费率豁免及测试密钥绑定；API 只对合成字节计量扩大测试预算。领域权限、受控命令、来源、回执、Temporal 与检查点均走实际实现。没有外部 provider 请求，没有真实签约材料、真实资格或生产启用。
- API 为实际鉴权 ASGI 路径及实际 lifespan，未把本批称为浏览器或真实模型整链验收。

## 剩余与下一步

本批补到了 Worker 进程层的实际恢复证据，**完整 M3/S1 未完成**。宿主接线检查确认，默认 `RuntimePorts` 中租户密钥、服务商身份和费率仍需实际配置实现；`Bootstrap` 在缺少密钥或服务商绑定时按现行规则拒绝运行。当前成功不能证明未注入这些端口的默认部署已具备真实模型能力。

下一步先补租户级宿主运行配置，并沿用现有元数据登记、签约、预算和凭据版本检查，再推进真实模型及资格审阅；实际服务商协议、真实材料/模型质量、正式性能与恢复、完整阶段出口仍需对应证据。S2–S4 保持冻结顺序，未恢复施工。

真实模型调用 **0**，无 golden-case 写入、真实外发、push 或生产操作。原设计稿及其他聊天备注保持未提交。
