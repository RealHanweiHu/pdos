# UX10 三页前端验证记录

- 最终冻结时间：2026-09-08 20:55 UTC（替代 20:49 UTC 中间版）。
- 范围：My Work、Project Workspace、AI Review 首屏的数据加载与可操作内容布局；未修改 AI 测试项对话或 source 选择逻辑。
- 本记录仅证明前端自动化回归与静态检查通过。生产构建、真实页面 30 次采样、P95 与桌面/手机首屏可见性由主任务独立验证，不由 jsdom 测试推断达标。

## 行为变化

1. AI Review 在身份确认后并行获取项目、Finding、摘要与一次 `/api/ai/risk-candidates` 汇总候选，按 `project_id` 分组，取消逐项目候选请求。摘要/候选有独立加载、错误和重试状态；主 Finding 内容不等待附加请求。候选和归档默认折叠，计数与批量动作保留；候选确认后仍保留撤销入口。
2. My Work 身份确认后并行加载个人待办与通知。通知失败不阻塞待办，通知独立重试；默认折叠通知列表，完整未读数始终可见。主页面只在实际待办请求成功后进入 ready。
3. 两页都使用主请求与附加请求序号，整页重试会立即使上一轮附加请求失效；旧成功或失败响应晚到均不能覆盖新状态。
4. Project Workspace 已选择项目时折叠完整项目导航，保留切换入口；仅 overview 获取活动，仅 overview/work-items 获取任务、问题、风险；其他深链标签不提前读取这些数据。空活动结果也会缓存，活动错误可重试，外部成员不发内部工作项/活动请求。
5. AI Review 移动端将所选 Finding 详情放在队列之前，队列限高滚动；长说明默认三行且可展开全文。桌面保留队列与详情两列。页面使用可复用日期格式器与项目映射减少列表重复计算。

6. 中间版真实浏览器反馈暴露移动导航、筛选占高与桌面接受按钮超出视口，最终版继续修复：手机导航默认仅显示当前入口与展开按钮，展开后全部权限内入口可达，支持 Enter/空格、Tab、Escape 收起回焦点；点击链接后收起。Review 手机类型筛选单行横向滚动，按钮保持键盘访问；桌面详情最大高度为 `min(700px, calc(100svh - 20rem))`，保留内部滚动与底部操作区。最终几何效果仍由主任务重建与重新采样确认。

## 自动化验证

执行目录：`web`。不运行全量生产 build，以免干扰主任务性能采样。

```sh
node node_modules/vitest/vitest.mjs run src/components/workspace-shell.test.tsx src/components/my-work src/components/ai/ai-review-inbox.test.tsx src/components/ai/review-inbox-extras.test.tsx src/components/ai/ai-risk-candidates-api.test.ts src/components/projects/project-workspace.test.tsx src/components/projects/project-workspace-tabs.test.ts src/components/dashboard
```

结果：**10 个测试文件、125 项测试全部通过**。最后一次执行开始于本地 13:55:16，用时 7.20 秒，退出码 0。

覆盖身份只请求一次、多个项目仅一次候选聚合请求、并行与独立加载、主数据未就绪不报 ready、错误与独立重试、旧附加请求成功/失败晚到隔离、200 条通知折叠但保留动作、75 候选/25 归档折叠与展开、批量确认后撤销、长说明展开、25 项目折叠导航、无关标签不预取内部工作数据、外部身份限制、导航收起/展开时的可访问链接集合和权限过滤、键盘操作与回焦点、完整筛选按钮键盘可达，以及原有 Finding 接受/应用的两个独立人工动作。

