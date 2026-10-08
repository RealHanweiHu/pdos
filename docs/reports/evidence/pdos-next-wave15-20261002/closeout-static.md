# Wave15 只读收口工具：静态交付

此记录只证明工具已实现并完成局部静态检查。未运行工具 main、数据库、HTTP、pytest、迁移、浏览器或构建；实际演练及 PG 分组由主会话继续执行，本记录不声明 Wave15 已验收。

工具：`pdos-next/tools/wave15_closeout.py`，SHA256 `698788020c40f23f2e57bd0377dde80f31ba9b42c09884fe7a4a4a8a1cefefd0`。

## 主线调用

从 `pdos-next` 目录调用，两个 UUID 均须取本轮主线真实保存的逻辑 Issue/Change：

```sh
PYTHONPATH=server server/.venv/bin/python tools/wave15_closeout.py demo --issue <logical-issue-uuid> --change <logical-change-uuid>
PYTHONPATH=server server/.venv/bin/python tools/wave15_closeout.py selection --issue <logical-issue-uuid> --change <logical-change-uuid>
```

工具惰性导入。两模式均读取现存 0600 私有 `.local/wave15-seed.json`，先 `verified(read_state())` 精确核对 62513、marker、容器、租户/产品及 `next_0023`，再使用 READ ONLY 管理连接及限定租户选择；不创建 Demo、不保存私有 checkpoint、不输出 URL/token 或报告全文。结束前再次核对目标身份。

成功分别写新 `demo-closure.json` / `final-selection.json`，退出 0。PG 或复验尚未完成时写唯一的 `*.pending-<timestamp>.json`，退出 2；缺失、矛盾或不可核验的证明写唯一失败记录，退出 1。所有输出均有界且不会覆盖已存在最终文件或原始日志。

## 强检查与边界

- 演练严格限定 seed 的 actor/project/build/request/run 及显式 Issue/Change。核保存 Run 的确定失败、原值 `11.0000`、实际 Start 版本2、只属于新 Run 的两份测试资源占用与一份样件使用；不混计同 Build 制造占用。
- 读取真实原件经过现有 OriginalStore 可逆访问门禁，以实际观测的固定扫描镜像配置和真实扫描回执核对当前安全 basis，再按原件字节、大小、SHA、固定测量证明核值；IO 后重新读取原件/安全/Artifact 并复核。缺 Docker 镜像或真实证明时失败，不补造 clean。允许既有门禁获取/创建受控读取锁元数据，不写原件、隔离标记或 effect。
- 核当前 Issue/CAPA 仍未完成：根因、完成、有效性与关闭事实保持空；核 FailureMap/EventLink 的固定失败及原计算投影，并逐版核 Receipt/Audit/Outbox、actor、前版和 SHA。
- 核 Change 固定当前 Issue/CAPA，历史 capture 原版根、完整读集、图 SHA、确定性影响与八 facet UNKNOWN；Order/实施/批准不补造。capture 到期只作历史读证，不授新的计算权限。
- `retained_before` 的 33 表只比对原来已存在行的逐行 SHA；允许新行，不将 Product/reference_epoch 当旧事实不变项，不扩大到整个旧工作区。
- 当前 backend-v2 的303路径、web-v2的138路径逐 SHA 核对。历史 backend-v1 保留，其两路径差集按 `backend-candidate-v2-delta.json` 完整核对；历史 hash 不匹配不冒充当前源码损坏。
- 原 PG 每组必须有退出结果、完整终结摘要及全部参数 node。v1 失败节点只有在原组完整收尾、同一精确 node 的 v2 复验完整成功时才能替代；报告仍保留原失败结果/日志，并标 `passed_with_exact_v2_replacement`。其他 v1 组须全部成功，明确不声称 v2 全文件全联合重跑。
- 81 backend pure、24 BFF、35 UI helper 分别核日志与对应范围，不相加成全仓联合。当前选择静态展开为13函数、13组、14参数病例，`pg-07` 为两参数；以实际完整日志匹配为最终依据。

静态检查：Ruff format 无变化；Ruff check 通过；AST parse/compile、惰性导入、无显式业务写入/commit/FOR UPDATE/存储 effect 调用检查通过。纯临时文本检查覆盖完整失败摘要、完整成功摘要、缺失终结摘要三种日志形状，不运行 pytest。查询表/列已定向对照当前模型；不会猜缺失字段或以模拟真值补缺项。

实际运行前仍未核：正式生产资格、当前执行许可、CAPA 独立有效性/关闭、正式 Change Order/生效、真实外发、浏览器人工 Exit、全仓回归。该工具输出是读取时点证据；即使旧保存 Start 存在，也不能将其解释为此时仍可开工或放行。
