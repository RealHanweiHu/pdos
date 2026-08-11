# Current Work Queue

> 唯一当前指针：**S0-2 Migration 0001。** S0-1 已由本地 `make verify-s0-1` 与 GitHub Actions run `31461239210` 双重验收。
> 产品范围与完成状态以 `docs/design/2026-08-09-preview-execution-plan.md` 为准。

## Gate B0: Baseline Freeze

- [x] 设计结构审查完成
- [x] 执行流程与 S0-1 验收补齐
- [x] UI accepted→applied 双动作校准
- [x] Agent 控制面/执行面数据库角色校准
- [x] 文档交叉口径扫描
- [x] 人确认本次文档校准
- [x] 创建首次本地 commit（`d28d984`，未 push）

## Completed: S0-1 Scaffold

### S0-1a Root Contract

**Acceptance criteria**

- [x] 根目录给出单一的 setup/dev/test/lint/type/build 入口与版本约束
- [x] `.env.example` 能在无 LLM key 下支持 Sprint 0/1
- [x] 不提交真实密钥、构建产物或本地数据卷

**Verification**

- [x] 新环境按 README 能完成依赖准备
- [x] secret/config 扫描无真实值

**Dependencies:** Gate B0

**Estimated scope:** Medium

### S0-1b Server Health Slice

**Acceptance criteria**

- [x] FastAPI `/healthz` 返回稳定、可测试的健康响应
- [x] Python lint/type/test 命令可重复运行
- [x] Alembic 环境存在且只有一个 head（`0000_scaffold`）

**Verification**

- [x] 聚焦测试先失败后通过
- [x] server lint/type/test 全绿
- [x] 运行时请求 `/healthz` 成功

**Dependencies:** S0-1a

**Estimated scope:** Medium

### S0-1c Web Shell Slice

**Acceptance criteria**

- [x] Next.js App Router 空应用采用 Tailwind v4、shadcn/ui、Geist、Phosphor
- [x] 公司橙、8px 圆角与双主题 token 落到基础样式
- [x] 首页可运行且不提前实现 Sprint 1 业务页面

**Verification**

- [x] web test/lint/type/build 全绿
- [x] 亮/暗主题运行时 smoke 通过；320/768/1024/1440 无横向溢出，浏览器控制台零 warning/error

**Dependencies:** S0-1a

**Estimated scope:** Medium

### S0-1d Local Data Isolation Slice

**Acceptance criteria**

- [x] compose 启动 pgvector/pg16 与 MinIO
- [x] `pdos`、`pdos_test` 独立创建
- [x] 测试入口遇到非 `pdos_test` URL 直接拒绝

**Verification**

- [x] `pdos_test` 可执行 `alembic upgrade head`
- [x] 故意传入 `pdos` URL 的隔离测试失败关闭
- [x] MinIO healthcheck 通过并初始化私有 `pdos-files` 桶

**Dependencies:** S0-1a, S0-1b

**Estimated scope:** Medium

### S0-1e CI Gate

**Acceptance criteria**

- [x] CI 覆盖 web/server lint、type、test、build
- [x] CI 启动隔离测试库、验证 pgvector 并执行 migration smoke
- [x] 失败步骤有明确日志，不静默跳过

**Verification**

- [x] 本地等价验证命令全绿
- [x] CI 首次成功运行全绿（GitHub Actions run `31461239210`）

**Dependencies:** S0-1b, S0-1c, S0-1d

**Estimated scope:** Medium

## S0-1 Completion Gate

- [x] 唯一执行计划 S0-1 的全部验收条款满足
- [x] 项目级 Definition of Done 满足
- [x] 执行计划 S0-1 checkbox 更新为 `[x]`
- [x] 当前指针移动到 S0-2

## Next: S0-2 Migration 0001

**Definition of Ready**

- [x] 规格出处：`PostgreSQL_Schema_Design.md`、`Workflow.md`、`System_of_Record_Matrix.md`
- [x] 依赖项：S0-1 已完成；Alembic 当前唯一 head 为 `0000_scaffold`
- [x] 迁移号冻结为 `0001`，仅在隔离的 `pdos_test` 中执行与验收

**Implementation slices**

- [ ] S0-2a：创建 10 个冻结 namespace，并建立跨表通用主键、时间戳与租户归属约定
- [ ] S0-2b：建立 `cehub_core` 的 Tenant/User/Customer 表、约束与索引
- [ ] S0-2c：建立 `cehub_project` 的 Requirement/DevelopmentCase/Project/Workflow/Stage/Gate 表与状态约束
- [ ] S0-2d：建立 `cehub_project` 的 Task/Issue/Risk/Decision 表、关系约束与查询索引
- [ ] S0-2e：补齐迁移正反向、单 head、实体清单、租户外键与开发/测试库隔离验收

**Acceptance evidence required**

- [ ] `pdos_test` 从空库升级到 `0001`，10 schema 与 13 张首批实体表精确存在
- [ ] 状态、唯一性、租户归属与跨实体引用约束的正反例测试通过
- [ ] downgrade→upgrade 往返后仍保持单一 Alembic head，完整门禁全绿
