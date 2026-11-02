import test from "node:test";
import assert from "node:assert/strict";
import { dueState, groupByCategory, myOpenItems, openRisks, openTasks, projectStateLabel, readPortfolio, readRunActivity, type Portfolio, type PortfolioProject } from "./portfolio-reads";

const me = "11111111-2222-4333-8444-555555555555";
const other = "99999999-8888-4333-8444-555555555555";

function project(id: string, name: string, plan: boolean, sourceStatus = "current", created = "2026-10-01T00:00:00+00:00"): PortfolioProject["project"] {
  return {
    id, name, purpose: "用途", scope: "范围", owner_id: me, visibility: "category",
    revision: 1, status: "active", source_status: sourceStatus, created_at: created,
    definition: { id: "d", title: "定义", revision: 1, status: "frozen", source_status: sourceStatus },
    plan: plan ? { id: "p", revision: 1, status: "applied", forecast: null as never } : null,
    plan_state: plan ? "available" : "not_created",
    work_packages: [], task_count: plan ? 0 : null,
  };
}

function entry(id: string, name: string, plan: boolean, items: PortfolioProject["openItems"], sourceStatus = "current", created?: string): PortfolioProject {
  return {
    project: project(id, name, plan, sourceStatus, created),
    category: { id: "c1", name: "品类一", purpose: "" },
    product: { id: "p1", name: "型号一", purpose: "" },
    openItems: items, openItemsError: "",
  };
}

const portfolio: Portfolio = {
  categories: [{ id: "c1", name: "品类一", purpose: "" }],
  readErrors: [],
  projects: [
    entry("j1", "甲项目", true, [
      { id: "i1", kind: "task", title: "我的逾期任务", owner_id: me, due_date: "2026-10-10", status: "assigned" },
      { id: "i2", kind: "risk", title: "开放风险", owner_id: other, due_date: null, status: "open" },
      { id: "i3", kind: "risk", title: "已关闭风险", owner_id: me, due_date: null, status: "closed" },
    ], "current", "2026-10-02T00:00:00+00:00"),
    entry("j2", "乙项目", false, [
      { id: "i4", kind: "task", title: "我的临期任务", owner_id: me, due_date: "2026-10-16", status: "assigned" },
      { id: "i5", kind: "task", title: "他人的任务", owner_id: other, due_date: "2026-10-01", status: "assigned" },
      { id: "i6", kind: "task", title: "已完成任务", owner_id: me, due_date: "2026-10-01", status: "done" },
    ], "needs_recheck", "2026-10-03T00:00:00+00:00"),
  ],
};

test("我的未决事项只含本人且未关闭，按到期日升序", () => {
  const mine = myOpenItems(portfolio, me);
  assert.deepEqual(mine.map(item => item.id), ["i1", "i4"]);
  assert.equal(mine[0].projectName, "甲项目");
  assert.equal(mine[0].categoryId, "c1");
});

test("开放风险只含 open 状态，关闭不计", () => {
  const risks = openRisks(portfolio.projects[0]);
  assert.deepEqual(risks.map(item => item.id), ["i2"]);
});

test("到期推导区分逾期、临期、排期与无期限", () => {
  const now = "2026-10-13";
  assert.equal(dueState({ due_date: "2026-10-10", status: "assigned" }, now), "overdue");
  assert.equal(dueState({ due_date: "2026-10-13", status: "assigned" }, now), "soon");
  assert.equal(dueState({ due_date: "2026-10-20", status: "assigned" }, now), "soon");
  assert.equal(dueState({ due_date: "2026-10-21", status: "assigned" }, now), "scheduled");
  assert.equal(dueState({ due_date: null, status: "assigned" }, now), "none");
  assert.equal(dueState({ due_date: "2026-10-10", status: "done" }, now), "none");
  const { overdue, soon } = openTasks(portfolio.projects[1], now);
  assert.deepEqual(overdue.map(item => item.id), ["i5"]);
  assert.deepEqual(soon.map(item => item.id), ["i4"]);
});

test("项目状态口径与品类工作台一致", () => {
  assert.equal(projectStateLabel(portfolio.projects[0]), "已有计划");
  assert.equal(projectStateLabel(portfolio.projects[1]), "需重核");
  assert.equal(projectStateLabel(entry("j3", "丙", false, [])), "待建计划");
  const unavailable = entry("j4", "丁", false, []);
  unavailable.project.plan_state = "unavailable";
  assert.equal(projectStateLabel(unavailable), "计划暂不可读");
});

test("按品类与型号分组保持项目归属", () => {
  const groups = groupByCategory(portfolio);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].products.length, 1);
  assert.deepEqual(groups[0].products[0].entries.map(item => item.project.id), ["j1", "j2"]);
});

test("项目由个人投影连续取完分页，不再逐品类型号扇出", async () => {
  const calls: string[] = [];
  const api = async <T,>(path: string): Promise<T> => {
    calls.push(path);
    return { items: [portfolio.projects[calls.length - 1]], next_cursor: calls.length === 1 ? "next" : null, unavailable_count: 0, as_of: "2026-10-16T00:00:00Z" } as T;
  };
  const result = await readPortfolio(api);
  assert.deepEqual(result.projects.map(item => item.project.id), ["j1", "j2"]);
  assert.deepEqual(calls, ["v1/personal/projects?page_size=100", "v1/personal/projects?page_size=100&cursor=next"]);
});

test("单项目直达只读所选项目，关联不可读有明确提示", async () => {
  const calls: string[] = [];
  const result = await readPortfolio(async <T,>(path: string): Promise<T> => {
    calls.push(path);
    return { items: [portfolio.projects[0]], next_cursor: null, unavailable_count: 1, as_of: "now" } as T;
  }, "j1");
  assert.deepEqual(calls, ["v1/personal/projects/j1"]);
  assert.equal(result.projects.length, 1);
  assert.match(result.readErrors[0].message, /关联资料当前不可读/);
});

test("后续页失败保留失败，不用不完整结果冒充完整列表", async () => {
  let calls = 0;
  await assert.rejects(readPortfolio(async <T,>(): Promise<T> => {
    if (++calls === 2) throw new Error("当前权限已失效");
    return { items: [portfolio.projects[0]], next_cursor: "next", unavailable_count: 0 } as T;
  }), /当前权限已失效/);
});

test("不推进的游标可恢复失败，避免无限加载", async () => {
  let calls = 0;
  await assert.rejects(readPortfolio(async <T,>(): Promise<T> => {
    calls++;
    return { items: [], next_cursor: "same", unavailable_count: 0 } as T;
  }), /分页位置未推进/);
  assert.equal(calls, 2);
});

test("等待答复跨页保留，最近运行只取明确的一页", async () => {
  const calls: string[] = [];
  const api = async <T,>(path: string): Promise<T> => {
    calls.push(path);
    return { items: [{ run_id: String(calls.length) }], next_cursor: calls.length === 1 ? "next" : null, as_of: "now" } as T;
  };
  assert.equal((await readRunActivity(api, true)).length, 2);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(path => path.startsWith("v1/personal/run-activity?")));
  calls.length = 0;
  assert.equal((await readRunActivity(api)).length, 1);
  assert.deepEqual(calls, ["v1/personal/run-activity?page_size=12&waiting=false"]);
});
