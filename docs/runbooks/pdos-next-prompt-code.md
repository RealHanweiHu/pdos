# 小Pai Prompt 代码工作流

主提示词是随代码评审的版本化资产，位于 `server/pdos_next/agent/prompt_packages/`。运行时只读取 `registry.json` 的 `active` 版本；动态上下文、权限、租户和资料仍由服务器按 Run 追加，不能写入固定前缀。

## 可见

在仓库根目录执行：

```sh
server/.venv/bin/python tools/xiaopai_prompt.py list
server/.venv/bin/python tools/xiaopai_prompt.py show 1.0.0
```

平台设置的“小Pai / 技能”页也展示当前主提示词、技能正文、内容 digest 和实际系统前缀 digest。主提示词正文、技能目录、技能正文和动态上下文是不同部分，不把最终私有上下文当作公共代码展示。

## 修改：草稿 → 登记 → diff

```sh
server/.venv/bin/python tools/xiaopai_prompt.py new 1.0.1-draft --source 1.0.0
# 编辑 server/pdos_next/agent/prompt_packages/versions/1.0.1-draft.md
server/.venv/bin/python tools/xiaopai_prompt.py register 1.0.1-draft
server/.venv/bin/python tools/xiaopai_prompt.py diff 1.0.0 1.0.1-draft
```

草稿只有在 `register` 后才可被评估。未登记草稿不影响当前激活版本；`active` 和曾经发布的 `published` 版本不能原地重新登记。版本文件和注册表一起进入代码评审，不需要数据库迁移。

## 同题 A/B

```sh
server/.venv/bin/python tools/xiaopai_prompt.py evaluate \
  --baseline 1.0.0 --candidate 1.0.1-draft \
  --output-dir docs/reports/evidence/pdos-next-prompt-1.0.1-control
```

输出目录必须不存在，生成 `report.json`、`result.md` 和 `diff.patch`。当前执行层是**相同题目、工具、输出 schema 与生产上下文准入逻辑的离线控制比较**：记录新增准入失败和固定 token 差量，不调用 provider 或数据库。

`quality_status=not_scored` 是有意保留的边界：该报告不证明真实回答正确、引用忠实、真实权限端到端或真人任务质量通过。真实模型回放与独立人工评分仍按 `docs/evaluations/xiaopai-v0/rubric.md` 执行；合成候选题不自动晋升为 golden-case。

激活前会核对评估时的全部输入源码 SHA-256。代码、题目、技能包或候选 Prompt 再变化后，旧报告不能激活新版本。

## 激活与回滚

```sh
server/.venv/bin/python tools/xiaopai_prompt.py activate 1.0.1-draft \
  --expected-active 1.0.0 \
  --evaluation docs/reports/evidence/pdos-next-prompt-1.0.1-control/report.json \
  --reviewer "实际代码评审人"

server/.venv/bin/python tools/xiaopai_prompt.py rollback 1.0.0 \
  --expected-active 1.0.1-draft \
  --reviewer "实际代码评审人" --reason "核对到回归，恢复原版本"
```

激活要求当前版本符合 `expected-active`、候选 digest 与报告完全一致、离线控制无新增准入失败，并记录具名代码评审人。这里的评审人是代码资产审查记录，不是业务 T2 批准，也不授予模型或 T0 资格。回滚只能回到曾经激活且仍已发布的版本，并保留激活/回滚历史。

新 Run 使用激活版本。未完成的旧 Run 不会因部署而静默换 Prompt；如果代码已切换，其原有 digest 守卫会明确拒绝继续，须恢复原版本或另起新 Run。

## T0 资格边界

案例审阅与资格命令绑定 `prompt_digest`，其值是主提示词加当前技能目录后的 `system_digest`。每个选定案例引用保存为：

```text
<batch_uuid>:<case_index>:prompt:<system_digest>
```

T0 执行要求当前模型调用、技能、工具、模型和全部案例引用对应同一 Prompt。旧记录缺少该绑定或 Prompt 改变后，不能直接用于新 Prompt 的 T0；保留历史与人工 T1，不删除审阅记录。该检查读取现有 `review_case_refs`，不让 AI 身份读取本人私有资格决定或回执，也不绕过 RLS。

激活或回滚本身不授予任何业务写入、真实外发、生产部署或阶段验收资格。
