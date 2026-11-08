# PDOS

**AI 原生的产品开发与 NPI 协作平台。**

PDOS 面向消费电子与硬件研发团队，以项目为工作中心，将产品要求、工程配置、样件、验证结果、问题变更和制造导入串成可追溯的工作过程。NPI（New Product Introduction，新产品导入）与工程研发共同推进，在每一轮实物活动中核对要求、配置和结果。

小Pai是系统唯一的 AI Agent，帮助团队研究资料、起草内容、核对缺项和跟进工作。它通过受控工具使用业务数据，产生的候选、来源和运行回执可供人员核对。

> **项目正在建设与试点验证中。** 代码结构见下文[仓库结构](#仓库结构)。下文介绍产品方向与开发入口；各项能力的实际覆盖、验证证据和剩余缺口，以[当前执行清单](tasks/ai-native-integrated-todo.md#current-queue)为准。

## 围绕项目开展工作

项目从客户需求、自主新品或派生迭代开始，经立项提案与 G0 评审进入开发，再沿产品定义、工程与制造策划、实物验证、问题整改和制造交付逐步推进。

| 工作区域 | 主要内容 |
|---|---|
| 我的工作 | 待决定、待接收、待验证、外部等待，以及本人任务、承诺和项目动态 |
| 项目工作区 | 项目目标与计划、专业职责、工程与制造准备、Build、样件、测试和交接 |
| 产品管理 | 品类知识、规格字典、竞品对标、立项提案、G0 评审与版本化产品定义 |
| 问题与变更 | 问题处置、工程与制造双线影响、批准实施、新配置采用和复验回链 |
| 制造与交付 | 试产、制造准备、固定交付包、具名发布决定及外部移交回执 |
| 知识与小Pai | 经验候选与适用范围、资料研究与解析、内容起草、候选确认和会话恢复 |

品类是权限范围根，型号是持续演进的产品身份，项目承载有明确目标与边界的开发活动。Build 表示一次固定配置、实物和验证范围的活动；测试结果保留对应样件、方法、原值和来源。

## 小Pai如何参与

对话、页面动作、事件和定时工作共用一个小Pai。技能包按需加载，外部能力通过已授权的 MCP 连接器接入；人员权限、当前范围、预算和资格由服务器核对。

AI 写入按操作分级：

| 档位 | 办理方式 |
|---|---|
| T0 | 在有效资格与当前授权内自动写入适用草稿，保留 AI 作者与运行记录 |
| T1 | 预填候选，由本人核对后一次确认 |
| T2 | 保留具名批准、专业签核、正式发布或外发决定；AI 仅准备材料 |

业务写入经过领域命令，保留幂等、来源、版本与回执。结果未知时先核对原请求；按运行撤回受到业务引用和当前状态约束。缺少模型配置时，小Pai显示不可用原因，人员仍可使用已开放的业务入口。

## 技术架构

| 层次 | 技术与职责 |
|---|---|
| Web | Next.js、React、TypeScript；shadcn/ui、Tailwind CSS v4、Geist 与 Phosphor 图标，支持亮暗主题 |
| 领域服务 | FastAPI、SQLAlchemy、Pydantic；负责业务事实、权限、版本、事务和批准 |
| 数据与迁移 | PostgreSQL、行级安全（RLS）、Alembic |
| AI 执行 | LangGraph 管理能力内执行与检查点；技能包和注册工具定义可用能力 |
| 持久任务 | Temporal 管理排队、等待、取消与恢复，通过 Workflow 和 Activity 调用 LangGraph |
| 模型与连接 | 支持 OpenAI 兼容和 Anthropic 原生协议；模型网关、MCP、预算与凭据由服务端管理 |

系统的业务事实与批准由领域服务持有，AI 通过同一套受控入口办理。ERP、MES、PLM 等外部系统按集成边界接入。

## 仓库结构

本仓库就是 pdos-next 工程（代号沿用），代码直接位于仓库根目录。

```text
web/                          Next.js 前端（页面与 BFF）
  src/app/                    路由：页面与 /api 代理
  src/features/<产品区>/       按产品区组织的组件与该区专用逻辑
  src/components/ui/          shadcn/ui 基础组件
  src/lib/                    跨产品区共用的视图模型与 API 客户端；src/lib/server/ 为服务端 BFF 代理
server/                       FastAPI 领域服务（Python 包 pdos_next）
  pdos_next/                  见下表
  migrations/                 Alembic 迁移链（只增不改）
  tests/                      后端测试，按与 pdos_next 相同的产品区分组
packages/pdos-agent-runtime/  共用 Agent 持久运行框架（LangGraph + Temporal）
contracts/                    机器可读契约：操作、载荷、事件、接口与验收
config/                       租户运行配置示例
containers/                   受隔离的原件解析容器
infra/                        本地设施：searxng（compose.yaml）、RDS CA 证书
assets/cehub/                 CEHub 交付物指南清单（工作模板直接读取）
tools/                        本地环境、评测与契约工具
docs/                         设计、运行手册、评测题集与验证证据
tasks/                        唯一活动状态清单
```

### 后端 `server/pdos_next/`

| 目录 | 内容 |
|---|---|
| `asgi.py`、`api.py` | ASGI 入口（`uvicorn pdos_next.asgi:app`）与 HTTP 路由装配 |
| `core/` | 共用内核：数据库与 ORM 注册、通用命令与回执、错误目录、时钟、请求证明、运行撤回、品类权限范围、事件外发（`dispatch/`） |
| `domain/` | 业务领域，按产品区分组，见下表 |
| `agent/` | 小Pai：`kernel/`（唯一注册执行图、工具、技能管理、上下文）、`skill_packages/`、`prompt_packages/`、`model_gateway/`、`model_configuration/`、`research/`、`enterprise_search/` |
| `providers/` | 模型服务商传输（OpenAI 兼容、Anthropic 原生） |
| `originals/` | 原件：授权读取、上传、撤回、对象存储与日志、生命周期规则与执行 |
| `evidence_processing/`、`evidence_security/`、`security_runtime/` | 原件解析、扫描与解析容器运行时 |
| `integrations/` | 外部渠道，目前是钉钉（`dingtalk/`） |
| `workflows/` | Temporal 工作流、Worker 与检查点 |
| `bootstrap/` | 仅供本地标记宿主使用的合成配置与受信导入 |
| `schemas/` | 跨领域共享的冻结 DTO |
| `errors.py` | `DomainError` |

`domain/` 的产品区与前端 `web/src/features/` 同名。每个产品区的根目录放该区的主体代码，子目录放具体环节：

| 产品区 | 子目录 |
|---|---|
| `categories/` 品类与立项前 | `preproject/`（品类、提案、G0）、`products/`（产品定义）、`discovery/` |
| `projects/` 项目 | `governance/`（阶段治理）、`planning/`（计划与 `engine/` 计算）、`work/`（工作与承诺）、`fulfillment/`、`risk/`、`external_wait/`、`sets/`（项目集） |
| `builds/` 样机构建 | `start/`、`execution/`、`operational_facts/`、`configurations/`、`sample_handoff/`、`resource_readiness/`、`test_resources/`、`professional_authority/` |
| `verification/` 测试验证 | 根目录是验证内核与规则；`preparation/`、`execution/`、`handoff/`、`launch/`、`results/`、`measurement/` |
| `quality/` 品质 | `issues/`、`execution/`、`followup/`、`field_feedback/`、`capa/`（含 `verification/`） |
| `change/` 变更 | 根目录是变更单、选择与完成流程；`control/`、`coverage/`、`execution/` |
| `manufacturing/` 制造交付 | `baseline/`、`trials/`、`resources/`、`supply_cost/`（含 `engine/` 计算）、`supply_execution/`、`cost_execution/`、`release/`（含 `exceptions/`）、`external_handoff/` |
| `knowledge/` 知识 | 经验、助手资料与来源 |
| `automations/` 工作规则 | 小Pai 工作规则、触发与摘要设置 |
| `my_work/` 我的工作 | 关注、摘要、偏好、搜索、`inbox/`（收件箱） |

前端把测试验证放在 `builds/verification/`、把变更放在 `quality/change-control/`，后端各自独立成区；前端 `xiaopai/` 与 `settings/` 对应后端 `agent/`。

几处位置是有意固定的：`errors.py` 留在包根，因为 `domain/verification/rules.py` 的内容哈希会写进验证结果；`providers/` 和 `schemas/` 受规格冻结测试约束；`evidence_processing/` 的两个源文件哈希固定在 `security_runtime/parser-image.json`；`contracts/` 固定了 v1.1 设计稿的 SHA-256，修改该设计稿前先重新生成契约。

### 工具 `tools/`

| 用途 | 脚本 |
|---|---|
| 本地环境 | `local_environment.py`（独立 `pdos_test` 与 API/Web 预览）、`workflow_environment.py`（Temporal 与检查点库）、`agent_runtime_environment.py`（共用 Agent 状态库与 Temporal 开发服务）、`comprehensive_preview.py`（完整预览）、`acceptance_account.py` |
| 小Pai 评测 | `xiaopai_prompt.py`（提示词版本与 A/B）、`xiaopai_recall_*`、`xiaopai_context_*`、`xiaopai_real_*`（真实服务商评测） |
| 契约与性能 | `export_contracts.py`、`validate_contracts.py`、`current_read_profiler.py` |

历次 wave/m2/m3/s0 检查点脚本已于 2026-11-01 删除，可在标签 `archive/pre-restructure-2026-11-01` 中查看。私有状态、预览配置与本地工具二进制放在被忽略的根目录 `.local/`。

## 开始开发

### 1. 准备依赖

使用 Node.js 22（见 [`.nvmrc`](.nvmrc)）、Python 3.12（见 [`.python-version`](.python-version)）、pnpm 11.16.0 和 uv。完整本地环境还需要 Docker，以及 PostgreSQL、Temporal、文件解析与安全检查所需的运行组件；相关环境由 `tools/` 管理。

在仓库根目录开始安装：

```bash
cd server
uv sync --locked

cd ../web
pnpm install --frozen-lockfile
```

后端通过本地路径依赖 `packages/pdos-agent-runtime/`，请保留仓库目录结构。

### 2. 配置独立环境

以 [`.env.example`](.env.example) 为配置清单，由启动进程显式提供环境变量；现行工具不会读取根目录里原工程留下的 `.env` 与 `.env.production`。

- **数据库**：应用、认证、派发与迁移使用分离的连接身份。应用连接使用非属主、非超级用户、无 `BYPASSRLS` 的角色；迁移凭据仅供迁移进程使用。
- **工作流**：API 与 Worker 连接一致的 Temporal 命名空间，并使用独立的检查点存储。
- **原件**：配置服务端私有文件目录和适用的扫描、解析运行组件。
- **模型**：API 与 Worker 使用同一份 `PDOS_TENANT_RUNTIME_CONFIG` 元数据。密钥由凭据后端保存，元数据只放引用；模型配置还需实际预算、技能启用及适用资格。

常用环境入口如下，均使用 `server/.venv/bin/python` 从仓库根目录执行对应脚本：

| 入口 | 用途 |
|---|---|
| [`local_environment.py`](tools/local_environment.py) | 建立或核对带身份标记的独立合成 `pdos_test` 环境，启动 API 与 Web 预览 |
| [`workflow_environment.py`](tools/workflow_environment.py) | 管理独立工作流状态库、Temporal 开发服务、健康检查与 Worker |
| [`agent_runtime_environment.py`](tools/agent_runtime_environment.py) | 管理共用 Agent 状态库与 Temporal 开发服务 |
| [`tenant_provision.py`](tools/tenant_provision.py) | 在带标记的本地合成环境里开通租户：首个管理员、首个品类和 72 小时单次有效的邀请链接（链接只写入私有状态文件） |

首次环境建立会创建临时资源并执行迁移。已有环境应先核对实例、端口、身份标记和真实迁移 head，再按当前候选的检查工具续接。私有 `.local/` 文件不作为通用生产启动入口。

模型与研究接线见[租户模型运行配置](docs/runbooks/pdos-next-tenant-model-runtime.md)和[公开研究运行配置](docs/runbooks/pdos-next-public-research-runtime.md)。基础 LLM 按[确认稿 P28/P29](docs/design/2026-10-08-pdos-next-design-confirmation.md#p29-在界面添加密钥与切换模型服务商用户-2026-10-26)支持任意 OpenAI 兼容 Chat Completions API，不限 MiniMax；页面可填写 API Key、Base URL 和模型名称，保存多份独立连接并确认切换，密钥进入 KMS/Keychain。出站仍执行 P26：服务商协议是可选治理工具，服务器逐次判定并记录服务商与资料类别，已登记的有效协议按类别限制执行。

### 3. 执行检查

在 `web/` 中执行：

```bash
pnpm typecheck
pnpm lint
pnpm build
```

后端检查按受影响的能力选择测试文件。依赖数据库的测试必须显式设置 `TEST_DATABASE_URL`，指向已核对的独立临时 `pdos_test`，并具备相应的应用、认证与派发连接；测试禁止回退旧 `.env`。一次检查的覆盖和失败应与具体候选一起记录。

前端构建使用 `next/font` 获取 Geist 字体，构建环境需要可用的字体下载网络。完整业务联验还包括迁移、HTTP、浏览器、工作流恢复及适用的资格验证，具体出口见当前执行清单。

## 文档入口

- [完整目标架构 v1.1](docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md)：产品、领域、体验、运行架构与验收依据。
- [设计确认与决策记录](docs/design/2026-10-08-pdos-next-design-confirmation.md)：冻结设计之后的已确认变更。
- [当前执行清单](tasks/ai-native-integrated-todo.md#current-queue)：可用能力、证据、剩余缺口与下一步。
- [设计文档索引](docs/design/README.md)：现行合同与历史材料的权威关系。
- [接口契约](contracts/openapi.json)与[操作目录](contracts/operations.json)：机器可读定义。
- [编码协作约定](AGENTS.md)：实现、验证、迁移和授权边界。

## 版本、分支与归档

本仓库只有 pdos-next 一个工程。2026-11-01 整仓重组先删除了原工程（当时同样位于根目录的 `server/` + `web/`）的遗留文件、原生产部署脚本、旧设计与历史证据，删除前的内容在本地标签 `archive/pre-restructure-2026-11-01`；随后把原 `pdos-next/` 目录下的代码提到仓库根目录，后端与测试按产品区重新分组。历史文档与证据里出现的 `pdos-next/…` 路径，对应现在去掉该前缀后的位置。

| 用途 | 分支 | 使用边界 |
|---|---|---|
| 本地开发主线 | `pdos-next/design-v1.1` | 新实现只从这里续接；保留本地分组提交，不直接推送到公开仓库 |
| 公开发布快照 | `codex/pdos-next-snapshot-20261022` | 仅在获得推送授权后发布选定本地提交的文件树；不把快照历史合回开发主线 |
| 历史与实验分支 | `main`、`archive/original-2026-10-08`、`codex/s0-*`、`codex/sprint-*`、`ui/linear-restyle` 等 | 只作历史追溯或旧实验对照，不作为新功能起点，也不因存在未合并提交而重新接入现行工程 |

GitHub 上的清理后快照不携带原工程提交历史，快照发布方法见[2026-10-31 发布记录](docs/reports/evidence/repository-sync-20261031/snapshot-publication.md)。旧工程归档标签 `original-final-2026-10-08` 仅保留在开发机器，原资格材料不自动授予新工程资格。[原生产环境下线](docs/runbooks/original-production-decommission.md)所需的部署脚本与 compose 文件从标签 `original-final-2026-10-08` 检出使用，手册里写明了步骤。
