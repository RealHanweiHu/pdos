# 摘要→本人钉钉 native UI fixture（root 执行）

`browser_fixture.py` 只在 root 明确执行时使用已核对的独立 PG/checkpoint，启动一个 loopback API；subagent 仅 collect/Ruff，无 DB、服务或真实 provider。复用 live `tests/dingtalk/test_summary_delivery_pg.py` 的 **summary_channel**、原生工作事实/账号绑定/自动化 T1/KernelActivity，不依赖其他 `/tmp` helper。已完成摘要是原 admitted Run；官方端口仅 httpx.MockTransport+SyntheticKms，零真实模型/KMS/发送，无入站 Message、新 chat 或伪造 Run/result。

## root 启动

沿用已通过 native6 的实际隔离环境，不 source `.env`：

- TEST_DATABASE_URL / DATABASE_URL / AUTH_DATABASE_URL / DISPATCH_DATABASE_URL：已核 `pdos_test` admin/app/auth/dispatch 角色。
- PDOS_CHECKPOINT_DATABASE_URL / PDOS_STATE_DB_PORT / PDOS_STATE_DB_MARKER：原已核独立 checkpoint 角色/目标。
- 无需新建 DB 或 Temporal；本 fixture 通过原 KernelActivity 预置一个确定性摘要，UI 不触发新运行。原 Run GET 显式接入 `Bootstrap(setup.engine).api_ports(RuntimeTemporal())`，RuntimeTemporal 未配置实际连接，模型 RuntimePorts 仍为空；ASGI 边界继续拒绝聊天写入。

选择 fresh **不存在**的输出目录（0700），设置 root 将实际使用的 frontend URL：

```sh
cd '/Users/huhanwei/Desktop/ai-native-R&D-platform/pdos-next/server'
PDOS_BROWSER_WEB_URL=http://127.0.0.1:<root-selected-web-port> \
PDOS_BROWSER_DIR=/tmp/pdos-summary-dingtalk-browser-actual-20261029-v1 \
PDOS_BROWSER_API_PORT=0 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests \
.venv/bin/python -m pytest -q -s -p no:cacheprovider \
  --confcutdir=/tmp/pdos-summary-dingtalk-browser-20261029 \
  /tmp/pdos-summary-dingtalk-browser-20261029/browser_fixture.py \
  --junitxml=<root-evidence>/browser-native.xml
```

`SUMMARY_DINGTALK_BROWSER_READY` 给出真实已绑定 API port 与 `ready.json`。启动/配置 root 管理的最终前端对准该 API（757 production build 可复用）：

```sh
cd '/Users/huhanwei/Desktop/ai-native-R&D-platform/pdos-next/web'
env -u PDOS_NEXT_PREVIEW_CONFIG -u PDOS_NEXT_LOCAL_SESSION \
  PDOS_NEXT_API_URL=http://127.0.0.1:<ready-api-port> \
  node_modules/.bin/next start --hostname 127.0.0.1 --port <root-selected-web-port>
```

用新输出的 **0600 storage.json** load 独立浏览器session；勿打印或复制 cookie。脚本只有在该实际 web `/api/v1/session` 返回 fresh本人后才写 `web-verified.json`，不能只看 API ready。

## 真实 UI 步骤

`ready.json` 给出 category/project/binding/run/delivery 的真实 ID、规则名称和两个 UI 路径。所有提交经浏览器原表单；不要人工 API 代替，不发新 chat、探测或手动运行。

1. 打开 `ui_paths.settings`，小Pai与模型→自动化规则→新建**摘要**。初始目的地应为“仅站内摘要”。展开必要高级配置，将规则名称改为 `ui_rule_name`（浏览器：本人钉钉工作摘要）；读取本人可见项目并选 `project_id`，保持实际原生分组/日历，无技能/钱包。
2. 在“摘要投递”点“读取本人钉钉绑定”，选择“站内及本人钉钉单聊 · 绑定第…版”。点“预览摘要订阅”，核对预览目的地为本人已验证钉钉单聊，再点原“确认此次规则状态变更”。刷新，读取刚创建 active 规则，点“编辑新草稿”查看已保留的目的地；只读后不必再次保存。
3. 打开 `ui_paths.original_run`，确认真实完整结构摘要可见：变化、与我有关、下一步、责任人和继续办理链接。它是 seed 原 Run 的实际显示字段，不预期原 facts/原件正文被复制。可截图包含原Run和四问字段。
4. 返回自动化规则摘要表单（可编辑已建规则，**不再保存**），展开“本人摘要投递回执”，点读取。初始实际状态是“结果待核对”unknown、发送登记1次；截图。点该行“只查询原回执”，Mock官方 lookup 应变“已送达”，刷新并再读取保留状态；发送仍1次。

初始 seed 规则名为 `Native summary to my verified DingTalk account`，供原摘要/回执展示。请为 UI 创建独立新规则，使用指定中文名称；脚本不会预创建该 UI 规则，也不会自动 tick 它。

## finish 原生核对

截图/步骤完成后，**root** 在实际输出目录创建空 `finish` marker（勿写 result.json）。fixture 自己读取实际 DB/普通接口并写 result.json：

- UI指定规则 active，真实草稿先于原 T1 activate；draft/active 都保留实际 own binding，零模型技能/钱包预算。
- Human本人版本/具名 Receipt/consumed Confirmation/同小Pai ServiceGrant 真实存在；ordinary rule GET 确实看到保存后的绑定。
- 原 Run结果hash、权限范围和完成状态不变；原投递 delivered、attempts=1，固定源ID和summary hash匹配原真实Run。
- 实际UI经过channels/statuses/原Run读取、commands preview/execute、原receipt reconcile路径。
- official MockTransport恰1次body send、至少1次原receipt lookup；新chat/Message/旧GDelivery/Artifact/通用ToolCall/模型钱包/技能均未新增。

缺任一真实UI结果会断言失败并写 `native_ui_checks_passed=false`；`exit0` 和实际 result 为验收信号。仅 ready/截图不算 native finish 通过。脚本只清理自己的API/socket；root统一收前端及其余环境。

## 本地静态检查

移除 DB/Temporal/checkpoint 环境后 collect：1 test collected；Ruff显式 repo config通过。详见 manifest.json、collect.txt、ruff.txt。未执行该fixture，实际UI/PG结果留给root。
