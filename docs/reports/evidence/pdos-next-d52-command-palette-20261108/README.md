# D52 ⌘K 执行命令与快速创建 · 证据（2026-11-08）

依据：确认稿 P22 的 B19（v1.1 §05.12.5）、B18（界面不出现档位词）、§05.11（键盘可达）。基点 `pdos-next/design-v1.1` @ 38f5a024。

## 做了什么

- ⌘K 面板（`web/src/features/shell/object-search.tsx`）在原有对象搜索之外，增加“快速创建”和“跳转”两组命令。原搜索行为不变：Enter 仍是搜索，编号检索只定位。
- 命令表与可见性规则在 `web/src/features/shell/lib/command-palette.ts`。只接 4 个已登记、已实现、且页面上已有入口的操作：

  | 命令 | 登记操作 · 档位 | 何时出现（服务器信号） | 打开的现有入口 |
  |---|---|---|---|
  | 新建任务 · 〈项目〉 | `work.task.create` · T0 | 身处该项目，且 `project-work` 成员列表里本人 `can_write === true` | 项目任务页同一个“新建任务”表单（本人填写后点“保存任务草稿”） |
  | 写状态更新 · 〈项目〉 | `work.status_update.create` · T1 | 同上 | 项目概览同一个“发布具名周报”编辑区（核对后再一次确认） |
  | 新建立项提案 · 〈品类〉 | `proposal.create` · T1 | `v1/categories` 中该品类 `capabilities.product_management === true`，每个这样的品类一条 | 立项提案页同一个“新建提案”对话框（查看创建预览后本人确认） |
  | 新建品类 | `category.create` · T1 | 至少有一个产品管理品类（与页面入口一致） | 品类列表同一个“新建品类”对话框（查看创建预览后本人确认） |

- 跳转组与侧栏同源：六个全局入口和设置对所有人可见；“品类”“立项提案”只给有产品管理权的人。
- 具名决定（T2）不进入面板。输入完整编号时不显示任何命令。界面只写“打开新建表单，本人确认后才保存”等办理方式，不出现档位枚举。
- 选中命令只是带一次性参数 `create=…` 跳到原页面，由 `web/src/features/shell/use-create-intent.ts` 打开原表单并立刻从地址移除该参数；`globalHref` 换页时也会丢弃它。面板不发任何写请求，确认步骤和服务器权限检查都在原表单里照旧发生。
- 权限信号在每次打开面板时按当前登录重新读取；任何一项读不回就少显示命令，并提示“部分权限暂未读回”，可重新读取。
- 键盘：↑↓ 选择（`role=combobox` + `aria-activedescendant`），Enter 执行选中命令，未选中时 Enter 照旧搜索，Esc 关闭。窄屏行高不小于 44px，说明文字换到下一行。

## 自动检查

| 检查 | 结果 |
|---|---|
| `command-palette.test.mjs`（7 例）：命令逐条对照 `contracts/operations.json`（已登记、已实现、档位一致、非 T2）；普通成员无快速创建、无产品管理入口；产品经理只在有权品类出现提案；项目成员只有服务器读回可写时才有任务/周报；权限只认明确的 `true`；完整编号不出命令；目标只能是站内相对地址；意图读一次即移除 | 7 通过 |
| `global-navigation.test.ts`（新增 1 例：换页丢弃 `create`） | 13 通过 |
| 受影响组件测试：`project-views`、`project-work`、`app-shell-knowledge`、`object-search` | 55 通过 |
| 前端全部 `.mjs` 测试（156 个文件） | 1898 通过，0 失败 |
| `tsc --noEmit` | 通过 |
| 改动文件 eslint | 0 错误 0 警告 |

## 浏览器验收

环境：本 worktree 用 `tools/local_environment.py create` 建的带标记独立库（容器 `pdos-next-test-20261002-602f19f0`）。建库时迁移往返在降级到 base 时失败于 `s0_0784`（“Release exception requires its exact reviewed confirmation predecessor”，与 D214 会话记录的同一问题），库停在 head，随后单独执行了种子。API 在无 Temporal 的模式下启动（⌘K 不依赖工作流）；前端 `next dev`。用 `tools/acceptance_account.py` 建了两个合成账号：产品经理（有产品管理权）和工程师（`--no-product-manager`）；用 G0 测试夹具经公开命令建了一个品类可见的合成项目“D52 合成项目”。验收后已停服务并 `destroy`，凭据文件已删除。

| 截图 | 内容 |
|---|---|
| [01](01-pm-my-work-light.jpg) | 产品经理，我的工作，亮色：快速创建只有“新建立项提案 · 汽车充气泵”“新建品类”，跳转含品类/立项提案 |
| [02](02-pm-create-category-opens-existing-dialog.jpg) | ↓↓ Enter 执行“新建品类”：到品类列表，打开原有“新建品类”对话框，地址中 `create` 已移除 |
| [03](03-pm-project-filter-task-light.jpg) | 项目内输入“任务”只剩“新建任务 · D52 合成项目”，选中行有底色 |
| [04](04-pm-task-form-opened.jpg) | 执行后打开项目任务页原有的新建任务抽屉 |
| [05](05-pm-status-update-opened.jpg) | “写状态更新”打开原有的“发布具名周报”编辑区（核对后还需确认） |
| [06](06-pm-project-dark.jpg) | 暗色主题，选中行高亮 |
| [07](07-pm-375-dark.jpg) / [08](08-pm-375-light.jpg) | 375px 暗色 / 亮色：左右 16px，无横向滚动，命令行高 51px（07 摄于去掉窄屏“跳转”说明字之前） |
| [09](09-pm-375-proposal-dialog.jpg) | 窄屏点击“新建立项提案”：打开原有“新建提案”对话框 |
| [10](10-engineer-project-light.jpg) | 工程师（无产品管理权、品类可写）：只有本项目“新建任务”“写状态更新”，无提案/品类，跳转无产品管理入口 |

另核对：输入完整项目编号时命令区隐藏、选项数为 0，Enter 只返回定位结果；控制台只有开发服务器重启造成的热更新连接报错。

## 未做 / 边界

- 只在“当前所在项目”给出项目内快速创建；不在别处选择项目后创建。
- 其余已登记且已实现的创建入口（外部等待、质量问题、变更提案、Build、验证请求、试产等）需要页内子状态或具体对象上下文，本项未接入。
- `category.create` 服务器只要求本人真人身份，界面（页面与面板）按产品管理权显示，面板沿用页面口径。
- 旁见问题登记为 D271：新建品类、新建提案等原生 dialog 贴左上角显示（与本改动无关）。
