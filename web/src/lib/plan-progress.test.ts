import assert from "node:assert/strict";
import test from "node:test";
import { parsePlanProgress, planCleanText } from "./plan-progress";

const fixture = `# PDOS AI-native 整合执行清单 v9.9

<a id="current-queue"></a>

## 当前队列（2099-01-01 执行优化）

### PDOS Next · 当前业务交付（2099-01-01 执行优化）

**最新已登记候选**：第N波运行/API/界面已接入 [正式变更](../docs/reports/evidence/x/result.md)；完整复验未完成。

**当前主交付：制造准备可办理。** 复用已接模块，连续完成以下步骤。

| 范围 | 已可使用的能力 | 必要缺口 |
|---|---|---|
| G0 可信执行 | 共同命令/回执 \`SOURCE_STALE\` 已定位 | 真实模型资格 |
| G1 产品起点 | 人工定义已接通 | 计划续版 |

| 顺序 | 施工动作 | 此闭环必须留下的结果 |
|---|---|---|
| 1 | 核对资源摘要依赖 | 耗时证据 |
| 2 | 作业指导首存/续版 | 正向保存可办理 |

**当前阻塞与恢复条件**：镜像受 Docker Hub 认证连接超时阻塞；网络条件变化后续验。

## 未完成工作 · 按功能闭环执行

| 功能闭环 | 主归属原条目 | 待收口的业务结果 |
|---|---|---|
| [研究到产品定义](#loop-product) | N1-01～03、N6-04 | 真实研究→规格发布 |
| [异常发现到处置](#loop-issue) | N0-04、N3-02 | 建单→关闭与反馈 |

### 产品经理：研究到产品定义 · 第一开发主线

- 与闭环无关的段落。

**数据库与事故边界**：存续联验库已恢复备份基线，不能宣称零丢失。

## 原条目验收底账

## N0 · 共同合同与基础修正

<a id="n0-01"></a>

- [x] **N0-01：增量盘点与共同对象合同收口**
  - 当前摘要：六项合同已获批准并冻结。
  - 依赖：无；可先开展本地准备
  - 业务责任：系统负责人；产品/工程/品质/ERP 职责协审
  - 交付：形成对象与Owner清单。

<a id="n0-04"></a>

- [~] **N0-04：修复结项与决策假完成**
  - 当前摘要：开发中（2099-01-01）：0097候选接通独立权限。
  - 依赖：N0-02
  - 业务责任：系统负责人

## P · 原版生产独立轨

<a id="p2"></a>

- [ ] **P2：生产模型可用与真实AI链**
  - 依赖：P1
  - 业务责任：用户授权；系统负责人
`;

test("parses items with status, group, anchor and fields", () => {
  const plan = parsePlanProgress(fixture);
  assert.equal(plan.version, "9.9");
  assert.equal(plan.counts.total, 3);
  assert.equal(plan.counts.done, 1);
  assert.equal(plan.counts.partial, 1);
  assert.equal(plan.counts.todo, 1);
  const first = plan.items[0];
  assert.equal(first.id, "N0-01");
  assert.equal(first.title, "增量盘点与共同对象合同收口");
  assert.equal(first.status, "done");
  assert.equal(first.group, "N0");
  assert.equal(first.groupLabel, "共同合同与基础修正");
  assert.equal(first.anchor, "n0-01");
  assert.equal(first.dependencies, "无；可先开展本地准备");
  assert.equal(first.responsibility, "系统负责人；产品/工程/品质/ERP 职责协审");
  const pending = plan.items.find((item) => item.id === "P2");
  assert.equal(pending?.status, "todo");
  assert.equal(pending?.groupLabel, "原版生产独立轨");
});

test("parses functional loops and expands id ranges", () => {
  const plan = parsePlanProgress(fixture);
  assert.equal(plan.loops.length, 2);
  assert.deepEqual(plan.loops[0].itemIds, ["N1-01", "N1-02", "N1-03", "N6-04"]);
  assert.deepEqual(plan.loops[1].itemIds, ["N0-04", "N3-02"]);
  assert.equal(plan.loops[0].items.length, 0);
  const resolved = plan.loops[1].items.map((item) => item.id);
  assert.deepEqual(resolved, ["N0-04"]);
});

test("parses queue tables and note paragraphs", () => {
  const plan = parsePlanProgress(fixture);
  assert.deepEqual(plan.nextAreas.map((area) => area.label), ["G0 可信执行", "G1 产品起点"]);
  assert.equal(plan.nextAreas[0].ready, "共同命令/回执 SOURCE_STALE 已定位");
  assert.equal(plan.nextAreas[0].gaps, "真实模型资格");
  assert.equal(plan.steps.length, 2);
  assert.equal(plan.steps[0].order, "1");
  assert.equal(plan.steps[1].result, "正向保存可办理");
  assert.equal(plan.notes.candidate, "第N波运行/API/界面已接入 正式变更；完整复验未完成。");
  assert.equal(plan.notes.focus, "制造准备可办理。 复用已接模块，连续完成以下步骤。");
  assert.ok(plan.notes.blocker.startsWith("镜像受 Docker Hub"));
  assert.ok(plan.notes.incident.startsWith("存续联验库已恢复备份基线"));
});

test("planCleanText strips links, bold and code marks", () => {
  assert.equal(planCleanText("**重点**见[证据](../docs/x.md)与\`SOURCE_STALE\`。"), "重点见证据与SOURCE_STALE。");
});
