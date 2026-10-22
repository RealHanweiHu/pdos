# UX10 AI Review 候选聚合 · 后端验证

日期：2026-09-08。范围仅为 `GET /api/ai/risk-candidates` 的只读聚合、权限及查询预算；不构成 UX10 浏览器三页 P95 或真实试点验收。

本记录整理本任务实际工具执行结果。未保存原始终端日志，以下结果行是从工具返回中摘录；不声称存在独立原始日志文件。

## 修改范围

- `server/app/api/review_candidates.py`：新增 GET，复用 `RiskCandidateListResponse` 与 `risk_response`，仅有查看 Finding 权限的内部角色可访问。
- `server/app/domain/risk_candidates.py`：新增 `list_visible_candidates`，单 SELECT 读取 draft 候选；按 created_at、id 升序；租户与直接成员范围由服务端绑定。
- `server/app/main.py`：导入与注册新路由。
- `server/tests/test_review_candidates_api.py`：23 项专项测试。

未修改 `api/ai.py`、`api/findings.py` 或 `/private/tmp/pdos-ux10-20260908` 基线。无迁移、生产、外发或远程 Git 操作。

## 隔离环境

实际创建独立临时容器 `pdos-review-candidates-test`，镜像为本机已有 `pgvector/pgvector:0.8.6-pg16-bookworm`，设置 `--pull=never --rm`，无持久卷，端口仅绑定 `127.0.0.1:58436`。数据库和账号均为 `pdos_test`，使用本次临时测试口令。

测试 fixture 先调用 `configured_test_database_url()` 验证库名，再对该库迁移到 head、清理隔离租户并种入合成数据。没有连接开发库、生产库或并行任务的 58432 端口。

最初数据库测试因本地沙箱禁止 TCP 连接而得到 `Operation not permitted`；该次为 9 项通过、13 项 setup error。随后以已批准的本地执行权限重跑，得到下述通过结果。这些 setup error 不被计作产品失败或从成功运行中删样。

## 实际执行与结果

以下命令均从仓库 `server` 目录运行；连接串中仅将本次临时口令遮盖。

1. 路由实现前运行新增回归：

   ```sh
   .venv/bin/python -m pytest tests/test_review_candidates_api.py::test_registered_endpoint_requires_a_session -q
   ```

   实际结果：`1 failed in 1.82s`，断言为未注册路由返回 404、预期 401。随后实现路由及会话边界。

2. 第一轮专项：

   ```sh
   TEST_DATABASE_URL='postgresql://pdos_test:<本次一次性测试口令>@127.0.0.1:58436/pdos_test' JWT_SECRET='test-only-jwt-secret-that-is-at-least-32-bytes' .venv/bin/python -m pytest tests/test_review_candidates_api.py -q --tb=short
   ```

   实际结果：`22 passed in 14.75s`。随后补入真实登录 JWT 的双租户验证。

3. 最终专项与相关回归：

   ```sh
   TEST_DATABASE_URL='postgresql://pdos_test:<本次一次性测试口令>@127.0.0.1:58436/pdos_test' JWT_SECRET='test-only-jwt-secret-that-is-at-least-32-bytes' .venv/bin/python -m pytest tests/test_review_candidates_api.py tests/test_risk_candidates_api.py tests/test_rbac_policy.py -q --tb=short
   ```

   实际结果：`36 passed in 20.31s`。新增文件的独立 collect-only 返回 `23 tests collected in 1.33s`。

4. 静态门禁：

   ```sh
   .venv/bin/python -m ruff check app/api/review_candidates.py app/domain/risk_candidates.py app/main.py tests/test_review_candidates_api.py
   .venv/bin/python -m ruff format --check app/api/review_candidates.py app/domain/risk_candidates.py tests/test_review_candidates_api.py
   .venv/bin/python -m mypy app/api/review_candidates.py app/domain/risk_candidates.py tests/test_review_candidates_api.py --cache-dir /private/tmp/pdos-review-candidates-mypy
   ```

   分别返回 `All checks passed!`、`3 files already formatted`、`Success: no issues found in 3 source files`。对四个修改文件执行的 `git diff --check` 退出码为 0。

## 关键证据判据

- **单查询**：`test_all_projects_require_exactly_one_read` 覆盖 Owner / Engineer × 0 / 1 / 25 个项目。SQLAlchemy 监听该 API 的所有业务连接执行，均断言只有一条 SELECT，无逐项目查询或写入。该测试覆盖业务查询预算；真实认证本身的身份查询不被宣称为零。
- **真实 JWT 双租户隔离**：`test_real_authenticated_sessions_keep_tenant_scopes_separate` 去掉身份/AuthService mock，实际调用本地 `/api/auth/login` 获得两个租户的 token，再访问新 API；两者各只取得自己租户候选。请求额外伪造 tenant_id 不改变结果。
- **角色和项目范围**：五类内部角色均验证；Owner/Admin 可见本租户全部项目，其他内部角色仅直接成员项目。仅为项目 owner 或风险 owner、但不是成员，不扩大可见范围。结果与 `/api/projects` 和 `/api/ai/review-inbox` 对账一致。
- **拒绝路径**：无会话 401；Supplier、Customer 及未知角色 403；拒绝时不调用候选加载。请求伪造 tenant/user/role 参数不能覆盖会话范围。
- **内容和兼容性**：仅 draft，排除 confirmed / cleared；created_at/id 排序稳定；同一项目返回值与既有项目级候选 API 逐字段一致；分数计算正确。成功响应 `Cache-Control: no-store`、`Pragma: no-cache`。

## 清理与结论边界

最终测试后实际运行 `docker stop pdos-review-candidates-test`，退出码 0，输出容器名；由于创建时使用 `--rm`，容器自动移除，58436 端口释放。未停止其他容器。

本次验证证明新增聚合 API 的功能、权限与固定单次业务查询。三页导航到可操作内容的浏览器测量、真实数据规模及 V1 / Sprint 人工出口由根任务另行验证和裁决。
