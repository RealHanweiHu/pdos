# 小Pai会话线程与追问恢复

基于 `36b2918`，补齐 v1.1 §06.2 的“每个会话一个 LangGraph thread”。新 Run 在服务器记录检查点布局，同会话共用线程、各次工作以存储命名空间隔离；LangGraph 图内命名空间、等待和 pending writes 保留。旧 Run 按原布局恢复，不搬迁检查点、不重新执行模型。短记忆和来源仍沿上一闭环的领域投影，不拼接旧工具或模型原文。

## 验证与实际结果

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 检查点协议、独立等待/恢复、旧无 Run 标记状态及原执行图 | 15 通过 | [pure-final](pure-final) |
| 续接、反馈、处理过程、采用等待及宿主读取 | 81 通过 | [affected-pg-01](affected-pg-01) |
| 真实生产 Worker 子进程、Temporal 与 PostgreSQL 检查点 | 3 通过 | [process-01](process/process-01) |
| 受影响 Ruff | 通过 | [ruff-final.log](ruff-final.log) |
| 未启用 MiniMax 草案格式及失效价格守卫、自有任务收尾 | 通过 | [最终核对](status-and-draft-final)、[结构化状态](runtime-and-draft-status.json) |

合计 **99 个不同病例**，不累加重跑；[完整收集清单](cases)记录范围。新实际进程场景共启动 3 个 Worker：原工作完成并由本人确认 1 个真实 T1 Claim；执行服务离线时受理追问，恢复后等待新答复；再次离线时提交答复，重启后仍是同一 Temporal execution。原工作与追问共用 1 个 PG thread、2 个 Run namespace，原检查点不变，追问不重建 Claim，预算占用归零。历史只含服务器引用。[Worker 阶段日志](process/worker-logs)保留 3+2 次合成模型阶段，无真实模型或 KMS 调用。原等待恢复及离线取消两项也通过。

测试仅使用已核对 marker 的独立 `127.0.0.1:64245/pdos_test` 与同标记检查点库，业务 head 保持 `s0_0772`，没有新增迁移。自有 4 个 Run 全部终结、占用归零；专用 namespace 无运行中工作，共用服务和合成历史保留。前端未改，本批不重复构建、浏览器或攻防；旧布局恢复由实际内存 saver/执行图验证，未将它表述为历史 PG 数据迁移验收。

## MiniMax 与剩余条件

用户指定**国内 MiniMax M3、没有协议**；已据官方文档准备[可审阅方案](../../../../runbooks/minimax-cn-m3-validation-draft.md)与[未启用配置](../../../../../pdos-next/config/minimax-cn-m3.draft.json)。草案通过宿主 DTO 校验，但因过期价格及未核对费用覆盖明确返回 `SOURCE_UNAVAILABLE`；未设置运行时路径或真实租户/凭据，不建立假协议。现有默认 Run 绑定内部/客户资料，不能把提示词写成合成而绕过签约守卫。模型协议细节、当前价格/计费上界、实际凭据、适用资料范围及对应真实外发授权仍待补齐。

真实模型调用 **0**、真实 KMS 请求 **0**、golden-case 写入 **0**、push/生产操作 **0**。真实模型资格、三入口真实模型及完整 M3/S1 出口未完成，S2–S4 仍按冻结顺序接续。

## 保留的初次检查问题

- [pure-01](pure-01)、[pure-02](pure-02)：测试错误地假设底层 saver 添加 allowlist 必须返回新对象；库可合法返回自身。改为验证适配器确实传递派生 saver/serde，最终 15 项通过，未放宽存储隔离。
- [status-and-draft](status-and-draft)、[status-and-draft-02](status-and-draft-02)：私有收尾脚本先后遇到领域模型初始化顺序与路由属性笔误；修正脚本后最终只读核对通过。均未调用模型或改变业务事实。

源码与证据摘要见 [source-manifest.json](source-manifest.json)、[checkpoint.json](checkpoint.json)。
