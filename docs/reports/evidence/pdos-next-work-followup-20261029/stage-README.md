# RAG §11.3：回答 → 准备资料跟进任务（独立冻结候选）

仅修改此 `/tmp` stage；未改 live、未连接 DB、未启动服务、未运行真实 provider/embedding、无外发/提交。主代理按 manifest 合入并统一跑实际 PG/Temporal。G service-loss、F taint、复验直接父桥、EvidenceLink 包均未修改。

## 结果与边界

- 项目引用回答提供“准备资料跟进任务”。实际项目工作只读接口核对项目/人员；讨论引用和“选中后纳入本次读取”的任务原件分开。无实际原件时不能把聊天变成原件；用户可用原附件选择器补齐。选人可空，不推断项目 owner 为执行人或成果接收人。
- 服务器沿实际直接父 Run/本人 Session/项目冻结 action、来源 proof 和当前已启用 `work_management` 方法。原注册图实际读取原件后形成 `work.task.create` 候选；缺少目标/成果等沿原 needs_input/answers 澄清。原技能内容、版本、工具、资格不变。
- `work.task.create` 原命令档位仍为 **T0**。这个明确入口始终走现 requires_human 候选，Host qualification 对这个服务器冻结 Run 返回 false，write 再拒绝。没有授予 T0、没有伪造资格。本人核对原 `project-work/inputs` 后确认原 Human create；它没有 T1 confirmation_token，因此界面没有伪造一个 T1 preview。
- 复用现 `AgentEvent.type=domain_candidate`，只加 `kind=work_followup` 的窄适配；没有新候选表/feed/领域命令，未改 preproject PreparedCandidate CHECK。实际模型响应/加载方法/服务器 intent/固定来源/取消 epoch 进入现 Event。native work helper 要求 UUID 形式 key，因此 Human command key 用服务器原 model intent 的确定性 UUID；事件仍保留完整原 intent 与 WriteSource。
- 确认后显示真实任务卡与“打开项目任务”。若先前选了人，读取当前真实 task 后沿原 `work.task.assign` inputs → native T1 preview → 一次确认；仍由项目负责人办理，受派人后续自行承接。没有日期承诺/自动承接/默认日期。
- 现 `domain_candidates.project_rows` 负责 feed；X2 work_state_candidates 继续复用它，只保留当前状态/真实 receipt metadata，不复制 payload/proof，不相信旧 seed 的 adopted。无 work_state.py 改动。
- 所有实际 parent/child carried 都作 current/audience 检查；只有显式讨论集合参与 discussion proof，任务原件必须本人选中、Run 已绑定、实际 READ 且通过原 direct_source_basis 逐字行校验。保持 ordinary context_selection/READ ledger。私有项目也按真实读者覆盖检查，不把 private 标签当成“仅本人”。
- work proof 的 `taint` 从所有当前实际 carried 重算（含父未引用项），合并到既有 parent._explicit_context_binding 后交原 conversation.merge_binding；不复制父初始 scope 作完整事实，不扩大 sources/引用/权限。
- 原 work owner 的 validate 只在原 server command_id 确实匹配本 kind 时重核固定 action/proof，覆盖候选展示后失效；普通 Human 命令没有 Event，沿原合同。选人是未来分派的选择，readonly proof 检查不锁 Grant；真实 native assign 时原 owner 重核成员及 T1。
- 刷新/重开不发送命令或模型；未知保存保留同一原请求，由本人明确核对；权限拒绝隐藏旧正文。普通自动/人工 work 及复验路径保留。

## 基线与归属

`manifest.json` 精确列出 **14 shared + 8 new**，只应用列出的文件，按 SHA 核对。`shared.patch` 是相同修改的局部补丁。

两个共享文件明确基于 **B 项目当前事实包之后**：

- bootstrap.py：B final `9e1c8bcf…`，只叠本包 prepare_candidate 的六行 action hook。
- api.py：B history-read hook final `b95ee84d…`，保留它并叠本包 StartInput/action startup。

其余 shared 基于 stage 创建时的当前 live（已含 X2 / D action_sources hooks / 直接父桥）。检查 manifest 的 base_sha256；若 root 另有同文件增量，按本包局部 hunk rebase，勿整文件覆盖。B 包路径 `/tmp/pdos-project-current-context-stage-20261029/apply-manifest.json`。本包没有 persistence / skill context registry 修改；只在 combine_contracts 加动态 action schema。

## 本地允许范围的验证

- **72 pure passed**：新 work action/source/原件边界、全 carried 污点、直接父桥、拒绝 T0、原 command 防篡改、X2 metadata 与既有 action_sources / action_parent_carry / work_state_candidates / work_management service。
- **53 frontend passed**：5 新流程 + 原复验/Start 恢复/候选/小Pai相关回归。
- 候选 web 完整 `tsc --noEmit --incremental false`、7 个变更 TS/TSX 文件 ESLint。
- 13 个 Python 文件 Ruff：显式 `--config pdos-next/ruff.toml`，以真实目标路径 `--stdin-filename` 校验 staged 文本（使 first-party 分类与 live 一致），未降低 E/F/I/B/UP 或 100 列规则。
- **4 PG/Temporal nodeids collect-only**，未执行。纯测 runner 只将 staged 模块绑定到正常 repo 包；交付测试全部使用正常 repo import，零 `/tmp` 依赖。允许范围原始结果在 `evidence/`。

## 主代理实际验证草案

新增 `tests/enterprise_search/test_work_followup_temporal_pg.py`，用原 conftest.setup 显式 4h 合成授权、原 G0 项目/原件命令、实际本地 PG/Temporal/注册图与离线 provider。`actual_runtime` 复用现原生 harness；通过原 T1 `ai.skill.enable` 仅启用 work_management，不造资格/模型资格或可信题集。

1. 真实父回答 → 缺成果先 needs_input，Human 回答后形成候选；此时零任务写；原 inputs/Human create 同 key 恢复；X2 同 revision 读回 adopted 与真实 receipt；随后原 assign T1，零 commitment。
2. 父实际读入但不引用的 private B，公共项目任务在 child Run 创建前拒绝。
3. child 当次 Human 确实选择 execution A + private B，实际 READ B；模型只把 A 当任务原件，但正文使用 B，仍无候选/Event/任务写。
4. 用现 work fixture 的真实上传/扫描/解析原件；候选后走原 T1 原件撤回，旧 inputs/原 create 均拒绝且 feed unavailable。

实际运行入口（使用 root 已核对独立 pdos_test 与已核对本地 Temporal/checkpoint 环境，不回退 .env）：

```text
cd pdos-next/server
.venv/bin/pytest -q tests/enterprise_search/test_work_followup_temporal_pg.py
```

本包不包含后续“复验 prepare_start 继承完整动态 taint”独立修复；该包将单独给 manifest 与 1 个实际分类/egress 草案，不能用现复验九项或本包 collect-only 冒充它的实际证据。
