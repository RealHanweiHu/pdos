# 小Pai 已登记来源选择与固定绑定 · 2026-10-17

接续[真实会话候选](../pai-sessions/result.md)，按指定 HTML、v1.1 §05.4–5/§05.12.4 与 P22 落实输入区的实际来源携带。本轮接通“选择已登记附件或资料 → 新工作精确绑定 → 运行读回 → 回传中断后恢复原意图”，未接管正在施工的 S4。

## 可用能力

- 输入区新增“已登记来源”。服务器按当前本人、品类、所选型号和提案权限读取真实 Artifact 头；无型号时只列品类根，有型号时列根资料和该型号资料。未生成 Artifact 的上传不伪装可用资料。
- Artifact 与 UploadedOriginal 各自版本分别显示。实际病例为资料 v1、原件 v2；选择保存固定 `artifact_id + expected_revision`，不再在提交时从最新 props 静默换版。
- 可用性实际经过既有 `source_for`、原件与安全守卫；扫描/来源条件不足的可读资料显示不可选及原因。普通 RLS 先过滤，再分页；不返回原文、定位正文、存储键或内容摘要哈希。
- 运行详情只读实际 `read_sources`，显示固定绑定与当前可读头；当前不可读则隐藏名称，版本变化分别列出。提案自动携带与手选来源不凭结果猜角色，也不把绑定宣称为已执行的 ContextSnapshot 或模型抽取。
- 新工作和继续原工作分开；继续沿用原链与原绑定。确定拒绝的新请求清理旧选择；202 后读取失败不谎称未受理；503 保留相同 body/key。刷新后的原请求单独列出原范围、来源数和固定引用，不借当前输入框的选择冒充。
- 两个独立 GET BFF 不改公共 catchall；无新增模型、迁移、权限、技能或自动重试。本人/范围/API 切换与读取失败隔离旧内容及迟到响应。

## 验证与候选

- 后端 8 项纯检查通过。6 个不同实库病例全部覆盖：首轮 2 过、4 因同一新增夹具错误失败；夹具把人工资料登记错送预览，改为该命令既有正式入口后，仅补验这 4 项通过，产品代码未变。未将两次执行写成一次完整通过。见 [首轮日志](backend-tests.log)、[补验日志](backend-recheck-tests.log)及两份 backend candidate JSON。
- 只使用已显式核对的 `127.0.0.1:64245/pdos_test`，标记 `f9048729-3f2a-4494-af75-56e1db7d743d`，实际 head `s0_0778`；本轮不迁移。原件经实际上传/登记、显式 synthetic scanner 端口和解析流程形成，扫描端口不代表真实扫描资格。
- 最终 72 项前端检查通过；3 份实际 DTO 严格解析与选定引用子集核对、13 项实际 Next BFF → API → PG 读取检查通过。见 [前端日志](frontend-tests.log)、[DTO](actual-dto-validation.json)、[实际 BFF](actual-bff-http.json)。
- 最终固定副本 350 个输入的 lint、生产构建和类型检查通过；lint 保留两条既有 `verification/contracts.js` 警告。初始构建后的真实 320px 页面发现来源面板被携带摘要挤至半宽，修正专属 CSS 后重新冻结、构建并核对。初始候选/日志以 `initial-*` 保留，最终见 [candidate](candidate.json)。
- 实库检查涵盖固定来源、幂等、撤回后拒绝新运行、本人/跨租户/当前 Product 与 Proposal 权限收窄、分页游标、GET 零写；实际 SQL 不选择原文、locator/parse manifest、Run 结果及客户身份正文。

实库候选之后，其他 S4 施工修改了 `manufacturing_trials/native_statistics_owner.py`、`native_service.py`、`native_material_owner.py` 与 `manufacturing_baseline/publication_service.py`。本轮 kernel、来源守卫及前端 350 个输入仍与对应候选一致；四项 S4 增量不在本轮通过声明内，未重复执行其验证。见 [最终范围核对](final-audit.json)。

## 实际页面与恢复

普通非 PM 合成属主登录真实本机 API，无响应代理。选择两份品类根资料后实际 POST 已受理，再由限定测试包装层仅丢弃第一次 202 回传并返回 503。刷新只 GET、不自动 POST；本人点击“重试原请求”后，以原 body/key 回到同一 Run `4ca55bfe-e98a-42f8-b7a2-7a12ff16bbc2`，两个固定版本正确读回。

Session、Run、受理事件各从 1 → 2，只有一个新运行；工具/输入仍为 0，业务审计/回执/Outbox/请求键仍为 7/7/7/5，Artifact/Original 仍为 3/2。运行保持 queued，模型调用 0，无执行结果或资格声明。计数脚本首遍把事件表名称误写为 `agent_events`，随后修正为实际 `agent_run_events` 并只读补核其恰增一条；没有更改业务数据以适配断言。见 [前后计数](browser-after.json)、[刷新前重试截点](refresh-before-retry.json)和请求日志。

1280×900 / 320×800 亮暗核对通过；320px 文档宽 320，来源面板宽 278、复选框 16×16，实际绑定面板宽 296，完整标识展开不溢出。关闭再打开保留同一 Run。截图在 `output/playwright/pdos-pai-sources-20261017/`：`final-selected-*`、`final-bindings-*`为最终候选；`actual-response-lost.png` / `actual-refreshed-original-intent.png`记录恢复过程，`initial-320-light-before-width-fix.png`保留修复前。几何与身份见 [页面记录](browser-observations.json)。

## 余项与边界

尚未接输入区新文件上传/拖入、语音、手动技能和完整对象范围选择；个人入口仍不能绑定业务资料。会话改名/置顶/归档恢复、真实阶段/健康度/冻结点、P18 具名更新、完整分诊承诺及部分项目摘要继续保留。上述资料读取与绑定不是内容抽取、真实模型/凭据/出站资格、生产启用或 S1–S5 正式验收；P13 性能暂缓及既有失败不改。自动续工继续。
