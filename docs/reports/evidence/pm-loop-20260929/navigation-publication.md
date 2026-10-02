# 产品经理闭环 · 导航、定义发布与父版更新

2026-09-29（浏览器日志UTC为9月30日），0404工作树，接续[页面走查与追溯修复](browser.md)。本次继续第一开发主线，未改变原N项勾选或正式出口。

## 修复

- 市场空间和分区改为从地址栏读取；选择空间、分区或研究/AI产品线写入浏览器历史。刷新、前进/后退保持同一导航状态，切换空间清除旧产品线、对象定位和责任移交参数。按当前Next本地文档使用原生历史API与useSearchParams，并补Suspense边界。
- 深链中的产品线默认用于AI资料准备；研究范围与AI产品线切换同步，范围切换后丢弃旧准备状态和在途结果。不存在/无权访问的空间或产品线明确阻断，需重新选择，不静默放大范围。这里对齐研究/AI资料范围，不声称竞品、定义等各业务表独立筛选已合并为全局筛选。
- 定义规格和市场细分的条件式pattern仍遗漏旧表达式，本轮补齐连字符转义。实际浏览器确认规格稳定标识与验证阶段标识可按`v`规则编译，最终页面0错误0警告。
- 父版三方对比原先把规格对象的字符串字段当成员编号，显示“原成员（当前不可用）”，嵌套依据显示`[object Object]`。现复用规格正文渲染，显示真实目标/单位/工况/判据/状态/负责人和原证据入口；仅专业人员或负责人字段进行成员解析，其他对象递归显示。对照[修复前](../../../../output/playwright/pm-navigation-0404/parent-comparison-before.txt)、[修复后](../../../../output/playwright/pm-navigation-0404/parent-comparison-fixed.txt)及[截图](../../../../output/playwright/pm-navigation-0404/parent-comparison-fixed.png)。

## 实际浏览器业务验证

复用前次独立57433/pdos_test合成样本，API8124、网页3104，未使用57432或业务环境。无真实模型调用，无repo测试清库，无真实角色批准；五专业分别通过同一合成Owner账号的独立表单记录，仅证明UI与领域流程可用。

1. 带产品线进入研究→点击竞品→刷新仍为竞品且AI产品线正确；浏览器后退回研究且原产品线保留。[刷新证据](../../../../output/playwright/pm-navigation-0404/navigation-reload.log)、[后退证据](../../../../output/playwright/pm-navigation-0404/navigation-back.log)。
2. 打开已有合成型号定义v2草稿 `39860b64-afd6-4723-90e8-07273112fe8b`，在页面把通过判据改为105～115kPa，与110kPa目标/±5kPa容差对齐并保存修改原因。提交协审后未齐五专业意见，发布按钮不可用。
3. 浏览器逐项填写ID/MD/EE/FW/DQE意见、勾选合成原证据并提交，填写发布原因后执行正式发布动作。v2显示当前生效，v1保留已被后续版本替代状态。[首项审阅后](../../../../output/playwright/pm-navigation-0404/review-first.txt)、[五项齐备](../../../../output/playwright/pm-navigation-0404/five-reviews.txt)、[发布后](../../../../output/playwright/pm-navigation-0404/published-definition.txt)。这些均为隔离库合成动作，不代表真人专业能力或审批通过。
4. 矩阵切换为定义v2；原路线图继续引用当时定义v1，并明确提示产品范围或定义已变化、待重核，未自动篡改原计划。[页面证据](../../../../output/playwright/pm-navigation-0404/matrix-after-publish.txt)。
5. 派生定义 `e778f87a-50bd-42a1-b5cd-69b57dafdba5` 起初仍锁父v1。本轮修复三方对比显示后，浏览器勾选pressure并具名说明原因，显式接受父v2该条变更。接受记录可查，内容成为110kPa/105～115kPa，派生定义仍是草稿；规格待确认、五专业待指定，不自动继承父版确认和签核。[接受后](../../../../output/playwright/pm-navigation-0404/parent-accepted.txt)、[编辑回读](../../../../output/playwright/pm-navigation-0404/derived-editor-final.txt)。最后仅打开编辑器核对数据并取消，未再保存。

## 检查与候选

- 新增3项导航交互回归，验证地址栏/组件恢复、跨空间清理、产品线进入真实资料请求体和无权链接拒绝；与原准备组件共[6项定向通过](../../../../output/playwright/pm-navigation-0404/tests.log)。
- [工作区37项回归](../../../../output/playwright/pm-navigation-0404/regression.log)通过。随后收紧无效line参数并修正新增测试类型后，[3项导航重验](../../../../output/playwright/pm-navigation-0404/navigation-final.log)通过；显示修复后[5项定义/派生回归](../../../../output/playwright/pm-navigation-0404/definition-regression.log)通过。重复项不累加为新用例。
- 初次构建因新增测试错误使用`exact`选项而失败，已删除不受支持参数。最终[完整构建](../../../../output/playwright/pm-navigation-0404/build-final-renderer.log)、受影响ESLint和diff检查通过。[浏览器pattern核验](../../../../output/playwright/pm-navigation-0404/patterns-final.log)、[最终控制台](../../../../output/playwright/pm-navigation-0404/console-final.log)保留。初次浏览器打开时网页服务未启动导致连接拒绝；服务启动后复用同一浏览器继续，无数据丢失或测试库重建。
- 本轮未改后端、迁移或模型政策。候选记录见[源文件摘要](navigation-source-sha256.json)，前序后端证据沿[RFQ](rfq.md)及此前链接保留，不能合并冒充正式联合出口。

## 剩余与续接

导航和本轮定义发布/父版接受的页面缺口已补。下一步验证AI候选从原运行回链、编辑/拒绝/登记和网络不确定恢复的实际页面路径，并核对研究采集及八项能力逐项尚缺验收。当前SHADOW未授真实资格；真实研究材料/provider、独立逐能力评测、真实角色试用和人工Exit仍未通过。RFQ需求“四类”名称依旧待补，不自行冻结枚举。

原联验事故、数据库边界、外部授权及P/Q保留。本轮无真实外发、生产部署、git push或golden-case写入。服务/浏览器在检查点结束；57433及本地合成原件保留，下一次用前先核对状态，不与清库型repo测试并发。
