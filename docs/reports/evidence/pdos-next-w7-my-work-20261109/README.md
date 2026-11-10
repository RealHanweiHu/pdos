# W7 我的工作、要我决定、提案页小修 · 证据（2026-11-09/10）

依据：[10-26 UI 对照报告](../pdos-next-ui-comparison-20261026/result.md)“我的工作”“双向承诺”；`web/src/app/ui-lab/platform`（`Work`、`Commitments`、`ProductContinue`）；确认稿 [P35](../../../design/2026-10-08-pdos-next-design-confirmation.md#p35)、[P36](../../../design/2026-10-08-pdos-next-design-confirmation.md#p36)、[P77](../../../design/2026-10-08-pdos-next-design-confirmation.md#p77)；v1.1 §06“一次确认的粒度”。基点 `c13c3fd6`，分支 `claude/wonderful-visvesvaraya-922b5d`，本地提交，未推送。**无迁移**（占位 `s0_0895`–`s0_0899` 未用）。

## 做了什么

| 条目 | 现在 | 读写 |
|---|---|---|
| D38 待我处理 | 按要我决定、要我接收、要我验证、等外部回复分组，另列“我的任务”（本人在办任务、计划安排、风险；口径已报协调会话待用户定） | 只读，原有队列 |
| D38 双向承诺 | “承诺”页切换“我承诺的 / 别人承诺给我的”；行内显示“我 → 接收人”或“承诺人 → 我”，详情含承诺人、成果范围、承诺原值与时区、任务进展 | 新队列 `GET /v1/personal/project-work?queue=received`（承诺人列来自承诺记录本身；已验收履行的不列，同“我承诺的”） |
| D38 继续提案 | 提案 / 入口 / 状态 / 更新四列，私有提案带锁形标记，按更新时间排序 | 提案列表接口加 `entry_kind`、`updated_at`（最近一次修订时间） |
| D78 | “要我决定”组内一运行一卡片：待答问题（跳到对话作答）与待确认候选；需要核对的等待（外部结果未知、模型不可用）只提示查看 | 新只读接口 `GET /v1/personal/run-decisions`：每个品类在各自只读快照里复用候选状态投影 `project_rows`，不预览、不写、不续跑；最多 30 个运行，超出与不可读计数在界面提示 |
| D78 深链 | `?area=work&decide=<运行>&candidate=<候选事件>` 定位并高亮卡片，只预选该版本；链接已失效时提示 | 只读 |
| D77 | 卡片上默认全选、可取消单条；“核对整包”逐条调用原预览接口取得各自令牌和核对内容（可展开原值、新值、来源与未定项，与对话中单条确认同一份渲染）；“确认整包”后逐条列出已保存 / 未保存 / 未进入整包 | 新接口 `POST /v1/categories/{c}/agent-runs/{run}/candidates/confirm`：每条按原命令走 `execute`，各自事务；T2、资料跟进 / 复验准备等多步候选、改动过的命令、未预览的条目拒收；意外异常时停下，其余标“未办理” |
| D271 | 全局 base 层 `dialog { margin: auto }`，模态居中；抽屉类显式 `margin:0` 不变 | 样式 |
| D336 | 提案重读时文档不卸载，读回后同一次渲染替换并清已保存草稿；焦点等输入框解锁后落到相邻行；视图结果仍先撤下 | 前端 |
| D337 | 问题负责人只列能读此提案的人，表下提示另有几位需先共享；已指定但不能读的负责人在行内标出 | 参与人接口加只读 `can_read_proposal`（`m3_audience_member`，与服务器拒绝规则同源） |
| D341 | 未指定页面的入口最多等 1.5 秒读回偏好；提醒数 = 要我决定（含小Pai运行，每运行一项）+ 接收 + 验证 | 前端 |

## 自动检查

| 检查 | 结果 |
|---|---|
| `next typegen && tsc --noEmit` | 通过 |
| `eslint src` | 0 错误，4 个既有警告（未改动的测试文件） |
| 前端全部 `.mjs`（168 个文件） | 1945 通过，0 失败；新增 `run-decisions.test.mjs` 5 项（解析拒收他人 / 不完整 / T2 包项、默认全选与深链预选、逐条预览与失败隔离、整包结果核对、负责人过滤） |
| BFF `route.test.ts` / `wave16-route.test.ts` | 91 / 30 通过（新增新接口放行与拒绝用例） |
| 服务器 PG（隔离 `pdos_test`，显式 `TEST_DATABASE_URL`） | 受影响 13 组共 333 项：325 通过，8 失败均在无库的 `tests/projects/work/test_personal_projection.py`（按精确字段集断言，未含新 `promisor` 字段）；同步后该文件 28 项全过 |
| 新 PG 用例 `test_candidate_package_pg.py` | 3 通过：运行分组只给本人、问题与核对等待的区分；整包逐条保存且部分失败如实列出、回执各自绑定；T2 / 外来 / 改动 / 未预览拒收、他人 403、重复 422、已保存后“已不是待确认” |
| `tests/core/test_public_api.py`、command_catalog、`validate_contracts`、ruff | 通过；`openapi.json` 重导，只增 |

## 浏览器走查

环境：本 worktree 用 `tools/local_environment.py create` 建的带标记隔离库；临时种子在 pytest 内起服务（合成账号，未提交），前端 `next dev --webpack`。数据经公开命令与合成运行事件建立：同一运行 3 个平台关联候选（其中两个平台编号相同，用于制造真实部分失败）和 1 个待答问题；他人承诺给本人、本人承诺给他人各一条；一份私有提案草稿。未调用模型。

| 截图 | 内容 |
|---|---|
| [01](01-decide-run-card-light.jpg) | 亮色：要我决定内的运行卡片，问题与 3 个候选默认全选；侧栏提醒数 1 |
| [02](02-package-review-dark.jpg) | 暗色：整包核对框居中，第 1 项展开完整核对内容 |
| [03](03-package-result-partial-dark.jpg) | 整包结果：2 项已保存、1 项未保存（服务器原因：平台编号已存在） |
| [04](04-after-package-dark.jpg) | 刷新后卡片只剩未保存的那一项 |
| [05](05-commitments-mine-light.jpg) / [06](06-commitments-received-light.jpg) | 承诺页两个方向，详情含承诺人与原值 |
| [07](07-deep-link-preselected-light.jpg) | 深链定位并预选该版本 |
| [08](08-decide-375-dark.jpg) / [09](09-package-preview-refused-375-dark.jpg) | 375px 暗色：无横向溢出；剩余项在预览阶段被拒，列为“不进入本次整包” |
| [10](10-proposal-owner-hint-input-kept-light.jpg) | 提案页：重读后单元格输入保留；负责人只列可读者并提示 |

另以脚本核对：触发窗口获焦重读后，问题单元格元素未卸载、输入与焦点保留（D336）；无类名的模态 `<dialog>` 左右各 400px、上下各约 395px（D271）。

## 未覆盖与余项

- D341 的慢偏好场景只有单元覆盖：本地偏好接口约 0.4 秒，没能稳定复现闪烁。
- 新建品类等具体对话框没有逐个点开，D271 的 51 个 dialog 按样式逐个核对（见清单 D271）。
- 余项登记为 D420–D426（阶段进度条、最新预计、开测承诺接收方、整包覆盖范围、就地作答、导出、读取上限）。
- 只用合成账号走查，不代表真人试用或验收。
