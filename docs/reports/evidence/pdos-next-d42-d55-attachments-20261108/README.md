# D42 / D55 小Pai 附件入口、DOCX、拖入、照片登记（2026-11-08）

分支 `claude/charming-almeida-2d1941`，基点 `pdos-next/design-v1.1` 的 `38f5a024`（含 M1）。本地提交，未推送。个人聊天携带附件按用户 11-08 选的 B 案实施，决策记录见[确认稿 P91](../../../design/2026-10-08-pdos-next-design-confirmation.md#p91)。

## 结论

- 个人聊天：输入框“附件”入口可选本人当前可读的已登记原件（跨品类），也可选存放品类后上传新文件；拖入输入框即打开上传并预填；本人确认后走原有原件登记→扫描→解析路径，可用后自动加入本次携带；已携带资料以小标签显示、可移除；续问沿用上一轮服务器已绑定的附件并逐份重新核对，也可再加附件。
- 品类小Pai：拖入与“上传后自动携带”同样可用，来源选择器刷新时保留仍可用的已选版本。
- DOCX：隔离解析器容器解析正文段落和表格行；照片（JPG/PNG/WebP/HEIC）只登记、不做 OCR，派生一行登记文字可被引用。
- 历史栏：随 1000px 断点和整页/侧栏状态更新。
- 服务器边界（P91）：逐份核对本人以人员身份、来源品类成员资格、小Pai 在该品类的读取授权、受众、精确版本和原件安全；运行记录 `versions.personal_sources` 记下每份来源的品类与数据类别；数据库守卫条件放行；权限收回后运行隐藏、续问 403。

## 浏览器整链（本地预览，合成数据，未调用真实模型）

环境：隔离 `pdos_test`（`tools/local_environment.py create`），独立开发账号租户 `809765df…`（两个品类：汽车充气泵（合成）、自行车打气筒（合成）），API 关闭 Temporal 工作流。上传后的扫描/解析由 `e2e-scripts/process_uploads.py` 调用与 worker 相同的函数完成（真实 ClamAV 容器 + 按新源码重建的解析器容器）；运行由 `e2e-scripts/execute_run.py` 执行：注册的内核图、工具、来源读取、引用账本、提取子任务与服务器答案全部真实，只有模型换成脚本客户端（不出站）。

| 截图 | 内容 |
|---|---|
| `01-light-1280-attachment-panel.jpg` | 个人聊天附件面板：存放品类、上传新文件、跨品类已登记原件 |
| `02-light-1280-three-carried-chips.jpg` | 已有原件（自行车打气筒）+ 拖入的 DOCX + 选择的照片，三枚小标签 |
| `03-light-1280-send-refused-before-fix.jpg` | 修复前：带原件的来源被扫描门控误判（见“过程中修的问题”①） |
| `04-light-1280-run-saved-carrying-3-from-2-categories.jpg` | 运行已保存，用户消息下“携带 3 份资料 · 来自 2 个品类”（读自服务器运行记录） |
| `05-light-1280-answer-cites-3-sources.jpg` | 回答引用 3 份来源：照片登记行、售后记录、DOCX 正文行 |
| `06-dark-1280-follow-up-composer-chip.jpg` | 暗色，续问输入框里的附件小标签 |
| `07-dark-1280-follow-up-carries-2-sources-cited.jpg` | 暗色，新对话 2 份跨品类资料；不加附件的续问自动延续 2 份并引用 |
| `08-dark-375-empty-history-closed.jpg` | 375px 暗色，历史栏默认收起 |
| `09-dark-375-attachment-panel-chip.jpg` / `10-light-375-attachment-panel-chip.jpg` | 375px 附件面板与小标签，无横向溢出 |
| `11-light-375-history-open.jpg` | 375px 展开会话列表 |
| `12-light-1280-category-chat-dropped-file-carried.jpg` / `13-light-1280-category-run-saved.jpg` | 品类小Pai 拖入 Markdown → 自动成为固定来源 → 运行受理 |

其他核对（脚本读页面状态）：历史栏 1280→900→1280 依次为展开/收起/展开；375px `scrollWidth` 不超出视口；网络请求全部 200（503 只出现在 API 重启窗口）。`e2e-run-receipts.txt` 是五条运行的回执摘要，`e2e-originals.txt` 是四份上传原件的状态（第一份 DOCX 扫描 `rejected` 是我脚本漏装读取引擎造成的，见下文②，保留作失败展示）。

## 过程中修的问题

1. 扫描门控用“当前会话的品类”重算扫描绑定，个人会话没有品类，带原件的来源一律判为失效（`SOURCE_OR_ACCESS_CHANGED`）。改为会话未绑定品类时按原件自己的品类计算（`originals/security.py` 一行，品类会话不变），并补 DOCX 原件作为个人来源的 PG 用例。
2. 验收脚本最初没像 worker 那样调用 `configure_lifecycle` 和装配安全运行时，导致第一份 DOCX 扫描被拒、运行准备时来源判为不安全；补齐后与 worker 一致。属于验收脚本问题，不是产品缺陷。
3. 个人续问原先不沿用上一轮附件（个人运行的“资料条件”被当作讨论里的固定而跳过），导致旧工作状态无法发送（`context_incomplete`）。改为只延续上一轮服务器已绑定的附件，讨论里另行固定的检索结果仍不当作读取集。
4. 前端：`inputSourceReference` 严格校验字段，个人来源多出的 `category` 会被拒（单元测试发现）；附件面板重开时恢复的旧上传会被再次自动携带；新对话没有清空上一会话的附件——均已修。

## 自动化验证

- 服务器单元：解析器与预检 `tests/originals/evidence_processing` + `evidence_security` + `security_runtime` 159 通过（含 DOCX 段落/表格、宏/外链/实体/压缩炸弹拒绝、照片头校验）。
- 服务器 PG（隔离 `pdos_test`，显式 `TEST_DATABASE_URL`）：`tests/agent/kernel/test_personal_run_sources_pg.py` 11 条（跨品类绑定与回执、DOCX 原件作为个人来源、个人来源列表、无权品类 403、小Pai 无授权品类 403、跨租户 403、AI 身份代绑被拒、伪造回执被数据库拒绝、引用作答与权限收回后隐藏、续问延续与重绑、带来源的个人运行写业务对象被拒）全部通过；`tests/originals/test_durable_evidence.py` 含 DOCX/照片上传→扫描→解析→登记来源；受影响套件结果见下节。
- 迁移（分支上，当时 down 为 s0_0855；11-08 集成时编号不变、down 改为 s0_0859）：s0_0855 ↔ s0_0860 降、升、降、升通过；升级后三条函数定义与审阅文本逐字一致。空库 head→base 在 s0_0784 失败是既有问题 D260，与本改动无关。
- 合同校验 `tools/validate_contracts.py` 通过。
- 前端：`tsc --noEmit`、`eslint` 0 错误；全部 1893 个 `.mjs` 测试通过。
- 解析器镜像：`containers/evidence-parser/build.py` 按新 `parsers.py` 重建，真实容器解析 DOCX 与 PNG 冒烟通过。

## 受影响 PG 套件

- 范围：`tests/originals`、`tests/agent/kernel`、`tests/agent/memory`、5 个企业检索 PG 文件、立项前证据命令、个人视图。结果 3212 通过、98 失败、27 错误、21 跳过（1 小时 10 分）。
- 归因：把这 125 个失败/错误用例在同一测试库上分别用基点 `38f5a024` 代码和本分支代码复跑，两边都是 97 失败、27 错误、1 通过，失败集合逐条相同；只在本分支失败的为 0。多出的 1 条是延迟阈值用例，两边复跑都通过，属计时抖动。27 个错误是 `test_registered_snapshot_reads.py` 的既有夹具问题（集成记录已注明），其余与集成记录和 D27/D242 里的既有失败同类。明细见 `pg-affected-attribution.txt`。
- `tests/core` + `tests/test_layout.py`：116 通过、4 失败（`test_business_audience_summary`、`test_category_capabilities_projection`、`test_category_source_consumers`、`test_trusted_source_work::test_migration_matches_orm_and_test_guard`），4 条在同一测试库上用基点代码复跑同样失败；前两类之外的两条集成记录已列为既有问题。
- 大套件启动后又改了扫描绑定、续问延续和小Pai 授权检查，因此在最终代码上另跑：续问、上下文纠正、会话权限、M1 记忆与个人来源 194 通过；原件生命周期与目录 142 通过；个人来源与原件整链 29 通过。

## 未验证 / 余项

- 未调用真实模型；回答由脚本客户端产生，只验证了服务器绑定、读取、引用和界面展示。
- 未在带 Temporal worker 的预览里走“上传→自动扫描→自动携带”（D275）。
- 原件生命周期图未覆盖个人运行的来源引用（D274）。
- `contracts/openapi.json` 未重导出新接口 `GET /v1/personal/agent-input-sources`。
- D42 的两项待复现风险未做（相关文件在主工作区另一线程）。
