# 项目 Builds 真实轮次与固定测试摘要 · 2026-10-17

接续[竞品细分候选](../competitor-segments/result.md)，按指定 HTML 的项目工作区 Builds 标签、v1.1 §01.6/§05 与 P15–P20/P22 落实。此次只改独立项目 UI 与读取层，不改领域命令、公共 BFF、模型或迁移。

## 可用能力

- 打开 Builds 才读取本项目轮次；人明确选择后，再复读轮次权限/版本并读取对应 Build 测试结果。固定工程与制造配置、原项目版本、计划数量字符串、计划窗口、前轮引用与验证目标保留。计划已登记不冒充实际开工，未从排序猜测“下一 Build”。
- 只采用服务器 current_by_run/current_by_request 的精确版本索引。Run 固定请求版本与请求当前版本分列；当前 Run 可以保留同依据的历史 Run 判定。数值判定、具名复核与处置独立，不汇总成整轮通过。
- 展开显示原时间/时区/微秒、测量原值/单位及具名结论；完整记录进入原工作台，未暴露全量内部 JSON。链接保留品类、型号、项目、Build 与办理步骤，使用原生导航。
- 身份、品类、型号、项目、API 或刷新变化立即隐藏旧资料；取消订阅阻止迟到响应恢复旧内容。权限、来源或固定版本失败隐藏旧轮次与结果；503 独立结果失败不伪造空读集。驾驶舱任务风险读取失败不再显示假零。

## 验证与候选

集中运行 66 项前端读取/状态检查通过（49 读取层、17 组件/项目视图），见 frontend-tests.log；最后将覆盖计数明确为“已登记/尚缺测量记录配对”，避免原报告明确缺值时被误读为完整原值，9 项受影响组件复验通过（与初轮重叠不累加），见 frontend-wording-check.log；实际四阶段 DTO 与同一冻结读取器相容，见 dto-contract-check.*。首次成功构建与改前截图保存在 initial-before-count-wording/，最终 322 输入隔离候选 lint、webpack 生产构建、类型检查通过，保留 verification/contracts.js 的两条既有 warning，见 candidate.json 与各日志；Geist 采用已缓存字体，未外部取字体。

显式 TEST_DATABASE_URL，经容器标记核对的 127.0.0.1:64245/pdos_test，marker f9048729-3f2a-4494-af75-56e1db7d743d、head s0_0776：3 项实际命令→PG→HTTP 检查全部通过，见 backend-tests.log/backend-candidate.json。覆盖同型号两项目隔离、精确数量/双配置、其他租户/品类/项目拒绝、父型号读取权限收窄，以及以下真实保存链；各阶段 GET 前后闭环表计数不变。

| 实际链状态 | 当前 Run | Run 固定请求 / 请求当前 | 保存的数值判定 | 测量记录配对 / 尚缺 |
|---|---|---|---|---|
| 开测，未回结果 | v2 | v4 / v6 | 无 | 0 / 2 |
| 部分返回 | v3 | v4 / v7 | indeterminate，绑定 Run v3 | 1 / 1 |
| 最终返回 | v4 | v4 / v8 | pass，绑定 Run v4 | 2 / 0 |
| 具名专业复核 | v5 | v4 / v8 | 保留同依据 Run v4 的 pass | 2 / 0 |

实际 Next BFF→FastAPI→PG 的 9 项只读核对通过，逐项见 actual-bff-http.json。第一次脚本误认为额外 project_id 必须返回 422；现有 BFF 会忽略它，复核随机其他项目参数仍返回相同显式 Build 的原响应；未改 BFF，初始失败和修正边界见 initial-http-assertion.md。最终计数与初轮重叠不累加。

## 浏览器核对

浏览器使用上述实际 API/PG 的普通非产品经理项目属主，非响应代理。另起的本机 API 只允许唯一既有 QA 会话与 GET/HEAD/OPTIONS；拒绝全部领域写入。有限合成 issuer 配置复用同一测试事实身份、scope、原决定和指纹，只让原证明在独立进程可读；不导入事实、不增权限、不轮换 issuer、不取得真实资格。原报告读取使用该测试原字节存储。

实际页面核对项目列表→显式选择→当前 Run v5/固定请求 v4/当前请求 v8→历史判定 v4→原值与具名专业结论。原生链接进入同项目测试结果工作台，可显式选择相同 Build；普通成员的 Run 办理选项仍按原专业权限禁用，没有尝试提交。返回项目并刷新后旧选择与结果同步隐藏，须再次显式选择。

1280×900 桌面与 320×800 亮暗主题已核对；320px 文档宽 320，两个面板各 288，800px Build 表在 286px 容器自身横滚；展开测量表 550px 在 240px 容器内横滚。原时间与来源身份展开无页面横向溢出。本机预览截点共 49 次领域 GET、零非GET，包含启动/BFF核对与浏览器读取；观察/请求计数/输入校验见 browser-observations.json 与 final-audit.json。

图片目录：output/playwright/pdos-project-builds-20261017/。final-desktop-light.png / final-desktop-dark.png 为轮次与固定配置，final-results-desktop-light.png 为原值与具名结论，final-320-* 为窄屏/表格横滚/展开，initial-before-count-wording/final-refresh-cleared-selection.png 为刷新隐藏旧选择，initial-before-count-wording/final-original-workbench.png 为真实原办理入口（计数措辞修正前的同一流程）；最终计数文案已再核对桌面和320px双主题。

## 剩余与边界

Build 执行优先级、项目实际样件去向/试模汇总、完整工程制造准备与评审资料尚未汇入摘要。阶段模板、门禁健康度规则、冻结点、具名 ProjectStatusUpdate、完整分诊/承诺、持久 Conversation 归档恢复及附件语音继续按自身前置续建。没有用计划记录猜测执行阶段或整轮通过。

S3/S4 已有施工者占用公共文件，本聊天不重复接管；S1/S2/S3 正式验收、P13 性能暂缓和既有未解决失败继续保留。本次合成数据与读验证不授真实资格、不构成正式阶段或生产验收；模型调用、迁移、性能采样、push、部署、生产和真实出站均为零。自动续工保持启用。

最后源码对照：本轮 UI/读取及实际 Build/结果领域读取模块与冻结候选一致；并行 S4 后续改变公共 BFF（新增 manufacturing-publications 分支，未改本轮 Builds/results 分支），以及 pdos_next/service.py、pdos_next/models.py、pdos_next/contracts.py、pdos_next/command_handlers.py、pdos_next/domain/professional_authority/service.py；新文件见 final-audit.json。公共 BFF 差异保存 concurrent-bff-delta.diff。最终322输入通过仅指本轮冻结候选，不声称覆盖这些之后的 S4 增量；对应施工负责汇合验证，本轮不追赶重跑其施工。
