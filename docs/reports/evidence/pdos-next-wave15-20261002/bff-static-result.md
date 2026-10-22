# Wave15 BFF 接线与局部验证

状态：BFF 候选冻结。真实路径为 `pdos-next/web/src/app/api/[...path]/route.ts`，不是最初任务中举例的 `api/pdos/[[...path]]/route.ts`。仅修改该 route、新建同目录 `route.test.ts`；未触碰 Workspace/导航/API helper、用户另一会话文件或 backend/migration。

## 接入范围

- GET `v1/products/{UUID}/quality-execution`：仅可选 `build_id/run_id/issue_id`。
- POST `.../quality-execution/inputs`：不接受 query。
- GET `.../change-execution`：仅可选 `issue_id/change_id`。
- POST `.../change-execution/inputs`、`.../change-execution/captures`：不接受 query。

新路径与查询标识使用规范 8-4-4-4-12 UUID；查询拒绝未知键、重复键、空值及不合法标识。列表仅 GET，输入/捕获仅 POST。没有公开 Policy 导入或 Order/正式发布路线。共同 Command 的操作允许与资格仍由服务器闭合合同决定；BFF 不新增客户端资格判断，也不替代领域 DTO 校验。

五路及共同 commands/preview、commands 中七个精确操作等待 180 秒：`quality.issue.create/merge/triage/containment.record`、`quality.capa.draft`、`change.request.create`、`change.impact.compute`。旧 Wave14 四操作/结果路径 180 秒与其余路径 60 秒保留。

body 仅 `request.text()` 读取一次；JSON 解析只辨识超时类别，字面 body 原样转发，包括原 command/key/token、长数字与未知 null，不序列化替换。fetch 单次、无重试，缓存关闭、重定向拒绝；同源/会话/服务配置护栏保持。未知写回执提示保留原请求恢复，读取失败单独标明未发起操作。响应状态、领域错误与原件下载头保留。

## 已运行检查

工作目录：`/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/web`。

1. 24/24 无 DB BFF tests 通过，0 failed/skipped/cancelled。实际 route 和实际 request-origin guard 在 Node VM 内执行，仅 cookies/fetch/timeout 等宿主 I/O 替换为测试对象；无真实网络、服务或数据库。覆盖五路、七操作双端点、严格范围/方法、body 单读/原样、同源/会话、180s/旧等待、写未知无重试、读失败/流失败和域错误/下载兼容。最终原始 TAP：[bff-pure-tests.log](bff-pure-tests.log)，工具结果 chunk `1bfc15`，exit 0。
2. 受影响文件 TypeScript 检查通过，exit 0，stdout/stderr 空，chunk `6d62e3`。没有执行 next typegen/build。
3. 仅 route 与对应 tests ESLint 通过，exit 0，stdout/stderr 空，chunk `25cc78`。没有全局 lint/build。

精确运行命令：

```sh
node --test --test-reporter=tap '/var/folders/sv/npxlc_k53696tn8hryg5dx5w0000gn/T/pdos-wave15-bff.lqHXtq/route.test.js'
node_modules/.bin/tsc --project '/var/folders/sv/npxlc_k53696tn8hryg5dx5w0000gn/T/pdos-wave15-bff.lqHXtq/tsconfig.json'
node_modules/.bin/eslint 'src/app/api/[...path]/route.ts' 'src/app/api/[...path]/route.test.ts'
```

测试临时编译（仅临时目录生成 JS，src 未生成 JS）：

```js
const fs = require('node:fs'), path = require('node:path'), ts = require('typescript');
const tmp = "/var/folders/sv/npxlc_k53696tn8hryg5dx5w0000gn/T/pdos-wave15-bff.lqHXtq", web = process.cwd();
const file = 'src/app/api/[...path]/route.test.ts';
fs.writeFileSync(path.join(tmp, 'route.test.js'),
  'module.paths.unshift(' + JSON.stringify(path.join(web, 'node_modules')) + ');\n' +
  ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }, fileName: file,
  }).outputText);
```

临时 tsconfig extends 本目录绝对 `tsconfig.json`，`noEmit:true/incremental:false`，typeRoots 本目录 node_modules/@types；include 仅 route、route.test 与未修改的 request-origin.ts，exclude 空。框架依据已读 bundled Next Route Handlers、route 文件约定与 async cookies 文档；此处没有宣称完整 Next runtime/真实 backend/UI 联验通过。

## 冻结 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `pdos-next/web/src/app/api/[...path]/route.ts` | `c17d2c59bba074b5c865ca4524405deb4c10ee36f15350a4bf0155dd8d04c900` |
| `pdos-next/web/src/app/api/[...path]/route.test.ts` | `2f876d4b1b73851305dc1c365d494d63829f96af984b647b9a660a6bdcc072a3` |
| `pdos-next/web/src/lib/request-origin.ts`（只读依赖） | `c0e2ddc00d747f0aae1f325e256cb8f32f9ef6fbe81e59ec0173007d46173f34` |

剩余：主线接公共 backend/迁移，并集中执行真实 API/生产构建/页面闭环及受影响验收；这里没有启动这些验证，也没有挂 BuildQualityLoop 共享导航。
