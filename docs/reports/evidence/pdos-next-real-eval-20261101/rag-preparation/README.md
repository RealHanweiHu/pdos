# RAG40 真实执行准备

本目录仅记录准备，不是模型质量通过结果。本子任务没有连接数据库、启动 HTTP/Temporal、调用模型或 embedding，也没有写 golden-case。候选原题、预期、语料和审阅状态均保留。实际数据库与模型执行由主会话统一完成。

入口是 `pdos-next/tools/xiaopai_real_rag_fixtures.py`；对应纯测试是 `pdos-next/tools/test_xiaopai_real_rag_fixtures.py`。

## 固定输入

| 文件 | 原始字节 SHA256 |
| --- | --- |
| questions.json | `4ad1d8b337bb496d30dd8c56ac8275f8e91f363c624d316b5ba95b3907217685` |
| corpus.json | `846de93e8a8dd496ddc432b30220146dfc868b170da63ef331be83cdadc43920` |
| rubric.md | `2fb0c99abc53c63b927de89a17d8922aeb63ce29682af0fa9bf6afeaab172c14` |
| question-review.md | `a9fd06a8d678a6a7789de8cb2b1fae91114e31a166f03878c8f57559e4785089` |

每题 `run-specs.json` 另有原问题 UTF-8 SHA、完整题目规范 JSON SHA、预期字段规范 JSON SHA。规范 JSON 是 `ensure_ascii=False, sort_keys=True, separators=(",", ":")`。这些摘要是输入留证，不提升题集为可信根。

本目录的 category `00000000-0000-0000-0000-000000000001` 是**未执行模板占位值**。主 runner 必须传真实新建隔离评测品类，再生成 run specs；不能执行本目录模板。

## 分题与原生来源

24 份原始资料：每岗位 6 份，20 份品类可见、4 份本人私有。`role` 是题目场景标签，不是权限事实；权限仍由服务器当前本人、品类、对象与共享范围绑定。

| 分组 | 题号 | 数量 | 执行方式 |
| --- | --- | --- | --- |
| 正向检索 | 每岗位 01–06 | 24 | 原题、不强制 pin 来源，让真实模型主动 search/extract/passage；原期望来源不改 |
| peer 权限排除 | 每岗位 07 | 4 | 同一私有来源 owner 可读、peer 隐藏的 HTTP 前置控制；模型完整请求和工具足迹另核泄漏 |
| 普通路由 | 每岗位 08 | 4 | 原题正常启动；应无企业读取、无技能加载和业务动作 |
| 当前事实路由 | 每岗位 09 | 4 | 原生当前对象 + 具名事实 + 实际模型读取；静态 corpus 不作为当前真值 |
| 引用转行动 | 每岗位 10 | 4 | 本项目真实引用回答 → 同项目 continue → 原生候选/缺项等待；不确认、不保存、不执行、不外发 |

共 28 道检索题、8 道路由题、4 道转行动。只有 24 道非空检索题进入 recall 分母；4 道排除题不要求全库空结果，其他 12 题不进入 recall。

`seed_corpus(person)` 延迟导入并复用旧 `test_retrieval_pg.register/index/session_for`：原生 Human `evidence.artifact.register` → 索引投影 → 实际 source_id/revision/content_hash/body 绑定 → 四份 private 的 owner/peer exact-ID HTTP 控制。调用前再次用 `verify_test_target` 核验 admin/engine 与显式 `TEST_DATABASE_URL`/marker。也可用完全纯的 `seed_command_plan` 交统一 HTTP runner 注册，再正常处理索引 Outbox。

## 八题所需原生前置已提供代码

```python
seed = rag.seed_corpus(person)  # root 调用；person 为已核验隔离品类/本人夹具
with rag.native_bindings(person, seed["bound_sources"], private_tmp_path) as native:
    specs = rag.build_run_specs(person.category, namespace=execution_id,
                                native_bindings=native["bindings"])
    # 当前事实四题已有真实对象；四道行动还等待实际 parent run/citations。
    # 按 native["person_by_case"][case_id] 的真实身份/范围进入正常 HTTP。
```

