# 复现与验证记录

在仓库根目录使用现有 server venv；未加载 `.env`，不需要 `TEST_DATABASE_URL`，不调用数据库、模型、embedding 或外发服务。

本目录 `questions.snapshot.json` 保存修改 F 档位前的原题集字节；其 SHA 与 `baseline.json.inputs.questions_sha256` 一致。原始材料的展开仍按题集 `replay_input` 执行，并与现有 `context-expanded-inputs.json` 逐消息核对。未来题集档位修改不覆盖这份原始候选证据。

初次生成命令（exit 0）：

```sh
PYTHONPATH=pdos-next/server:packages/pdos-agent-runtime/src \
  pdos-next/server/.venv/bin/python \
  pdos-next/tools/xiaopai_context_admission_baseline.py \
  --output-dir docs/reports/evidence/pdos-next-eval-v0-20261029/context-admission
```

输出：`{"case_count": 12, "provider_calls": 0, "output_dir": "docs/reports/evidence/pdos-next-eval-v0-20261029/context-admission"}`。

用保存的原候选复现到新目录（工具以独占写入保护已有结果；目录需没有同名结果文件）：

```sh
PYTHONPATH=pdos-next/server:packages/pdos-agent-runtime/src \
  pdos-next/server/.venv/bin/python \
  pdos-next/tools/xiaopai_context_admission_baseline.py \
  --questions docs/reports/evidence/pdos-next-eval-v0-20261029/context-admission/questions.snapshot.json \
  --output-dir /tmp/xiaopai-context-admission-replay
```

生产实现若变化，先比较 `production_fixed_prefix` 的 system/tools/schema SHA 及 `inputs.production_source_sha256`；不得把不同候选的数值混用。

最终适用检查：

```sh
PYTHONPATH=pdos-next/server:packages/pdos-agent-runtime/src \
  pdos-next/server/.venv/bin/python -m pytest -q \
  pdos-next/tools/tests/test_xiaopai_context_admission.py
pdos-next/server/.venv/bin/ruff check \
  pdos-next/tools/xiaopai_context_admission_baseline.py \
  pdos-next/tools/tests/test_xiaopai_context_admission.py
git diff --check -- \
  pdos-next/tools/xiaopai_context_admission_baseline.py \
  pdos-next/tools/tests/test_xiaopai_context_admission.py
```

结果：`4 passed in 3.95s`；Ruff `All checks passed!`；diff check exit 0。测试覆盖原始展开及哈希、篡改拒绝、撤权场景正文不进入探针、四档生产固定前缀准入和“下界准入不等于全题通过”的结果状态。没有把 scenario tool 消息当可信根。

12题 × 4档共48次离线 `fit_messages`：原两档各12次 `CONTEXT_INCOMPLETE/fixed_context_exceeds_window`；建议两档各12次 `admitted_lower_bound_only`。每题当前问题下界 admission 35,096–35,157 tokens；完整原生回放12题均未运行，须先建立可核验绑定与授权/撤回历史。上述计数不包含任何模型质量通过数。
