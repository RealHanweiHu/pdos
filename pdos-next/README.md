# pdos-next

PDOS 的现行工程。设计依据是[完整目标架构 v1.1](../docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md)，活动状态见[整合清单](../tasks/ai-native-integrated-todo.md#current-queue)。

## 目录地图

```text
pdos-next/
  web/                      Next.js 前端（BFF 与页面）
    src/app/                路由：页面与 /api 代理
    src/features/<领域>/    按产品区域组织的组件与该区域专用逻辑
    src/components/ui/      shadcn/ui 基础组件
    src/lib/                跨区域共用的视图模型与 API 客户端
    src/lib/server/         只在服务端运行的 BFF 代理
  server/                   FastAPI 领域服务（Python 包 pdos_next）
    pdos_next/              见下表
    migrations/             Alembic 迁移链（只增不改）
    tests/                  后端测试，目录名对应被测领域
  packages/
    pdos-agent-runtime/     共用的 Agent 持久运行框架（LangGraph + Temporal）
  contracts/                机器可读契约：operations、payloads、events、openapi、acceptance
  config/                   租户运行配置示例
  containers/               受隔离的原件解析容器
  infra/                    本地设施：searxng（compose.yaml）、RDS CA 证书
  assets/cehub/             CEHub 交付物指南清单（工作模板直接读取）
  tools/                    本地环境、评测与契约工具，见下文
```

### 后端 `server/pdos_next/`

| 目录 | 内容 |
|---|---|
| `asgi.py`、`api.py` | ASGI 入口（`uvicorn pdos_next.asgi:app`）与 HTTP 路由装配 |
| `core/` | 共用内核：数据库与 ORM 注册（`models.py`）、通用命令与回执（`service.py`、`command_handlers.py`）、错误目录、时钟、请求证明、运行撤回、品类权限范围、事件外发（`dispatch/`） |
| `domain/` | 各业务领域的规则、存储与命令处理，一个子目录对应一个领域；`domain/engines/` 是计划、供应成本等纯计算引擎 |
| `features/` | 面向页面的应用层切片，组合多个领域的读取视图、HTTP 接口和宿主接线：`personal/`（我的工作、摘要、偏好）、`projects/`、`change/`、`quality/`、`capa/`、`lifecycle/`、`inbox/` |
| `agent/` | 小Pai：`kernel/`（唯一注册执行图、工具、技能管理、上下文）、`skill_packages/`、`prompt_packages/`、`model_gateway/`、`model_configuration/`、`research/`（公开研究）、`enterprise_search/`（企业检索） |
| `providers/` | 模型服务商传输（OpenAI 兼容、Anthropic 原生） |
| `originals/` | 原件：授权读取、上传生命周期、撤回、对象存储与日志、生命周期规则与执行 |
| `evidence_processing/`、`evidence_security/`、`security_runtime/` | 原件解析、扫描与解析容器运行时 |
| `integrations/` | 外部渠道，目前是钉钉只读入口（`dingtalk/`） |
| `workflows/` | Temporal 工作流、Worker 与检查点 |
| `bootstrap/` | 仅供本地标记宿主使用的合成配置与受信导入，不注册为公开命令或 AI 工具 |
| `schemas/` | 跨领域共享的冻结 DTO |
| `errors.py` | `DomainError` |

几处位置是有意保留的：`errors.py` 留在包根，因为 `domain/verification/rules.py` 的内容哈希会写进验证结果；`providers/` 和 `schemas/` 受规格冻结测试约束；`evidence_processing/` 的两个源文件哈希固定在 `security_runtime/parser-image.json`，与已构建的解析镜像对应。移动这些文件前，先处理对应的哈希或镜像。

### 工具 `tools/`

| 用途 | 脚本 |
|---|---|
| 本地环境 | `local_environment.py`（独立 `pdos_test` 与 API/Web 预览）、`workflow_environment.py`（Temporal 与检查点库）、`agent_runtime_environment.py`（共用 Agent 状态库与 Temporal 开发服务）、`comprehensive_preview.py`（完整预览）、`acceptance_account.py` |
| 小Pai 评测 | `xiaopai_prompt.py`（提示词版本与 A/B）、`xiaopai_recall_*`、`xiaopai_context_*`、`xiaopai_real_*`（真实服务商评测） |
| 契约与性能 | `export_contracts.py`、`validate_contracts.py`、`current_read_profiler.py` |

历次 wave/m2/m3/s0 检查点脚本已于 2026-11-01 删除，可在标签 `archive/pre-restructure-2026-11-01` 中查看。

## 安装与检查

```bash
cd pdos-next/server && uv sync --locked
cd ../web && pnpm install --frozen-lockfile
```

工具从仓库根目录用 `pdos-next/server/.venv/bin/python pdos-next/tools/<脚本>` 执行，不读取旧 `.env`；私有状态与凭据只放在被忽略的 `.local/`。

- 前端：在 `web/` 执行 `pnpm typecheck`、`pnpm lint`、`pnpm build`。
- 后端：依赖数据库的测试必须显式设置 `TEST_DATABASE_URL`、`DATABASE_URL`、`AUTH_DATABASE_URL`、`DISPATCH_DATABASE_URL`，指向已核对的独立临时 `pdos_test`；没有回退。
- 本地搜索：`docker compose -f pdos-next/infra/compose.yaml --profile research up -d searxng`。

正常服务必须显式配置非属主的 `DATABASE_URL` 和只读的 `AUTH_DATABASE_URL`，迁移另用 `MIGRATION_DATABASE_URL`。真实部署、模型资格、出站许可和正式发布按对应授权办理。
