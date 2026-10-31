# 小Pai按 UI-lab 连续工作区对齐 · 2026-10-27

## 结论

本次授权范围内，小Pai已从“选择一次 Run、处理一次结果”调整为围绕同一事务的持续对话与成果编辑工作区：短回答留在消息流，品类资料、提案、通用文档和表格进入主编辑区；保存后保留会话，历史恢复消息、草稿和成果，手机在编辑与对话之间逐层切换。

实现继续使用真实 Temporal/LangGraph 注册执行图、Run、Receipt、固定来源版本、T0/T1/T2、私有受众、幂等和审计；没有复制 UI-lab 的定时器、规则生成、假附件或内存权限，没有新增 Agent，也没有给予 AI 直接业务表写入或 T2 权限。

## 已落地能力

### 对话与历史

- 首轮和续聊共用 `PaiComposer`，统一发送、停止、技能、来源、附件、上下文、中文组字和 Enter/Shift+Enter。
- 未发送内容按“本人 × 范围 × 会话”保存；切换、搜索、重命名、置顶和刷新不再随意清空当前工作，权限失效清理对应私有内容。
- 续聊可以追加真实固定版本来源，不能替换原来源；原请求和未知结果恢复保留。
- 会话列表、历史消息、已保存品类/提案和通用成果都能重新打开；提案页通过服务器返回的 `session_proposal_id` 核对绑定链，可打开绑定前的合法空提案祖先，不把任意空提案 Run 当作当前提案。

### 主编辑工作区

- 复用品类、竞品/声音/参数和提案编辑器；桌面主文档与旁聊并存，手机逐层切换。
- 保存后保持原工作区并显示真实标题/版本；收起与重新打开保留对应对象。
- 普通候选预览有独立类型标识，不再被“保留材料编辑器”的隐藏规则误伤；手机使用原生模态对话框隔离背景，桌面继续允许旁聊，关闭后焦点返回原触发按钮。
- 通用文档/表格只从真实 `completed` Run 的非空回复创建；表格必须存在真实 Markdown 表格。成果为本人私有，不发布到品类/项目，也不提交 G0。
- AI 原文与人工修订分离，人工修改追加版本；原 AI 内容可对照。未知创建/保存沿用原请求键，晚到响应不能跨会话。
- 版本冲突会重新读取同一 root 的最新版本，同时保留当前未保存标题和正文，避免反复以旧版本保存。

### 服务器与迁移

- `agent_session_bindings` 以追加记录把会话从品类范围推进到真实保存提案；只接受 `proposal.create` Receipt、原 Run、本人和品类校验，不改写旧 Session/Run，不放宽原不可变约束。
- 绑定前原续接运行可以按原范围完成；新续接由服务器读取当前提案绑定。其他活跃续接、跨提案、跨用户、跨租户和撤权路径仍拒绝。
- `agent_work_products` 提供私有成果列表、详情、从 Run 创建和追加修订；RLS、append-only、当前受众和版本冲突均在服务器执行，版本并发使用 advisory lock。
- 当前迁移头为 `s0_0824`。最终复审修正了 `s0_0823` 的守卫基线：从实际 `s0_0793` 继承项目范围校验，只细化提案绑定判断；升级与降级都不丢项目不可变规则。
- BFF 对成果列表/详情只开放 GET，对创建/续版只开放 POST；列表仅接受 UUID `session_id`，其他查询禁止。

## 最终验证

最终代码复审确认此前迁移守卫、原续接历史、移动候选、提案祖先、背景隔离和成果版本冲突六项均已解决；最终 verdict 为 APPROVE，无阻断问题。

以下计数按各完整命令去重，不把后续单项复跑重复累加。

### 后端与实际 PostgreSQL/API

最终受影响回归 **67 passed**：

```text
tests/agent_kernel/test_run_continuation.py
tests/agent_kernel/test_session_views.py
tests/agent_kernel/test_session_views_pg.py
tests/agent_kernel/test_session_presentation.py
tests/agent_kernel/test_session_presentation_pg.py
tests/agent_kernel/test_material_candidate_edits_pg.py
tests/agent_kernel/test_work_products_pg.py
tests/agent_kernel/test_proposal_runs_pg.py
```

覆盖：会话绑定、真实 Receipt、保存前原续接、其他活跃续接拒绝、提案历史、当前受众、追加来源、通用成果所有权、真实 completed 回复、版本/幂等、撤权、RLS 和 append-only。中间曾因漏导入 `AgentSession` 出现两项失败，补齐后相关用例及上述完整集合均通过；没有隐藏失败。

迁移守卫另在本机两个已核对的独立 `pdos_test` 重放并读取实际函数：