```sh
node node_modules/eslint/bin/eslint.js src/components/workspace-shell.tsx src/components/workspace-shell.test.tsx src/components/my-work src/components/ai/ai-review-inbox.tsx src/components/ai/ai-review-inbox-view.tsx src/components/ai/review-inbox-extras.tsx src/components/ai/ai-review-inbox.test.tsx src/components/ai/review-inbox-extras.test.tsx src/components/ai/ai-risk-candidates-api.test.ts src/components/ai/ai-api.ts src/components/projects/project-api.ts src/components/projects/project-workspace.tsx src/components/projects/project-workspace-view.tsx src/components/projects/project-workspace.test.tsx src/components/projects/project-timeline.tsx
node node_modules/typescript/bin/tsc --noEmit -p /tmp/pdos-dashboard-tsconfig.json
```

结果：均退出码 0。20:49 UTC 首批文件 lint 通过，20:55 UTC 对本轮修改的 workspace-shell 与 Review view/test 再次执行 lint，并重跑类型检查。临时类型检查配置继承 `web/tsconfig.json`，设置 `incremental: false`，包含 `next-env.d.ts` 和全部 `src/**/*.ts(x)`，排除 `node_modules` 与历史重复 `**/* 2.*` 文件；未包含 `.next` 中历史重复生成声明。主任务另行对隔离快照执行正式构建/类型检查。对本次文件执行 `git diff --check`，退出码 0。

## 真实浏览器测量入口

| 页面 | Ready / 可操作内容判据 | 附加状态 |
| --- | --- | --- |
| `/my-work` | `[data-testid="my-work-ready"]` 出现，并检查 `section[aria-label="任务"] a` 中已知真实任务可操作且进入 viewport | 通知可以仍在加载或明确报错；不能将标题出现解释为通知已完成 |
| `/projects?project=<UUID>&tab=overview` | `#project-tab-overview[aria-selected="true"]`、`[data-metric="task"]` 等真实计数与“编辑项目”动作 | `section[aria-label="项目阶段 Timeline"][data-state="ready"]` 表示活动已完成；独立错误/重试可见 |
| `/projects?project=<UUID>&tab=work-items` | `#task-title:enabled` 与已知任务的查看详情按钮 | 不应请求项目活动 |
| `/ai-review?finding=<普通待审Finding UUID>` | `[data-testid="ai-review-ready"]`、`article[aria-label="Finding 详情"] h2` 的已知标题，以及名称以“接受建议”开头的已启用按钮；实测按钮无需页面滚动即进入 viewport | `[data-testid="review-extras"][data-state="loading"/"ready"/"error"]` 独立观察 |

折叠入口保留计数：“展开通知”、“切换项目（N）”、“展开候选（N）”、“展开归档（N）”。首屏可见性必须使用实际元素边界和截图验证，不能仅检查上述 class 或标题。

本轮未扩展 Project Workspace 初次主请求失败后的整页重试恢复原始深链逻辑，不声明该既有路径已验证。

## 冻结文件清单

```text
web/src/components/my-work/my-work.tsx
web/src/components/my-work/my-work-view.tsx
web/src/components/my-work/my-work.test.tsx
web/src/components/projects/project-api.ts
web/src/components/projects/project-workspace.tsx
web/src/components/projects/project-workspace-view.tsx
web/src/components/projects/project-workspace.test.tsx
web/src/components/projects/project-timeline.tsx
web/src/components/ai/ai-api.ts
web/src/components/ai/ai-review-inbox.tsx
web/src/components/ai/ai-review-inbox-view.tsx
web/src/components/ai/ai-review-inbox.test.tsx
web/src/components/ai/review-inbox-extras.tsx
web/src/components/ai/review-inbox-extras.test.tsx
web/src/components/ai/ai-risk-candidates-api.test.ts
web/src/components/workspace-shell.tsx
web/src/components/workspace-shell.test.tsx
```

以上 17 文件相对只读基线 `/private/tmp/pdos-ux10-20260908` 的最终补丁输出到 `/private/tmp/pdos-ux10-frontend.patch`，对应当前源文件 SHA-256 清单为 `/private/tmp/pdos-ux10-frontend.sha256`，供主任务向隔离快照应用并记录实际运行版本。
