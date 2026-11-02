# D01 核对：预览与真实评测共用库和 Temporal（2026-11-01 22:20–22:30 PST）

[欠债总表 D01](../../../../tasks/ai-native-integrated-todo.md#debt-board) 的处理依据。全部是只读核对，连接时设了 `default_transaction_read_only=on`。唯一的改动是下面“改动”一节列的两处本机配置。

## 核对目标

- 预览库：容器 `pdos-comprehensive-c351c0ca`（ID a75fd85c2c11），端口 64387，库 `pdos_test`，`environment_guard` 标记 `c351c0ca-b874-49b9-bf1b-44c3ad150aaf`。三项与 `.local/comprehensive-runtime-20261022.json` 一致。
- Temporal：开发服务 127.0.0.1:61596，命名空间 `pdos-next-comprehensive-20261023`。
- 预览租户：`78340ac0-57c2-4235-87c6-a468dd3d8173`，取自 `.local/comprehensive-preview-20261022.json` 的工作台角色。

## 结论

- **原来担心的续派风险不成立。**
  - 派发只在 Worker 里做（`server/pdos_next/workflows/worker.py` 的 `dispatch_once` 和 `dispatch_pending_runs`），而且只处理 `PDOS_WORKFLOW_TENANTS` 列出的租户。预览只配了预览租户。
  - API 启动时只连接 Temporal，不派发（`server/pdos_next/api.py` 的 lifespan）。
  - `.claude/launch.json` 里没有 Worker 配置，当时也没有 Worker 进程。
- **预览租户没有积压。**
  - 排队中的运行 0 个，没派发的出站记录 0 条，自动化相关的 6 张表都是 0 行。
  - 运行状态分布：failed 40、completed 9、partial 3、cancelled 1、waiting_input 1。
- **库里有克隆来的历史积压，但预览碰不到。**
  - 有 2750 个“运行中”和 2203 个“排队中”的运行，还有 36408 条没派发的出站记录，时间都在 10-11 到 10-22 之间。
  - 它们分属 4394 个测试租户，不在预览租户内。
- **Temporal 现状**：命名空间里共 62 个工作流，只有 1 个还开着。
  - 工作流 ID：`pdos-next:xiaopai:78340ac0-…:aeea2e42-…`，类型 `XiaopaiWork`。
  - 挂在评测队列 `pdos-real-eval-20261101` 上。UTC 18:35 启动，18:36 完成一个活动后就在等待，没有待办活动。
  - 对应库里那个 waiting_input 的运行，属于评测遗留。
  - 两个队列（`pdos-next-domain-v1` 和评测队列）都没有 Worker 在拉任务，积压都是 0。
- **评测确实写进了预览租户。**
  - UTC 18:06–22:12 有 37 个对话运行，来自 4 个请求人，其中 28 个属于同一请求人。
  - 18:37 之后基本全部是 `EXTERNAL_OUTCOME_UNKNOWN` 失败，与 W1 的 D05、D06 相关。
  - 这段时间（PST 10:06–14:12）早于整仓重组挪目录（PST 19:45–21:47），两者没有撞上。
- **整仓重组的副作用**：`.local/agent-runtime/environment.json` 的 `temporal_binary` 仍指向已不存在的 `pdos-next/.local/tools/temporal`。
  - Temporal 当时没有停（PID 31427），但一旦重启，`tools/agent_runtime_environment.py` 的 `start()` 会找不到程序。

## 改动（只改本机配置，不进 git）

1. `.claude/launch.json`：`comprehensive-api` 去掉 `--watch tools`，保留 `server/pdos_next` 和 `packages/pdos-agent-runtime/src` 两个监视目录。
   - 改动前的副本在会话临时目录，未入库。
   - 当时在跑的 API 是 PST 22:15 由「项目代码结构优化」会话启动的，仍按旧参数运行，新参数要等下次启动预览才生效。
   - 没有重启它，原因有两个：API 重启本来就不派发；由本会话重启会让预览归到本会话名下，以后归档本会话时会被一起停掉。
2. `.local/agent-runtime/environment.json`：`temporal_binary` 改为 `.local/tools/temporal`（版本 1.9.1，Server 1.32.0）。
   - 写法与 `private_write` 一致：紧凑 JSON，权限 600。
   - 原文件备份为同目录下的 `environment.json.before-d01-20261101`。

## 留给其他条目

- 评测与预览仍然共用一个库、一个租户和一个命名空间。评测运行会出现在预览的小Pai 历史里，预览里的操作也可能混进评测数据。真正隔离要靠 D59：每个会话独立工作树，评测另起一个库。
- 那个还开着的评测工作流，以及临时 API 和 Temporal，由 D08 收尾时一并关掉。
- `.local/` 下还有几十个 10-16 到 10-19 的历史状态文件写着 `pdos-next/` 旧路径。它们已不再使用，没有改。