- 隔离测试库 `127.0.0.1:53502`：项目 ID 更新被拒绝并回滚；会话/项目错配插入被拒绝并回滚。
- 合成预览库 `127.0.0.1:57358`：实际 `kernel_run_guard` 同时包含项目 UPDATE 与 INSERT 校验。
- 两库均为 `s0_0824`。原始输出见 `migration-guard-recheck.txt`、`migration-state.txt`。

已有绑定/成果历史时的降级保护以及无历史往返已在前面候选检查；最终基线修正没有重复做全链升降级，而是对实际变更的函数进行重放与负例验证，不把较早结果冒充全新全链演练。

### 前端、静态检查与合同

最终受影响组件/纯函数/BFF 回归 **109 passed**：

```text
pai/use-session-draft.test.mjs                 3
pai/run-continuation.test.mjs                 11
pai/session-history.test.mjs                  18
pai/use-work-products.test.mjs                 4
pai/work-product-editor.test.mjs               5
pai/run-candidates.test.mjs                   13
pai/proposal-workspace.test.mjs                5
category-create/personal-run-materials.test.mjs 2
category-create/components.test.mjs           26
xiaopai.test.mjs                              18
app/api/route-pai-work-products.test.mjs       4
```

普通候选与移动组合场景的最终日志见 `candidate-preview-tests.txt`。

- `npm run typecheck`：通过，日志 `typecheck.txt`。
- `npm run build`：Next.js 16.3.3 生产构建通过，编译、TypeScript、静态页面和构建跟踪均完成，日志 `build.txt`。
- 受影响 Python 文件 `ruff check`：通过，日志 `ruff.txt`。
- `eslint src --ignore-pattern '**/* 2.*' --ignore-pattern '**/* 3.*'`：**0 errors，6 个既有 warning**，日志 `eslint.txt`。这是命令行排除备份，不是修改 ESLint 配置；配置保护钩子阻止了配置改动，配置保持原样。
- 不过滤的 `npm run lint` 仍会被未跟踪备份 `use-work-products 2.ts` 的解析错误阻断；未删除或改写备份，不能宣称无过滤全量 lint 通过。
- 受影响路径 `git diff --check`：通过。全工作树另有两个无关在途文件的 trailing whitespace，未纳入本次修改。
- Impeccable 检测：最终输出 `[]`。
- 合同导出：126 个实际 payload schemas 与 OpenAPI 路由，包含最终 Run 详情实现。

## 浏览器整链

详见 `browser-final.md` 与 `browser-conflict-state.txt`。

- 真实历史回复可打开文档；原 AI 内容与人工修订可读。
- 两个真实浏览器标签页从同一 v2 开始：A 保存 v3，B 以旧 v2 保存时读取 v3 并保留 B 的未保存内容；数据库只有 v1/v2/v3，没有额外 v4。
- 1280、900、390、320px 按影响检查亮暗边界，无横向溢出。390/320 暗色编辑态背景对话实际为 `display:none`，且不在可访问性快照中；“继续对话/返回编辑”往返正常。
- 已保存提案显示真实标题，可以打开小Pai旁聊；未发送新消息。
- 预览当前没有新绑定样本或普通待确认候选，因此“新保存提案后的浏览器续接”和“普通候选手机确认”不冒称已做浏览器验收，分别由 PostgreSQL/API 和组件/原生模态/CSS 回归覆盖。
- 截图工具不允许写仓库证据路径，本证据保留可访问性快照与计算样式结论，没有伪造截图。

## 备份与运行状态

- `pdos-next/.local/session-bindings-53502-before-0823.dump`
- `pdos-next/.local/pai-work-products-preview-57358-before-0824.dump`
- 备份、迁移模块、成果模块和最终 OpenAPI 的 SHA-256 见 `hashes.txt`；历史备份未覆盖。
- 预览 API 已按原配置重载最终代码。预览存在既有 queued/running/waiting_input 历史记录，因此未重启 worker，避免恢复派送；没有新增真实模型调用。
- 没有生产部署、RDS/OSS/ECS 操作、git push、真实外发或新增 T0/T2 资格。

## 剩余边界

- 本闭环完成的是小Pai交互与真实持久化，不代表 UI-lab 其他页面差异全部关闭，也不代表模型回答质量、红队、S1–S5 或生产验收已通过。
- 普通候选手机确认的浏览器样本和新保存提案的浏览器续接可在已有合成样本就绪后补看；不需要为此新增真实模型调用。
- 无过滤 lint 的备份解析问题属于工作区卫生余项；本次保持备份不动，正式源码按上述命令检查通过。
- 工作树还有大量其他在途修改，本证据只覆盖小Pai相关文件和明确列出的合同/测试，不宣称整个工作树由本闭环独占或全部验收。
