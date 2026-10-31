# 综合本地预览 · 2026-10-22

**入口已于 2026-10-23 按用户纠正改为统一产品工作台**：当前使用一个账号和正式产品导航，不再显示下述九案例选择器。最新行为、范围和验证见 [统一产品预览](product-mode/result.md)。下文保留首次案例导览的历史证据。

已提供 [综合预览](http://localhost:57859/preview)：从一个入口选择 9 个已有业务案例和 22 个列名演示身份，进入实际业务页面查看持久化合成记录；页面可返回切换场景/身份。进展直接读取唯一整合清单，不另造完成率。

## 可体验内容

| 场景 | 已核对的实际内容 |
|---|---|
| 品类提案与小Pai | 原 S1 提案、真实起草与本人确认历史、G0 项目承接的副本 |
| 工作、承诺与计划 | 1 项人工任务、已应用计划 v1 的 2 项任务，以及办理入口 |
| 双批次试制与验证 | 1 个 Build、2 批实物、2 个样品/Run；品质身份可看 10.0000 mm 原值、23°C 干燥工况、评审及处置历史 |
| 问题与整改 | 1 个问题的 7 个版本及失败范围；整改证据当前受原件安全状态守卫阻断 |
| 制造准备与试产 | 3 份制造文件、已有发布和试产记录、固定基线与 Build |
| 发布与外部交接 | 固定发布包、工程/制造分别决定、交接和 6 条合成外部回执 |
| 限定放行与例外 | 发布包版本、4 条例外决定及撤回记录 |
| 现场反馈与变更 | 现场振动反馈、版本历史、变更/验证/关闭入口及已有完成记录 |
| 经验与知识复用 | 4 个经验候选、1 条当前规则及其 2 个版本 |

案例来自不同合成流程，不冒充同一产品连续完成全部生命周期。计数为准备时快照，业务页面读取当前数据库。演示账号有效至 2026-10-29；专业事实、资格和原件安全状态的原有效期不延长。

## 环境与限制

- 网页 `localhost:57859`、API `127.0.0.1:57858`。localhost 隔离原 S1 的 127.0.0.1 会话；原 `59650` 演示和本人确认数据保留。
- 独立 `127.0.0.1:57358/pdos_test`，marker `c351c0ca-b874-49b9-bf1b-44c3ad150aaf`，容器 `pdos-comprehensive-c351c0ca`，复制时 head `s0_0813`。克隆前核对来源/目标/标记，来源库未改写。
- 仅在副本为列名合成身份准备短期会话、续接同范围访问；未扩大 can_write 或专业资格。首次工作案例的写权限已撤销，计划创建被拒且零写入；随后改用已有正向案例及实际计划，没有绕过守卫。
- 新模型执行显式关闭，实际 POST 返回 `503 MODEL_UNAVAILABLE / PREVIEW_MODEL_DISABLED`。未启动外发/模型 Worker，未增加真实调用、预算、技能启用或 T0 资格。全岗位小Pai自动接续仍在建设中。
- 部分专业操作因原资格期限、原件或缺少当前材料只能回看。质量整改读取返回 `409 SOURCE_UNAVAILABLE / ORIGINAL_SECURITY_BLOCKED`，需重核原件安全状态；页面已标明，未算通过。外部回执含原有失败状态，不代表真实外发或全部成功。
- 组合资源、完整阶段门禁、部分驾驶舱汇总及各阶段正式验收仍按唯一清单保留；综合预览不等于全功能完成。

## 验证与证据

- 新会话入口 5 项测试通过：本机/同源、列名场景身份、禁止任意跳转、实际身份核对、失效/服务不可用及私有凭据不序列化。当前进度解析 3 项测试通过。
- 前端类型检查、受影响 lint、启动器 Ruff、diff 空白检查通过。末次修改仅收紧导览间距，已截图复核。
- 22 个身份经普通鉴权接口均读取到对应目标项目，见 [身份及质量结果](roles-and-quality.json)；这不冒充完整权限回归。
- 九场景主要页面实际进入；计划、试制原值、制造文件、固定包/回执、现场反馈、知识候选均有可见记录。各页面 AX 记录在同目录对应 `.txt` 文件。
- 1280×720 导览亮暗主题已核对，九场景可见：[亮色](preview-light.png)、[暗色](preview-dark.png)。本轮未声明窄屏、生产构建、全后端回归或迁移往返。
- 初始探测的错误路径/缺参已按实际接口修正；早期 JSON 保留原结果，不计作通过。业务页既有 React 重复 key `0` 开发警告仍保留，不声明全站控制台无警告。

## 恢复

私有状态在 `pdos-next/.local/comprehensive-runtime-20261022.json`、`comprehensive-preview-20261022.json`；克隆备份为同目录 `comprehensive-source-20261022.dump`。不提交凭据或备份。公开 [案例目录](catalog.json) 不含 Token。

在仓库根目录分别启动两个进程，启动器先核验容器/端口/marker，使用专属 `.next-comprehensive` 输出，不重置数据：

```sh
pdos-next/server/.venv/bin/python pdos-next/tools/comprehensive_preview.py api --runtime pdos-next/.local/comprehensive-runtime-20261022.json --catalog pdos-next/.local/comprehensive-preview-20261022.json
pdos-next/server/.venv/bin/python pdos-next/tools/comprehensive_preview.py web --runtime pdos-next/.local/comprehensive-runtime-20261022.json --catalog pdos-next/.local/comprehensive-preview-20261022.json
```

本交付为共享工作树上的本地候选；本轮源码范围见 [source-manifest.json](source-manifest.json)。不覆盖同期改动，不声明已提交或推送。
