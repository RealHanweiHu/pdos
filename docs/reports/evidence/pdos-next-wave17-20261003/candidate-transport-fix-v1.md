# 候选专用 BFF transport 修复 v1（已冻结）

仅候选 operation `quality.capa.verification.candidate.record` opt-in 模块持有的 `undici@7.22.0` Agent，`headersTimeout/bodyTimeout=600000`；原 URL-string fetch、单次原正文、单次 fetch、无重试、`AbortSignal.timeout(600000)`、`redirect:error/cache:no-store` 均保留。其余路径没有 dispatcher 参数，保留原180/60秒和Node默认传输。使用官方导出 `Dispatcher` 类型，定向实际TS配置编译0诊断；无内部Next API或全局dispatcher改动。

运行版本实读 Node25.8.1、Next16.3.3、Node内置Undici7.22.0。本地内置Undici源码SHA `13026cf155735ef042891ab18f49b8ec10280b59bdb3693289d86edc6f9b5422`；明确运行时独立headers/body默认300000。新固定包 `lib/dispatcher/client.js:253–254` 同样默认300000。实际Next `dist/server/lib/patch-fetch.js` 的URL-string输入保留 `...otherInput`，将本次 dispatcher 传入原fetch；`dedupe-fetch.js` 对已有signal直接原样调用。Node http/https.Agent配置不替代fetch dispatcher。

官方来源由Root已核对：[Node Custom dispatcher](https://nodejs.org/api/globals.html#custom-dispatcher)、[Undici Client options](https://github.com/nodejs/undici/blob/main/docs/docs/api/Client.md)。具体版本仍绑定已安装7.22.0包与锁文件，不以main文档代替当前源码。

真实route VM25项、Wave16旧三操作route VM30项、新helper/合成socket4项，全59通过；日志与逐文件hash见 `candidate-transport-check-result-v1.json`。路由VM读取真实route/真实origin/真实helper，只替换Cookie与fetch/Agent宿主IO。旧三操作显式无dispatcher，原401/403/领域错误/未知结果/正文只读一次均保留。

临时127.0.0.1随机端口仅提供合成字节。100ms窄headers/body计时分别产生UND_ERR_HEADERS_TIMEOUT/UND_ERR_BODY_TIMEOUT，5秒总Abort当时尚未到期；实际helper 600000 Agent完成1.5秒延迟。另100ms总Abort仍终止候选请求。每次真实fetch仅一个服务端请求，未重试，own Agent/socket/timer均清理。合成4项约5.5秒，没有5分钟等待、没有PDOS HTTP/DB/browser/build。

初次 `node --test` 对目录中 `[]` 按glob匹配，只实际选择helper4项，原日志保留；后改直接Node执行实际两route测试文件，重复4项不叠加。首次lint仅新test局部变量module命名错误，已更名并最终0错误；生产源码无该修复。

历史UI UNKNOWN没有保存原传输cause，不能唯一归因300秒计时。Root已独立确认实际保存与原请求回执恢复；本次短合成不冒充真实600秒端到端结果。正式build/restart与必要真实恢复验证由Root执行。
