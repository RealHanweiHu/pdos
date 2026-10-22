# S4-4 Context Builder 补层契约

日期：2026-08-12  
状态：实施冻结  
依据：`2026-08-09-preview-execution-plan.md` S4-4、`AI_Runtime_Architecture.md` 四层 Context、§11 前缀冻结/代码预聚合/最小权限纪律

## 1. 目标与非目标

S4-4 把已预留的 Multimodal Context 与 User Context 接入统一的 Event→Context Builder→Agent 执行链，形成版本化 `run-context-v2`。两层都由服务端从 run 的 tenant/project/event/agent lease 推导，模型传入的 tenant、project、document、user 或 role 一律不作为政策事实。

本项不做 OCR、图像视觉模型、音视频解析、任意文档检索、用户画像学习、个人偏好记忆、动态 system prompt、Agent 互审或新的业务写出口。PDF/XLSX 抽取继续复用 S2-5 已交付能力；OCR required 文档显式显示不可用，不伪装成空文本。

## 2. `run-context-v2` 四层合同

持久化 `cehub_ai.agent_runs.context_version = run-context-v2`，JSON 内 `schema_version = 2`。原有 `project` 与 `execution` 字段保持语义不变，并新增：

### 2.1 Multimodal Context

- 来源仅为当前 run 的 `DOCUMENT_UPLOADED` trigger event 所引用的 document id；不扫描“最近文档”，避免无关材料和跨轮次污染。
- 仅 `classification=internal` 且 `extraction_status=extracted` 的抽取产物可进入；`confidential`、`restricted`、跨 tenant/project、无 fragment 或 OCR required 全部 fail closed。
- 每个 run 最多 5 份 trigger 文档、总计最多 20 个 fragment；单 fragment excerpt 最多 1,000 字符，总 excerpt 最多 12,000 字符。排序固定为 event row id、fragment ordinal。
- 仅输出 `document_id/filename/media_type/extraction_status/reference_id/locator/excerpt` 与 shown/total/truncated/status；永不输出 object key、source URL、SHA、上传者、原文件字节或未经抽取的 event payload。
- `status` 精确区分 `not_applicable`、`ready`、`not_available`，使模型和遥测可识别“没有文档 trigger”与“文档因分类/OCR/缺失不可用”。

### 2.2 User Context

- Agent 运行不是用户会话，不伪造“当前登录用户”。角色视角由 Agent key 静态绑定：Project Intelligence=`project_manager`，Knowledge Lite/Engineering Intelligence=`engineer`，Quality Intelligence=`quality`。
- 项目受众只输出 active project member 的去重角色与人数，不输出 user id、username、display name、email 或个人行为历史；无 active member 时返回空集合而不是跨范围补查。
- 固定输出 `decision_mode=advisory_only`、`review_required=true`、`apply_requires_separate_human_action=true`，明确 Agent 只能建议、Finding 裁决与 Apply 是两个独立人工动作。
- `role_lens` 是代码内版本化静态映射，属于观察视角，不授予数据库或业务权限；真实权限仍由 RBAC、project membership 与数据库角色决定。

## 3. 安全与数据库边界

- `pdos_agent` 仍只经 lease-bound `security_barrier` view 读取。新增角色聚合 projection 只暴露同 run project 的 role/count；现有 document fragment projection 继续只允许 internal。
- `persist_agent_run_context` 同时验证 run/tenant/project/agent 与 `schema_version=2`，并原子写入 `context_version=run-context-v2`；伪造 v1/v3、跨 run 或模型自报 scope 被拒。
- `pdos_agent` 对 users/project_members/documents/document_fragments 与全部业务表仍无直接 SELECT/INSERT/UPDATE/DELETE 权限。
- prompt 与工具定义前缀不插入动态内容；四层 Context 作为结构化 JSON 追加到 user context 末尾。

## 4. 迁移与兼容

- migration 冻结为 `0025_context_builder_v2`，仅把新建 run 的默认 `context_version` 切到 v2；历史 v1 run 保留原值与原 JSON，不回写、不假装拥有新层。
- downgrade 仅在不存在 `run-context-v2` 记录时允许，防止静默丢失版本语义。
- `FrozenRunContext` v2 为严格、冻结 Pydantic 合同；所有生产 builder 必须显式构造两层。测试 helper 可使用同一空层工厂，但不得绕过字段校验。

## 5. 验收判据

1. internal PDF/XLSX 抽取 fragment 通过真实 dispatcher/executor 进入模型尾部 context，引用可追溯；object key、SHA、上传者与 raw event payload 不出现。
2. confidential/restricted、OCR required、跨 project/tenant 文档均 0 穿透，并给出确定性 `not_available` 或 scope error。
3. 四 Agent 的 role lens 精确稳定；项目角色聚合只含当前 project active member，跨租户角色与 PII 0 穿透。
4. owner 路径与真实 `pdos_agent` 受限路径生成的 v2 Context 语义一致；持久化 `context_version/schema_version` 一致。
5. prompt/tool 冻结前缀不变；新层只出现在结构化动态 context 尾部。
6. migration 往返、metadata drift、聚焦/全量测试、Ruff/format/mypy/compile、web lint/type/test/build 全绿。
7. 真实 HTTP/worker/浏览器验收至少覆盖 internal 文档、受限文档、两个角色视角与 console 0 warning/0 error；不触碰生产。
