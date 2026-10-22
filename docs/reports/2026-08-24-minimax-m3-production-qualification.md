# MiniMax M3 生产资格真实复验报告

日期：2026-08-24

状态：**真实评测 3/3 与人工逐项复核均通过，完整本地 production preflight 全绿；未 push、未部署、未修改生产环境。**

## 授权与数据边界

- 人于 2026-08-24 明确授权，将 `server/golden/model-gateway-v1.json` 中 3 条合成 golden-case 经运行时白名单投影后发送给 MiniMax M3 进行真实评测。
- 评测从本地 `.env.production` 读取服务端配置，但未输出或写入任何 API key。
- 出站内容仅为冻结的 system prompt、instruction、输出 schema 与白名单上下文字段；`confidential_notes`、`document_original` 等禁发字段不进入供应商请求。
- 本报告只保存供应商/模型身份、suite 身份、逐用例通过状态、尝试次数、错误码和 token 数；不保存模型响应正文、密钥或生产业务数据。

## 冻结身份

- Provider：`minimax`
- Model：`MiniMax-M3`
- Suite version：`s2-model-gateway-v1`
- Suite digest：`sha256:9a0ee7c02391940a461c6ceaee60a771e85e5cb3587d3cb5a5dab91361ed01ab`
- Pass threshold：`1.0`

上述 suite version/digest 与 `server/golden/model-gateway-v1.json` 的当前可信根及 `server/golden/model-qualifications.json` 中 MiniMax M3 资格条目精确匹配。

## 真实评测结果

| Case | 结果 | 尝试次数 | 错误码 | Input tokens | Output tokens |
|---|---|---:|---|---:|---:|
| `project-risk-high` | passed | 1 | — | 393 | 104 |
| `project-risk-low` | passed | 1 | — | 394 | 126 |
| `project-risk-boundary` | passed | 1 | — | 394 | 152 |

- 总体状态：`passed`
- Pass rate：`1.0`（3/3）
- 总尝试次数：3；重试：0
- Token 合计：input 1,181；output 382
- Provider/schema 错误：0

## 人工复核与本地发布门禁

- 人于 2026-08-24 确认已复核本报告；3/3、pass rate、provider/model 与 suite version/digest 均获确认。
- 人已补齐本地 `.env.production` 的 `PDOS_WORKER_DATABASE_URL` 与 `PDOS_AGENT_DATABASE_URL`，没有在对话、日志或仓库中披露连接值。
- `make production-preflight` 全绿：环境文件安全校验与 `compose.production.yaml` 解析均通过，检查过程只输出通过状态。
- `.env.production.example` 已补充两个必填受限 DSN，并用生产部署合同测试固定三个数据库角色必须隔离。
- 完整 `make check` 全绿：916 个锁定依赖/0 已知漏洞、Server 414、Web 145、Ruff/253 format、mypy 217、ESLint/TypeScript、Next 37 页生产构建与 Python compileall 均通过。
- 首次全量复验发现本机 `.env` 的测试 DSN 仍指向已被老 CEHub 占用的 `55432`；只读确认 PDOS 的 `pdos_test` 容器实际位于 `57432` 后纠正本地忽略文件，测试安全检查再次确认只连接 `pdos_test`。生产配置未受影响。

## 发布边界与下一门禁

- 本次评测不自动发布或改写模型资格；当前资格文件无需变更，因为 provider、model、status、suite version 与 digest 已精确匹配。
- 人工复核与本地 production preflight 门禁现已完成；这只证明发布配置可用，不代表生产已启用 MiniMax M3。
- 新 release SHA、Git push、ECS build/deploy、migration、权限重施、容器重启及部署后 smoke 均不在本次授权范围内。
