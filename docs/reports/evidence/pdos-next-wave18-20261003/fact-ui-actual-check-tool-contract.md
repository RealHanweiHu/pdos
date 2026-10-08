# Wave18 真实服务器 JSON 离线消费检查器

新增 `pdos-next/tools/wave18_actual_fact_ui.cjs`，只读实际服务器响应，不发 HTTP、不访问数据库、不启动浏览器，也不创建或修改任何业务请求。用安装的 web TypeScript 在同一个 Node realm 内加载冻结的 `ui-contract` / `fact-workflow-contract` / `fact-workflow-state`；实际 JSON 也在该 realm 解析，避免跨 realm 原型检查误判。模块 SHA 必须与已冻结 `fact-ui-source-manifest-v1.json` 完全一致。

默认读取主线随后生成的四个私有文件：GET 当前 host、inputs、preview 及 `.local/wave18-fact-demo.json` 中 `observation_setup.command`。前三份是直接响应 body，工具不猜 envelope。对 command/key/null token 不做投影或重写；主线明确首次发出前把尚未发出的草稿 key 改为 UUID 并省略 null token，该事实应由主线单独留痕。

检查依次调用真正的 `validFactHost`、`validFactCommand`、`factCanPrepare`、`factInputsCommand`、`factPrepared` 与 `readFactBusinessReview`，要求 scope/actor/product/Issue/CAPA/Current CAS 相符、完整实际 13 键和读集闭合、完整业务阅读及非空 sections/effect。选定整条原记录的可选时钟必须完整可读；显示原事件时区、微秒钟及所有原措施完成钟逐字保留。候选有效性和问题关闭必须仍未启用。

示例（由主线在四份实际响应生成后执行）：

```text
node pdos-next/tools/wave18_actual_fact_ui.cjs --report docs/reports/evidence/pdos-next-wave18-20261003/fact-ui-actual-contract-check-v1.json
```

可显式覆写 `--host` / `--inputs` / `--preview` / `--demo` 路径。默认按照运行时当前时刻拒绝过期预览。若主线要离线核已经过期的历史预览，可传明确 `--preview-at <aware ISO>`；结果身份会是 `PASS_RECORDED_PREVIEW_DISPLAY_ONLY`，绝不代表当前可提交或资格有效。没有自动补钟或修改命令。报告只保留布尔、计数、源码/响应 SHA、固定失败码，既不输出令牌、key、完整命令、原文、业务值或凭据，也不吞掉失败改为通过。

已做 `node --check` 静态语法检查退出 0。此时未运行实际响应检查器；HTTP 文件是否完整及业务结果由主线生成后核对。字段/历史/资格检查来自冻结宿主 DTO 和真实前端规则，本检查仍不等于字节安全、同事务 proof 消费、数据库写入、实际职业资格或浏览器操作验收。
