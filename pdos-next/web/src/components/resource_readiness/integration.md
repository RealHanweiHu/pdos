# 资源准备度 UI 独立交付

本目录仅交付包内组件，不修改父页面、API/BFF、公共命令或政策注册，不连接数据库/服务、不接合成数据到业务入口。

## 主线消费

- `ResourceReadiness` 接收服务器只读 `ResourceReadinessView`、`ResourceContext`、固定 `ResourceCandidate[]` 和共同办理状态。
- 父客户端容器传入 `onPrepare(candidate, contextKey)`；该回调只准备主线现有受控动作，不代表占用、提交或资格授予。通过 `actionReview` ReactNode 传入现有共同T1实质预览、一次确认与回执。T2治具验收沿 `npi.fixture.accept` 的具名决定入口；组件无自己的确认、命令或回执协议。
- 后端 `ExecutionWindow.original_timezone` 由主线映射为 `originalTimezone`；`ReadinessReport.checks` 映射成逐资源 `checks`，`capacity_status` 独立映射为 `capacity.status`。资源身份 `id/revision/kind` 原值保持。`line/tooling` 与 `equipment/fixture/person` 共用固定引用，未创建SampleUnit或库存权威。
- `physicalReceived/actualStarted` 只映射真实独立事件及其来源；不从执行区间、暂定时段或正式预约回填。预约历史保留 tentative/formal/released/cancelled，不覆写或隐去释放取消事件。
- `context.portReady`/`current`/服务器候选可办理状态不可用时失能。未注册人员资格签发、校准接受、独立预约/释放/取消动作只显示接入需求；不得以组件字段、模型输出或合成fixture授权。

## 服务器责任与失败恢复

主线从run/session绑定租户、项目、ACL、当前具名身份、真实资格与固定资源版本，并在共同预览和提交时重核所有读集、摘要、有效期、来源撤回、维护、日历/容量与当前授权。候选的 `policy`、`available`、`contextKey` 是服务器投影，组件守卫仅用于交互，不能作为服务器政策事实。

固定候选须由共同主线绑定全部资源版本、用途和半开执行区间。校准与人员资格有效期覆盖整个执行区间，不能只核开测时点。资格覆盖展示遇到未知边界/时区不明为UNKNOWN，明确不能覆盖则提示阻塞；整体状态仍由服务器规则投影。

资源+样件联合正式预约必须同一调用者UOW确定性锁定、CAS、一起提交或一起回滚；UI仅准备主线候选，检查成功/容量checked不形成占用。不自动重试写入。`action.outcomeUnknown` 或 `reviewPending` 失能新办理，由父容器恢复原预览和回执查询；组件不发起第二套确认。准备调用抛错保留服务器候选，并显式显示错误。

## 验证范围

局部nonincremental/noEmit TypeScript、ESLint --no-cache通过。`node --test render.test.mjs` 10项通过，含真实React SSR和纯交互守卫；原始输出已集中保存到 `docs/reports/evidence/pdos-next-resource-readiness-20261002/` 的 `typecheck.log`、`eslint.log`、`components.log`。

纯检查不代表DB/HTTP/浏览器、亮暗/尺寸或正式G/N/P/Q验收。尚待主线服务器投影与政策注册、共同受控动作绑定、父客户端页面接线，以及公共集中验证。
