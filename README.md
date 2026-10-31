# PDOS

**AI 原生的产品开发与 NPI 协作平台。**

PDOS 面向消费电子与硬件研发团队，以项目为工作中心，将产品要求、工程配置、样件、验证结果、问题变更和制造导入串成可追溯的工作过程。NPI（New Product Introduction，新产品导入）与工程研发共同推进，在每一轮实物活动中核对要求、配置和结果。

小Pai是系统唯一的 AI Agent，帮助团队研究资料、起草内容、核对缺项和跟进工作。它通过受控工具使用业务数据，产生的候选、来源和运行回执可供人员核对。

> **项目正在建设与试点验证中。** 现行代码位于 [`pdos-next/`](pdos-next/)。下文介绍产品方向与开发入口；各项能力的实际覆盖、验证证据和剩余缺口，以[当前执行清单](tasks/ai-native-integrated-todo.md#current-queue)为准。

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

```text
pdos-next/
  web/                         Next.js 应用与前端测试
  server/                      FastAPI 服务、领域模块、迁移与后端测试
  contracts/                   操作、载荷、事件、接口与验收契约
  config/                      运行时元数据示例
  tools/                       本地环境、检查和受控演练工具
packages/pdos-agent-runtime/    共用 Agent 持久运行框架
server/scripts/                保留的共用运行环境管理入口
server/golden/                 原资格材料，仅作可信历史留存
infra/                         数据库安全与本地搜索等设施配置
assets/                        可复用业务资产
certs/                         公共证书链
scripts/pnpm.sh                pnpm / Corepack 调用入口
docs/                          架构、决策、运行手册与验证证据
tasks/                         唯一活动状态清单及历史记录
```

## 开始开发

### 1. 准备依赖

使用 Node.js 22（见 [`.nvmrc`](.nvmrc)）、Python 3.12（见 [`.python-version`](.python-version)）、pnpm 11.16.0 和 uv。完整本地环境还需要 Docker，以及 PostgreSQL、Temporal、文件解析与安全检查所需的运行组件；相关环境由 `pdos-next/tools/` 管理。

在仓库根目录开始安装：

```bash
cd pdos-next/server
uv sync --locked

cd ../web
pnpm install --frozen-lockfile
```

后端通过本地路径依赖 `packages/pdos-agent-runtime/`，请保留仓库目录结构。

### 2. 配置独立环境

以 [`pdos-next/.env.example`](pdos-next/.env.example) 为配置清单，由启动进程显式提供环境变量；现行工具不会继承旧工程根目录的 `.env`。

- **数据库**：应用、认证、派发与迁移使用分离的连接身份。应用连接使用非属主、非超级用户、无 `BYPASSRLS` 的角色；迁移凭据仅供迁移进程使用。
- **工作流**：API 与 Worker 连接一致的 Temporal 命名空间，并使用独立的检查点存储。
- **原件**：配置服务端私有文件目录和适用的扫描、解析运行组件。
- **模型**：API 与 Worker 使用同一份 `PDOS_TENANT_RUNTIME_CONFIG` 元数据。密钥由凭据后端保存，元数据只放引用；模型配置还需实际预算、技能启用及适用资格。

常用环境入口如下，均使用 `pdos-next/server/.venv/bin/python` 从仓库根目录执行对应脚本：

| 入口 | 用途 |
|---|---|
| [`local_environment.py`](pdos-next/tools/local_environment.py) | 建立或核对带身份标记的独立合成 `pdos_test` 环境，启动 API 与 Web 预览 |
| [`workflow_environment.py`](pdos-next/tools/workflow_environment.py) | 管理独立工作流状态库、Temporal 开发服务、健康检查与 Worker |
| [`agent_runtime_environment.py`](server/scripts/agent_runtime_environment.py) | 管理共用 Agent 状态库与 Temporal 开发服务 |

首次环境建立会创建临时资源并执行迁移。已有环境应先核对实例、端口、身份标记和真实迁移 head，再按当前候选的检查工具续接。候选专用的 `wave*` 工具与私有 `.local/` 文件不作为通用生产启动入口。

模型与研究接线见[租户模型运行配置](docs/runbooks/pdos-next-tenant-model-runtime.md)和[公开研究运行配置](docs/runbooks/pdos-next-public-research-runtime.md)。基础 LLM 按[确认稿 P28/P29](docs/design/2026-10-08-pdos-next-design-confirmation.md#p29-在界面添加密钥与切换模型服务商用户-2026-10-26)支持任意 OpenAI 兼容 Chat Completions API，不限 MiniMax；页面可填写 API Key、Base URL 和模型名称，保存多份独立连接并确认切换，密钥进入 KMS/Keychain。出站仍执行 P26：服务商协议是可选治理工具，服务器逐次判定并记录服务商与资料类别，已登记的有效协议按类别限制执行。

### 3. 执行检查

在 `pdos-next/web/` 中执行：

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
- [接口契约](pdos-next/contracts/openapi.json)与[操作目录](pdos-next/contracts/operations.json)：机器可读定义。
- [编码协作约定](AGENTS.md)：实现、验证、迁移和授权边界。

## 版本与归档

`pdos-next/` 是当前开发主线。原 `server/` + `web/` 业务工程已停用，旧业务源码、旧迁移、旧测试与旧 CI 已从当前目录移除；仍需使用的运行框架、golden 材料和复用资产继续保留。

GitHub 上的清理后快照不携带原工程提交历史，旧工程归档标签仅保留在开发机器。原资格材料不自动授予新工程资格。根目录仍保留的旧生产 compose 与部署脚本服务于[原生产环境下线](docs/runbooks/original-production-decommission.md)，现行应用使用 `pdos-next/` 的独立环境。
