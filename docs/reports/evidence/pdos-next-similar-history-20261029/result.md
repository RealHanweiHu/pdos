# Issue 详情相似历史候选 · 2026-10-29

本候选完成 RAG v0.4 §11.5 的 **Issue 详情**实现链：实际问题详情 → 普通 RLS 检索 → 最多五张固定版本卡片 → 原对象入口 / 本人检索反馈 / 原 T1 归并预览 / 小Pai 比较预填。Change 详情及新建表单防重复提示不在本次分工中，仍待后续实施。本报告不将代码及纯测试通过冒充浏览器、真实模型或完整阶段验收。

## 实际入口与行为

- 项目驾驶舱 → 问题与措施 → 质量问题或后续措施 → 选择试制轮次 → 点击实际问题记录，详情侧栏挂载相似历史。使用该行的真实 `issue_id` 与固定版本 `id`，不取“最新”替代历史选择。
- “维护记录与专业办理”中的当前问题阅读区域也挂载同一侧栏。宽容器以正文和侧栏两列显示；窄容器堆叠，字段及操作可以换行，焦点和原生 details 支持键盘操作。
- 仅打开页面发起 GET，不建 Run、不写业务回执、不调用模型或 embedding。查询取当前固定问题标题及登记说明，通过已有关键词、编号和关系检索服务；复用现有 catalog、原始依据复核及普通 RLS，在排序前排除本人问题的所有版本与登记关联对象。
- 卡片显示类型、标题、状态、品类、项目、命中原因、固定源版本、当前/历史版本、原对象入口、具名根因、临时措施、CAPA/变更措施、有效性/复验登记。缺失明确为“未记录”或“待复验”；假设和已完成措施不提升成根因或有效性。
- 差异使用已读的结构化型号、实际配置 BOM 料号集合、Build 名称及项目当前登记阶段。料号明确标为“已读实际配置 BOM”，不认定故障件；阶段明确为当前阶段，不虚构问题发生阶段。Change 卡片读取已登记计划、实施、验证与生效记录；Change 自身没有根因/遏制字段时明确缺失。
- “打开原对象”使用服务器生成的现有入口，另页打开并记录本人 opened 反馈。“不相关”在反馈成功后收起当前卡片，不静默修改排序。“让小Pai看看”通过 React context 打开原工作栏并预填案例比较；同时携带当前 Issue 对象 ID / 固定版本 ID / revision 和候选对象 ID / 固定源版本 ID / revision，标记为待服务器重读的选择元数据。点击不会发送或建 Run。
- “标为重复，核对后确认”只对同范围当前 Issue、现有界面明确可用的 `quality.issue.merge` 展示。反馈确认后接入原 inputs → T1 preview → 本人一次确认 → receipt 管线；候选元数据不作为写权限或已验证读取证明。

## 持久反馈与权限

新增单一 append-only 表 `similar_history_feedback`，迁移 `s0_0833`，`down_revision=s0_0832`；后继恢复代理已确认 `s0_0834` 衔接。仅记录服务器绑定的本人、范围、当前对象固定版本、候选固定版本、排序版本、有限动作及幂等标识/摘要，不存正文、标题、查询或自由反馈文字。

本人显式 POST 才追加。服务重新按当前实际对象与普通 RLS 查候选，不接受浏览器 tenant/viewer/ranking。相同请求 key 和内容重试返回原 ack；改变内容 409。强制本人 RLS，app 仅 SELECT/INSERT，Agent 零表权限，UPDATE/DELETE 受权限与 append-only 触发器双重限制。网络响应丢失保留原请求；403/409 隐藏旧卡并要求重新查找。归并反馈原请求重试成功后继续既有预览。

主会话已报告 0833 空表 up/down/up、ORM/RLS/角色权限核对通过；本代理未执行数据库操作。非空反馈表拒绝降级，避免销毁已记录反馈，待主会话统一验证该情形。

## 文件归属

本代理新增：

