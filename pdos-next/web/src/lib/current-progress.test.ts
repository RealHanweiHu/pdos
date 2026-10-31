import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { parseCurrentProgress } from "./current-progress";

test("current queue stops before historical entries and keeps source status verbatim", () => {
  const result = parseCurrentProgress(`| M0 旧条目 | 已完成 | 不应出现 |
<a id="current-queue"></a>
## 当前队列
**S1 最小演示切片已关闭（用户指定范围）**：完整 S1 仍未验收。
| 里程碑 | 状态 | 说明 |
|---|---|---|
| M3 品类研究到立项 | 最小切片通过；M3 未完成 | 见[实际证据](../evidence.md) |
<a id="queue-history-20261005"></a>
| M9 历史条目 | 已完成 | 不应出现 |
- [x] **N0-01：历史条目**`);
  assert.deepEqual(result.milestones, [{ id: "M3", title: "品类研究到立项", status: "最小切片通过；M3 未完成", detail: "见实际证据" }]);
  assert.equal(result.highlights[0].text, "完整 S1 仍未验收。");
});

test("missing current queue does not promote historical progress", () => {
  assert.deepEqual(parseCurrentProgress("| M1 历史 | 已完成 | 旧材料 |"), { milestones: [], highlights: [] });
});

test("actual active checklist provides unique milestones without archived N/P/Q totals", () => {
  const result = parseCurrentProgress(readFileSync("../../tasks/ai-native-integrated-todo.md", "utf8"));
  assert.ok(result.milestones.some(item => item.id === "M3" && item.title.includes("S1")));
  assert.ok(result.milestones.some(item => item.id === "M9" && item.title.includes("S5")));
  assert.equal(new Set(result.milestones.map(item => item.id)).size, result.milestones.length);
  assert.ok(result.milestones.every(item => /^M\d+$/.test(item.id)));
});
