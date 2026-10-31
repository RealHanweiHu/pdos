# 本人工作摘要 → 本人钉钉单聊（RAG v0.4 §11.6）

独立 stage；未改 live，未连 DB，未调用真实 KMS、模型或钉钉。原生默认仍为站内摘要。新增选择仅 `personal_summary.dingtalk_binding_id?: UUID`；省略或 null 序列化仍省略，保留旧固定版本及摘要 digest。本人选择当前已验证绑定后，沿原规则保存草稿→预览→一次 T1 确认；原暂停只停止新受理。

## 集成文件

以 `manifest.json` 为准。复制 `new_files`；其余只应用补丁：

- `sql-model-public-hooks.patch`：模型 import、生命周期目录登记。SQL/模型冻结子集见 `sql-model-manifest.json`，candidate SQL 保持原冻结 SHA；模型最终只追加 p26/provider_receipt 的 SQL NULL 绑定修正（none_as_null=True），以该 manifest 当前 SHA 为准。当前 live lifecycle_catalog 额外已有 `enterprise_search_sources.original_ids`，须保留；此补丁只追加新表登记。
- `owned-hooks.patch`：原摘要 DTO/接口注册/规则当前性/ChannelSender，以及原摘要表单、确认预览和父测试隔离边界共 8 个文件。
- `runtime-public-hooks.patch`：worker 注册、有限 BFF 分发、category-bound Run 深链 3 个锚点、挂载现有 PersonalSummaryRunResult，共 5 个文件。保留当前 B 的 ProjectCockpit `onOpenRun`。

`files/` 下既有文件是精确检查副本，不应整体覆盖公共文件。两个 `*-bases.json` 记录补丁前/后 SHA。SQL/模型子包已先交 root；未编号 candidate 以实际 head851 导出为前驱，正式版本由 root 分配（预期 852）。

## HTTP 与 UI

- GET `/v1/personal/inbox/summary-channels`：本人当前绑定 ID/版本及应用版本；只读，不取密钥、不出站。
- GET `/v1/personal/inbox/summary-deliveries`：本人最近 100 条安全状态、P26 与原安全回执，不返回 payload。
- POST `/v1/personal/inbox/summary-deliveries/{id}/reconcile`：UI/BFF 仅提交 `{}`；普通本人读取原记录后仅查询原回执，无发送分支。

原自动规则表单内显式读取本人绑定，目的地默认“仅站内摘要”；预览显示已选目的地。原钉钉 Run 链支持可选 category UUID，仅选择 UI 上下文，实际 Run owner/category READ 仍为权威。原摘要结果组件挂入已完成/部分完成原运行；无需创建入站 Message 或新 chat。

## 持久执行与发送合同

原 deterministic 个人摘要依然由原 T1 自动化受理的 XiaopaiWork/KernelActivity 生成。现 ChannelSender 发现明确选定绑定的已完成摘要，Temporal 新 workflow 仅携 tenant/run IDs；Activity 进入同一注册 `xiaopai` LangGraph 完成固定投递，无 Host/model/新工具定义。

服务端通过真实 Run→admitted Attempt→Grant→具名 T1 Version/Receipt→本人 Binding→Application 获得元数据；按原 owner ordinary RLS 快照重读 `_bound` 与 `_check_sources`。仅复制原摘要显示的变化、本人关系、具名下一步和原事项链接。原件/私聊正文、facts 任意 JSON 与模型输入不进入外发文本。P26 服务商由服务器固定 `dingtalk`，只读本原生摘要事实为 internal。

每 Run 一条持久投递，固定原 binding/application revision、cancel epoch、summary/payload hash；`source_ids` 仅捕获服务端实际 Summary ObjectRef id/version_id。原 app→binding 锁顺序及发送前当前性复验保留。发送登记单次 0→1 后提交，再用现有官方 adapter；unknown/sending 恢复只 lookup 原 request key/安全 provider receipt，不重发。绑定撤销仍可核对原安全回执；没有原回执的超时保留 unknown。原 Run 不修改。

## Schema / down

唯一新表 `dingtalk_summary_deliveries` 使用 FORCE RLS；新辅助函数按现 G owner/dispatcher/service 权限分工。8 表 head851 owner/ACL 导出表明无需改既有表 GRANT，仅为 pdos_next_owner 增两条 G 应用/绑定元数据 SELECT policy，down 精确移除。唯一 typed lifecycle functions `m3_lifecycle_source_links`/`nodes` 扩展新表，不新增权限根；source IDs 与真实 Run 共同保留。插入遵循现 reference clock/待销毁原件 fence。

`migrations/candidates/summary_dingtalk.py` 导出 `BASE_SQL`、`LIFECYCLE_UP_SQL`、`DOWN_SQL`、精确851 `PREVIOUS_FUNCTIONS`/新 `NATIVE_FUNCTIONS`。down 首先拒绝非空投递历史；空表恢复两个精确前驱及仅本次增量，保留原 owner/SECDEF/ACL。正式迁移/元数据一致性/up-down-up/非空 guard 由 root 执行。

## 验证与剩余

- 后端纯测 52 passed，含新增 7（不叠加）；`pure-summary-legacy-final.xml`。覆盖旧摘要、原 feed/质量边界及实际官方 MockTransport pending/lookup、真实 LangGraph Activity IDs-only。
- 前端 35 passed：`frontend-node-final2.txt`（含原表单 20、原 summary 10、连接 DTO 3、真实 React 子表单 SSR 2）。父浅渲染测试只 stub 独立 stateful 子表单，后者有单独真实 React 测试。
- 隔离全副本 tsc exit0；10 个变更 TS/TSX ESLint exit0；stage server+worker Ruff exit0，显式使用 repo Ruff config。详见 `verification.json`。
- 新原生 PG/HTTP/Temporal **5 项仅 collect**，`pg-collect-final.txt`：真实 T1/原 Run/官方 mock pending→撤绑定→lookup-only；绑定撤销/应用停用/源权限撤销 3 个发送前拒绝；真实原 XiaopaiWork→新投递 Temporal/LangGraph 并核 IDs-only history。复用 repo 原 fixture，无 /tmp helper、无真实 provider。

Root 应在审应用迁移/源后，使用原已核独立 TEST_DATABASE_URL 和现 Temporal/checkpoint 环境执行：

```sh
PYTHONPATH=.:tests .venv/bin/python -m pytest tests/dingtalk/test_summary_delivery_pg.py -q --junitxml=<evidence>/pg-summary-dingtalk-run1.xml
```

在 `pdos-next/server/` 执行，勿回退 .env。Root 负责实际 PG/Temporal、最终统一 build 和 native UI；这里的 collect/静态证据尚不代表这些实际验证通过。真实 channelsends 保持禁用。