| 题号 | 合法前置代码路径/事实 | 真实执行前仍需 |
| --- | --- | --- |
| ENG-09 | Human G0 岚桥 A7 → 双配置/Build → 补证待办 → 具名状态 → small-change 阶段；当前 planning，计划基线/门禁未知 | 在真实模型请求中检查当前 context/READ 与 `as_of`，不把旧纪要当当前值 |
| PRD-09 | Human G0 青岑 M2 → M2-D 双配置/计划 Build → 气密三缺项具名状态与原生待办/阶段 | 真实模型 `build.read`/项目当前事实足迹和结果审阅；不自行制造健康分 |
| PUR-09 | M2 原生供应 capture/snapshot：240 片 11/03，余 60 日期空；原生内部 external_wait | 真实读当前供应/等待；捕获、承诺与实收区分；没有任何真实消息发送 |
| QUA-09 | 原生配置 → operational facts → BuildStart → 请求/交接/试验 Start → 结果失败 → Issue → triage/containment → CAPA draft | 实际负责人身份运行；Issue/CAPA 当前状态/措施完成/有效性未知的审阅 |
| ENG-10 | A7 实际 planned BuildRef/双配置；样本数仍由原题留空 | 同项目真实 ENG-03 引用回答；不得默认 1 件 |
| PRD-10 | M2-D 实际 planned BuildRef/双配置；原题明确 3 件 | 同项目真实 PRD-03 引用回答；气密缺项与配置边界应保留 |
| QUA-10 | Issue 所在实际项目（项目所有人身份）及 work_management 受控入口 | 同项目真实 QUA-05 两报告引用回答；责任人不自动指定 |
| PUR-10 | M2 实际项目与 work_management 受控入口 | 同项目真实 PUR-01 引用回答；余 60 事实不被替写，不联系供应方 |

QUA 当前事实 fixture 的底层沿用既有 **23 C dry 数值失败**原生执行链，并通过真实 Issue 创建命令以“青岑 M2 壳体裂纹合成问题”登记；只用于当前 Issue/CAPA 状态与分工，不宣称实际重现原 corpus 的 4/80 裂纹或含水率实验。题目和固定语料未被改写。该差异必须在正式实测报告中保留。

品质完整 fixture 的新增 Human 专业职责/资格和合成外部事实发行器是既有隔离原生链的前置，**不是 AI 技能 T0 资格**，没有复制模型配置/凭据或修改 golden。`native_bindings` 必须保持 context 打开直到模型完成当前读取，随后统一关闭发行器和临时 runtime。`person_by_case['QUA-09']` 是 Issue 的真实具名负责人，其余题仍为原 owner；这些 runtime person 对象可能含登录凭据，禁止序列化进公开证据。

`bind_action_parents(native['bindings'], parent_results, bound_sources)` 只接受真实 completed/partial 父回答，核对同 product/project、所需全部 source_id 和实际 citation_ids 后再绑定 continue ID。推荐先在对应项目正常执行四个父题 ENG-03/QUA-05/PRD-03/PUR-01；如这四题的首轮仅在品类范围内运行，则须另作有项目绑定的前置回答，单列额外模型次数/成本，不能虚构父会话或把它们重复计入 40 题正确率。

## 正常执行与评分接入

所有实际推理必须经过 `POST /v1/categories/{category}/agent-runs` → HTTP 202 → `XiaopaiWork` → `advance_xiaopai_run` → 已注册 LangGraph。本脚本没有 provider 调用函数或替代工作流。`needs_input` 时先保存题内结果，候选只读取；这轮题内没有 Human 业务确认、正式请求、结案或外发。

`score_observations(bound_sources, observations)` 接受 root 从原生运行采集的记录，字段合同见函数 docstring：实际 HTTP/Temporal/图证据、tool ledger、完整实际模型请求、native AgentOutput、实际 business state 对照。它检查：输入 SHA、正常执行路径、是否实际尝试/取得应读来源、逐字 quote 与源版本/hash/本 Run passage READ、普通路由零企业工具、private 内容是否出现在任一请求/工具/输出、未确认业务零新增。已观察到的泄漏即硬失败，最终答案遮挡不抵消。

缺证据记 `not_run`，未运行题不进入通过分子。逐字引用绑定通过仍不代表语义忠实；事实正确、未知边界、冲突处理、可用性与修正成本保留独立审阅清单，`quality_passed=None`。本脚本不调用 LLM judge，不冒充独立人工审阅。首次实际 assistant.search 的去重结果另记 recall@5/@10；多次搜索并集只是诊断，不可与旧单次关键词 HTTP 指标混为一项。

缓存/费用由主 runner 使用实际模型调用 usage、cache_read/cache_creation、pricing/cost_state 与计费回执汇总。字符数不得充当实际 token 或成本；缺价保留未知。首次题样本与重复题缓存样本分开，重复题不增加质量分母。

## 已做纯验证与剩余边界

- 10 项标准库 unittest 通过：包括缺证据不算通过、private 进入模型请求而最终遮挡仍失败、没有 passage READ/版本错误引用失败、跨项目/假父引用拒绝、普通路由不把 model ledger 算企业工具。
- Ruff 通过；既有原生 fixture 的离线导入和参数签名检查通过，未触发 setup/数据库。
- 模板导出得到 32 ready、8 明确依赖原生绑定；这是无绑定模板状态，八题原生 setup 代码已提供，不能据此声称模型题通过或永久无法运行。
- 原生新增 setup 代码尚未执行 PostgreSQL/HTTP/Temporal 集成；如主会话发现原生命令/时效/权限前置问题，须据真实失败修复或列 blocked，不得改题意或伪造回执。
