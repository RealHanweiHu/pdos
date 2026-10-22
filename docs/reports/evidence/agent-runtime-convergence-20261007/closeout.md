# 检查与环境收尾

原测试目标 `58949/pdos_test`（head `0431_conversation_research_exploration`）和 Next 测试目标 `61762/pdos_test`（head `next_0032`）均通过 Docker label、端口与数据库 marker 核对。三个数据库归档已保存至私有目录 `/Users/huhanwei/.codex/agent-convergence-recovery-20261007/`，权限 0600，归档清单可读并记录 SHA-256；两套自有测试容器停服，卷与数据保留。完整记录见 [收尾 JSON](closeout.json)。未停止或操作其他测试/业务容器。

项目途中迁至 iCloud Documents，读取被 macOS 拒绝。完成独立备份与停服后，用户恢复可访问路径，随后明确项目移至桌面。源码、证据完整保留；目录迁移没有触发重建、覆盖或业务数据恢复。桌面路径为 `/Users/huhanwei/Desktop/ai-native-R&D-platform`。

已核对开发状态服务身份与零在途工作，保留私有配置副本后更新本机 Temporal 工具路径，并仅重启本会话自有、空闲的 Agent Worker 与 Temporal。PostgreSQL `61595/pdos_agent_runtime` 与 Temporal `61596/pdos-agent-local` 保持运行；迁移后复核 Workflow/Activity poller 各 1，工作数与运行中 Workflow 均为 0，见 [Worker 状态](worker-state.json)。未发起真实模型或业务动作；现有预览 API 与网页未重启。开发 API 入口使用 `python -m uvicorn`，避免项目迁移后旧命令脚本路径失效。

受影响 Next 前端全类型检查与两个文件的 ESLint 均通过。第一次类型检查被生成缓存 `.next/types/cache-life.d 2.ts` 重复声明阻断，保留其私有副本后移除重复生成文件，复查通过；未新增全构建或 GUI 声明。

新增原工程四个运行适配器采用严格类型检查、`--follow-imports=silent` 聚焦受影响源码；结果及最终入口检查见 [最终检查记录](final-checks.json)。展开全依赖的类型检查未通过，报告 12 个依赖文件的 115 个错误（schema 约束类型、现有授权/上下文/流式处理/会话等）；不能据聚焦检查宣称整个后端类型检查通过。本轮未扩展修改这些依赖。受影响 Python 规范与启动脚本语法、受影响已跟踪文件 diff 空白检查通过。迁移后虚拟环境的旧 pytest 命令脚本路径失效，检查改用同一解释器的 `python -m pytest`，没有改变依赖版本。

启动独立状态服务时首次尝试未缓存 PostgreSQL 镜像被 Docker 认证连接失败阻断；改用已有 PG16/pgvector 缓存镜像并显式禁止拉取后启动通过。临时测试 PG 锁容量不足的失败与处理、事件结果编码修复及原影子用例合同拒绝均在 [结果](result.md)及原日志中保留。

无 commit/push、生产部署、真实外发、真实资格授予或人工 Exit 改动。
