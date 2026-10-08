# Wave16 BFF 新增测试合同与静态检查

状态：新增测试源码冻结，**未运行测试**。公共 BFF 检查由主线统一执行；本证据不表示 HTTP、数据库、业务资格或完整联合验收通过。

## 唯一源码归属

新增 `pdos-next/web/src/app/api/[...path]/wave16-route.test.ts`。没有修改原 `route.test.ts`、实际路由、同源守卫、公共 API、UI 或任何业务文件。

宿主沿用原 BFF 测试的 Node VM 方式：运行时从磁盘读取并转译真实 `route.ts` 与真实 `request-origin.ts`。仅替换 cookies、服务配置、计时信号与 fetch 等宿主 IO；没有复制路由允许表、输入验证器或同源实现。合成 token、URL 和返回值仅用于传输断言，不构成真实 Receipt 或资格。

## 检查范围

- 单 Issue GET 必须有真实 UUID 格式的 `issue_id`；可选 `revision` 为规范正整数且不超过 `2147483647`。重复、未知 query、空值、非整数、越界及 unsafe integer 拒绝；inputs 不允许 query。
- `quality.issue.root_cause.decide`、`quality.capa.actions.complete`、`quality.capa.followup.link` 三操作均以完整 Common Command 输入。核对同产品、必需结构、固定 Issue 版本、1–20 条唯一 Artifact 版本引用、大小写规范比较；Product/Issue/Artifact 版本允许 int32 最大值，拒绝最大值加一和 unsafe integer。
- 原正文只读一次并原样转发一次；空格、数值字面文本、approval/confirmation token 不被重写。payload 的业务语义、资格、来源完整性仍由实际领域 API 核对，测试不模拟领域批准。
- 三操作经共同 preview/commands 路由均使用 180 秒；无隐藏重试、补命令或自动重新确认。非法 JSON 的共同命令保留原有领域转交行为。
- 当前同源守卫、无会话 401、无配置失能、后端 401/403/409/422/503、未知写结果、只读失能、正文与回包流失败均保留旧恢复行为。

## 本次实际完成的检查

仅运行离线 TypeScript AST 解析、CommonJS/ES2022 转译及 `vm.Script` **编译**。没有执行 VM、注册测试、Node test runner、数据库、HTTP 或公共 build。

结果：语法/转译诊断 0；源码有 19 个 `test(...)` 调用点，按静态注册循环展开预计 30 项。此数字是注册结构核对，不能写成“30 passed”。具体源码摘要见 `bff-wave16-test-source.json`。

## 主线最短运行方式

工作目录为 `pdos-next/web`。以下命令是供主线执行的运行说明，本次没有执行：

```sh
node -e 'const fs=require("node:fs"),ts=require("typescript");const p="src/app/api/[...path]/wave16-route.test.ts";fs.mkdirSync(".local",{recursive:true});fs.writeFileSync(".local/wave16-route.test.cjs",ts.transpileModule(fs.readFileSync(p,"utf8"),{fileName:p,compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText)'
node --test .local/wave16-route.test.cjs
```

运行目录必须保持为 web，测试才会读取该目录的真实路由与守卫。若实际路由摘要变化，主线应记录新候选及影响范围；当前静态证据不能替代该候选的实际运行结果。
