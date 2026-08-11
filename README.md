# PDOS · AI-native 产品开发操作系统（工作名）

面向制造业产品开发与项目管理的过程记录与 AI 装配层：事件驱动 Agent 产出发现，人审裁决落库。
按 [preview.zip 规格](docs/specs/cehub-v3.2-preview/) 全量建设；老 CEHub 为可选代码复用源，最终由本系统替换。

## 文档索引

| 文档 | 内容 |
|---|---|
| [执行计划](docs/design/2026-08-09-preview-execution-plan.md) | 六 Sprint 工作项与验收、基础设施复用参数、方法论审查纪律（§11） |
| [汇合决策](docs/design/2026-08-09-cehub-v32-convergence.md) | 规格地位、CEHub 角色、切换策略 |
| [UI 基线](docs/design/2026-08-09-ui-baseline.md) | 设计系统 token、信息架构、三承重界面交互（已拍板） |
| [结构与实施校准](docs/design/2026-08-10-structure-and-delivery-review.md) | 六层结构确认、已收口冲突、进入 S0-1 的条件 |
| [当前执行队列](tasks/todo.md) | 当前工作项的可验证切片；不替代唯一执行计划 |
| [产品提案 v0.3](docs/design/proposal.md) / [M0 计划](docs/design/m0-plan.md) | 历史工程参考（连接器/检查项导入/LLM trace 纪律仍取用） |
| [调研报告](docs/research/report.md) | 11-agent 全网调研（Attio/Lightfield 等） |

## 快速开始（开发）

前置版本：Node.js 22+、Python 3.12、`uv`、pnpm（或 Corepack）和 Docker Compose。仓库中的
`.nvmrc`、`.python-version`、`web/package.json` 与锁文件共同固定运行时和依赖版本。

```bash
cp .env.example .env  # Sprint 0/1 无需 LLM key；Sprint 2 前填写所选供应商凭据
make setup
make dev
```

根目录命令是本地与 CI 的统一契约：

| 命令 | 用途 |
|---|---|
| `make setup` | 校验工具版本并按锁文件安装 web/server 依赖 |
| `make infra-up` | 启动固定版本的 pgvector/PG16 与 MinIO |
| `make db-migrate-test` | 经过 fail-close 保护后只升级 `pdos_test` |
| `make dev` | 同时启动 Next.js 与 FastAPI 开发进程 |
| `make production-preflight` | 在任何生产迁移/部署前 fail-close 校验目标库、TLS、凭据模板与文件权限 |
| `make smoke-app` | 在隔离端口启动 web/API 并核对真实 HTTP 响应 |
| `make smoke-production` | 构建生产镜像，并仅对隔离的 `pdos_test` 执行容器级 smoke |
| `make test` | 运行 web/server 测试 |
| `make lint` | 运行 ESLint、Ruff 与格式检查 |
| `make type` | 运行 TypeScript 与 Python 严格类型检查 |
| `make build` | 构建 Next.js 并编译检查 Python 源码 |
| `make check` | 顺序执行 lint、type、test、build 完整门禁 |
| `make verify-s0-1` | 执行隔离迁移、完整门禁和运行时 smoke，作为 S0-1 单一验收入口 |
| `make verify-sprint-0` | 汇总全部 Sprint 0 本地门禁，并增加生产容器级 smoke |

`make dev` 会保留本地数据卷并按需启动依赖；`make infra-down` 只停止容器，不删除数据卷。
若 55432 已被其他本地项目占用，可临时设置 `PDOS_POSTGRES_PORT`，并让
`DATABASE_URL`/`TEST_DATABASE_URL` 使用相同端口；compose 的默认值仍为 55432。

首次启动认证服务前，确认 `.env` 中的 `JWT_SECRET` 至少 32 字节；早期模板生成的
`dev-only-change-me` 已不再接受。空库通过 `POST /api/setup` 原子创建首个租户与初始化
管理员；该入口成功一次后永久 fail-close。随后使用 `POST /api/auth/login` 获取短期 Bearer
JWT，并通过 `GET /api/auth/me` 验证服务端重新解析的活跃租户上下文。

浏览器入口为 `/login`。Next.js 的同源 `/api/session/*` BFF 使用
`PDOS_API_INTERNAL_URL` 访问 FastAPI，将 JWT 只写入 HttpOnly、SameSite=Lax cookie；token
不会返回给客户端 JavaScript，也不写入浏览器存储。生产环境不要给该内部地址添加
`NEXT_PUBLIC_` 前缀。

生产部署使用 `compose.production.yaml`，启动顺序固定为 migration→API healthy→web
healthy，宿主机只绑定 `127.0.0.1:${APP_PORT}:3000`。部署、Nginx、DNS 与回滚步骤见
[`docs/runbooks/sprint-0-ecs-smoke.md`](docs/runbooks/sprint-0-ecs-smoke.md)；执行任何外部环境动作前必须取得明确授权。

## 不可协商项（摘要）

1. AI-native：Sprint 2 起 AI 在关键路径，拆除测试为验收判据
2. AI 输出人审：Agent 唯一写出口 = finding；`pdos_agent` 数据库角色零业务表写权限
3. 不替代 ERP/MES/PLM；SoR 边界见规格
4. Alembic 迁移与 schema 永不脱节；测试库独立隔离
