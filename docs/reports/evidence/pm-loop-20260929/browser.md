# 产品经理闭环 · 页面走查与追溯修复

2026-09-29，0404工作树，接续[RFQ原件到需求草稿](rfq.md)。本次完成合成业务链的页面走查和三处界面修复，不代表真实研究、模型资格或原N项已全部验收。

## 环境与方法

使用独立 `127.0.0.1:57433/pdos_test`（Docker `pdos-pytest-postgres`，head0404），API8124、网页3104。禁用配置文件回退，没有读取业务 `.env`、触及57432存续联验库或更改既有3000/8000服务。初次8021端口启动失败，改用8124后恢复；初次登录503来自该启动失败。

在已核对为空的临时库调用既有 `test_product_manager_loop_api.test_research_to_released_definition_matrix_and_roadmap_without_project` 合成接口场景，执行全部断言并留下样本供浏览器检查；本次没有重复运行会清理该库的pytest夹具。样本包括研究、竞品、市场、三方案、四类实验、策略、五专业合成审核、发布定义及路线图。此处的署名与批准均为测试数据，不是真人业务审批。[样本标识](../../../../output/playwright/pm-loop-0404/seed.json)与[准备结果](../../../../output/playwright/pm-loop-0404/seed.log)保留。

原件存储使用本地文件适配器（`/tmp/pdos-pm-browser-files-0404`），浏览器通过真实网页代理/HTTP上传XLSX字节、服务端真实解析；没有验证MinIO/OSS集成，没有调用真实模型。网页使用完整构建后的Next服务，Playwright CLI驱动，未向外部账户发送数据。

## 已观察到的业务结果

| 路径 | 本次证据与边界 |
|---|---|
| 客户原件→解析→选择片段→准备 | 上传合成 `customer-rfq.xlsx`，保留 `sheet:Customer RFQ,rows:1-3` 和A1～D3坐标；120kPa、25℃、验收方法待客户澄清保持原文。核对一段原文成功。能力SHADOW时显示未开放与真实资格待完成，分析按钮禁用；没有为了走查解除资格守卫。[页面](../../../../output/playwright/pm-loop-0404/rfq-scope-light.png) |
| 研究/专业补证→原快照 | 研究结论与专业办理记录均能展开原引用版本正文、snapshot ID及完整摘要。正文保留失败实验、不同单位/工况和“不是业务实测”说明。[页面](../../../../output/playwright/pm-loop-0404/research-source-fixed-light.png) |
| 竞品→市场 | 浏览器选择A/B两项并请求比较，100kPa/25℃与0.1MPa/0℃显示口径不齐、方法未记录；价格未知，不自动排名。细分页TAM/SAM/SOM及缺少参数仍为未知。[比较快照](../../../../output/playwright/pm-loop-0404/competitor-comparison.txt)、[页面](../../../../output/playwright/pm-loop-0404/competitor-conditions-light.png) |
| 机会/实验→策略 | 三方案存在；四维实验分别显示三项证据不足、一项被证伪，失败结果未删除。策略和原定义可读，沿用合成场景的具名专业约束与发布记录；未在浏览器重新办理全部签核。 |
| 原发布定义→派生 | 实际点击派生并创建 `PM-BROWSER-DERIVED-0404`，返回定义 `e778f87a-50bd-42a1-b5cd-69b57dafdba5`。父定义原版引用保留，新版为草稿，规格重新确认、五专业审核缺项可见。[页面](../../../../output/playwright/pm-loop-0404/derived-definition-light.png) |
| 定义→矩阵→路线图 | 当前发布矩阵只展示原发布型号，派生草稿未被冒充为已发布；打开指定产品路线图，显示当时定义v1和原定义链接、具名负责人、日期未定及缺实际资源条件。计划不表示实际完成。[最终页面快照](../../../../output/playwright/pm-loop-0404/roadmap-final.txt) |

## 本次修复与验证

1. 研究结论和专业办理卡原先只显示来源名称/摘要，不能直接核对原快照。新增共用正文入口，读取确切snapshot并比对摘要；历史来源不在最近列表仍可读取，返回版本不符则拒绝显示为该引用。
2. 产品工作区编号表单的旧HTML pattern在当前浏览器的`v`规则下无效。统一转义连字符。实际浏览器确认 `bad/name` 的patternMismatch为true，`PM-BROWSER:0404_test.1`为false；没有提交额外空间。[非法编号](../../../../output/playwright/pm-loop-0404/pattern-invalid.log)、[合法编号](../../../../output/playwright/pm-loop-0404/pattern-valid.log)。
3. 矩阵外层fieldset默认最小宽度将390px页面撑到970px。为相关fieldset设置最小宽度0、查询按钮允许换行；重新构建后无临时样式注入的页面宽度为390px，920px表格只在324px的自身容器内滚动。[测量](../../../../output/playwright/pm-loop-0404/layout-mobile-final.log)。

[产品工作区34项交互回归](../../../../output/playwright/pm-loop-0404/ui-regression.log)通过，包含新增的原版本读取和不匹配拒显场景；布局仅作低风险样式修复，没有新增镜像测试。受影响ESLint、TypeScript、最终[完整构建](../../../../output/playwright/pm-loop-0404/build-layout.log)及diff检查通过。最终矩阵/路线图导航控制台0错误0警告，[日志](../../../../output/playwright/pm-loop-0404/console-final.log)。

已检查1200px桌面原件/研究/竞品/派生定义，以及390×844路线图亮暗主题：[窄屏亮色](../../../../output/playwright/pm-loop-0404/roadmap-mobile-light-final.png)、[窄屏暗色](../../../../output/playwright/pm-loop-0404/roadmap-mobile-dark-final.png)。这不是所有页面/状态的完整尺寸矩阵覆盖。

[当前源文件摘要](browser-source-sha256.json)覆盖前序RFQ候选文件和产品工作区组件；[候选差异](../../../../output/playwright/pm-loop-0404/candidate-diff.json)中前序登记的后端文件无漂移。0404后端既有验证沿[RFQ记录](rfq.md)保留，不将历史分散通过当作本候选正式联合出口。DC-13冻结摘要保持 `7456c277eaab892f840f06d866396f47f7b8135d70e24ce5d842037be65a3af5`。

## 剩余工作与下一步

- 继续修复导航状态：当前工作台切换分区仅更新页面状态，URL仍保留原tab，刷新可能回到旧分区；产品线深链与AI资料准备的默认范围也需对齐并验证。这是后续明确的独立建设项，不需要等待真实模型资格。
- 当前浏览器覆盖原件输入、准备失能、业务读取、原文追溯、派生创建和矩阵路线图；AI候选编辑/登记、完整专业签核/发布/替代与异常恢复仍需按适用范围补页面证据。T1接口原子性/幂等已在前序测试验证，不能因此宣称浏览器也全部完成。
- 真实品类研究、真实来源采集/provider、八项模型能力逐项评测、真实角色试用与正式联合出口未完成，资格未授予。RFQ“四类”名称仍待用户提供或定位原设计，本次不自行定义。
- 未部署、外发、git push或写入golden-case；原N项及P/Q状态不变。本次8124/3104服务和浏览器已结束，临时库及原件目录保留合成样本。若后续复用样本走查，不得同时运行会清库的repo测试；需要测试时先按需保留样本。
