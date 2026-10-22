# Wave16 事后只读核验工具合同

状态：工具源码与静态检查已交付，**未运行业务核验**。编写时主线首次根因 T2 因 `next_0024` guard 的 SQL 括号问题回滚，主线决定新增单调迁移 `next_0025`；不能据此文件声明根因、完成或回链已保存。旧失败与旧迁移证据保留。

新增源码仅 `pdos-next/tools/wave16_closeout.py`。server/web 冻结源码没有修改。

## 明确选择与目标护栏

CLI 必须由主线在实际业务保存后运行，以下 UUID 参数全部显式给定，不猜最新行、不从列表第一项选择：

| 参数 | 含义 |
|---|---|
| `--marker` | 唯一允许 `916f950f-2d2b-405d-b809-c15db75dc20c` |
| `--issue` | 原 Issue 逻辑 ID |
| `--issue-v4` / `--root-v5` / `--complete-v6` | CAPA 草稿、具名根因、本人完成的三个不可变版本行 ID |
| `--action` | 原 CAPA 措施 ID，不是新造措施 |
| `--new-preparation-request` / `--new-preparation-version` | 新 Preparation 逻辑 ID 与固定行 ID |
| `--new-formal-request` / `--new-formal-version` | 新 Formal 逻辑 ID 与固定行 ID |
| `--new-link` | 实际保存的 RemediationLink 行 ID，无另一虚构 logical Link ID |
| `--report-name` | 可选，新证据 basename；只接受受限 `.json` 名称，已有文件拒绝覆盖 |

仅读取已有 `.local/runtime.json`、`.local/wave15-seed.json`、`.local/wave16-seed.json`。要求本人拥有的单链接、非符号链接 `0600` 普通文件，拒绝重复 JSON 字段/非有限 JSON/超大输入。seed 的 Issue、CAPA、措施与 scope 必须一致。

先检查实际 `read_state()` 容器/网络与三份连接配置，再调用 `verified(state)`；所有 URL 必须为 `postgresql+psycopg`、`127.0.0.1:62513/pdos_test`，不回退 `.env`。数据库唯一可接受 head 是 **`next_0025`**，`next_0024` 不可通过。

每个数据库事务显式 `REPEATABLE READ, READ ONLY`，核对 `transaction_read_only=on`；15 秒语句、5 秒锁超时。只用明确 tenant/product/project 的有界 SELECT。相同查询仅在本次只读事务内复用，新事务重新读取。最后用独立新只读快照核对已观察的版本、Current、权限和来源，重新观察容器及扫描器配置。Outbox 投递/lease/attempts 等运行字段不当作业务证明，固定事件绑定仍核对。

## 已实现的断言范围

1. IssueCurrent 必须精确指向所选 v6，历史 v4/v5/v6 的逻辑身份、scope、owner/writer、不可变摘要、前版 CAS 与单条追加历史都一致。v4 摘要还须等于事前 private setup 保存的 `observed_issue_basis`，v4 的根因/完成仍为空。v5 仍 actioning；v6 是 awaiting_verification。原失败、原 CAPA 与原措施身份不变，根因先于全部完成办理。
2. 根因 v5 保存的具名 T2 与完成 v6 的 T1，各自核对真实 consumed Confirmation、操作/本人/Product 水位、有效办理时间区间、Python `material_digest`、实质 before/after、保存的 authority/policy/source/read-set。Link 同样核对真实 T1 及完整 resolution 预览。三个 proof 跨 IssueVersion/Link 只能使用一次；不以猜测 token 代替证明。
3. 三个 Issue 版本、新 Preparation、新 Formal、新 Link 各有精确 Receipt/Audit/Outbox 一组，subject 是实际不可变行、版本/操作/本人/事件/correlation 一致；核对共同与已有领域语义摘要。原 request-key 绑定至少一条与保存的 request_digest 一致，不输出 key/token。不同 replay key 不被当作多一张 Receipt。
4. 实际完成整行使用原 `line:N;quote_sha256:<整行 UTF8 SHA>`，调用现有严格 CompletionFact 核验。原 private observation JSON 与真实整行字段一致，保留六位微秒与 offset 对应的完整 instant；事件 `occurred_at`、原 IANA 时区、独立服务器 `received_at` 分开，绝不用 JavaScript 日期改写。根因是服务器决定时间，不要求实际措施发生晚于根因决定；只要求根因版本先于完成版本保存。
5. 原 FailureRef 回到固定 Run 版本、原 Measurement 与 Projection、精确结果事件；现行纯规则重算仍为确定 fail。原值保持原 `11.0000` 的本次合成 fixture，不改测量。沿既有 `wave15_closeout.original_proof` 读取真实保留字节、固定扫描器配置/安全 epoch 与整行原值核验，返回的私有内容立即丢弃，不写入报告。
6. 新 Preparation/Formal 必须各是明确新 logical 的 v1 Current；Formal 为直接 `verification.request.create` 回执行、固定新 Preparation 的真实摘要/Build/配置。它不同于旧失败请求，samples/offered/acceptances/returns 均为空，没有新 Run；实际 timeline 除服务器 `request_created` 外均为空。首次记录钟必须绑定各自真实创建命令回执。expected/tentative 等意向时间不冒充实际时钟。Formal 可以因专业必需资料增添 documents，不要求与准备 documents 错误地逐字相同。
7. Link 必须固定原措施与 Issue v6/CAPA，basis 从真实 Issue 重建，输出只能是所选新 Formal 固定行，直接 Receipt/current/owner/snapshot/完整来源摘要一致。Link 的 basis/resolution/owner 摘要核对后，IssueCurrent 仍 v6。实际 candidate evidence 表对此 Issue 为零行；Issue effectiveness/history/closure 仍空，resolution.action_fulfilled 为 null。

