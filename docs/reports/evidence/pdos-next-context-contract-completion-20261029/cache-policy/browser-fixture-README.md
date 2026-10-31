# 协议缓存实际 UI 夹具（主会话运行）

源码为 `pdos-next/server/tests/agent_kernel/prompt_cache_browser_fixture.py`。本分支只完成 Ruff、语法和 collection（1项），未连接数据库、启动服务器或登记协议。它不依赖 Temporal、KMS、Keychain 或真实模型；实际 API 使用空 `RuntimePorts`、关闭工作流，并在原生路由外拒绝所有协议登记/回执恢复以外的 HTTP 写请求。

使用已经核对的四种数据库角色环境、53502/pdos_test 与 guard marker。从仓库根目录启动；目录必须是不存在的 `/tmp` 直属或其既有子目录中的新目录，Web URL 使用为本次生产构建预留的 loopback 地址：

```sh
cd pdos-next/server
PDOS_BROWSER_DIR=/tmp/pdos-prompt-cache-ui-run1 \
PDOS_BROWSER_WEB_URL=http://127.0.0.1:53140 \
PDOS_BROWSER_TIMEOUT_SECONDS=2400 \
.venv/bin/python -m pytest -q -s \
  tests/agent_kernel/prompt_cache_browser_fixture.py \
  --junitxml=../../docs/reports/evidence/pdos-next-context-contract-completion-20261029/cache-policy/browser-fixture-pg.xml
```

等 `PROMPT_CACHE_BROWSER_READY`。API 已绑定随机 loopback 端口、实际 `/v1/session` 成功、试探 POST agent-runs 已拒绝、协议仍为0，才写 `ready.json`。该公开 ready 没有 token，包含真实 API/Web/入口路径、8表基线和以下文件路径：

- `storage.json`：浏览器 storage state，cookie 含新合成管理员的登录 token，文件为0600。
- `state.json`：运行元数据，文件为0600。整个运行目录0700。
- `web-verified.json`：选择的真实生产 Web BFF 成功读取该新登录后生成。
- `preview` / `preview-verified.json`：第一次 UI 预览时的零写入检查点。
- `finish` / `result.json`：完成信号与实际 API/DB 核对结果。

主会话把生产 Web 的 `PDOS_NEXT_API_URL` 设为 `ready.api_base`，加载 `storage.json` 到浏览器，打开 `ready.web_base + ready.settings_path`。无需预览 catalog 或摘要/钉钉 fixture。进入“集成与治理”→“服务商协议”。

1. 填写固定合成服务商 `synthetic-prompt-cache-ui`、有效签约/到期时间（ready 提供 ISO 建议值）、至少一种允许类别及合成留存/训练条款。默认缓存选项应未勾选；勾选“协议明确允许提示缓存”，点“核对协议并预览”。截图确认允许，但尚未批准。
2. 此时写 `preview` 标记，例如 `touch /tmp/pdos-prompt-cache-ui-run1/preview`，等 `PROMPT_CACHE_PREVIEW_ZERO_WRITES` 或 `preview-verified.json`。夹具核对协议数量、登记POST均为0，8张受保护表保持，再继续。
3. 点“本人批准登记”，列表应显示第1版允许；刷新并重新进入同页，确认实际保存。以此协议续版，取消缓存选择，再预览/本人批准；第2版应为关闭，刷新保持。
4. 截图与字段核对完成后 `touch /tmp/pdos-prompt-cache-ui-run1/finish`。没有 actual API served、fresh Web身份或零写入预览检查点时不能完成。

最终必须是恰好两个原生登记POST、两个协议版本 `[True, False]`，与同一Human的T2回执、Audit、Outbox一致；原生HTTP列表读到第2版关闭；Artifact、AgentSession、AgentRun、AgentToolCall、模型调用/预算与embedding调用等8表计数和摘要保持。只核对，不自动补写缺少的版本。失败写 `native_ui_checks_passed=false` 并保留原因。

完成或异常都会关闭 loopback API；主会话统一停 Web、清理合成登录和私有运行文件。不要把 `storage.json` 复制到公共证据或输出其内容；可保存无token的 ready、web/preview/result 与浏览器截图。