- `pdos-next/server/pdos_next/enterprise_search/similar_history{,_api,_context,_models,_schemas}.py`
- `pdos-next/server/migrations/schema_s0_0833.py`、`migrations/versions/s0_0833_similar_history_feedback.py`
- `pdos-next/server/tests/enterprise_search/test_similar_history.py`、`test_similar_history_pg.py`
- `pdos-next/web/src/components/similar-history.tsx`、`similar-history-pai.tsx`、`similar-history.module.css`、`similar-history.test.mjs`
- `pdos-next/web/src/lib/similar-history.ts`、`similar-history-proxy.ts`、`similar-history.test.mjs`
- `pdos-next/web/src/app/api/v1/categories/[categoryId]/products/[productId]/quality-issues/[issueId]/similar-history/route.ts` 与 `feedback/route.ts`

必要父入口修改：`app-shell.tsx` / `app-shell-knowledge.test.mjs`，`category-material-editor.tsx` 的 material kind，`builds/build-quality-loop.tsx` 的侧栏和既有 merge 接线，`projects/project-professional-records.tsx` / 测试的实际行详情挂载。共享文件其他既有修改不属于本次实现。公共 `models.py` import 与 `api.py` register 已由主会话汇合，未由本代理编辑。未改 agent_kernel、检索 query/sources/knowledge_sources、索引 worker/recovery、golden-case、唯一清单或偏好逻辑。

输入摘要见 [candidate-sha256.txt](candidate-sha256.txt)，是本子任务冻结时的 24 个输入，不代表其他代理尚在变化的全工程候选。

## 检查证据与统一验收交接

- 后端纯测试 **11/11**：结构化字段、假设/完成与专业决定区分、显式有限 DTO、反馈服务器绑定/幂等、AI/借用范围拒绝。原始日志 [backend-pure.txt](backend-pure.txt)。
- 9 个受影响后端/迁移/测试文件 Ruff 通过：[backend-ruff.txt](backend-ruff.txt)。
- 前端/BFF及父入口 **33/33**：卡片 6、BFF/预填 6、实际 AppShell 16、实际专业记录入口 5。具体命令与检查记录 [frontend-checks.md](frontend-checks.md)。受影响 10 个 TS/TSX 文件 ESLint 通过。
- PG 专用文件 **8 个 pytest cases** 已完成，待主会话在核对后的独立数据库统一运行：真实质量命令建对象/索引、低权限无痕迹、页面无 Run/回执/反馈写入、本人私有 append/幂等/冲突、原 merge 后排除所有逻辑关联对象、12 次暖读 p95/SQL 次数、Agent 四种零表权限。
- 主会话统一负责最终类型检查、完整构建、实际 HTTP/PG 与新候选浏览器截图。本代理没有启动 DB、完整构建或新浏览器，没有关闭共享服务。

浏览器夹具可复用 PG 文件的 `pair` 思路：实际完成 `quality_work` → 发布质量政策 → 为两个独立失败以 `create_issue` 建立 “D16-01 接口漏气历史线索” / “D16-02 接口漏气处理记录” → 普通人 scope 下分别 `indexing.project(..., "issue", fixed_version_id)`。本人须使用具备真实质量读取/归并资格的 `work.quality`，`work.setup` 在该 fixture 中是低权限负例，不能拿它冒充本人可办理。

入口 URL 形状为 `/?area=cockpit&category=<category>&product=<product>&project=<project>&projectView=issues&panel=quality&build=<build>&issue=<logical-issue-id>`；只需一般列表详情则不传 `issue`，点击实际问题行。API GET 使用对应固定 `version_id`；可将第二张卡的服务器 `object_url` 作为原对象回链。新候选应观察宽/窄与明暗、键盘焦点和局部溢出，opened/not_relevant 的实际持久 ack，归并只进入预览，Pai 含双方固定引用但不发送；推理端口维持抛错禁用。

本次没有运行模型或 embedding，也没有业务数据外发、git commit/push 或自动修改 golden-case。没有将 §14.1 的真实人员完整复验故事宣称完成。