此 CLI 专门核对本次 **一条合成确定失败、一个本人措施、一份新 Draft Formal 回链**。不接受混合真实/合成链、AI 原生来源、多个输出、另外上传的原件或多措施范围来冒充已覆盖；这些需要另行扩合同。

## 必须失败关闭

- 标记、62513 地址、scope、`next_0025`、私有输入或任何显式 fixed ID 不符；未保存 root/complete/link，不填充空值为通过。
- v4 事前基线缺失；Current 或固定历史被覆盖；CAPA/措施/失败身份变化、存在闭环有效性/关闭结果。
- 当前本人读取权限失效；来源撤回/摘要不符/私人原文不可读；原件隔离、安全 epoch、真实保留字节、实际扫描配置无法核对。缺运行时不降级为仅 DB metadata 通过。
- 确认缺失、未消费、tier/实质预览/水位不符；Receipt/Audit/Outbox 缺失或重复；共享 proof 被第二行使用。
- 实际完成来源/完整微秒/时区/本人/措施文本或接收时钟不符；新 Draft 已有样件/实物时钟/Run；新 Formal 没有直接创建回执；Link 错绑历史或 logical UUID。
- 跨字节读取期间版本、来源、ACL、Current、容器或扫描配置变化，报告只留下固定 reason_code。

## 不属于本工具通过含义

工具不会执行 HTTP、preview、consume、apply、replay、扫描、迁移或实际措施；不会初始化 app/重新注册运行时或补造对象。既有 OriginalStore 只读 gate 可以获取/创建有界控制锁，但不变更业务字节、注册状态或生命周期决定。

保存的 Confirmation/material/预览可以事后核对；**原 token preimage 和 False→True 同 UOW 的实际转移不能仅从 consumed=true 重建**，完整 request body 的 request_digest 也不能在无 token 时伪重算。SAVEPOINT/回滚/双向延期原子守卫仍须主线 PostgreSQL 负例验证。SQL 没有被声称能重建 Python sorted JSON digest。

历史 authority 明确按保存的具名、qualified 与 synthetic 事实核对；当前专业 issuer/职责/资格不重新授予或保证。新 Formal 当前可读取也不代表方法已适用、样件已 ready、已交样、已预约或已开测。Candidate 的公开 GET、integration 的 false 能力与 UI 文案不通过 HTTP 检查；本工具仅核真实零 candidate 行和空 effectiveness/closure，界面/API仍由主线联验。

任何运行成功只表示 `passed_as_of_read_only_synthetic_scope`，不表示正式整改有效、Issue 已关闭、生产资格、外发/发布或人工 Exit。

## 交付静态证据与运行方式

源码 SHA256：`2a1b6d34b8e46b0730db705d426ea4048775948c839c0e4e6758c144c7af88f6`。

实际运行 `pdos-next/server/.venv/bin/ruff format pdos-next/tools/wave16_closeout.py` 后，仅该新文件格式化。最后 `pdos-next/server/.venv/bin/ruff check pdos-next/tools/wave16_closeout.py` 退出 0，原始输出 `All checks passed!`。

最后 AST/内存 compile/入口结构静态检查使用 `pdos-next/server/.venv/bin/python -`，输入如下；未导入或执行 tool，无 DB/HTTP/browser：

```python
import ast
import hashlib
from pathlib import Path
p = Path('pdos-next/tools/wave16_closeout.py')
b = p.read_bytes()
t = ast.parse(b)
compile(t, str(p), 'exec')
assert all(isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.If, ast.Expr)) for n in t.body)
for n in t.body:
    if isinstance(n, ast.Expr):
        assert isinstance(n.value, ast.Constant)
    if isinstance(n, ast.If):
        assert ast.unparse(n.test) == "__name__ == '__main__'"
for n in ast.walk(t):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
        assert n.func.id not in {'execute', 'preview_command', 'consume_confirmation', 'create_app'}
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
        assert n.func.attr not in {'flush', 'commit', 'rollback', 'post', 'put', 'delete', 'inspect'}
        if n.func.attr == 'add':
            assert ast.unparse(n.func.value) == 'seen'
print('AST parse / in-memory compile / inert import structure / no application mutation call: passed')
print('Tool was not imported or executed; no DB/HTTP/browser interaction')
print('sha256=' + hashlib.sha256(b).hexdigest())
```

退出 0，原始三行输出为上面两条 `passed`/未执行说明及上述源码 SHA。早期 Ruff 发现五处超长行，格式化后消除；早期额外 AST 启发式把纯 `set.add` 当成持久写入而失败，修正为仅允许 `seen.add` 后通过。它们不是业务运行或 DB 回归结果。

主线后续使用上述全部显式 UUID 参数执行 `pdos-next/server/.venv/bin/python pdos-next/tools/wave16_closeout.py ...`；不把完整私有命令/UUID复制进公开证据。默认生成独立时间戳 `closeout-*.json`，不覆盖旧失败。stdout 只含 status、固定 reason_code、已完成检查数量；报告包含固定检查名称、选择摘要和边界，不复制 token、URL、私有原文/时间/测量值。退出 0 才是实际只读观察通过；本次交付尚无该业务运行结果。
